"""多通道（两个刀架同时干，ADR-0106 C4c、ADR-0123）：时间线、刀架互碰、节拍。

双主轴 + 两个刀架：通道 1（主主轴一侧）车第 n+1 件的右端，同时通道 2（副主轴一侧）车第 n 件的背面；两边都干完（等待 1）才交接
（接料、切断、副主轴退回，通道 1 做，通道 2 等），交接完（等待 2）下一循环。

- `track`：一个通道的刀路按 `sim.timing` 的每段时间排成时间线（换刀按机床的换刀时间原地停）。
- `clashes`：同时干的那段，按 STEP 秒一步取两个刀架的位置，在机床坐标里查：刀架 1（刀尖、刀杆、跟着它的部件）↔ 刀架 2，
  刀架 2 ↔ 主主轴的卡盘和棒料，刀架 1 ↔ 副主轴的卡盘和工件。干完的通道停在最后的位置。
- `report`：每个通道的切削、快移、换刀、等待时间，交接时间，循环节拍；同一个零件一个刀架干（单通道）的节拍。
"""

from __future__ import annotations

import bisect

import numpy as np

from analysis.cam import collide as CL
from analysis.cam import machine_model as MM
from analysis.cam import machine_sim as MS
from analysis.cam import sim

STEP = 0.05


def track(moves: list, m: dict, tip) -> dict:
    """moves：sim.parse 的刀路（已经 sim.timing 过，带 dt）；tip(x 直径, z) → 机床坐标的刀尖点。
    返回 {"segs": [(t0, t1, p0, p1, 刀号)], "total", "cut", "rapid", "tool"}"""
    tc = float(m.get("tool_change_s", 0.0))
    segs, t, cur, pos = [], 0.0, None, None
    cut = rap = tool = 0.0
    for mv in moves:
        if mv["tool"] != cur and mv["tool"]:
            p = pos if pos is not None else tip(mv["a"][0], mv["a"][2])
            segs.append((t, t + tc, p, p, mv["tool"]))
            t += tc
            tool += tc
            cur = mv["tool"]
        p0, p1 = tip(mv["a"][0], mv["a"][2]), tip(mv["b"][0], mv["b"][2])
        dt = float(mv["dt"])
        segs.append((t, t + dt, p0, p1, mv["tool"]))
        t += dt
        if mv["t"] == "rapid":
            rap += dt
        else:
            cut += dt
        pos = p1
    return {"segs": segs, "total": t, "cut": cut, "rapid": rap, "tool": tool}


def at(tr: dict, t: float):
    """t 时刻的 (刀尖点, 刀号)；超过末尾停在最后"""
    segs = tr["segs"]
    if not segs:
        return None, None
    i = min(bisect.bisect_right([s[0] for s in segs], t) - 1, len(segs) - 1)
    t0, t1, p0, p1, n = segs[max(i, 0)]
    u = 1.0 if t1 <= t0 else min(max((t - t0) / (t1 - t0), 0.0), 1.0)
    return p0 + (p1 - p0) * u, n


def _rz(box):
    return [-box[3], -box[4], box[2], -box[0], -box[1], box[5]]


def assembly(raw: dict, cid: int, cfg: dict, parsed: dict) -> dict:
    """一个刀架在机床坐标里跟着刀尖走的东西：每把刀的刀尖、刀杆（刀尖坐标里的长方体），跟着这个刀架的部件。
    返回 {"tools": {刀号: [(名, 形状)]}, "comps": [(名, 形状)], "gauge", "flip"}"""
    ch = next(c for c in MM.channels(raw) if c["id"] == cid)
    flip = next(a for a in raw["axes"] if a["id"] in ch["axes"] and abs(a["direction"][0]) > 0.5)["direction"][0] < 0
    specs, _notes = MS._lathe_specs(cfg, parsed)
    tools = {}
    for n, sp in specs.items():
        r = max(p["r"] for p in sp["parts"])
        items = [("刀尖", CL.Cylinder(np.zeros(3), np.array([0.0, 0.0, 1e-6]), r))]
        for bx in sp.get("boxes", []):
            items.append(("刀杆", CL.Box.from_minmax(_rz(bx["box"]) if flip else bx["box"])))
        tools[n] = items
    comps = []
    for c in raw.get("components") or []:
        if c.get("attached_to") in ch["axes"]:
            s = CL.shape(c)
            if s is not None:
                comps.append((c.get("name", c["id"]), s))
    return {"tools": tools, "comps": comps, "gauge": np.asarray(ch["tool"]["gauge_point_mm"], float)}


def _moved(s, d):
    T = np.eye(4)
    T[:3, 3] = d
    return s.moved(T)


def _placed(asm: dict, tip, n):
    out = [(nm, _moved(s, tip)) for nm, s in asm["tools"].get(n, [])]
    return out + [(nm, _moved(s, tip - asm["gauge"])) for nm, s in asm["comps"]]


def clashes(tr1: dict, tr2: dict, asm1: dict, asm2: dict, fixed1: list, fixed2: list, margin: float = 1.0) -> list:
    """同时干的那段（0 ~ 两边较长的那段），按 STEP 一步查。fixed1：通道 1 会碰到的不动的东西（副主轴的卡盘、工件）；
    fixed2：通道 2 会碰到的（主主轴的卡盘、棒料）。返回错误清单（同一对东西只报第一次）"""
    end = max(tr1["total"], tr2["total"])
    out, seen = [], set()
    k = 0
    while True:
        t = min(k * STEP, end)
        p1, n1 = at(tr1, t)
        p2, n2 = at(tr2, t)
        a1 = _placed(asm1, p1, n1) if p1 is not None else []
        a2 = _placed(asm2, p2, n2) if p2 is not None else []
        pairs = [(1, x, f"通道 2 的{y[0]}", y[1], n1) for x in a1 for y in a2]
        pairs += [(1, x, nm, s, n1) for x in a1 for nm, s in fixed1]
        pairs += [(2, x, nm, s, n2) for x in a2 for nm, s in fixed2]
        for c, (pa, sa), nb, sb, n in pairs:
            key = (c, pa, nb)
            if key in seen or not CL.hit(sa, sb, margin):
                continue
            seen.add(key)
            out.append({"line": None, "level": "error",
                        "text": f"两个刀架同时干时：通道 {c} 的{pa}（T{n}）碰到{nb}（第 {t:.2f} s）"})
        if t >= end:
            break
        k += 1
    return out


def report(t1: dict, tp: dict, tb: float, t2: dict) -> dict:
    """t1：通道 1 右端各工序（不含切断）；tp：切断；tb：副主轴移过来、夹持、退回；t2：通道 2 背面各工序。单位秒"""
    transfer = tp["total"] + tb
    par = max(t1["total"], t2["total"])
    cycle = par + transfer
    single = t1["total"] + t2["total"] + transfer
    r3 = lambda v: round(v, 3)
    return {"channels": [
        {"id": 1, "cut_s": r3(t1["cut"] + tp["cut"]), "rapid_s": r3(t1["rapid"] + tp["rapid"]), "tool_s": r3(t1["tool"] + tp["tool"]),
         "transfer_s": r3(transfer), "wait_s": r3(par - t1["total"])},
        {"id": 2, "cut_s": r3(t2["cut"]), "rapid_s": r3(t2["rapid"]), "tool_s": r3(t2["tool"]), "transfer_s": 0.0,
         "wait_s": r3(par - t2["total"] + transfer)}],
        "right_s": r3(t1["total"]), "back_s": r3(t2["total"]), "part_s": r3(tp["total"]), "sub_move_s": r3(tb),
        "transfer_s": r3(transfer), "cycle_s": r3(cycle), "single_s": r3(single)}


def timed(parsed: dict, m: dict) -> dict:
    sim.timing(parsed, m)
    return parsed
