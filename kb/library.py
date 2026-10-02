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


class WithGenerated:
    """在组件库之上叠加本会话生成的转接件（ADR-0041）：get 能找到它们，all 只列组件库本身。

    生成件由求解时按端口尺寸生成，不进入组件库；方案随后的复核、布局与导出都要能按 id 找到它们。
    """

    PREFIX = "adapter.fap-generated."

    def __init__(self, base: Library):
        self.base = base
        self._generated: dict[str, dict] = {}

    def register(self, comp: dict) -> None:
        if not str(comp.get("id", "")).startswith(self.PREFIX):
            raise ValueError(f"只能登记生成的转接件（id 以 {self.PREFIX} 开头）：{comp.get('id')}")
        old = self._generated.get(comp["id"])
        if old is not None and old != comp:
            raise ValueError(f"生成件 {comp['id']} 与已登记的内容不同")
        self._generated[comp["id"]] = comp

    def get(self, cid: str) -> dict | None:
        return self.base.get(cid) or self._generated.get(cid)

    def all(self, category: str | None = None) -> list[dict]:
        return self.base.all(category)


def default_library() -> Library:
    path = os.environ.get("FAP_LIBRARY")
    if path:
        return JsonLibrary(path)
    if os.environ.get("DATABASE_URL"):
        from kb.db import connect

        return KbLibrary(connect())
    raise RuntimeError("未配置组件库：请设置 FAP_LIBRARY（JSON 目录）或 DATABASE_URL（知识库）")
