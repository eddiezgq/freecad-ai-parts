"""安装包要装进 FreeCAD 自带 Python 的第三方依赖（ADR-0066）：pyproject 的基本依赖加 llm、mbd、fea、optimize、report（有限元的 Word 报告与云图）。

    python installer/windows/deps.py [full|fea]     # 每行一个要求
问渠有限元版（fea，ADR-0096）只要 llm、fea、report：不装多体（mujoco）与优化（optuna）。
"""

import sys
import tomllib
from pathlib import Path

EXTRAS = ("llm", "mbd", "fea", "optimize", "report")
FEA_EXTRAS = ("llm", "fea", "report")


def requirements(pyproject: Path, edition: str = "full") -> list[str]:
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    reqs = list(project["dependencies"])
    for extra in (FEA_EXTRAS if edition == "fea" else EXTRAS):
        reqs += project["optional-dependencies"][extra]
    return [r.split("#")[0].strip() for r in reqs if r.strip()]


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    sys.stdout.write("\n".join(requirements(root / "pyproject.toml", sys.argv[1] if len(sys.argv) > 1 else "full")) + "\n")
