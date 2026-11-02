# -*- coding: utf-8 -*-
"""工艺路线的检查与计算（第 13 轮十二；《机械制造技术》第 56 章）：SH-101 的参照路线没有“路线”意见，
各种排错的路线被找出来；加工方案链与临界批量。"""
import copy
import os

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REF = yaml.safe_load(open(os.path.join(HERE, "..", "std", "SH-101_route.yaml"), encoding="utf-8"))


def plan():
    return copy.deepcopy(REF)


def review(p):
    from hub import process
    return process.review(p)


def route_texts(p, level=None):
    return [f["text"] for f in review(p) if f["rule"] == "路线" and (level is None or f["level"] == level)]


def op(p, seq):
    return next(o for o in p["operations"] if o["seq"] == seq)


def move(p, seq, before):
    o = op(p, seq)
    p["operations"].remove(o)
    i = p["operations"].index(op(p, before))
    p["operations"].insert(i, o)
    for k, x in enumerate(p["operations"]):
        x["seq"] = 10 * (k + 1)


def test_reference_route_is_clean():
    f = review(plan())
    assert not [x for x in f if x["level"] in ("error", "warning")], f


def test_keyway_and_hobbing_after_carburizing():
    p = plan()
    move(p, 50, 80)                      # 铣键槽挪到渗碳淬火、磨削之后
    assert any("铣键槽排在渗碳淬火之后" in t for t in route_texts(p, "error"))
    p = plan()
    move(p, 40, 70)
    assert any("滚齿排在渗碳淬火之后" in t for t in route_texts(p, "error"))


def test_missing_grinding_after_hardening():
    p = plan()
    p["operations"] = [o for o in p["operations"] if o["seq"] != 70]
    t = " ".join(route_texts(p, "error"))
    assert "热处理之后没有磨削" in t and "轴承位" in t


def test_center_holes_must_be_lapped():
    p = plan()
    op(p, 70)["content"] = "两顶尖装夹，粗磨、精磨两处轴承位、密封轴颈和轴伸"
    assert any("修研中心孔" in t for t in route_texts(p, "warning"))


def test_skipped_step_and_small_grinding_allowance():
    p = plan()
    for o in p["operations"]:
        if o["seq"] == 30:
            o["features"] = [f for f in o["features"] if f["name"] != "轴承位"]
    assert any("轴承位" in t and "跳级" in t for t in route_texts(p, "warning"))
    p = plan()
    f = next(x for x in op(p, 30)["features"] if x["name"] == "轴承位")
    f["size_mm"] = 25.12
    assert any("磨削余量" in t for t in route_texts(p, "warning"))


def test_blank_checks():
    p = plan()
    p["blank"]["spec"] = "Ø54"
    assert any("棒料" in t for t in route_texts(p, "error"))
    p = plan()
    p["blank"] = {"kind": "模锻件", "spec": "按毛坯图"}
    assert any("正火" in t for t in route_texts(p, "warning"))
    p["blank"]["heat"] = "正火"
    assert not any("正火" in t for t in route_texts(p))


def test_drawing_comes_from_the_part_file():
    """学生把图纸要求写松了也没用：评审员按 std/SH-101_part.yaml 核对"""
    p = plan()
    p["drawing"] = [{"name": "轴承位", "size_mm": 25, "es_mm": 0.1, "ei_mm": -0.1, "Ra_um": 3.2}]
    f = next(x for x in op(p, 70)["features"] if x["name"] == "轴承位")
    f["es_mm"], f["ei_mm"] = 0.05, -0.05
    assert any("不在图纸要求" in x["text"] for x in review(p))


def test_aux_operations():
    p = plan()
    for o in p["operations"]:
        o.pop("aux", None)
    t = " ".join(route_texts(p, "warning"))
    assert "去毛刺" in t and "清洗" in t


def test_chains_and_critical_batch():
    from hub import route as R
    c = R.chains("外圆", 6, 0.8, hardened=True)
    assert c and c[0]["heat_at"] is not None and "热处理" in c[0]["zh"] and c[0]["zh"].endswith("精磨")
    assert R.chains("齿面", 8, None, hardened=True)[0]["zh"] == "滚齿 → 热处理"
    assert R.check_chain(["od_rough_turn", "od_finish_grind"], 6, 0.8)          # 跳级
    a = R.route_cost(REF["operations"], 100)
    assert a["bottleneck"] and a["cost"] > 0
    few = [dict(o, setup_min=o.get("setup_min", 0) * 4, minutes=o["minutes"] * 0.7) for o in REF["operations"]]
    n = R.critical_batch(REF["operations"], few)
    assert n and n > 0
    a1, s1 = R.cost_line(REF["operations"])
    a2, s2 = R.cost_line(few)
    assert abs((a1 + s1 / n) - (a2 + s2 / n)) < 1e-6


def test_sh101_models():
    """三维模型：各工序状态的体积逐道变小，成品有齿形和键槽"""
    import pytest
    pytest.importorskip("build123d")
    from models3d import route3d as X
    v = [X.sh101(s).shape.volume for s in ("blank", "op20", "op30", "op40", "op50", "op70")]
    assert all(a > b for a, b in zip(v, v[1:-1]))
    assert v[-1] < v[3]
    assert len(X.involute_gear()) == 24 * (2 * 9 + 2)
