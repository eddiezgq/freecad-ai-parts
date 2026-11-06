# -*- coding: utf-8 -*-
"""器件电气参数（第 104 轮）：eda/parts/<型号>.yaml，每个数带出处（厂家规格书名称、版本、网址、页码）和“核对过没有”。

判定规矩：
  - 没录这个参数 → unknown（未知）
  - 录了但没核对（checked: false）→ pending（待核对）：照样把数和要求列出来，但不算通过
  - 核对过 → 按数判 pass / fail
读文件，只做计算：不联网、不调 AI。"""

from __future__ import annotations

import glob
import os

from .blocks import common as c
from .schema.design import read_yaml

FORMAT = "wqeda.part/1"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARTS_DIR = os.path.join(HERE, "parts")


class Devices:
    def __init__(self, entries):
        self.entries = entries  # 型号 → 文件内容

    @classmethod
    def load(cls, folder=PARTS_DIR):
        out = {}
        for path in sorted(glob.glob(os.path.join(folder, "*.yaml"))):
            doc = read_yaml(path)
            if isinstance(doc, dict) and doc.get("format") == FORMAT:
                out[doc["part"]] = doc
        return cls(out)

    def _p(self, part, key):
        return ((self.entries.get(part) or {}).get("params") or {}).get(key)

    def value(self, part, key):
        p = self._p(part, key)
        return None if p is None else p.get("value")

    def checked(self, part, key):
        p = self._p(part, key)
        return bool(p and p.get("checked"))

    def source(self, part, key):
        e, p = self.entries.get(part), self._p(part, key)
        if not p:
            return ""
        ds = e.get("datasheet") or {}
        return "{} {}，{}".format(ds.get("title", ""), ds.get("revision", ""), p.get("where", "")).strip("，")

    def note(self, part, key):
        p = self._p(part, key)
        if p is None:
            return "{} 的这项参数没录".format(part)
        return "" if p.get("checked") else "待核对"

    def _status(self, part, key, ok):
        p = self._p(part, key)
        if p is None or ok is None:
            return c.UNKNOWN
        if not p.get("checked"):
            return c.PENDING
        return c.PASS if ok else c.FAIL

    def judge(self, part, key, name, need, unit="", rule=""):
        """额定值 ≥ 要求"""
        have = self.value(part, key)
        ok = None if have is None else have >= need - 1e-12
        return c.judge(
            key,
            name,
            need,
            have,
            unit,
            rule,
            status=self._status(part, key, ok),
            source=self.source(part, key),
            note=self.note(part, key),
        )

    def in_range(self, part, key, name, x, unit=""):
        """工作范围 [下限, 上限] 包含 x"""
        p = self._p(part, key)
        lo, hi = (p.get("min"), p.get("max")) if p else (None, None)
        ok = None if lo is None or hi is None else lo <= x <= hi
        have = None if lo is None or hi is None else "{:g}–{:g}".format(lo, hi)
        return c.judge(
            key,
            name,
            x,
            have,
            unit,
            "范围包含 {:g} {}".format(x, unit),
            status=self._status(part, key, ok),
            source=self.source(part, key),
            note=self.note(part, key),
        )

    def equals(self, part, key, name, x, unit=""):
        have = self.value(part, key)
        ok = None if have is None else abs(have - x) < 1e-9
        return c.judge(
            key,
            name,
            x,
            have,
            unit,
            "器件数据 = 设计值",
            status=self._status(part, key, ok),
            source=self.source(part, key),
            note=self.note(part, key),
        )
