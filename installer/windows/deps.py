"""安装包要装进 FreeCAD 自带 Python 的第三方依赖（ADR-0066）：pyproject 的基本依赖加 llm、mbd、fea、optimize。

    python installer/windows/deps.py      # 每行一个要求
"""

import sys
import tomllib
from pathlib import Path

EXTRAS = ("llm", "mbd", "fea", "optimize")


def requirements(pyproject: Path) -> list[str]:
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    reqs = list(project["dependencies"])
    for extra in EXTRAS:
        reqs += project["optional-dependencies"][extra]
    return [r.split("#")[0].strip() for r in reqs if r.strip()]


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    sys.stdout.write("\n".join(requirements(root / "pyproject.toml")) + "\n")
