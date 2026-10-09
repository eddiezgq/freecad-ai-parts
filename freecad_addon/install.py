"""把 AI Parts 工作台装进 FreeCAD（ADR-0036）：在 FreeCAD 用户目录的 Mod/FreeCADAIParts/ 写入 InitGui.py。

    python -m freecad_addon.install [--mod-dir 目录] [--uninstall]

缺省（开发用）：InitGui.py 只记录本仓库路径并调用 freecad_addon.gui.workbench.register()，代码仍在本仓库中，
更新仓库即更新插件。对话面板还需要在 FreeCAD 的 Python 中安装依赖：<FreeCAD 的 python> -m pip install -e ".[llm]"

--standalone（ADR-0066）：把运行时代码与数据（freecad_addon.bundle）复制到 Mod/FreeCADAIParts/lib/，
InitGui.py 指向这个 lib，装完可以删掉仓库。--from-bundle 目录：用已生成的包（安装包用这个）。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

MOD_NAME = "FreeCADAIParts"
REPO_ROOT = Path(__file__).resolve().parents[1]
MARKER = "# 由 python -m freecad_addon.install 生成"


def _freecad_root() -> Path:
    home = Path.home()
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / "FreeCAD"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "FreeCAD"
    return Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "FreeCAD"


def default_mod_dir() -> Path:
    """FreeCAD 1.0 的用户 Mod 目录（可在 FreeCAD 的 Python 控制台中用 FreeCAD.getUserAppDataDir() 核对）。"""
    return _freecad_root() / "Mod"


def default_mod_dirs() -> list[Path]:
    """要安装到的全部 Mod 目录：1.0 的目录，加上已有的按版本分开的用户目录（FreeCAD 1.1 起为 v1-1/ 等）。"""
    root = _freecad_root()
    versioned = sorted(d for d in root.glob("v*") if d.is_dir() and re.fullmatch(r"v\d+-\d+", d.name)) \
        if root.is_dir() else []
    return [root / "Mod", *(d / "Mod" for d in versioned)]


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


def standalone_init_gui_source(lib: Path) -> str:
    """自包含安装的 InitGui.py：优先按自身位置找 lib/（整个目录被挪动也能用），找不到再用安装时的绝对路径。"""
    return (
        f"{MARKER} --standalone（AI Parts 工作台，ADR-0066）\n"
        "import os\n"
        "import sys\n\n"
        f"LIB = {str(lib)!r}\n"
        "try:\n"
        "    _here = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib')\n"
        "    if os.path.isdir(_here):\n"
        "        LIB = _here\n"
        "except NameError:  # FreeCAD 执行 InitGui.py 时可能没有 __file__\n"
        "    pass\n"
        "if LIB not in sys.path:\n"
        "    sys.path.insert(0, LIB)\n\n"
        "from freecad_addon.gui.workbench import register\n\n"
        "register()\n"
    )


def install(mod_dir: Path, standalone: bool = False, bundle: Path | None = None) -> Path:
    target = mod_dir / MOD_NAME
    if target.is_dir():
        init = target / "InitGui.py"
        if init.is_file() and MARKER not in init.read_text(encoding="utf-8"):
            raise RuntimeError(f"{target} 不是本安装程序生成的，未覆盖")
        shutil.rmtree(target)
    target.mkdir(parents=True)
    if not (standalone or bundle):
        (target / "InitGui.py").write_text(init_gui_source(), encoding="utf-8")
        return target
    lib = target / "lib"
    if bundle:
        from freecad_addon.bundle import MANIFEST

        if not (Path(bundle) / MANIFEST).is_file():
            raise RuntimeError(f"{bundle} 不是工作台包（缺 {MANIFEST}）")
        shutil.copytree(bundle, lib)
    else:
        from freecad_addon.bundle import build

        build(lib)
    (target / "InitGui.py").write_text(standalone_init_gui_source(lib), encoding="utf-8")
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
    parser.add_argument("--standalone", action="store_true", help="复制代码与数据进 Mod，不依赖仓库（ADR-0066）")
    parser.add_argument("--from-bundle", type=Path, default=None, help="用已生成的工作台包目录（隐含 --standalone）")
    args = parser.parse_args(argv)
    mod_dirs = [args.mod_dir] if args.mod_dir else default_mod_dirs()
    if args.uninstall:
        for mod_dir in mod_dirs:
            print(f"已卸载：{mod_dir / MOD_NAME}" if uninstall(mod_dir) else f"未安装：{mod_dir / MOD_NAME}")
        return 0
    targets = [install(mod_dir, args.standalone, args.from_bundle) for mod_dir in mod_dirs]
    if args.standalone or args.from_bundle:
        print("已安装（自包含）到：\n" + "\n".join(f"  {t}" for t in targets) + "\n"
              "重启 FreeCAD 后，在工作台列表中选择 “AI Parts”。\n"
              "依赖装进 FreeCAD 的 Python：<FreeCAD 的 python> -m pip install pyyaml jsonschema pint httpx anthropic")
        return 0
    print("已安装到：\n" + "\n".join(f"  {t}" for t in targets) + "\n"
          "重启 FreeCAD 后，在工作台列表中选择 “AI Parts”。\n"
          "列表中没有时，在 FreeCAD 的 Python 控制台运行 FreeCAD.getUserAppDataDir() 查看用户目录，"
          "再用 --mod-dir <用户目录>/Mod 安装。\n"
          "对话面板还需要：\n"
          "  1. 在 FreeCAD 的 Python 中安装依赖：<FreeCAD 的 python> -m pip install -e \".[llm]\"\n"
          "  2. 启动 FreeCAD 前设置环境变量 ANTHROPIC_API_KEY（或写在本仓库的 .env 中）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
