"""数控编程（ADR-0059，M11 第二步）：阶梯轴车削、2.5 轴铣削生成 FANUC 风格 G 代码；读任意 FANUC 风格 G 代码（包括 FreeCAD CAM
工作台输出的）算加工时间、仿真切削、检查撞料、过切 / 残留、超程、转速、切削功率。搬自问渠数字工厂第 13 轮。

设置（单位 mm、m/min、mm/r、mm/min）：
  mode: "turn" | "mill" | "check"；machine: 机床 id（analysis/cam/machines.py：示例机床为虚构，企业在 machines.yaml 填自己的）
  kienzle: Kienzle 表行（analysis/common/kienzle.yaml 的 key）；不填时切削功率为待确认
  turn：segments [[直径, 长度], ..]（从左到右）、chamfer_mm、stock_d_mm（毛坯直径；缺省 = 最大直径 + 4 向上取整）、
        face_allow_mm（每端车端面余量，缺省 1）、finish_allow_mm（粗车单边留量，缺省 0.5）、max_rpm（G50 限速，缺省 3000 与机床取小）、
        cut: {"rough": {"vc", "f", "ap"}, "finish": {"vc", "f"}}（缺省见 DEFAULT_CUT）
        先车右端到最大直径段，调头再车左端；每次装夹一个程序，粗车 T01、精车 T02。
  mill：stock: {"box": [x0, y0, x1, y1]}（上表面 Z0）；features: [
          {"type": "slot", "a": [x, y], "b": [x, y], "width", "depth"},
          {"type": "pocket", "rect": [x0, y0, x1, y1], "corner_r", "depth"},
          {"type": "contour", "rect": [..], "corner_r", "depth"},
          {"type": "holes", "d", "points": [[x, y], ..], "depth"}]，每项可给 tool_d 与 cut（缺省见 DEFAULT_CUT）
  check：gcode（程序文本）；可选 stock（车：{"d", "z_right", "z_left"}；铣：{"box"}）与 tools（{刀号: {"kind": "turn" | "groove" | "endmill" |
         "drill", "d" 或 "w"}}）——给了毛坯才仿真
结果 data：programs [{title, gcode, time（cut_s、rapid_s、tool_s、total_s）, checks [{line, level, text}], sim, power}]、
  total_time_s、verdict（error / warn / unknown / ok：检查中最严重的一级）、machine（id、name、example）。
"""

from __future__ import annotations

import math
import time

from analysis.cam import machines as M
from analysis.cam import paths as P
from analysis.cam import post, power, sim
from analysis.common import result

MODULE = {
    "id": "cam", "name": "数控编程", "version": "1",
    "description": "阶梯轴车削、2.5 轴铣削生成 G 代码；检查任意 FANUC 风格程序：时间、仿真、撞料、过切、超程、切削功率",
    "python": ["numpy", "yaml"], "solvers": [],
    "install": '安装：pip install -e ".[fea]"（numpy）',
}
# 缺省切削参数：教学示意值（45 钢、硬质合金车刀 / 立铣刀，高速钢键槽铣刀、麻花钻），搬自数字工厂第 13 轮；按刀具样本改
DEFAULT_CUT = {
    "turn_rough": {"vc": 120.0, "f": 0.3, "ap": 2.5},
    "turn_finish": {"vc": 150.0, "f": 0.15},
    "slot": {"vc": 25.0, "fz": 0.03, "z": 2, "ap": 1.0},
    "endmill": {"vc": 100.0, "fz": 0.04, "z": 4, "ap_d": 0.5, "stepover": 0.45},
    "drill": {"vc": 20.0, "f": 0.12},
}
ENDMILLS = (20.0, 16.0, 12.0, 10.0, 8.0, 6.0, 5.0, 4.0, 3.0)
LEVEL = {"error": 3, "warn": 2, "unknown": 1}
LIMITS = ["仿真按刀尖、平底刀简化：车刀刀尖圆弧按 0，钻头按平底，不计刀具变形与让刀",
          "缺省切削参数是教学示意值（45 钢），实际按刀具样本与材料改",
          "机床行程、功率按所选机床的参数；示例机床是虚构的"]


class SetupError(ValueError):
    pass


def _verdict(progs):
    worst = max((LEVEL.get(c["level"], 0) for p in progs for c in p["checks"]), default=0)
    return {3: "error", 2: "warn", 1: "unknown", 0: "ok"}[worst]


def _cut(given, default):
    return {**default, **(given or {})}


# ---------------------------------------------------------------- 车削
def _turn(setup, mach):
    if mach["kind"] != "lathe":
        raise SetupError(f"{mach['name']} 不是车床")
    segs = [[float(d), float(seg_len)] for d, seg_len in setup.get("segments") or []]
    prof = P.design_profile(segs, float(setup.get("chamfer_mm", 0)))
    total = prof[-1][0]
    dmax = max(d for _, d in prof)
    stock_d = float(setup.get("stock_d_mm") or math.ceil(dmax + 4))
    if stock_d < dmax:
        raise SetupError(f"毛坯直径 {stock_d:g} 小于零件最大直径 {dmax:g}")
    e = float(setup.get("face_allow_mm", 1.0))
    allow = float(setup.get("finish_allow_mm", 0.5))
    cut = setup.get("cut") or {}
    rough, fin = _cut(cut.get("rough"), DEFAULT_CUT["turn_rough"]), _cut(cut.get("finish"), DEFAULT_CUT["turn_finish"])
    max_rpm = min(float(setup.get("max_rpm", 3000)), mach["max_rpm"])
    progs = []
    for k, side in enumerate(("right", "left")):
        tgt, reach = P.setup_profile(prof, side)
        if not tgt:
            continue
        mv_r = (P.turn_face(stock_d, e, max(min(rough["ap"], 2.0), 0.2), rough["f"]) if e > 1e-3 else []) + \
            P.turn_rough(tgt, stock_d, rough["ap"], rough["f"], allow, 0.1)
        mv_f = P.turn_finish(tgt, stock_d, fin["f"])
        title = "右端（第一次装夹）" if side == "right" else "左端（调头装夹）"
        prog = {"number": 1001 + k, "title": f"{setup.get('item') or '阶梯轴'} 车削 {title}",
                "header": {"item": setup.get("item"), "stock": f"Ø{stock_d:g}×{total + 2 * e:g}"},
                "ops": [{"tool": {"n": 1, "name": "外圆粗车刀"}, "spindle": {"css": rough["vc"], "max_rpm": max_rpm}, "moves": mv_r,
                         "title": "粗车"},
                        {"tool": {"n": 2, "name": "外圆精车刀"}, "spindle": {"css": fin["vc"], "max_rpm": max_rpm}, "moves": mv_f,
                         "title": "精车"}]}
        g = post.post(prog, mach)
        parsed = sim.parse(g, mach)
        checks = sim.machine_checks(parsed, mach)
        tm = sim.timing(parsed, mach)
        stock = {"d": stock_d, "z_right": e, "z_left": -(total + e)}
        s = sim.simulate_turn(parsed, stock, {1: {"kind": "turn"}, 2: {"kind": "turn"}}, target=tgt)
        checks += s["issues"]
        if s.get("under_mm", 0) > 0.05:
            checks.append({"line": None, "level": "error", "text": f"残留：最多 {s['under_mm']:.3f} mm（半径），Z{s['under_z'][0]:.2f} ~ Z{s['under_z'][1]:.2f}"})
        if s.get("face_left", 0) > 0.01:
            checks.append({"line": None, "level": "error", "text": "端面没车干净"})
        ap = {t: max((m.get("ap", 0.0) for m in parsed["moves"] if m["tool"] == t), default=0.0) for t in (1, 2)}
        pw, pdet = power.check(setup.get("kienzle"), mach, [
            ("粗车", "turn", {"vc": rough["vc"], "f": rough["f"], "ap": max(ap[1], 1e-3)}),
            ("精车", "turn", {"vc": fin["vc"], "f": fin["f"], "ap": max(ap[2], 1e-3)})])
        checks += pw
        progs.append({"title": title, "side": side, "number": prog["number"], "gcode": g, "time": tm, "checks": checks,
                      "sim": {"dev_min_mm": round(s.get("dev_min", 0.0), 4), "dev_max_mm": round(s.get("dev_max", 0.0), 4),
                              "under_mm": round(s.get("under_mm", 0.0), 4), "ap_max_mm": {"rough": round(ap[1], 3), "finish": round(ap[2], 3)},
                              "reach_mm": reach},
                      "power": pdet, "target": [[float(z), float(d)] for z, d in tgt]})
    return progs, {"profile": [[float(t), float(d)] for t, d in prof], "stock_d_mm": stock_d, "length_mm": total}


# ---------------------------------------------------------------- 铣削
def _sdf_rrect(X, Y, rect, r):
    import numpy as np

    x0, y0, x1, y1 = rect
    cx, cy, hw, hh = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    r = max(0.0, min(r, hw, hh))
    qx, qy = np.abs(X - cx) - (hw - r), np.abs(Y - cy) - (hh - r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def _sdf_seg(X, Y, a, b, r):
    import numpy as np

    ax, ay = a
    bx, by = b
    vx, vy = bx - ax, by - ay
    t = np.clip(((X - ax) * vx + (Y - ay) * vy) / max(vx * vx + vy * vy, 1e-12), 0, 1)
    return np.hypot(X - (ax + t * vx), Y - (ay + t * vy)) - r


def _mill_target(features):
    import numpy as np

    def target(X, Y):
        T = np.zeros_like(X)
        band = np.zeros(X.shape, bool)
        for f in features:
            if f["type"] == "contour":
                sd = -_sdf_rrect(X, Y, f["rect"], f.get("corner_r", 0))  # 外面是要铣掉的
            elif f["type"] == "pocket":
                sd = _sdf_rrect(X, Y, f["rect"], f.get("corner_r", 0))
            elif f["type"] == "slot":
                sd = _sdf_seg(X, Y, f["a"], f["b"], f["width"] / 2)
            else:
                sd = np.min([np.hypot(X - x, Y - y) - f["d"] / 2 for x, y in f["points"]], axis=0)
            T = np.where(sd < -0.05, np.minimum(T, -f["depth"]), T)
            band |= np.abs(sd) <= 0.05
        T[band] = np.nan
        return T

    return target


def _mill(setup, mach):
    if mach["kind"] != "mill":
        raise SetupError(f"{mach['name']} 不是铣床 / 加工中心")
    stock = setup.get("stock") or {}
    if len(stock.get("box") or []) != 4:
        raise SetupError("铣削要给毛坯 stock.box = [x0, y0, x1, y1]")
    box = [float(v) for v in stock["box"]]
    feats = setup.get("features") or []
    if not feats:
        raise SetupError("没有要加工的特征")
    ops, tools, items = [], {}, []
    for n, f in enumerate(feats, 1):
        kind = f.get("type")
        depth = float(f.get("depth", 0))
        if depth <= 0:
            raise SetupError(f"第 {n} 项深度要大于 0")
        if kind == "holes":
            c = _cut(f.get("cut"), DEFAULT_CUT["drill"])
            d = float(f.get("tool_d") or f["d"])
            rpm = P.spindle_rpm(c["vc"], d, mach["max_rpm"])
            feed = round(c["f"] * rpm, 1)
            mv = P.drill([tuple(p) for p in f["points"]], depth, round(d, 3) if depth > 3 * d else 0.0, feed)
            tools[n] = {"kind": "drill", "d": d}
            name = f"钻孔 Ø{d:g}"
            items.append((name, "drill", {"vc": c["vc"], "f": c["f"], "d": d}))
        elif kind == "slot":
            c = _cut(f.get("cut"), DEFAULT_CUT["slot"])
            d = float(f.get("tool_d") or f["width"])
            rpm = P.spindle_rpm(c["vc"], d, mach["max_rpm"])
            feed = round(P.mill_feed(c["fz"], c["z"], rpm), 1)
            mv = P.mill_slot(f["a"], f["b"], float(f["width"]), depth, d, c["ap"], feed, feed)
            tools[n] = {"kind": "endmill", "d": d}
            name = f"铣槽 宽 {f['width']:g}"
            items.append((name, "mill", {"fz": c["fz"], "ap": min(c["ap"], depth), "ae": d, "d": d, "vf": feed}))
        elif kind in ("pocket", "contour"):
            c = _cut(f.get("cut"), DEFAULT_CUT["endmill"])
            x0, y0, x1, y1 = (float(v) for v in f["rect"])
            cr = float(f.get("corner_r", 0))
            if f.get("tool_d"):
                d = float(f["tool_d"])
            elif kind == "contour":
                d = 10.0
            else:
                lim = min(x1 - x0, y1 - y0) * (1 if cr > 0 else 1 / 3)
                fit = [t for t in ENDMILLS if t <= lim and (cr <= 0 or t <= 2 * cr + 1e-9)]
                d = fit[0] if fit else ENDMILLS[-1]
            rpm = P.spindle_rpm(c["vc"], d, mach["max_rpm"])
            feed = round(P.mill_feed(c["fz"], c["z"], rpm), 1)
            ap = c.get("ap") or d * c["ap_d"]
            if kind == "pocket":
                mv = P.mill_pocket((x0, y0, x1, y1), cr, depth, d, c["stepover"], ap, feed, round(feed / 3, 1))
                name = "铣型腔"
                ae = d
            else:
                mv = P.mill_contour((x0, y0, x1, y1), cr, depth, d, ap, feed)
                name = "铣外轮廓"
                ae = max(0.1, min(d, x0 - box[0], y0 - box[1], box[2] - x1, box[3] - y1))
            tools[n] = {"kind": "endmill", "d": d}
            items.append((name, "mill", {"fz": c["fz"], "ap": min(ap, depth), "ae": ae, "d": d, "vf": feed}))
        else:
            raise SetupError(f"第 {n} 项类型 {kind!r} 不认识：slot、pocket、contour、holes")
        f["tool_d"] = d
        ops.append({"tool": {"n": n, "name": ("麻花钻" if kind == "holes" else "立铣刀") + f" Ø{d:g}", "d": d},
                    "spindle": {"rpm": round(rpm)}, "moves": mv, "title": name})
    prog = {"number": 5001, "title": f"{setup.get('item') or '零件'} 铣削", "header": {"item": setup.get("item")}, "ops": ops}
    g = post.post(prog, mach)
    parsed = sim.parse(g, mach)
    checks = sim.machine_checks(parsed, mach)
    tm = sim.timing(parsed, mach)
    s = sim.simulate_mill(parsed, {"box": box, "top": 0.0}, tools, _mill_target(feats))
    checks += s["issues"]
    under = int(s["under_mask"].sum()) if "under_mask" in s else 0
    if under:
        checks.append({"line": None, "level": "warn",
                       "text": f"残留：{under} 格比目标高，最多 {s['dev_max']:.3f} mm（型腔转角圆角小于刀具半径时转角会留料）"})
    pw, pdet = power.check(setup.get("kienzle"), mach, items)
    checks += pw
    return [{"title": "铣削", "number": 5001, "gcode": g, "time": tm, "checks": checks, "power": pdet,
             "sim": {"over_cells": s.get("over", 0), "under_cells": under, "dev_min_mm": round(s.get("dev_min", 0.0), 4),
                     "dev_max_mm": round(s.get("dev_max", 0.0), 4), "ap_max_mm": round(s["ap_max"], 3), "cell_mm": round(s["h"], 4)},
             "tools": {str(k): v for k, v in tools.items()}}], {}


# ---------------------------------------------------------------- 检查已有程序
def _check(setup, mach):
    text = setup.get("gcode") or ""
    if not text.strip():
        raise SetupError("没有 G 代码")
    parsed = sim.parse(text, mach)
    if not parsed["moves"]:
        raise SetupError("程序里没有读到运动")
    checks = sim.machine_checks(parsed, mach)
    tm = sim.timing(parsed, mach)
    out = {"title": "检查", "gcode": text, "time": tm, "checks": checks, "power": {"status": "unknown"},
           "tools_used": parsed["tools"], "moves": len(parsed["moves"])}
    stock = setup.get("stock")
    if stock:
        tools = {int(k): v for k, v in (setup.get("tools") or {}).items()}
        if parsed["lathe"]:
            s = sim.simulate_turn(parsed, {k: float(v) for k, v in stock.items()}, tools)
            out["sim"] = {"ap_max_mm": round(s["ap_max"], 3)}
        else:
            if not tools:
                raise SetupError("铣削仿真要给 tools（刀号 → 类型与直径）")
            s = sim.simulate_mill(parsed, {"box": stock["box"], "top": 0.0}, tools)
            out["sim"] = {"ap_max_mm": round(s["ap_max"], 3), "cell_mm": round(s["h"], 4)}
        checks += s["issues"]
    return [out], {}


def run(setup: dict) -> dict:
    t0 = time.time()
    mode = setup.get("mode")
    try:
        mach = M.get(setup.get("machine", ""))
        fn = {"turn": _turn, "mill": _mill, "check": _check}.get(mode)
        if fn is None:
            raise SetupError(f"mode 要是 turn、mill 或 check：{mode!r}")
        progs, extra = fn(setup, mach)
    except (SetupError, P.CamError, M.MachineError) as exc:
        return result.failed("cam", MODULE["version"], setup, str(exc))
    msgs = []
    if mach.get("example"):
        msgs.append(f"{mach['name']} 是示例机床（参数虚构）；用于真实加工前请在 machines.yaml 填自己的机床")
    if mode in ("turn", "mill") and not setup.get("cut"):
        msgs.append("切削参数用的是缺省教学示意值（45 钢），请按刀具样本与材料改")
    data = {"mode": mode, "machine": {"id": mach["id"], "name": mach["name"], "example": bool(mach.get("example"))},
            "programs": progs, "total_time_s": round(sum(p["time"]["total_s"] for p in progs), 3), "verdict": _verdict(progs),
            **extra}
    return result.make("cam", MODULE["version"], setup, data, limitations=LIMITS, messages=msgs, elapsed_s=time.time() - t0)
