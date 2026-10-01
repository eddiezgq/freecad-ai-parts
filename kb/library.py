"""组件库接口（M4a #65）：MCP 工具与 REST 读取组件的唯一入口。

两种实现：
- JsonLibrary：读一个目录下的组件 JSON（golden fixtures、知识库导出的快照 <品类>/<id>.json）
- KbLibrary：读知识库（PostgreSQL）

配置：环境变量 FAP_LIBRARY 指向 JSON 目录时用 JsonLibrary；否则有 DATABASE_URL 时用 KbLibrary。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol


class Library(Protocol):
    def get(self, cid: str) -> dict | None: ...

    def all(self, category: str | None = None) -> list[dict]: ...


class JsonLibrary:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        if not self.directory.is_dir():
            raise FileNotFoundError(f"组件库目录不存在：{self.directory}")
        self._comps: dict[str, dict] = {}
        for path in sorted(self.directory.rglob("*.json")):
            comp = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(comp, dict) or "id" not in comp or "category" not in comp:
                continue
            if comp["id"] in self._comps:
                raise ValueError(f"组件 id 重复：{comp['id']}（{path}）")
            self._comps[comp["id"]] = comp

    def get(self, cid: str) -> dict | None:
        return self._comps.get(cid)

    def all(self, category: str | None = None) -> list[dict]:
        return [c for _, c in sorted(self._comps.items()) if category is None or c["category"] == category]


class KbLibrary:
    def __init__(self, conn):
        from kb.store import get_component

        self.conn = conn
        self._get = get_component

    def get(self, cid: str) -> dict | None:
        return self._get(self.conn, cid)

    def all(self, category: str | None = None) -> list[dict]:
        from kb.store import list_components

        return [self._get(self.conn, cid) for cid in list_components(self.conn, category)]


def default_library() -> Library:
    path = os.environ.get("FAP_LIBRARY")
    if path:
        return JsonLibrary(path)
    if os.environ.get("DATABASE_URL"):
        from kb.db import connect

        return KbLibrary(connect())
    raise RuntimeError("未配置组件库：请设置 FAP_LIBRARY（JSON 目录）或 DATABASE_URL（知识库）")
