"""首次启动设置（ADR-0066 第 3 项）：AI 密钥写进本机用户目录，可选连接企业数字工厂。纯函数，不依赖 FreeCAD。

设置存 ~/.freecad-ai-parts/settings.json（first_run_done、factory_url、factory_cafile），
密钥存 ~/.freecad-ai-parts/.env（llm_gateway.save_user_env），都不进安装目录。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from freecad_addon.core import factory_link, library_choice

PROVIDERS = {"deepseek": ("DeepSeek（国内推荐）", "DEEPSEEK_API_KEY"),
             "claude": ("Claude（Anthropic）", "ANTHROPIC_API_KEY")}


def is_standalone(root: Path | None = None) -> bool:
    """是否从自包含包运行（包根目录有 BUNDLE.json，见 freecad_addon.bundle）。"""
    from freecad_addon.bundle import MANIFEST

    root = root or Path(__file__).resolve().parents[2]
    return (root / MANIFEST).is_file()


def needed(settings: Mapping) -> bool:
    return not settings.get("first_run_done")


def key_status(env: Mapping[str, str]) -> dict[str, bool]:
    """各家密钥是否已设置（不返回密钥本身）。"""
    return {p: bool(env.get(var)) for p, (_, var) in PROVIDERS.items()}


def check_factory(url: str, cafile: str | None = None,
                  client: Callable[..., factory_link.HubClient] = factory_link.HubClient) -> tuple[bool, str]:
    """测试工厂地址：能连上、数据库正常，并说明登录方式。"""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return False, "地址要以 http:// 或 https:// 开头，例如 https://factory.你的公司.com"
    if cafile and not Path(cafile).is_file():
        return False, f"根证书文件不存在：{cafile}"
    c = client(url, timeout=10, cafile=cafile or None)
    try:
        health = c._req("/api/health")
        auth = c.auth()
    except factory_link.FactoryError as exc:
        return False, str(exc)
    if not health.get("ok"):
        return False, "连上了，但工厂的数据库不正常"
    how = {"enterprise": "企业账号", "wenquest": "问渠账号", "local": "填名字"}.get(auth, auth)
    return True, f"连接正常（登录方式：{how}）"


def save(provider: str | None, key: str, factory_url: str, cafile: str,
         settings_path: Path | None = None, env_path: Path | None = None) -> list[str]:
    """保存首次设置；返回做了什么（给界面显示）。密钥为空就不改原来的密钥。"""
    from llm_gateway import save_user_env

    done = []
    if provider and key.strip():
        save_user_env({PROVIDERS[provider][1]: key}, env_path)
        done.append(f"已保存 {PROVIDERS[provider][0]} 的密钥（只在本机用户目录）")
    if factory_url.strip():
        library_choice.write_setting("factory_url", factory_url.strip().rstrip("/"), settings_path)
        library_choice.write_setting("factory_cafile", cafile.strip(), settings_path)
        done.append(f"数字工厂地址：{factory_url.strip()}")
    library_choice.write_setting("first_run_done", True, settings_path)
    return done
