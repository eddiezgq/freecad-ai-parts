"""“帮助与培训”打开哪个网页（issue #687）。

问渠 CAD 安装包把课程网页放在 Mod/FreeCADAIParts/help/wqcad/（中文 index.html，英文 en/index.html）。
有本机副本就开它；没有（开发安装）就开学习平台上的网页：国内 learn.wenquestech.online，其他 learn.wenquestrobotics.com。
纯函数：不联网、不读设置，调用方传入语言、地区和安装目录。
"""

from __future__ import annotations

from pathlib import Path

ONLINE = {"cn": "https://learn.wenquestech.online/static/help/wqcad/",
          "intl": "https://learn.wenquestrobotics.com/static/help/wqcad/"}


def addon_dir() -> Path:
    """Mod/FreeCADAIParts：自包含安装时本包在 Mod/FreeCADAIParts/lib/freecad_addon/ 下。"""
    return Path(__file__).resolve().parents[3]


def help_target(lang: str, region: str, base: Path | None) -> tuple[str, str]:
    """返回 ("file", 本机路径) 或 ("url", 网址)。lang 为 zh / en，region 为 cn / intl。"""
    page = "en/index.html" if lang == "en" else "index.html"
    if base is not None:
        p = Path(base) / "help" / "wqcad" / page
        if p.is_file():
            return "file", str(p)
    return "url", ONLINE.get(region, ONLINE["intl"]) + page
