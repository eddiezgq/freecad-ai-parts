# -*- coding: utf-8 -*-
"""第 8 轮 Q6：参数配置器——默认参数校核通过、超载拦下、非标传动比加价、两级中心距不变、三维和图纸能生成、参数夹到范围内。"""
import pytest

from hub import configurator as C


def test_templates_and_defaults():
    ids = [t["id"] for t in C.templates()]
    assert ids == ["SH-301", "WQR-105"]
    for t in ids:
        r = C.evaluate(t, {}, 2)
        assert r["ok"] and not r["errors"], (t, r["errors"])
        assert r["quote"]["qty"] == 2 and r["quote"]["total"] == pytest.approx(r["quote"]["unit_price"] * 2)


def test_reducer_rules():
    for r in C.ratios():                                   # 两级中心距不变（壳体通用）
        z1, z2, z3, z4 = r["z"]
        assert C.M1 * (z1 + z2) / 2 == C.A1 and C.M2 * (z3 + z4) / 2 == C.A2
    std = C.evaluate("WQR-105", {})
    assert std["quote"]["unit_price"] == 1650.0 and dict(std["figures"])["传动比"] == "10.50"
    big = C.evaluate("WQR-105", {"power_kw": 7.5})
    assert not big["ok"] and "额定" in big["errors"][0]
    other = C.evaluate("WQR-105", {"ratio": C.ratios()[0]["key"], "power_kw": 7.5})     # 传动比小，转矩小
    assert other["ok"] and other["quote"]["unit_price"] > 1650.0                       # 非标加价
    assert C.values("WQR-105", {"power_kw": 99, "n1": 123})["power_kw"] == 11 and C.values("WQR-105", {"n1": 123})["n1"] == 1450


def test_shaft_and_models():
    bad = C.evaluate("SH-301", {"kw_l": 70})
    assert not bad["ok"] and "超过该轴段长度" in bad["errors"][0]
    pytest.importorskip("build123d")
    for t in ("SH-301", "WQR-105"):
        glb, svg = C.model(t, {})
        assert glb[:4] == b"glTF" and svg.startswith(b"<svg")
    assert C.model_key("SH-301", {}) == C.model_key("SH-301", {"d1": 30}) != C.model_key("SH-301", {"d1": 32})
