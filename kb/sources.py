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
    vendor_names: frozenset[str] = field(default_factory=frozenset)

    @property
    def approved(self) -> bool:
        """已核实条款允许，或已取得厂商授权。"""
        return self.terms_checked or self.license == "partner"

    def covers(self, vendor: str) -> bool:
        """该来源的文档能否用于此厂商的组件（ADR-0019）。"""
        return normalize_vendor(vendor) in self.vendor_names


def normalize_vendor(name: str) -> str:
    """厂商名比较时忽略大小写与首尾空白。"""
    return " ".join(name.split()).casefold()


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
                vendor_names=frozenset(
                    normalize_vendor(v) for v in [s.get("vendor", ""), *s.get("covers_vendors", [])] if v
                ),
            )
            for s in data.get("sources") or []
        ]
        return cls(sources)

    @classmethod
    def load(cls, path: Path = SOURCES_FILE) -> SourceRegistry:
        return cls.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    def check_document(self, doc: str, *, vendor: str | None = None, allow_test: bool = False) -> str | None:
        """检查来源文档能否用于入库：可以则返回 None，否则返回原因。

        给出 vendor 时，还要求文档所属来源覆盖该厂商（ADR-0019）。
        """
        if doc == TEST_DOC:
            return None if allow_test else "测试专用来源文档不得进入正式库"
        owner = self._doc_owner.get(doc)
        if owner is None:
            return f"来源文档 {doc} 未在 data/sources.yaml 登记"
        if not owner.approved:
            return f"来源文档 {doc} 所属来源 {owner.id} 尚未核实条款或取得授权"
        if vendor is not None and not owner.covers(vendor):
            return (f"来源文档 {doc} 属于 {owner.vendor}（来源 {owner.id}），不能用于厂商 {vendor} 的组件；"
                    "经销商目录或第三方手册须在 covers_vendors 中列出该厂商")
        return None
