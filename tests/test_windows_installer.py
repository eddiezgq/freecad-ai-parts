"""Windows 单机安装包的配置（ADR-0066 第 2 项）。真正打包在 CI 的 Windows 作业里。"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "installer" / "windows"
sys.path.insert(0, str(WIN))

import deps


def test_requirements_cover_runtime_extras():
    reqs = deps.requirements(ROOT / "pyproject.toml")
    names = {re.split(r"[<>=\[ ]", r)[0] for r in reqs}
    assert {"anthropic", "gmsh", "numpy", "scipy", "mujoco", "optuna", "pint", "jsonschema", "fastmcp"} <= names
    assert not names & {"pytest", "ruff"}
    assert all("#" not in r for r in reqs)


def test_files_are_utf8_with_bom():
    for name in ("fap.iss", "NOTICES.txt", "build.ps1", "accept.ps1"):
        raw = (WIN / name).read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf"), name
        raw[3:].decode("utf-8")


def test_freecad_version_matches_linux_pin():
    linux = re.search(r"^VERSION=(\S+)", (ROOT / "scripts/fetch_freecad.sh").read_text(), re.MULTILINE).group(1)
    win = re.search(r'\$Version = "([^"]+)"', (WIN / "build.ps1").read_text(encoding="utf-8-sig")).group(1)
    assert win == linux


def test_iss_basics():
    iss = (WIN / "fap.iss").read_text(encoding="utf-8-sig")
    assert "LicenseFile=NOTICES.txt" in iss and "PrivilegesRequiredOverridesAllowed" in iss
    assert r"{app}\bin\FreeCAD.exe" in iss
    notices = (WIN / "NOTICES.txt").read_text(encoding="utf-8-sig")
    for word in ("Apache License 2.0", "LGPL", "GPL", "OpenFOAM", "github.com/FreeCAD/FreeCAD"):
        assert word in notices
