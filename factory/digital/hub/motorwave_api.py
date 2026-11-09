# -*- coding: utf-8 -*-
"""电机终检波形（第 131 轮，电机厂）：终检过的每台电机。车间仿真在终检工位记 mt_ke 时带上终检波形的生成参数（种子、磁钢强度与位置、充磁系数、三相系数），
这里列出最近的电机，并按参数用 sim/motorwave.py 还原反电势波形和齿槽转矩曲线——和仿真算测量值用的是同一个函数，所以曲线和测量值一定对得上。"""
from sim import motorwave

ITEMS = ("WQ-SM100", "WQ-SM200", "WQ-SM400", "WQ-AM750")
CODES = ("mt_ke", "mt_unbal", "mt_thd", "mt_cog", "mt_i0", "st_r_unbal", "st_surge", "st_leak")


def _rows(db, mode, limit=6000):
    return db.messages(["quality.measurement"], mode=mode, order="desc", limit=limit)


def motors(db, mode, limit=80):
    """最近终检的电机（新的在前）：序列号、型号、工单、绕线机、主要测量与是否合格"""
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
        if d.get("characteristic") != "mt_ke" or not d.get("mw") or d["part_serial"] in seen:
            continue
        seen.add(d["part_serial"])
        out.append({"serial": d["part_serial"], "item": d.get("item"), "work_order": d.get("work_order"), "ts": m.get("ts"),
                    "winder": d.get("assembled_on"), "pass": all(r == "pass" for r in res.get(d["part_serial"], [])),
                    "meas": meas.get(d["part_serial"], {})})
        if len(out) >= limit:
            break
    return out


def motor(db, mode, serial):
    for m in _rows(db, mode):
        d = m["data"]
        if d.get("characteristic") == "mt_ke" and d.get("part_serial") == serial and d.get("mw"):
            g = motorwave.render(d["mw"])
            g.update({"serial": serial, "item": d.get("item"), "work_order": d.get("work_order"), "ts": m.get("ts"),
                      "winder": d.get("assembled_on"), "recorded_ke": d["value_mm"]})
            return g
    raise KeyError(serial)
