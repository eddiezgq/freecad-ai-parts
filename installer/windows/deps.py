"""安装包要装进 FreeCAD 自带 Python 的第三方依赖（ADR-0066）：pyproject 的基本依赖加 llm、mbd、fea、optimize、report（有限元的 Word 报告与云图）。

    python installer/windows/deps.py [full|fea|mbd]     # 每行一个要求
问渠有限元版（fea，ADR-0096）只要 llm、fea、report：不装多体（mujoco）与优化（optuna）。
问渠多体动力学版（mbd，ADR-0102）要 llm、fea（实体柔性体的 gmsh）、report，加 FMU 联合仿真的 fmpy；不装 mujoco（旧的机械臂模块才用）与优化。
"""

import sys
import tomllib
from pathlib import Path

EXTRAS = ("llm", "mbd", "fea", "optimize", "report")
FEA_EXTRAS = ("llm", "fea", "report")
MBD_EXTRAS = ("llm", "fea", "report")
MBD_ONLY = ("fmpy",)


def requirements(pyproject: Path, edition: str = "full") -> list[str]:
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    reqs = list(project["dependencies"])
    extras = {"fea": FEA_EXTRAS, "mbd": MBD_EXTRAS}.get(edition, EXTRAS)
    for extra in extras:
        reqs += project["optional-dependencies"][extra]
    if edition == "mbd":
        reqs += [r for r in project["optional-dependencies"]["mbd"] if r.split("=")[0].split(">")[0].strip() in MBD_ONLY]
    return [r.split("#")[0].strip() for r in reqs if r.strip()]


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    sys.stdout.write("\n".join(requirements(root / "pyproject.toml", sys.argv[1] if len(sys.argv) > 1 else "full")) + "\n")
