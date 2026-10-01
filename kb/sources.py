"""来源登记（data/sources.yaml）与许可判断（ADR-0015、ADR-0018）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

SOURCES_FILE = Path(__file__).resolve().parent.parent / "data" / "sources.yaml"
TEST_DOC = "src-test-fixture"


@dataclass(frozen=True)
class Source:
    id: str
    vendor: str
    license: str
    terms_checked: bool
    documents: frozenset[str] = field(default_factory=frozenset)

    @property
    def approved(self) -> bool:
        """已核实条款允许，或已取得厂商授权。"""
        return self.terms_checked or self.license == "partner"


class SourceRegistry:
    def __init__(self, sources: list[Source]):
        self.sources = {s.id: s for s in sources}
        self._doc_owner: dict[str, Source] = {}
        for s in sources:
            for doc in s.documents:
                if doc in self._doc_owner:
                    raise ValueError(f"来源文档 {doc} 被重复登记")
                self._doc_owner[doc] = s

    @classmethod
    def from_dict(cls, data: dict) -> SourceRegistry:
        sources = [
            Source(
                id=s["id"],
                vendor=s.get("vendor", ""),
                license=s.get("license", "pending"),
                terms_checked=bool(s.get("terms_checked", False)),
                documents=frozenset(d["id"] for d in s.get("documents", [])),
            )
            for s in data.get("sources") or []
        ]
        return cls(sources)

    @classmethod
    def load(cls, path: Path = SOURCES_FILE) -> SourceRegistry:
        return cls.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    def check_document(self, doc: str, *, allow_test: bool = False) -> str | None:
        """检查来源文档能否入库：可以则返回 None，否则返回原因。"""
        if doc == TEST_DOC:
            return None if allow_test else "测试专用来源文档不得进入正式库"
        owner = self._doc_owner.get(doc)
        if owner is None:
            return f"来源文档 {doc} 未在 data/sources.yaml 登记"
        if not owner.approved:
            return f"来源文档 {doc} 所属来源 {owner.id} 尚未核实条款或取得授权"
        return None
