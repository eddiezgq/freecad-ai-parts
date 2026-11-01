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


ROBOT = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
from hub import configurator as C
out = {{"ids": [t["id"] for t in C.templates()]}}
std = C.evaluate("WQ-CR5", {{}}, 2)
out["std"] = [std["ok"], std["design"], std["quote"]["unit_price"], std["quote"]["total"], std["warnings"]]
six = C.evaluate("WQ-CR5", {{"payload_kg": 6}})
out["six"] = [six["ok"], six["design"]["modules"], six["quote"]["unit_price"]]
out["ten"] = C.evaluate("WQ-CR5", {{"payload_kg": 10}})["ok"]
try:
    C.evaluate("WQR-105", {{}})
    out["wqr"] = "available"
except KeyError:
    out["wqr"] = "hidden"
glb, svg = C.model("WQ-CR5", {{"reach_mm": 1000}})
out["model"] = [glb[:4].decode(), svg.startswith(b"<svg")]
print(json.dumps(out, ensure_ascii=False))
"""


def test_robot_plant_cobot_template():
    """第 63 轮：机器人厂的配置器只有“协作臂定制”；默认参数就是标准 WQ-CR5（18000）；6 kg 时 J3 换大模组、加差价和非标费；
    10 kg 时没有够用的模组；减速器厂的模板在机器人厂不出现；三维和简图能生成"""
    import json
    import os
    import subprocess
    import sys
    dig = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fac = os.path.dirname(dig)
    env = dict(os.environ, WQ_PLANT_FILE=os.path.join(fac, "plants", "wenquest-robot.yaml"))
    r = subprocess.run([sys.executable, "-c", ROBOT.format(dig=dig, fac=fac)], capture_output=True, text=True, env=env, cwd=dig, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    assert out["ids"] == ["WQ-CR5"] and out["wqr"] == "hidden"
    ok, design, price, total, warn = out["std"]
    assert ok and design == {"a2": 0.4, "a3": 0.36, "modules": ["L", "L", "M", "S", "S", "S"], "standard": True}
    assert price == 18000 and total == 36000 and any("J3" in w for w in warn)
    assert out["six"][0] and out["six"][1] == ["L", "L", "L", "S", "S", "S"] and out["six"][2] == round((18000 + 500) * 1.08, 2)
    assert out["ten"] is False and out["model"] == ["glTF", True]
