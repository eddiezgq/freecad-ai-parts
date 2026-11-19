"""数控编程（ADR-0059，M11 第二步）：阶梯轴车削、2.5 轴铣削生成 FANUC 风格 G 代码；读任意 FANUC 风格 G 代码（包括 FreeCAD CAM
工作台输出的）算加工时间、仿真切削、检查撞料、过切 / 残留、超程、转速、切削功率。搬自问渠数字工厂第 13 轮。

设置（单位 mm、m/min、mm/r、mm/min）：
  mode: "turn" | "mill" | "check"；machine: 机床 id（analysis/cam/machines.py：示例机床为虚构，企业在 machines.yaml 填自己的）
  kienzle: Kienzle 表行（analysis/common/kienzle.yaml 的 key）；不填时切削功率为待确认
  turn：segments [[直径, 长度], ..]（从左到右）、chamfer_mm、stock_d_mm（毛坯直径；缺省 = 最大直径 + 4 向上取整）、
        face_allow_mm（每端车端面余量，缺省 1）、finish_allow_mm（粗车单边留量，缺省 0.5）、max_rpm（G50 限速，缺省 3000 与机床取小）、
        cut: {"rough": {"vc", "f", "ap"}, "finish": {"vc", "f"}}（缺省见 DEFAULT_CUT）
        先车右端到最大直径段，调头再车左端；每次装夹一个程序，粗车 T01、精车 T02。
        grooves: [{"z": 槽右边（零件坐标，Z0 在零件右端，向左为负）, "width", "d": 槽底直径, "tool_w": 刀宽（缺省 = 槽宽）}]  T03
        threads: [{"z_start", "z_end"（z_end 在左）, "d": 大径, "pitch"}]  外螺纹，T04，G97 恒转速、G32 逐刀，牙底按 ISO 965-1 d3
        bore: {"segments": [[直径, 深度], ..]（从孔口往里）, "drill_d", "drill_depth"（缺省 = 内孔总深）, "from": "right" | "left"}
              先钻 T05（X0）再镗 T06；槽、螺纹按位置自动分到所在的那次装夹
  mill：stock: {"box": [x0, y0, x1, y1]}（上表面 Z0）；features: [
          {"type": "slot", "a": [x, y], "b": [x, y], "width", "depth"},
          {"type": "pocket", "rect": [x0, y0, x1, y1], "corner_r", "depth"},
          {"type": "contour", "rect": [..], "corner_r", "depth"},
          {"type": "holes", "d", "points": [[x, y], ..], "depth"}]，每项可给 tool_d 与 cut（缺省见 DEFAULT_CUT）
  check：gcode（程序文本）；可选 stock（车：{"d", "z_right", "z_left"}；铣：{"box"}）与 tools（{刀号: {"kind": "turn" | "groove" | "endmill" |
         "drill", "d" 或 "w"}}）——给了毛坯才仿真
  machine_sim（可选，三种 mode 都认）：整机仿真（analysis/cam/machine_sim.py）——work_offset_mm、fixtures、tool_library、
         tools {刀号: {"tool": 刀具库 id, "length_mm": 刀长}}、clearance_mm、step_mm；铣削毛坯另可给 stock.height。
         turn、mill 生成的程序整机仿真不通过就不输出（gcode 为 null）；check 只报不扣。
  post（可选，turn、mill）：数控系统 fanuc | siemens | gsk（广数只有车）——出正式程序 programs[].release
         {controller, post, version, verified, fingerprint, text}。没给 machine_sim、整机仿真不通过、回读刀路与仿真不一致，都不出（release 为 null）。
结果 data：programs [{title, gcode, time（cut_s、rapid_s、tool_s、total_s）, checks [{line, level, text}], sim, power}]、
  total_time_s、verdict（error / warn / unknown / ok：检查中最严重的一级）、machine（id、name、example）。
"""

from __future__ import annotations

import math
import time

from analysis.cam import machine_sim as MS
from analysis.cam import machines as M
from analysis.cam import paths as P
from analysis.cam import post, postproc, power, sim
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
    "groove": {"vc": 80.0, "f": 0.05},
    "thread": {"vc": 60.0},
    "lathe_drill": {"vc": 20.0, "f": 0.1, "peck": 0.0},
    "bore": {"vc": 100.0, "f": 0.15, "ap": 1.0, "f_finish": 0.08},
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


def _msim_hook(setup, mach, parsed):
    """整机仿真（ADR-0104 C1）：设置里有 machine_sim 才跑。返回 (高度图钩子, 钩子查出的问题列表)"""
    cfg = setup.get("machine_sim")
    if not cfg or parsed["lathe"]:
        return None, []
    specs, _ = MS.tool_specs(mach["model"], cfg, parsed)
    extra: list = []
    return MS.heightmap_hook(specs, extra), extra


def _msim(setup, mach, parsed, gcode, stock, extra, prog, withhold, expect_d=None):
    """跑整机仿真，结果并进程序的检查；withhold 时不通过就扣下程序（ADR-0104 安全底线第 1 条）。
    expect_d：程序按什么刀径算的（{刀号: 直径}）——与刀具库里对应的刀不一样就报错"""
    cfg = setup.get("machine_sim")
    if not cfg:
        return
    res = MS.run(mach["model"], parsed, cfg, stock, gcode)
    for t, d in (expect_d or {}).items():
        got = res["tool_d"].get(t)
        if got is not None and abs(got - d) > 1e-6:
            extra.append({"line": None, "level": "error", "text": f"T{t}：程序按 Ø{d:g} 算，刀具库里对应的刀是 Ø{got:g}"})
    res = MS.finish(res, extra)
    prog["checks"] += res["checks"]
    prog["machine_sim"] = {"status": res["status"], "fingerprint": res["fingerprint"], "samples": res["samples"]}
    if withhold and res["status"] == "error":
        prog["gcode"] = None
        prog["checks"].append({"line": None, "level": "error", "text": "整机仿真不通过，程序没有输出（改好再算）"})


def _same_path(a_text, b_text, mach):
    """两份程序回读后的刀路是否一致（终点、类型；容差 1e-3 mm）"""
    pa = [m for m in sim.parse(a_text, mach)["moves"] if not m.get("home")]
    pb = [m for m in sim.parse(b_text, mach)["moves"] if not m.get("home")]
    if len(pa) != len(pb):
        return False
    return all(x["t"] == y["t"] and max(abs(u - v) for u, v in zip(x["b"], y["b"], strict=True)) < 1e-3 for x, y in zip(pa, pb, strict=True))


def _release(setup, mach, prog, out):
    """正式程序（ADR-0104 第 4 节）：设置里 post 给了数控系统才出。没跑整机仿真或不通过不出；
    出了以后回读一遍，与整机仿真用的刀路逐段比对，不一致也不出"""
    ctl = setup.get("post")
    if not ctl:
        return
    try:
        rel = postproc.render(prog, mach, ctl, out.get("machine_sim"))
        back = postproc.to_fanuc(rel["text"], ctl, mach["kind"] == "lathe")
        if out.get("gcode") and not _same_path(out["gcode"], back, mach):
            raise postproc.ReleaseError("后处理出的程序回读后与整机仿真用的刀路不一致，不输出")
    except postproc.ReleaseError as exc:
        out["release"] = None
        out["checks"].append({"line": None, "level": "error", "text": f"正式程序没有输出：{exc}"})
        return
    out["release"] = rel
    if not rel["verified"]:
        out["checks"].append({"line": None, "level": "warn",
                              "text": f"{rel['post']} 后处理还没在实机上验证过：首件空运行、单段试切确认"})


# ---------------------------------------------------------------- 车削
def _turn_features(setup, total, reach_right):
    """槽、螺纹按所在位置分到两次装夹，换成该次装夹的坐标（Z0 在本次右端面，向左为负）。
    零件坐标：Z0 在零件右端，向左为负（与第一次装夹相同）。调头后 z' = -(z + 全长)，左右翻过来"""
    def side(z_hi, z_lo):
        if z_lo >= -reach_right - 1e-9:
            return "right"
        if z_hi <= -reach_right + 1e-9:
            return "left"
        raise SetupError(f"Z{z_hi:g} ~ Z{z_lo:g} 跨在两次装夹之间（第一次装夹车到 Z{-reach_right:g}），放不进一次装夹")

    out = {"right": {"grooves": [], "threads": []}, "left": {"grooves": [], "threads": []}}
    for g in setup.get("grooves") or []:
        z, w, d = float(g["z"]), float(g["width"]), float(g["d"])
        if w <= 0 or d <= 0:
            raise SetupError("槽宽、槽底直径要大于 0")
        sd = side(z, z - w)
        zz = z if sd == "right" else -(z - w + total)
        out[sd]["grooves"].append({"z": zz, "width": w, "d": d, "tool_w": float(g.get("tool_w") or w), "cut": g.get("cut")})
    for t in setup.get("threads") or []:
        za, zb, d, pch = float(t["z_start"]), float(t["z_end"]), float(t["d"]), float(t["pitch"])
        if zb >= za:
            raise SetupError("螺纹 z_end 要在 z_start 左边（更负）")
        sd = side(za, zb)
        if sd == "left":
            za, zb = -(zb + total), -(za + total)
        out[sd]["threads"].append({"z_start": za, "z_end": zb, "d": d, "pitch": pch, "cut": t.get("cut")})
    return out


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
    _, reach_right = P.setup_profile(prof, "right")
    feats = _turn_features(setup, total, reach_right)
    bore = setup.get("bore")
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
        tools_sim = {1: {"kind": "turn"}, 2: {"kind": "turn"}}
        tg = {"outer": tgt, "grooves": [], "threads": []}
        for gi, gv in enumerate(feats[side]["grooves"]):
            c = _cut(gv["cut"], DEFAULT_CUT["groove"])
            d_from = P.d_at(tgt, gv["z"] - gv["width"] / 2)
            mv = P.turn_groove(gv["z"], gv["d"], gv["width"], d_from, c["f"], gv["tool_w"])
            prog["ops"].append({"tool": {"n": 3, "name": f"切槽刀 宽 {gv['tool_w']:g}"},
                                "spindle": {"css": c["vc"], "max_rpm": max_rpm}, "moves": mv, "title": f"切槽 {gi + 1}"})
            tools_sim[3] = {"kind": "groove", "w": gv["tool_w"]}
            tg["grooves"].append((gv["z"], gv["width"], gv["d"]))
        for ti, tv in enumerate(feats[side]["threads"]):
            run_in = max(2 * tv["pitch"], P.CLEAR)
            free = tv["z_start"] >= -1e-9 or any(gv["z"] >= tv["z_start"] + run_in - 1e-9 and gv["z"] - gv["width"] <= tv["z_start"] + 1e-9
                                                 for gv in feats[side]["grooves"])
            if not free:
                raise SetupError(f"螺纹起刀处（本次装夹 Z{tv['z_start']:g} 右边 {run_in:g} mm）没有退刀槽，也不在端面——起刀会撞工件")
            c = _cut(tv["cut"], DEFAULT_CUT["thread"])
            rpm = P.spindle_rpm(c["vc"], tv["d"], max_rpm)
            mv = P.turn_thread(tv["z_start"], tv["z_end"], tv["d"], tv["pitch"])
            prog["ops"].append({"tool": {"n": 4, "name": f"外螺纹车刀 P{tv['pitch']:g}"}, "spindle": {"rpm": round(rpm)},
                                "moves": mv, "title": f"车螺纹 {ti + 1}"})
            tools_sim[4] = {"kind": "thread"}
            tg["threads"].append((tv["z_start"], tv["z_end"], tv["d"] - P.ISO_D3 * tv["pitch"]))
        stock = {"d": stock_d, "z_right": e, "z_left": -(total + e)}
        if bore and bore.get("from", "right") == side:
            cb = _cut(bore.get("cut"), DEFAULT_CUT["bore"])
            cd = _cut(bore.get("drill_cut"), DEFAULT_CUT["lathe_drill"])
            inner = P.inner_profile([[float(d), float(L)] for d, L in bore["segments"]])
            dd = float(bore["drill_d"])
            depth = float(bore.get("drill_depth") or -inner[-1][0])
            rpm = P.spindle_rpm(cd["vc"], dd, max_rpm)
            prog["ops"].append({"tool": {"n": 5, "name": f"麻花钻 Ø{dd:g}", "d": dd}, "spindle": {"rpm": round(rpm)},
                                "moves": P.lathe_drill(depth, dd, cd["f"], cd["peck"]), "title": "钻孔"})
            prog["ops"].append({"tool": {"n": 6, "name": "镗刀"}, "spindle": {"css": cb["vc"], "max_rpm": max_rpm},
                                "moves": P.turn_bore(inner, dd, cb["ap"], cb["f"], f_finish=cb["f_finish"]), "title": "镗孔"})
            tools_sim[5] = {"kind": "drill", "d": dd}
            tools_sim[6] = {"kind": "bore"}
            tg["inner"] = inner
        g = post.post(prog, mach)
        parsed = sim.parse(g, mach)
        checks = sim.machine_checks(parsed, mach)
        tm = sim.timing(parsed, mach)
        s = sim.simulate_turn(parsed, stock, tools_sim, target=tg)
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
        out = {"title": title, "side": side, "number": prog["number"], "gcode": g, "time": tm, "checks": checks,
                      "sim": {"dev_min_mm": round(s.get("dev_min", 0.0), 4), "dev_max_mm": round(s.get("dev_max", 0.0), 4),
                              "under_mm": round(s.get("under_mm", 0.0), 4), "ap_max_mm": {"rough": round(ap[1], 3), "finish": round(ap[2], 3)},
                              "reach_mm": reach,
                              **({"inner_dev_min_mm": round(s["inner_dev_min"], 4), "inner_dev_max_mm": round(s["inner_dev_max"], 4)}
                                 if "inner_dev_min" in s else {})},
                      "power": pdet, "target": [[float(z), float(d)] for z, d in tgt]}
        _msim(setup, mach, parsed, g, stock, [], out, withhold=True)
        _release(setup, mach, prog, out)
        progs.append(out)
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
    hook, extra = _msim_hook(setup, mach, parsed)
    s = sim.simulate_mill(parsed, {"box": box, "top": 0.0}, tools, _mill_target(feats), on_move=hook)
    checks += s["issues"]
    under = int(s["under_mask"].sum()) if "under_mask" in s else 0
    if under:
        checks.append({"line": None, "level": "warn",
                       "text": f"残留：{under} 格比目标高，最多 {s['dev_max']:.3f} mm"
                               "（型腔转角圆角小于刀具半径时转角留料；外轮廓离毛坯角太远时一圈铣不到）"})
    pw, pdet = power.check(setup.get("kienzle"), mach, items)
    checks += pw
    out = {"title": "铣削", "number": 5001, "gcode": g, "time": tm, "checks": checks, "power": pdet,
           "sim": {"over_cells": s.get("over", 0), "under_cells": under, "dev_min_mm": round(s.get("dev_min", 0.0), 4),
                   "dev_max_mm": round(s.get("dev_max", 0.0), 4), "ap_max_mm": round(s["ap_max"], 3), "cell_mm": round(s["h"], 4)},
           "tools": {str(k): v for k, v in tools.items()}}
    _msim(setup, mach, parsed, g, {"box": box, "top": 0.0, "height": stock.get("height")}, extra, out, withhold=True,
          expect_d={k: v["d"] for k, v in tools.items()})
    _release(setup, mach, prog, out)
    return [out], {}


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
    extra: list = []
    if stock:
        tools = {int(k): v for k, v in (setup.get("tools") or {}).items()}
        if parsed["lathe"]:
            s = sim.simulate_turn(parsed, {k: float(v) for k, v in stock.items()}, tools)
            out["sim"] = {"ap_max_mm": round(s["ap_max"], 3)}
        else:
            if not tools:
                raise SetupError("铣削仿真要给 tools（刀号 → 类型与直径）")
            hook, extra = _msim_hook(setup, mach, parsed)
            s = sim.simulate_mill(parsed, {"box": stock["box"], "top": 0.0}, tools, on_move=hook)
            out["sim"] = {"ap_max_mm": round(s["ap_max"], 3), "cell_mm": round(s["h"], 4)}
        checks += s["issues"]
    _msim(setup, mach, parsed, text, stock, extra, out, withhold=False)
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
    except (SetupError, P.CamError, M.MachineError, MS.SimSetupError) as exc:
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
