# -*- coding: utf-8 -*-
"""编码器误差曲线（第 125 轮，传感器厂）：终检过的每台编码器。车间仿真在终检工位记 enc_acc 时带上误差曲线的生成参数（种子、偏心、幅值、污点……），
这里列出最近的编码器，并按参数用 sim/enccurve.py 还原整条曲线——和仿真算测量值用的是同一个函数，所以曲线和测量值一定对得上。"""
from sim import enccurve

ITEM = "WQ-ENC17"
CODES = ("enc_acc", "enc_h1", "enc_interp", "enc_amp", "enc_amp_min")


def _rows(db, mode, limit=4000):
    return db.messages(["quality.measurement"], mode=mode, order="desc", limit=limit)


def encoders(db, mode, limit=80):
    """最近终检的编码器（新的在前）：序列号、工单、粘接对心机、五项测量与是否合格"""
    rows = _rows(db, mode)
    meas = {}
    for m in rows:
        d = m["data"]
        if d.get("item") == ITEM and d.get("characteristic") in CODES:
            meas.setdefault(d["part_serial"], {}).setdefault(d["characteristic"], {"v": d["value_mm"], "result": d.get("result"),
                                                                                   "hi": d.get("upper_tol_mm"), "lo": d.get("lower_tol_mm")})
    out, seen = [], set()
    for m in rows:
        d = m["data"]
        e = d.get("enc")
        if d.get("characteristic") != "enc_acc" or not e or d["part_serial"] in seen:
            continue
        seen.add(d["part_serial"])
        mm = meas.get(d["part_serial"], {})
        out.append({"serial": d["part_serial"], "work_order": d.get("work_order"), "ts": m.get("ts"), "station": e.get("station"),
                    "pass": all(x.get("result") == "pass" for x in mm.values()), "meas": mm, "spots": len(e.get("spots") or [])})
        if len(out) >= limit:
            break
    return out


def encoder(db, mode, serial):
    for m in _rows(db, mode):
        d = m["data"]
        if d.get("characteristic") == "enc_acc" and d.get("part_serial") == serial and d.get("enc"):
            g = enccurve.render(d["enc"])
            g.update({"serial": serial, "work_order": d.get("work_order"), "ts": m.get("ts"), "station": d["enc"].get("station"),
                      "recorded_acc": d["value_mm"], "acc_hi": d.get("upper_tol_mm")})
            return g
    raise KeyError(serial)
