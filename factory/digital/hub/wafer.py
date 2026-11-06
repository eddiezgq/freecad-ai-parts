# -*- coding: utf-8 -*-
"""晶圆图（第 103 轮，芯片封测厂）：CP 做完的每片晶圆。车间仿真在 CP 工位记 cp_yield 时带上晶圆图的生成参数（种子、各测试位接触电阻……），
这里列出最近的晶圆，并按参数用 sim/wafermap.py 还原整张图（每颗芯片的分档）——和仿真算良率用的是同一个函数，所以图和良率一定对得上。"""
from sim import wafermap

ITEM = "WAF-ENCIF-CP"


def _rows(db, mode, limit=4000):
    return db.messages(["quality.measurement"], mode=mode, order="desc", limit=limit)


def wafers(db, mode, limit=60):
    """最近 CP 完的晶圆（新的在前）：片号、工单、良率、各测试位失效率、分档统计，以及同一片的其他 CP 测量"""
    rows = _rows(db, mode)
    other = {}
    for m in rows:
        d = m["data"]
        if d.get("item") == ITEM and d.get("characteristic") != "cp_yield":
            other.setdefault(d["part_serial"], {})[d["characteristic"]] = {"v": d["value_mm"], "result": d.get("result"), "unit": d.get("unit")}
    out, seen = [], set()
    for m in rows:
        d = m["data"]
        w = d.get("wafer")
        if d.get("characteristic") != "cp_yield" or not w or d["part_serial"] in seen:
            continue
        seen.add(d["part_serial"])
        sf = w.get("site_fail_pct") or []
        worst = max(range(len(sf)), key=lambda i: sf[i]) if sf else None
        out.append({"serial": d["part_serial"], "work_order": d.get("work_order"), "ts": m.get("ts"), "yield_pct": d["value_mm"],
                    "pass": d.get("result") == "pass", "site_fail_pct": sf, "by_bin": w.get("by_bin"), "total": w.get("total"),
                    "worst_site": worst + 1 if worst is not None else None, "site_rc": w.get("site_rc"),
                    "meas": other.get(d["part_serial"], {})})
        if len(out) >= limit:
            break
    return out


def wafer(db, mode, serial):
    for m in _rows(db, mode):
        d = m["data"]
        if d.get("characteristic") == "cp_yield" and d.get("part_serial") == serial and d.get("wafer"):
            w = d["wafer"]
            g = wafermap.render(w)
            g.update({"serial": serial, "work_order": d.get("work_order"), "ts": m.get("ts"), "site_rc": w.get("site_rc"),
                      "recorded_yield_pct": d["value_mm"], "sites": wafermap.SITES})
            return g
    raise KeyError(serial)
