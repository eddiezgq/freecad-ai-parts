"""费斯托 EGC 直线模组的录入（ingest/festo_egc.py，ADR-0129 129.2）。不联网、不调用 AI。

不需要目录 PDF 的部分：组件合 schema、与零件库文件一致、案例 B 要用的数（X 轴 2.5 m/s、12.5 m/s²）。
有目录 PDF（data/raw/festo/，不入库）时：每行原文都在那一页上、每个数都在原文里、SHA-256 与登记一致。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from ingest import festo_egc as F
from kb.validation import errors

ROOT = Path(__file__).parents[1]
LIB = ROOT / "data" / "library" / "linear_module"


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def test_components_are_valid_and_match_the_library():
    comps, problems = F.build()
    assert not problems and len(comps) == 11
    for c in comps:
        assert not list(errors("component.schema.json", c)), c["id"]
        saved = json.loads((LIB / f"{c['id']}.json").read_text(encoding="utf-8"))
        assert saved == json.loads(json.dumps(c)), f"{c['id']}：零件库文件与录入表不一致，重跑 python -m ingest.festo_egc"


def test_every_value_appears_in_its_quote():
    for doc, rows in F.ROWS.items():
        for target, page, quote, unit, cols, _ in rows:
            nums = [_num(m) for m in re.findall(r"\d+(?:[.,]\d+)?", quote)]
            for key, v in cols.items():
                assert any(abs(n - v) < 1e-9 for n in nums), (doc, page, target, key, v, quote)


def test_case_b_x_axis_numbers():
    """案例 B 的 X 轴要 2.5 m/s、12.5 m/s²：同步带 EGC-TB 达得到，丝杠 EGC-BS 达不到（最高 2 m/s、15 m/s²）"""
    comps = {c["model"]: c["params"] for c in F.build()[0]}
    tb80 = comps["EGC-80-TB-KF-GK"]
    assert tb80["max_speed_m_s"]["value"] == 5 and tb80["max_accel_m_s2"]["value"] == 50
    assert tb80["mass_kg"]["value"] == 3 and tb80["mass_per_10mm_stroke_kg"]["value"] == pytest.approx(0.062)
    assert tb80["lead_mm"]["value"] == 90 and tb80["max_thrust_n"]["value"] == 350
    assert max(p["max_speed_m_s"]["value"] for m, p in comps.items() if "-BS-" in m) == 2
    assert comps["EGC-80-BS-KF-20P-GK"]["lead_mm"]["value"] == 20
    assert "行程长了" in comps["EGC-185-BS-KF-40P-GK"]["max_speed_m_s"]["condition"]


def test_registered_sources_have_pinned_sha():
    src = yaml.safe_load((ROOT / "data" / "sources.yaml").read_text(encoding="utf-8"))
    docs = {d["id"]: d for s in src["sources"] for d in s.get("documents", [])}
    for doc in F.DOCS:
        assert len(docs[doc].get("sha256", "")) == 64


@pytest.mark.skipif(not all(p.exists() for p in F.DOCS.values()) or shutil.which("pdftotext") is None,
                    reason="费斯托目录 PDF（data/raw/festo/）或 pdftotext 不在")
def test_quotes_are_on_the_catalog_pages():
    src = yaml.safe_load((ROOT / "data" / "sources.yaml").read_text(encoding="utf-8"))
    docs = {d["id"]: d for s in src["sources"] for d in s.get("documents", [])}
    for doc, pdf in F.DOCS.items():
        assert hashlib.sha256(pdf.read_bytes()).hexdigest() == docs[doc]["sha256"]
        for _, page, quote, *_ in F.ROWS[doc]:
            assert quote in F.page_text(pdf, page), (doc, page, quote)
