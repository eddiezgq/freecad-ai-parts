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


FEA = WIN / "wenquest-fea"


def test_fea_requirements_are_lean():
    """问渠有限元版（ADR-0096 第 5 步）：要报告的 python-docx、matplotlib；不装多体与优化"""
    names = {re.split(r"[<>=\[ ]", r)[0] for r in deps.requirements(ROOT / "pyproject.toml", "fea")}
    assert {"anthropic", "gmsh", "numpy", "scipy", "python-docx", "matplotlib", "cryptography", "httpx"} <= names
    assert not names & {"mujoco", "optuna", "pytest", "ruff"}
    full = {re.split(r"[<>=\[ ]", r)[0] for r in deps.requirements(ROOT / "pyproject.toml")}
    assert {"python-docx", "matplotlib"} <= full                      # 全功能版的有限元报告也要


def test_fea_files_are_utf8_with_bom():
    for path in (FEA / "wenquest-fea.iss", FEA / "NOTICES.txt", WIN / "accept_fea.ps1"):
        raw = path.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf"), path.name
        raw[3:].decode("utf-8")


def test_fea_iss_basics():
    iss = (FEA / "wenquest-fea.iss").read_text(encoding="utf-8-sig")
    app_id = re.search(r"^AppId=(.+)$", iss, re.MULTILINE).group(1)
    assert app_id != re.search(r"^AppId=(.+)$", (WIN / "fap.iss").read_text(encoding="utf-8-sig"), re.MULTILINE).group(1)
    assert "OutputBaseFilename=WenQuest-FEA-Setup-{#AppVersion}" in iss and "SetupIconFile=wenquest-fea.ico" in iss
    assert (FEA / "wenquest-fea.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"
    for pdf in re.findall(r'\{#DocsDir\}\\([^"]+\.pdf)', iss):                     # 验证手册随安装包
        assert (ROOT / "docs/verification" / pdf).is_file(), pdf
    notices = (FEA / "NOTICES.txt").read_text(encoding="utf-8-sig")
    for word in ("Apache License 2.0", "LGPL", "GPL", "github.com/FreeCAD/FreeCAD", "gmsh.info", "dhondt.de"):
        assert word in notices
    build = (WIN / "build.ps1").read_text(encoding="utf-8-sig")
    assert "--test-build" in build and "wenquest-fea.iss" in build
    wf = (ROOT / ".github/workflows/windows.yml").read_text(encoding="utf-8")
    job = wf[wf.index("  wenquest-fea:"):]
    assert "-Edition fea -TestBuild" in job and "gh release" not in job          # 测试版只作 CI 产物，不发布
