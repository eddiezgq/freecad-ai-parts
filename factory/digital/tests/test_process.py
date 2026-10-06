# -*- coding: utf-8 -*-
"""第 13 轮：工艺规程——AI 工艺评审员的规则、提交—批注—批准—生效、MES 按生效工艺派工、工艺数据表副本与原件一致。"""
import copy
import os
from pathlib import Path

import pytest
import yaml

import wqbus

HERE = Path(__file__).resolve().parents[1]
PLAN = yaml.safe_load((HERE / "std" / "SH-301_process.yaml").read_text(encoding="utf-8"))
DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0] + "/wq_proc_test"


def plan():
    return copy.deepcopy(PLAN)


def rules(findings, level=None):
    return [(f["rule"], f["seq"]) for f in findings if level is None or f["level"] == level]


def op(p, name):
    return next(o for o in p["operations"] if o["operation"].startswith(name))


# ---------------------------------------------------------------- 规则
def test_the_reference_plan_passes_without_errors():
    from hub import process
    f = process.review(plan())
    assert rules(f, "error") == [], f
    assert rules(f, "warning") == [], f          # 键槽工序用 V 形块，不算精加工基准（精车、磨削都用中心孔）
    assert process.suggested_score(f) == 100


def test_order_rules():
    from hub import process
    p = plan()
    ops = p["operations"]
    ops[2], ops[5] = ops[5], ops[2]               # 磨外圆和调质对调：磨在热处理前
    for i, o in enumerate(ops):
        o["seq"] = 10 * (i + 1)
    f = process.review(p)
    texts = " ".join(x["text"] for x in f if x["level"] == "error")
    assert "磨削排在热处理之前" in texts and "调质排在精车之后" in texts
    p = plan()
    ops = p["operations"]
    ops[4], ops[5] = ops[5], ops[4]               # 键槽放到磨削之后
    for i, o in enumerate(ops):
        o["seq"] = 10 * (i + 1)
    assert any("铣键槽排在磨削之后" in x["text"] for x in process.review(p))
    p = plan()
    p["operations"].pop()                         # 没有检验
    assert any(x["rule"] == "完整" and "检验" in x["text"] for x in process.review(p))


def test_accuracy_allowance_and_drawing_rules():
    from hub import process
    p = plan()
    for f in op(p, "精车")["features"]:
        f["ei_mm"] = -0.016                       # 精车做到 IT6：超出经济精度（精车 IT7–IT8）
    assert any(x["rule"] == "精度" and "经济精度" in x["text"] for x in process.review(p))
    p = plan()
    op(p, "精车")["features"][0]["size_mm"] = 35.0    # 磨削没有余量
    assert any(x["rule"] == "余量" and x["level"] == "error" for x in process.review(p))
    p = plan()
    op(p, "磨外圆")["features"][0]["Ra_um"] = 1.6       # 达不到图纸 Ra 0.8
    assert any("达不到图纸" in x["text"] for x in process.review(p))


def test_cutting_power_and_time_rules():
    from hub import process
    p = plan()
    c = op(p, "粗车")["cut"]
    P, Fc, cite = process.cutting_power_kw("45", c)
    assert 3.5 < P < 4.5 and cite                               # 约 3.9 kW，出处来自 Kienzle 表
    c.update(ap_mm=6, f_mm_r=0.6, vc_m_min=200)            # 约 17 kW：超过 11 kW 的数控车床
    assert any(x["rule"] == "切削用量" for x in process.review(p))
    p = plan()
    op(p, "精车")["minutes"] = 0.5                         # 比基本时间还短
    assert any(x["rule"] == "工时" for x in process.review(p))
    p = plan()
    op(p, "粗车")["workstation"] = "滚齿机 HOB-01"
    assert any(x["rule"] == "工序与设备" for x in process.review(p))


# ---------------------------------------------------------------- 提交—批准—生效
@pytest.fixture()
def db():
    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(DSN.rsplit("/", 1)[0] + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_proc_test with (force)")
            c.execute("create database wq_proc_test")
    except psycopg.OperationalError:
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    d = DB(DSN)
    d.init()
    return d


def test_submit_review_approve_release_and_dispatch(db):
    from hub import process
    from hub.mes import MES
    out = []

    def emit(tp, type_, data):
        msg = wqbus.make(type_, "plm", data, mode="teach")
        db.insert_message(tp, msg)
        out.append((tp, msg))

    p = plan()
    op(p, "精车")["minutes"] = 13                 # 学生把精车工时从 15 优化到 13
    p["attachments"] = []                          # 没附计算书：AI 提一条建议
    s = process.submit(db, emit, "teach", "学生甲", "u1", p, "精车工时优化")
    assert s["status"] == "pending"                # 教学模式也进待审
    assert [c["author"] for c in s["comments"]] == [process.AI_REVIEWER]
    with pytest.raises(PermissionError):
        process.approve(db, emit, s["id"], "学生甲", approver_uid="u1")
    with pytest.raises(ValueError):                # 评审意见没处理不能批准
        process.approve(db, emit, s["id"], "老师", approver_uid="t1")
    process.resolve(db, s["id"], s["comments"][0]["id"])
    a = process.approve(db, emit, s["id"], "老师", "同意", approver_uid="t1")
    assert a["status"] == "approved" and a["revision"] == 1
    rel = [m for _, m in out if m["type"] == "process.release"][0]
    assert rel["data"]["total_minutes"] == 74 and rel["data"]["operations"][3]["minutes"] == 13
    assert process.active_routing(db, "teach", "SH-301")[3] == ["精车 Finish turning", 13]
    # MES 下达工单时按生效的工艺派工
    sent = []
    mes = MES(db, lambda tp, t, src, data, corr, mode: sent.append(data))
    db.insert_message("wq/gearbox/office/erp/doc", wqbus.make("erp.doc", "bridge", {
        "doctype": "Work Order", "name": "MFG-WO-T1", "action": "submitted", "production_item": "SH-301", "qty": 5,
        "docstatus": 1, "status": "Not Started"}, mode="teach"))
    mes.release("MFG-WO-T1", "teach", "老师")
    assert [d["std_min"] for d in sent][3] == 13 and sent[0]["routing"][3] == ["精车 Finish turning", 13]
    r = process.reject
    s2 = process.submit(db, emit, "teach", "学生乙", "u2", plan())
    with pytest.raises(ValueError):
        r(db, emit, s2["id"], "老师", "  ")
    assert r(db, emit, s2["id"], "老师", "工时没有依据")["status"] == "rejected"


def test_release_message_is_valid():
    m = wqbus.make("process.release", "plm", {"item": "SH-301", "revision": 1, "operations": [
        {"operation": "下料 Sawing", "workstation": "带锯床 SAW-01", "minutes": 3}]}, mode="teach")
    from wqbus import envelope
    envelope.validate(m)
    with pytest.raises(envelope.ValidationError):                  # 生效的工艺规程不能没有工序
        wqbus.make("process.release", "plm", {"item": "SH-301", "revision": 1, "operations": []}, mode="teach")


def test_the_factory_copy_of_the_tables_is_identical_to_the_textbook():
    """factory/digital/std 是教材原件的副本（工厂镜像看不到 textbook/）；改原件后运行 std/sync.py。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("wqsync", HERE / "std" / "sync.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    for src, dst in m.FILES.items():
        if not src.exists():
            pytest.skip("不在完整的问渠仓库里")
        assert src.read_bytes() == dst.read_bytes(), "{} 与原件不同：运行 python3 factory/digital/std/sync.py".format(dst.name)


def test_v2_checks_inspection_locating_chains_and_sketch():
    """第 13 轮 N5：漏检验项目、定位误差过大、尺寸链算不通、工序简图与工序尺寸不一致，评审员都能查出。"""
    from hub import process
    p = plan()
    fin = op(p, "零件检验")
    fin["inspect"] = [i for i in fin["inspect"] if i["char"] != "C6"]
    assert ("检验", None) in rules(process.review(p), "error")
    p = plan()
    op(p, "铣键槽")["locate_check"]["Td"] = 0.5     # 直接用毛坯外圆定位：下母线基准的误差 Td/(2 sin45°) − Td/2 ≈ 0.10 > 0.17/3
    assert ("定位误差", 50) in rules(process.review(p))
    p = plan()
    p["chains"][0]["links"][0]["ei"] = -0.25                          # 槽底尺寸公差放宽：d − t 保证不了
    assert ("尺寸链", None) in rules(process.review(p), "error")
    p = plan()
    op(p, "精车")["features"][0]["size_mm"] = 35.4
    assert ("工序简图", 40) in rules(process.review(p), "warning")
