# -*- coding: utf-8 -*-
"""第 17 轮 D 期第 6 步：实验 15——比对模式、自动评分、老师注入缺料、指导书和报告模板、课程接口。"""
import json

import pytest
from psycopg.types.json import Jsonb

import wqbus
from tests.test_agent import env  # noqa: F401  —— 实验 7 情景

STU = {"name": "学生甲", "role": "planner", "teacher": False, "mode": "teach"}
TEA = {"name": "王老师", "role": "manager", "teacher": True, "mode": "teach"}


def _down(db):
    return db.one("select * from anomaly where rule='P1' and subject_key='grd-01' and status in ('open','ack','doing')")


def test_compare_mode_only_for_started_students(env):  # noqa: F811
    from hub import lab15
    H, eng = env
    db = H.db
    other = dict(STU, name="学生乙")
    assert not lab15.locked(db, other)                      # 没开始实验 15 的学生不受影响
    lab15.start(db, STU["name"])
    assert lab15.locked(db, STU) and not lab15.locked(db, TEA)
    # 代理的“比较方案”在比对模式下不给建议
    from hub.ont.agent import Tools, Run
    t = Tools(H, STU, Run(STU), locked=lambda u, aid=None: lab15.locked(db, u, aid))
    out = t.compare_options(anomaly_id=_down(db)["id"])
    assert "reason" not in out and all("recommended" not in o for o in out["options"])


def test_scoring_through_the_five_tasks(env):  # noqa: F811
    from hub import lab15
    from hub.ont import actions as AC
    from hub.ont import plan as P
    H, eng = env
    db = H.db
    a = _down(db)
    lab15.start(db, STU["name"])
    # 任务 1：按系统因果链答
    wos, sos = lab15._scope(db, a)
    base = lab15._base_late(db, a)
    r = lab15.answer(db, STU["name"], "l15_t1", {"anomaly_id": a["id"], "work_orders": sorted(wos), "sales_orders": sorted(sos),
                                                   "late_days": base if base is not None else 0})
    assert r["score"] == 15, r
    bad = lab15.answer(db, "学生丙", "l15_t1", {"anomaly_id": a["id"], "work_orders": [], "sales_orders": [], "late_days": 9})
    assert bad["score"] == 3 and "系统的因果链" in bad["feedback"]
    # 任务 2：保存 3 个不同的场景
    sid, st, _ = H.plan_snaps.take("teach")
    ctx = P.context(db, "teach", __import__("datetime").datetime.fromisoformat(st["factory_now"]))
    ids = []
    for title, ch in (("不处理", []), ("维修加急", [{"type": "expedite", "unit": "grd-01", "factor": 0.5}]),
                      ("调序", [{"type": "reorder", "unit": "grd-01", "work_order": "MFG-WO-2026-00016"}])):
        res = P.simulate(st, ch, ctx)
        ids.append(db.one("insert into scenario (mode, title, snapshot_id, changes, result, created_by, anomaly_id) values "
                          "('teach',%s,%s,%s,%s,%s,%s) returning id", (title, sid, Jsonb(ch), Jsonb(res), STU["name"], a["id"]))["id"])
    s = lab15.check(db, STU["name"])
    assert next(t for t in s["tasks"] if t["id"] == "l15_t2")["score"] == 15
    assert len(s["options"]["scenarios"]) == 3 and s["locked"]
    # 任务 3：理由太短不行；提交后比对模式解除
    assert lab15.answer(db, STU["name"], "l15_t3", {"scenario_id": ids[1], "reason": "加急"})["score"] == 0
    r3 = lab15.answer(db, STU["name"], "l15_t3", {"scenario_id": ids[1], "reason": "维修加急能按交期完成，比加班的成本低，风险是备件到货"})
    assert r3["score"] == 10 and not lab15.locked(db, STU)
    # 任务 4：学生发起的动作，老师批准执行
    ch = {"type": "expedite", "unit": "grd-01", "factor": 0.5}
    tr = AC.trial(db, H.plan_snaps, "teach", [ch], st)
    aid = AC.create(db, "teach", STU, "expedite", ch, ids[1], a["id"], tr)
    AC.submit(db, aid, STU, tr)
    assert next(t for t in lab15.check(db, STU["name"])["tasks"] if t["id"] == "l15_t4")["score"] == 6

    class Mes:
        def command(self, *a, **k):
            pass
    H2 = type("H", (), {"db": db, "mes": Mes(), "ai": H.ai})
    AC.approve(H2, aid, TEA, "王老师")
    assert next(t for t in lab15.check(db, STU["name"])["tasks"] if t["id"] == "l15_t4")["score"] == 10
    # 任务 5：复盘结论
    from hub.ont import retro as RT
    RT.init(db)
    assert lab15.answer(db, STU["name"], "l15_t5", {"bucket": lab15.BUCKETS[0]})["score"] == 0     # 还没有复盘
    db.x("insert into retro (mode, anomaly_id, title, deviation, partial) values ('teach', %s, '复盘', %s, false)",
         (a["id"], Jsonb({"finish_pct": 3.2})))
    assert lab15.answer(db, STU["name"], "l15_t5", {"bucket": lab15.BUCKETS[0]})["score"] == 10
    final = lab15.status(db, STU["name"])
    assert final["score"] == 60 == final["of"] and final["report_points"] == 40
    assert any(c["user"] == STU["name"] and c["total"] == 60 for c in lab15.class_view(db))


def test_teacher_injects_shortage(env):  # noqa: F811
    from hub import kpi, lab15
    from hub.historian import Historian
    H, eng = env
    h = Historian(H.db)

    class HH:
        db = H.db

        @staticmethod
        def publish(tp, ty, src, data, corr=None, mode=None):
            h.handle(tp, wqbus.make(ty, src, data, mode=mode or "teach", corr=corr))
    with pytest.raises(PermissionError):
        lab15.inject(HH, STU, "shortage", {"item": "RM-45-D50", "qty": 3})
    r = lab15.inject(HH, TEA, "shortage", {"item": "RM-45-D50", "qty": 3})
    assert "RM-45-D50" in r["text"]
    m = next(x for x in kpi.overview(H.db, None, "teach")["materials"] if x["code"] == "RM-45-D50")
    assert m["tone"] == "bad"


def test_lab15_documents_and_course_entry():
    pytest.importorskip("docx")
    from cae import labdoc
    g = labdoc.guide_docx("lab15")
    t = labdoc.report_template_docx("lab15")
    assert g[:2] == b"PK" and t[:2] == b"PK" and len(g) > 8000
    import io

    import docx
    text = "\n".join(p.text for p in docx.Document(io.BytesIO(g)).paragraphs)
    assert "比对模式" in text and "任务 5" in text
    src = open(__import__("hub.course", fromlist=["x"]).__file__, encoding="utf-8").read()
    assert '"id": "lab15"' in src and "/api/cae/lab15/guide.docx" in src
    _ = json
