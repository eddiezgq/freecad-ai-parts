"""把 AI Parts 工作台装进 FreeCAD（ADR-0036）：在 FreeCAD 用户目录的 Mod/FreeCADAIParts/ 写入 InitGui.py。

    python -m freecad_addon.install [--mod-dir 目录] [--uninstall]

InitGui.py 只记录本仓库路径并调用 freecad_addon.gui.workbench.register()，代码仍在本仓库中，更新仓库即更新插件。
对话面板还需要在 FreeCAD 的 Python 中安装依赖：<FreeCAD 的 python> -m pip install -e ".[llm]"
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

MOD_NAME = "FreeCADAIParts"
REPO_ROOT = Path(__file__).resolve().parents[1]
MARKER = "# 由 python -m freecad_addon.install 生成"


def default_mod_dir() -> Path:
    """FreeCAD 1.0 的用户 Mod 目录（可在 FreeCAD 的 Python 控制台中用 FreeCAD.getUserAppDataDir() 核对）。"""
    home = Path.home()
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / "FreeCAD" / "Mod"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "FreeCAD" / "Mod"
    return Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "FreeCAD" / "Mod"


def init_gui_source(repo: Path = REPO_ROOT) -> str:
    return (
        f"{MARKER}（AI Parts 工作台，ADR-0036）\n"
        "import sys\n\n"
        f"REPO = {str(repo)!r}\n"
        "if REPO not in sys.path:\n"
        "    sys.path.insert(0, REPO)\n\n"
        "from freecad_addon.gui.workbench import register\n\n"
        "register()\n"
    )


def install(mod_dir: Path) -> Path:
    target = mod_dir / MOD_NAME
    target.mkdir(parents=True, exist_ok=True)
    (target / "InitGui.py").write_text(init_gui_source(), encoding="utf-8")
    return target


def uninstall(mod_dir: Path) -> bool:
    target = mod_dir / MOD_NAME
    init = target / "InitGui.py"
    if not init.is_file():
        return False
    if MARKER not in init.read_text(encoding="utf-8"):
        raise RuntimeError(f"{target} 不是本安装程序生成的，未删除")
    shutil.rmtree(target)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="安装或卸载 FreeCAD 的 AI Parts 工作台")
    parser.add_argument("--mod-dir", type=Path, default=None, help="FreeCAD 用户 Mod 目录（缺省按系统推断）")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)
    mod_dir = args.mod_dir or default_mod_dir()
    if args.uninstall:
        print(f"已卸载：{mod_dir / MOD_NAME}" if uninstall(mod_dir) else f"未安装：{mod_dir / MOD_NAME}")
        return 0
    target = install(mod_dir)
    print(f"已安装到 {target}\n重启 FreeCAD 后，在工作台列表中选择 “AI Parts”。\n"
          "对话面板还需要：\n"
          "  1. 在 FreeCAD 的 Python 中安装依赖：<FreeCAD 的 python> -m pip install -e \".[llm]\"\n"
          "  2. 启动 FreeCAD 前设置环境变量 ANTHROPIC_API_KEY（或写在本仓库的 .env 中）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
