# -*- coding: utf-8 -*-
"""电路板厂功能测试台（第 88 轮，电子 E4）：驱动板 DRV-JOINT 的出厂测试程序、每块板的测试记录复现、学生复测。

车间仿真在功能测试工位为每块板记下 6 个特性（quality.measurement）；这里把它们还原成测试程序每一步的“仪器读数”：
网页用第 82 轮的仪器模型把读数画成示波器、万用表画面。学生复测：自己读仪器、填读数、判合格与否；
平台按这块板的记录和测试规范核对，复测记录存进 fct_retest（单件档案），不改车间的原始测量值。"""
from __future__ import annotations

ITEM = "DRV-JOINT"
OP = "功能测试 FCT"
STEPS = [
    {"key": "ict_shunt", "title": "在线测试：采样电阻阻值", "inst": "dmm4w", "unit": "mΩ",
     "how": "四线法量 R21（A 相采样电阻）：电流线和电压线分开，导线电阻不进读数"},
    {"key": "fct_vbus", "title": "母线电压读数", "inst": "dmm", "unit": "%",
     "how": "程控电源给 48.00 V，万用表量板上 J1 两端；板子经 CAN 报它读到的母线电压。误差 = (板子读数 − 万用表) ÷ 万用表"},
    {"key": "fct_isense", "title": "相电流采样", "inst": "isrc", "unit": "%",
     "how": "电流源从 J2 的 U 相注入 10.00 A；板子报 A 相电流。误差 = (板子读数 − 10 A) ÷ 10 A"},
    {"key": "fct_deadtime", "title": "栅极死区", "inst": "scope", "unit": "ns",
     "how": "示波器 CH1 接 A 相上管栅极 GH_A、CH2 接下管栅极 GL_A；量一个下管关断到上管开通之间的空白（两条都低于 2 V 的时间）"},
    {"key": "fct_enc", "title": "编码器接口", "inst": "enc", "unit": "count",
     "how": "编码器模拟器在 J3 发 1000 个 A/B 正交脉冲（四倍频 4000 计数）；板子报计数，误差 = 板子读数 − 4000"},
    {"key": "fct_drift", "title": "老化后电流零点", "inst": "zero", "unit": "mA",
     "how": "不加电流，读板子报的 A 相电流（老化 2 小时之后测）"},
]
RETEST = ("ict_shunt", "fct_vbus", "fct_isense", "fct_deadtime")
TOL = {"ict_shunt": 0.002, "fct_vbus": 0.15, "fct_isense": 0.25, "fct_deadtime": 8.0}     # 复测读数与记录之差的允许范围（仪器分辨力 + 噪声）


def boards(db, mode, limit=60):
    rows = db.messages(["quality.measurement"], mode=mode, order="desc", limit=6000)
    out = {}
    for r in rows:
        d = r["data"]
        if d.get("item") != ITEM or d.get("operation") != OP:
            continue
        b = out.setdefault(d["part_serial"], {"serial": d["part_serial"], "ts": r["ts"], "work_order": d.get("work_order"),
                                              "lot": d.get("lot"), "fail": 0, "n": 0})
        b["n"] += 1
        b["fail"] += d["result"] == "fail"
    return list(out.values())[:limit]


def record(db, mode, serial):
    rows = db.messages(["quality.measurement"], mode=mode, order="desc", limit=6000)
    rec = {}
    meta = None
    for r in rows:
        d = r["data"]
        if d.get("part_serial") == serial and d.get("operation") == OP:
            rec.setdefault(d["characteristic"], {"value": d["value_mm"], "lo": d["lower_tol_mm"], "hi": d["upper_tol_mm"],
                                                 "nominal": d["nominal_mm"], "result": d["result"], "name": d.get("name") or d["characteristic"]})
            meta = meta or {"serial": serial, "item": d.get("item"), "ts": r["ts"], "work_order": d.get("work_order"), "lot": d.get("lot")}
    if not rec:
        raise KeyError(serial)
    return meta, rec


def case(db, mode, serial):
    """测试程序 + 这块板的“真值”（驱动仪器画面用）；学生看画面读数，提交复测后才显示车间记录"""
    meta, rec = record(db, mode, serial)
    steps = []
    for s in STEPS:
        r = rec.get(s["key"])
        if r is None:
            continue
        steps.append(dict(s, true=r["value"], lo=r["lo"], hi=r["hi"], nominal=r["nominal"]))
    return {"board": meta, "steps": steps, "retests": retests(db, serial)}


def retests(db, serial):
    return [{"ts": str(r["ts"]), "user": r["user_name"], "verdict": r["verdict"], "readings": r["readings"], "rows": r["check_rows"]}
            for r in db.q("select * from fct_retest where serial=%s order by ts desc limit 20", (serial,))]


def retest(db, mode, user, serial, readings, verdict):
    """学生复测：读数与这块板的记录比（允许仪器误差），合格判定与测试规范比；记进单件档案"""
    meta, rec = record(db, mode, serial)
    rows, all_in = [], True
    for k in RETEST:
        r = rec.get(k)
        if r is None:
            continue
        g = (readings or {}).get(k)
        try:
            x = float(g)
        except (TypeError, ValueError):
            x = None
        close = x is not None and abs(x - r["value"]) <= TOL[k]
        in_spec = r["lo"] <= r["value"] <= r["hi"]
        all_in = all_in and in_spec
        rows.append({"key": k, "given": g, "close": close, "in_spec": in_spec, "lo": r["lo"], "hi": r["hi"], "tol": TOL[k],
                     "recorded": r["value"]})
    right = "pass" if all_in else "fail"
    v = str(verdict or "").lower()
    out = {"rows": rows, "verdict": v, "verdict_ok": v == right, "all_close": all(r["close"] for r in rows),
           "should_be": right}
    from psycopg.types.json import Jsonb
    db.x("insert into fct_retest (mode, user_name, serial, item, readings, verdict, check_rows) values (%s,%s,%s,%s,%s,%s,%s)",
         (mode, user, serial, meta.get("item"), Jsonb(readings or {}), v, Jsonb(out)))
    return out
