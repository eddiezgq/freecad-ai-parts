"""自包含工作台包（ADR-0066 第 1 项）：把运行时需要的代码与数据按仓库布局复制到一个目录，装进 FreeCAD 的 Mod，不依赖仓库。

    python -m freecad_addon.bundle <目标目录>

保持仓库布局（engine/、kb/、schema/、data/library/、tests/golden/ ……），因为校验规则、端口类型、来源登记、
golden 示例都是按“包所在目录的上一级”找的；这样不用改 engine/ 等的任何路径。
第三方依赖（pyyaml、jsonschema、pint、gmsh、numpy、scipy 等）另装进 FreeCAD 自带的 Python。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 运行时要的全部内容（相对仓库根）。data/raw、数据库、数字工厂、开发脚本不进包。
PACKAGES = ("freecad_addon", "engine", "kb", "analysis", "mcp_server", "llm_gateway", "ingest")
DATA = ("schema", "data/library", "data/sources.yaml", "tests/golden", "tests/recordings/requirement",
        "LICENSE", "NOTICE")
MANIFEST = "BUNDLE.json"

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache")


def _version(repo: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10, check=False)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def build(dest: Path, repo: Path = REPO_ROOT) -> dict:
    """把运行时内容复制到 dest（先清空）。返回清单。"""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    items = []
    for rel in (*PACKAGES, *DATA):
        src = repo / rel
        if not src.exists():
            raise FileNotFoundError(f"打包缺少 {rel}")
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, target, ignore=_IGNORE)
        else:
            shutil.copy2(src, target)
        items.append(rel)
    manifest = {"name": "freecad-ai-parts", "commit": _version(repo), "items": items}
    (dest / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成自包含的 AI Parts 工作台目录")
    parser.add_argument("dest", type=Path)
    args = parser.parse_args(argv)
    m = build(args.dest)
    print(f"已生成 {args.dest}（{m['commit']}）：{len(m['items'])} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
