"""自包含工作台（ADR-0066 第 1 项）：包里有运行时要的代码与数据，从包里导入不碰仓库。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from freecad_addon import bundle, install

PROBE = r"""
import json, sys
lib = sys.argv[1]
sys.path.insert(0, lib)
from engine import rules, golden, checks_interface
from kb import validation, sources
from freecad_addon.core import library_choice
import freecad_addon.gui, analysis.common.materials, mcp_server, llm_gateway
mods = [rules, golden, checks_interface, validation, sources, library_choice, analysis.common.materials]
choice = library_choice.choose({}, settings={})
print(json.dumps({
    "outside": [m.__name__ for m in mods if not m.__file__.startswith(lib)],
    "rules": rules.RULES_DIR.is_dir(), "port_types": checks_interface._PORT_TYPES.is_dir(),
    "schema": validation.SCHEMA_DIR.is_dir(), "sources": sources.SOURCES_FILE.is_file(),
    "golden": golden.GOLDEN.is_dir(), "library": choice.kind, "library_in_lib": str(choice.path).startswith(lib),
}))
"""


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    dest = tmp_path_factory.mktemp("bundle") / "lib"
    return dest, bundle.build(dest)


def test_bundle_contents(built):
    dest, manifest = built
    assert json.loads((dest / bundle.MANIFEST).read_text(encoding="utf-8")) == manifest
    for rel in ("engine/rules.py", "schema/rules", "schema/port-types", "data/sources.yaml",
                "tests/golden/fixtures", "freecad_addon/gui/workbench.py", "analysis/common/materials.yaml",
                "kb/migrations", "LICENSE", "NOTICE"):
        assert (dest / rel).exists(), rel
    assert any((dest / "data/library").glob("*/*.json"))
    assert not list(dest.rglob("__pycache__"))
    assert not (dest / "data/raw").exists() and not (dest / "factory").exists()


def test_bundle_imports_without_repo(built, tmp_path):
    dest, _ = built
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "FAP_LIBRARY", "DATABASE_URL",
                                                             "FAP_ENTERPRISE_LIBRARY")}
    env["HOME"] = str(tmp_path)  # 不读本机 ~/.freecad-ai-parts 设置
    out = subprocess.run([sys.executable, "-c", PROBE, str(dest)], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=120, check=False)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["outside"] == []
    assert r["rules"] and r["port_types"] and r["schema"] and r["sources"] and r["golden"]
    assert r["library"] == "repo" and r["library_in_lib"]


def test_standalone_install_and_uninstall(tmp_path):
    target = install.install(tmp_path, standalone=True)
    src = (target / "InitGui.py").read_text(encoding="utf-8")
    compile(src, "InitGui.py", "exec")
    assert install.MARKER in src and "--standalone" in src and str(install.REPO_ROOT) not in src
    assert (target / "lib" / bundle.MANIFEST).is_file()
    # 重装覆盖本程序生成的目录
    assert install.install(tmp_path, standalone=True) == target
    assert install.uninstall(tmp_path) and not target.exists()


def test_install_from_bundle(built, tmp_path):
    dest, _ = built
    target = install.install(tmp_path / "Mod", bundle=dest)
    assert (target / "lib/engine/rules.py").is_file()
    with pytest.raises(RuntimeError, match="不是工作台包"):
        install.install(tmp_path / "Mod2", bundle=tmp_path / "Mod")


def test_install_refuses_foreign_dir(tmp_path):
    foreign = tmp_path / install.MOD_NAME
    foreign.mkdir()
    (foreign / "InitGui.py").write_text("# 别人的插件\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="未覆盖"):
        install.install(tmp_path, standalone=True)


def test_standalone_cli(tmp_path, capsys):
    assert install.main(["--mod-dir", str(tmp_path), "--standalone"]) == 0
    assert "自包含" in capsys.readouterr().out
    assert (tmp_path / install.MOD_NAME / "lib" / "engine").is_dir()


def test_init_gui_finds_moved_lib(tmp_path):
    """整个 Mod 目录挪了位置：InitGui.py 按自身位置找 lib/。"""
    target = install.install(tmp_path / "a", standalone=True)
    moved = tmp_path / "b"
    target.rename(moved)
    ns = {"__file__": str(moved / "InitGui.py")}
    code = (moved / "InitGui.py").read_text(encoding="utf-8").split("from freecad_addon.gui")[0]
    exec(compile(code, "InitGui.py", "exec"), ns)  # noqa: S102 — 只执行本程序生成的 InitGui 前半段
    assert Path(ns["LIB"]) == moved / "lib"
    sys.path.remove(ns["LIB"])


@pytest.mark.freecad
def test_bundle_in_freecad_python(built, tmp_path):
    """FreeCAD 自带的 Python 从包里加载工作台模块并建出零件实体。"""
    from freecad_addon.fc import client

    python = Path(os.environ.get("FAP_FREECAD_PYTHON") or client.DEFAULT_PYTHON)
    fc_lib = Path(os.environ["FAP_FREECAD_LIB"]) if os.environ.get("FAP_FREECAD_LIB") else client._module_dir(python)
    dest, _ = built
    probe = ("import sys; sys.path.insert(0, sys.argv[1]); import FreeCAD, Part; "
             "import freecad_addon.fc.shapes as s; import engine.rules as r; "
             "assert s.__file__.startswith(sys.argv[1]) and r.__file__.startswith(sys.argv[1]); "
             "print('ok', Part.makeBox(1, 2, 3).Volume)")
    env = {**os.environ, "PYTHONPATH": str(fc_lib)}
    out = subprocess.run([str(python), "-c", probe, str(dest)], cwd=tmp_path, capture_output=True, text=True,
                         timeout=180, env=env, check=False)
    assert out.returncode == 0 and "ok 6.0" in out.stdout, out.stderr


@pytest.mark.freecad
def test_freecad_gui_loads_standalone_workbench(tmp_path):
    """装进一个干净用户目录（不碰仓库路径），真实 FreeCAD 界面启动时加载出 AI Parts 工作台。"""
    import shutil

    from freecad_addon.fc import client

    python = Path(os.environ.get("FAP_FREECAD_PYTHON") or client.DEFAULT_PYTHON)
    fc_lib = Path(os.environ["FAP_FREECAD_LIB"]) if os.environ.get("FAP_FREECAD_LIB") else client._module_dir(python)
    data = tmp_path / "share"
    install.install(data / "FreeCAD" / "Mod", standalone=True)
    probe = ("import FreeCAD, FreeCADGui; FreeCADGui.showMainWindow(); import freecad_addon; "
             "print('WB', 'AiPartsWorkbench' in FreeCADGui.listWorkbenches(), freecad_addon.__file__)")
    cmd = [str(python), "-c", probe]
    if not os.environ.get("DISPLAY"):
        if not shutil.which("xvfb-run"):
            pytest.skip("没有显示环境")
        cmd = ["xvfb-run", "-a", *cmd]
    env = {**os.environ, "PYTHONPATH": str(fc_lib), "HOME": str(tmp_path), "XDG_DATA_HOME": str(data),
           "XDG_CONFIG_HOME": str(tmp_path / "config")}
    out = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True, timeout=240, env=env, check=False)
    line = next((ln for ln in out.stdout.splitlines() if ln.startswith("WB ")), "")
    assert line.startswith("WB True") and str(data) in line, out.stdout + out.stderr
