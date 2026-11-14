# -*- coding: utf-8 -*-
"""发布流水线与服务监控（第 167 轮，软件公司）。车间仿真在发布门禁记 sw_pass、rtos_irq、os_leak 时带上构建流水线模型的生成参数，
在服务验收记 cl_p99、cl_err 时带上 24 小时服务曲线的生成参数；这里列出最近的版本 / 订阅，并按参数用 sim/softsim.py 还原——
和仿真算测量值用的是同一个函数，所以页面上的曲线、测试数和测量记录一定对得上。"""
from sim import softsim

BUILD_CODES = ("sw_pass", "sw_cov", "rtos_irq", "rtos_boot", "os_leak", "os_boot", "api_p99")
SVC_CODES = ("cl_p99", "cl_err", "cl_avail")


def _rows(db, mode, limit=6000):
    return db.messages(["quality.measurement"], mode=mode, order="desc", limit=limit)


def _list(db, mode, items, codes, key_code, key, limit):
    rows = _rows(db, mode)
    meas, res = {}, {}
    for m in rows:
        d = m["data"]
        if d.get("item") in items:
            s = d["part_serial"]
            res.setdefault(s, []).append(d.get("result"))
            if d.get("characteristic") in codes:
                meas.setdefault(s, {}).setdefault(d["characteristic"], {"v": d["value_mm"], "result": d.get("result"),
                                                                         "hi": d.get("upper_tol_mm"), "lo": d.get("lower_tol_mm")})
    out, seen = [], set()
    for m in rows:
        d = m["data"]
        if d.get("characteristic") != key_code or not d.get(key) or d["part_serial"] in seen:
            continue
        seen.add(d["part_serial"])
        desc = d[key]
        out.append({"serial": d["part_serial"], "item": d.get("item"), "work_order": d.get("work_order"), "ts": m.get("ts"),
                    "runner": desc.get("runner") if key == "sw" else None, "bench": desc.get("bench") if key == "sw" else None,
                    "host": d.get("assembled_on"), "pass": all(r == "pass" for r in res.get(d["part_serial"], [])),
                    "meas": meas.get(d["part_serial"], {})})
        if len(out) >= limit:
            break
    return out


def builds(db, mode, limit=80):
    """最近通过发布门禁的版本（新的在前）：构建服务器、测试台、主要测量与是否合格"""
    return _list(db, mode, tuple(softsim.BUILD), BUILD_CODES, "sw_pass", "sw", limit)


def build(db, mode, serial):
    for m in _rows(db, mode):
        d = m["data"]
        if d.get("characteristic") == "sw_pass" and d.get("part_serial") == serial and d.get("sw"):
            g = softsim.build(d["sw"])
            g.update({"serial": serial, "work_order": d.get("work_order"), "ts": m.get("ts"), "recorded_pass": d["value_mm"],
                      "pass_lo": d.get("lower_tol_mm"), "stages": list(softsim.STAGES)})
            return g
    raise KeyError(serial)


def services(db, mode, limit=80):
    """最近验收的订阅（新的在前）：宿主机、可用区、主要测量与是否合格"""
    return _list(db, mode, tuple(softsim.SERVICE), SVC_CODES, "cl_p99", "svc", limit)


def service(db, mode, serial):
    for m in _rows(db, mode):
        d = m["data"]
        if d.get("characteristic") == "cl_p99" and d.get("part_serial") == serial and d.get("svc"):
            g = softsim.render_service(d["svc"])
            g.update({"serial": serial, "work_order": d.get("work_order"), "ts": m.get("ts"), "recorded_p99": d["value_mm"],
                      "limit": d.get("upper_tol_mm")})
            return g
    raise KeyError(serial)
