# -*- coding: utf-8 -*-
"""整机老化曲线（第 166 轮，计算机厂）：做完整机功能测试的每台整机。车间仿真在整机功能测试记 pc_tmax 时带上老化曲线的生成参数
（种子、产品类型、硅脂层与散热器热阻、CPU 功耗系数），这里列出最近的整机，并按参数用 sim/burnin.py 还原老化曲线——
和仿真算测量值用的是同一个函数，所以曲线和测量值一定对得上。"""
from sim import burnin

ITEMS = tuple(burnin.ITEM_KIND)
CODES = ("pc_tmax", "pc_pavg", "pc_noise", "pc_boot", "pc_membw")


def _rows(db, mode, limit=6000):
    return db.messages(["quality.measurement"], mode=mode, order="desc", limit=limit)


def units(db, mode, limit=80):
    """最近测完的整机（新的在前）：序列号、型号、工单、点胶机、主要测量与是否合格"""
    rows = _rows(db, mode)
    meas, res = {}, {}
    for m in rows:
        d = m["data"]
        if d.get("item") in ITEMS:
            s = d["part_serial"]
            res.setdefault(s, []).append(d.get("result"))
            if d.get("characteristic") in CODES:
                meas.setdefault(s, {}).setdefault(d["characteristic"], {"v": d["value_mm"], "result": d.get("result"),
                                                                         "hi": d.get("upper_tol_mm"), "lo": d.get("lower_tol_mm")})
    out, seen = [], set()
    for m in rows:
        d = m["data"]
        if d.get("characteristic") != "pc_tmax" or not d.get("bi") or d["part_serial"] in seen:
            continue
        seen.add(d["part_serial"])
        out.append({"serial": d["part_serial"], "item": d.get("item"), "work_order": d.get("work_order"), "ts": m.get("ts"),
                    "dispenser": d.get("assembled_on"), "pass": all(r == "pass" for r in res.get(d["part_serial"], [])),
                    "meas": meas.get(d["part_serial"], {})})
        if len(out) >= limit:
            break
    return out


def unit(db, mode, serial):
    for m in _rows(db, mode):
        d = m["data"]
        if d.get("characteristic") == "pc_tmax" and d.get("part_serial") == serial and d.get("bi"):
            g = burnin.render(d["bi"])
            g.update({"serial": serial, "item": d.get("item"), "work_order": d.get("work_order"), "ts": m.get("ts"),
                      "dispenser": d.get("assembled_on"), "recorded_tmax": d["value_mm"], "limit": d.get("upper_tol_mm")})
            return g
    raise KeyError(serial)
