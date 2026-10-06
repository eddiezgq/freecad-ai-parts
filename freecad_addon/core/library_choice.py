"""FreeCAD 中用哪个组件库（ADR-0048 第 2 条）。纯函数，不依赖 FreeCAD。

顺序：
1. FAP_LIBRARY（JSON 目录）
2. DATABASE_URL（知识库）
3. 插件所在仓库的 data/library/（真实厂商组件），其中有组件时
4. 虚构测试组件（tests/golden/fixtures）

企业库（ADR-0055）：FAP_ENTERPRISE_LIBRARY 或设置文件 ~/.freecad-ai-parts/settings.json 的 enterprise_library
指定时，叠加在上面选出的公共库之上。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


SETTINGS = Path.home() / ".freecad-ai-parts" / "settings.json"


@dataclass(frozen=True)
class LibraryChoice:
    kind: str  # env_json | database | repo | fixtures
    path: Path | None
    note: str  # 面板与浏览器顶部的说明
    enterprise: Path | None = None  # 企业库目录（ADR-0055）


def read_settings(path: Path = SETTINGS) -> dict:
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_setting(key: str, value, path: Path = SETTINGS) -> None:
    import json

    data = read_settings(path)
    data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def enterprise_dir(env: Mapping[str, str], settings: Mapping | None = None) -> Path | None:
    raw = env.get("FAP_ENTERPRISE_LIBRARY") or (settings or {}).get("enterprise_library")
    return Path(raw) if raw else None


def _count(path: Path) -> int:
    return sum(1 for _ in path.glob("*/*.json"))


def choose(env: Mapping[str, str], repo_root: Path = REPO_ROOT, settings: Mapping | None = None) -> LibraryChoice:
    base = _choose_public(env, repo_root)
    ent = enterprise_dir(env, settings if settings is not None else read_settings())
    if ent is None:
        return base
    if not (ent / "components").is_dir():
        return LibraryChoice(base.kind, base.path, base.note + f"；企业库目录无效（缺 components/）：{ent}，未使用")
    n = _count(ent / "components")
    return LibraryChoice(base.kind, base.path, f"企业库 {n} 个组件（{ent}）叠加在 " + base.note, ent)


def _choose_public(env: Mapping[str, str], repo_root: Path) -> LibraryChoice:
    if env.get("FAP_LIBRARY"):
        path = Path(env["FAP_LIBRARY"])
        return LibraryChoice("env_json", path, f"组件库：{path}（FAP_LIBRARY）")
    if env.get("DATABASE_URL"):
        return LibraryChoice("database", None, "组件库：知识库（DATABASE_URL）")
    real = repo_root / "data" / "library"
    n = _count(real) if real.is_dir() else 0
    if n:
        return LibraryChoice("repo", real, f"组件库：真实厂商组件 {n} 个（仓库 data/library）")
    fixtures = repo_root / "tests" / "golden" / "fixtures"
    return LibraryChoice("fixtures", fixtures, "组件库：虚构测试组件（仓库中没有 data/library，也未设置 FAP_LIBRARY）")


def load(choice: LibraryChoice):
    """按选择打开组件库。"""
    from kb.library import JsonLibrary, default_library

    base = default_library() if choice.kind == "database" else JsonLibrary(choice.path)
    if choice.enterprise is None:
        return base
    from kb.enterprise import EnterpriseLibrary
    from kb.library import LayeredLibrary

    return LayeredLibrary(EnterpriseLibrary(choice.enterprise), base)
