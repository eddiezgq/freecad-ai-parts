"""FreeCAD 中用哪个组件库（ADR-0048 第 2 条）。纯函数，不依赖 FreeCAD。

顺序：
1. FAP_LIBRARY（JSON 目录）
2. DATABASE_URL（知识库）
3. 插件所在仓库的 data/library/（真实厂商组件），其中有组件时
4. 虚构测试组件（tests/golden/fixtures）
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LibraryChoice:
    kind: str  # env_json | database | repo | fixtures
    path: Path | None
    note: str  # 面板与浏览器顶部的说明


def _count(path: Path) -> int:
    return sum(1 for _ in path.glob("*/*.json"))


def choose(env: Mapping[str, str], repo_root: Path = REPO_ROOT) -> LibraryChoice:
    if env.get("FAP_LIBRARY"):
        path = Path(env["FAP_LIBRARY"])
        return LibraryChoice("env_json", path, f"组件库：{path}（FAP_LIBRARY）")
    if env.get("DATABASE_URL"):
        return LibraryChoice("database", None, "组件库：知识库（DATABASE_URL）")
    real = repo_root / "data" / "library"
    n = _count(real) if real.is_dir() else 0
    if n:
        return LibraryChoice("repo", real, f"组件库：真实厂商组件 {n} 个（仓库 data/library）")
    fixtures = repo_root / "tests" / "golden" / "fixtures"
    return LibraryChoice("fixtures", fixtures, "组件库：虚构测试组件（仓库中没有 data/library，也未设置 FAP_LIBRARY）")


def load(choice: LibraryChoice):
    """按选择打开组件库。"""
    from kb.library import JsonLibrary, default_library

    if choice.kind == "database":
        return default_library()
    return JsonLibrary(choice.path)
