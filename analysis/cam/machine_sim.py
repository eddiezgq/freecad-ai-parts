"""整机仿真（ADR-0104 第 2、4 节；C1：两轴车床、三轴加工中心）。

在现有的切削仿真（`sim.simulate_mill` / `simulate_turn`，材料去除）之外，按机床模型（cam-machine/1）把整台机床动起来查：
1. 刀具（刃部）、刀杆、刀柄 ↔ 夹具、工作台等机床部件；
2. 主轴头等刀具一侧的部件 ↔ 工件一侧的部件、夹具、毛坯外形；
3. 刀杆、刀柄 ↔ 剩下的材料（铣：高度图；刃部切材料是正常的，不算）；
4. 轴位置由运动学逆解（`kinematics.inverse`）算，达不到或超程都报。
查不了的（刀长没给、刀柄外形没写、网格文件读不到）报“未知”，不当“通过”。

设置 `machine_sim`：
  work_offset_mm: [x, y, z]     工件零点（G54）在工件一侧零位坐标里的位置
  fixtures: [{id, name, box_mm | cylinder_mm}]   夹具、压板、卡爪，工件坐标（程序坐标）
  tool_library: 刀具库文件路径（缺省用仓库的示例库）
  tools: {刀号: {"tool": 刀具库里的 id, "length_mm": 刀长（主轴端面基准点到刀尖）}}
  clearance_mm: 安全间隙（缺省 1）
  step_mm: 采样间距（缺省 5）
结果：{"status": pass | error | unknown, "checks": [...], "fingerprint": 16 位, "samples": 采样数}
指纹按机床、程序、刀具、毛坯、夹具、本模块版本算，写进程序头（ADR-0104 安全底线第 2 条）。
"""

from __future__ import annotations

import hashlib
import json
import math
from itertools import pairwise
from pathlib import Path

import numpy as np

from analysis.cam import collide as CL
from analysis.cam import holders as HD
from analysis.cam import kinematics as K
from analysis.cam import tools as TL

VERSION = "q2.1"                       # ADR-0106 Q2：车刀刀杆、网格部件


class SimSetupError(ValueError):
    pass


def fingerprint(machine: dict, gcode: str, cfg: dict, stock: dict | None, tool_specs: dict) -> str:
    data = {k: v for k, v in machine.items() if not k.startswith("_")}       # 机床文件放在哪里不影响指纹
    meshes = {}
    for c in machine.get("components") or []:                                # 网格部件按文件内容算
        if "mesh" in c and machine.get("_dir"):
            f = Path(machine["_dir"]) / c["mesh"]
            meshes[c["mesh"]] = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None
    if meshes:
        data["_meshes"] = meshes
    blob = json.dumps({"v": VERSION, "machine": data, "gcode": gcode, "cfg": cfg, "stock": stock, "tools": tool_specs},
                      sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ---------------- 机床部件、刀具外形 ----------------

def _prefix_pose(machine: dict, attached: str, q: dict) -> np.ndarray:
    """部件跟着 attached 轴动：该轴所在链上从底座到它（含）的变换；base 不动；spindle 跟整条刀具链"""
    if attached == "base":
        return np.eye(4)
    tool, work = K.chains(machine)
    if attached == "spindle":
        chain = tool
    else:
        side = tool if any(a["id"] == attached for a in tool) else work
        ids = [a["id"] for a in side]
        if attached not in ids:
            raise SimSetupError(f"部件跟着的轴 {attached!r} 机床里没有")
        chain = side[: ids.index(attached) + 1]
    T = np.eye(4)
    for a in chain:
        T = T @ K._motion(a, float(q.get(a["id"], 0.0)))
    return T


def _side(machine: dict, attached: str) -> str:
    if attached == "base":
        return "base"
    if attached == "spindle":
        return "tool"
    return next(a["carrier"] for a in machine["axes"] if a["id"] == attached)


def components(machine: dict) -> tuple[list[dict], list[str]]:
    out, notes = [], []
    for c in machine.get("components") or []:
        s = CL.shape(c, machine.get("_dir"))
        if s is None:
            notes.append(f"部件 {c.get('name', c['id'])} 的网格文件 {c.get('mesh')} 读不到，没查")
            continue
        out.append({"id": c["id"], "name": c.get("name", c["id"]), "attached": c["attached_to"],
                    "side": _side(machine, c["attached_to"]), "shape": s})
    return out, notes


def tool_parts(tool: dict) -> tuple[list[dict], list[str]]:
    """沿刀轴、从刀尖量的外形：[{part: cutter | shank | holder, z0, z1, r}]；缺数据的部分不画，记一条说明"""
    notes, parts = [], []
    d = tool.get("diameter_mm")
    flute = tool.get("flute_length_mm")
    stick = tool.get("stickout_mm")
    if d is None:
        notes.append(f"刀具 {tool['id']} 没写直径，刀具外形没法查")
        return parts, notes
    cut_len = flute if flute is not None else stick
    if cut_len is None:
        notes.append(f"刀具 {tool['id']} 没写刃长和伸出长，刀杆碰撞没查")
        cut_len = 0.0
    parts.append({"part": "cutter", "z0": 0.0, "z1": float(cut_len), "r": d / 2})
    if stick is not None and flute is not None and stick > flute:
        sd = tool.get("shank_diameter_mm")
        if sd is None:
            notes.append(f"刀具 {tool['id']} 没写柄径，刀杆碰撞没查")
        else:
            parts.append({"part": "shank", "z0": float(flute), "z1": float(stick), "r": sd / 2})
    prof = (tool.get("holder") or {}).get("profile_mm")
    if not prof:
        notes.append(f"刀具 {tool['id']} 没写刀柄外形，刀柄碰撞没查")
    else:
        for (r0, z0), (r1, z1) in pairwise(prof):
            if z1 > z0 + 1e-9:
                parts.append({"part": "holder", "z0": float(z0), "z1": float(z1), "r": float(max(r0, r1))})
    return parts, notes


PART_CN = {"cutter": "刀具刃部", "shank": "刀杆", "holder": "刀柄"}


# ---------------- 主流程 ----------------

def _tool_specs(cfg: dict, parsed: dict) -> tuple[dict, list[dict]]:
    lib_path = cfg.get("tool_library")
    lib = TL.load(lib_path) if lib_path else TL.load()
    specs, checks = {}, []
    given = {int(k): v for k, v in (cfg.get("tools") or {}).items()}
    for t in sorted(set(parsed["tools"]) | {mv["tool"] for mv in parsed["moves"]}):
        if t == 0:
            continue
        g = given.get(t)
        if not g or "tool" not in g:
            checks.append({"line": None, "level": "unknown", "text": f"T{t} 没对应到刀具库里的刀具，刀具、刀柄碰撞没查"})
            continue
        try:
            tool = TL.get(lib, g["tool"])
        except TL.ToolError as exc:
            raise SimSetupError(str(exc)) from exc
        if g.get("length_mm") is None:
            checks.append({"line": None, "level": "unknown", "text": f"T{t}（{tool['id']}）没给刀长，整机位置没法算，碰撞没查"})
            continue
        parts, notes = tool_parts(tool)
        checks += [{"line": None, "level": "unknown", "text": f"T{t}：{n}"} for n in notes]
        specs[t] = {"tool": tool, "L": float(g["length_mm"]), "parts": parts}
    return specs, checks


def tool_specs(machine: dict, cfg: dict, parsed: dict) -> tuple[dict, list[dict]]:
    """刀号 → {tool, L, parts}，以及查不了的说明（“未知”）"""
    try:
        if machine["kind"] == "mill_turn":       # 车铣：车削段的刀按车刀查，铣削段（动力刀）按铣刀查（ADR-0106 C2b）
            mill = {mv["tool"] for mv in parsed["moves"] if mv.get("mill")}
            part = lambda keep: {"tools": [t for t in parsed["tools"] if keep(t)],
                                 "moves": [mv for mv in parsed["moves"] if keep(mv["tool"])]}
            s1, c1 = _lathe_specs(cfg, part(lambda t: t not in mill))
            s2, c2 = _tool_specs(cfg, part(lambda t: t in mill))
            return {**s1, **s2}, c1 + c2
        return _lathe_specs(cfg, parsed) if machine["kind"] == "lathe" else _tool_specs(cfg, parsed)
    except TL.ToolError as exc:
        raise SimSetupError(str(exc)) from exc


def finish(res: dict, extra: list[dict]) -> dict:
    """把高度图那一步（heightmap_hook）查出的问题并进结果，重定结论"""
    keep = ("line", "level", "text")
    res["checks"] = res["checks"] + [{k: c[k] for k in keep} for c in extra]
    lv = {c["level"] for c in res["checks"]}
    res["status"] = "error" if "error" in lv else "unknown" if lv else "pass"
    return res


def _samples(a, b, step):
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = max(1, math.ceil(np.linalg.norm(b - a) / step))
    return [a + (b - a) * (i / n) for i in range(n + 1)]


def run(machine: dict, parsed: dict, cfg: dict, stock: dict | None = None, gcode: str = "") -> dict:
    """parsed 来自 sim.parse；stock 同 sim.simulate_mill 的毛坯，另可给 "height"（毛坯高度，没给就不查主轴头碰毛坯外形）"""
    lathe = machine["kind"] in ("lathe", "mill_turn")
    off = np.asarray(cfg.get("work_offset_mm") or [0, 0, 0], float)
    margin = float(cfg.get("clearance_mm", 1.0))
    step = float(cfg.get("step_mm", 5.0))
    comps, notes = components(machine)
    checks = [{"line": None, "level": "unknown", "text": n} for n in notes]
    fixtures = []
    for fx in cfg.get("fixtures") or []:
        s = CL.shape(fx)
        if s is None:
            raise SimSetupError(f"夹具 {fx.get('id')} 要写 box_mm 或 cylinder_mm")
        fixtures.append({"id": fx["id"], "name": fx.get("name", fx["id"]), "shape": s.moved(_translate(off))})
    specs, tchecks = tool_specs(machine, cfg, parsed)
    checks += tchecks
    stock_shape = None
    if stock and not lathe and stock.get("box") and stock.get("height"):
        x0, y0, x1, y1 = stock["box"]
        top = float(stock.get("top", 0.0))
        stock_shape = CL.Box.from_minmax([x0, y0, top - float(stock["height"]), x1, y1, top]).moved(_translate(off))
    seen: dict = {}
    prefer, n = {}, 0

    def report(key, line, text):
        """同一对东西相碰只报一条（第一处的行号），后面的行数记在 lines 里"""
        if key not in seen:
            seen[key] = {"line": line, "level": "error", "text": text, "lines": {line}}
            checks.append(seen[key])
        else:
            seen[key]["lines"].add(line)

    approach = millturn = False
    live_pre = _live_by_tool(machine, parsed)
    for mv in parsed["moves"]:
        if mv.get("home"):
            continue
        if mv.get("approach"):                   # 倾斜后机床 Z 还在原点的那几段：位置由数控系统的倾斜面功能定，不按工件坐标逆解
            approach = True
            continue
        sp = specs.get(mv["tool"])
        if mv.get("mill"):                       # 车铣的铣削段（ADR-0106 C2b、ADR-0110）：按机床文件的动力刀朝向逆解 C 轴
            live = (machine.get("live_tools") or {}).get("axial" if mv["mill"] == "polar" else "radial")
            if live is None or sp is None:
                millturn = True
                continue
            mach_u = {**machine, "tool": live}
            pts = []
            for p0, p1, w in mv["pieces"]:
                pts += [(np.asarray(p, float), w) for p in _samples(p0, p1, step)]
        else:
            if sp is None:
                continue
            live = live_pre.get(mv["tool"])
            mach_u = {**machine, "tool": live} if live else machine   # 动力刀在插补前后的定位段：刀还是那把动力刀，朝向照旧
            w = _unit3(live["direction"]) if live else mv.get("axis")
            pts = [((np.array([p[0] / 2, 0.0, p[2]]) if lathe else p), w) for p in _samples(mv["a"], mv["b"], step)]
        d0 = np.asarray((mach_u.get("tool") or {}).get("direction", [0, 0, 1]), float)
        for tip, axis in pts:
            n += 1
            tip = tip + off
            pref = prefer
            if mv.get("mill") == "polar":            # 极坐标插补：转 C 把点转到 +X 一侧（Y 不动）；刀轴沿 C 轴是奇异点，C 取这个值
                pref = {**prefer, "C": -math.degrees(math.atan2(tip[1] - off[1], tip[0] - off[0]))}
            elif lathe and not mv.get("mill") and any(a["id"] == "C" for a in machine["axes"]):
                pref = {**prefer, "C": 0.0}              # 车削、定位段：程序里 Y = 0，C 停在哪不影响回转体的碰撞，按 C0 算
            try:
                q = K.inverse(mach_u, tip, axis, sp["L"], prefer=pref)
            except K.KinematicsError as exc:
                report(("reach",), mv["line"], f"机床走不到：{exc}")
                break
            prefer = q
            Tt = _prefix_pose(mach_u, "spindle", q)
            Tw = np.eye(4)
            for a in K.chains(mach_u)[1]:
                Tw = Tw @ K._motion(a, float(q.get(a["id"], 0.0)))
            tip0 = np.asarray((mach_u.get("tool") or {}).get("gauge_point_mm", [0, 0, 0]), float) - sp["L"] * d0
            tparts = [(pt, CL.Cylinder(tip0 + pt["z0"] * d0, tip0 + max(pt["z1"], pt["z0"] + 1e-6) * d0, pt["r"]).moved(Tt))
                      for pt in sp["parts"]]
            tparts += [(bx, CL.Box.from_minmax(bx["box"]).moved(Tt @ _translate(tip0))) for bx in sp.get("boxes", [])]
            wobjs = [("夹具", f, f["shape"].moved(Tw)) for f in fixtures]
            if stock_shape is not None:
                sobj = stock_shape.moved(Tw)
            cposes = [(c, c["shape"].moved(_prefix_pose(machine, c["attached"], q))) for c in comps]
            # 1. 刀具各部分 ↔ 夹具、工件一侧和不动的机床部件
            for pt, ts in tparts:
                for kind, f, ws in wobjs:
                    if CL.hit(ts, ws, margin):
                        report(("tf", pt["part"], f["id"]), mv["line"],
                               f"{PART_CN[pt['part']]}碰到{kind}“{f['name']}”（T{mv['tool']}，第 {mv['line']} 行，间隙 {margin:g} mm 内）")
                for c, cs in cposes:
                    if c["side"] != "tool" and CL.hit(ts, cs, margin):
                        report(("tc", pt["part"], c["id"]), mv["line"],
                               f"{PART_CN[pt['part']]}碰到机床的{c['name']}（T{mv['tool']}，第 {mv['line']} 行）")
            # 2. 刀具一侧部件 ↔ 工件一侧部件、夹具、毛坯外形
            for c, cs in cposes:
                if c["side"] != "tool":
                    continue
                for c2, cs2 in cposes:
                    if c2["side"] != "tool" and CL.hit(cs, cs2, margin):
                        report(("cc", c["id"], c2["id"]), mv["line"], f"机床的{c['name']}碰到{c2['name']}（第 {mv['line']} 行）")
                for kind, f, ws in wobjs:
                    if CL.hit(cs, ws, margin):
                        report(("cf", c["id"], f["id"]), mv["line"], f"机床的{c['name']}碰到{kind}“{f['name']}”（第 {mv['line']} 行）")
                if stock_shape is not None and CL.hit(cs, sobj, margin):
                    report(("cs", c["id"]), mv["line"], f"机床的{c['name']}碰到毛坯（第 {mv['line']} 行）")
    if millturn:
        checks.append({"line": None, "level": "unknown",
                       "text": "车铣的铣削段（极坐标、圆柱插补）：C 轴、动力刀的整机仿真还没做（ADR-0106 C2b），碰撞和超程没查"})
    if approach:
        checks.append({"line": None, "level": "unknown",
                       "text": "倾斜面：转回转轴后到第一次下刀那几段，刀具在机床 Z 原点，实际走法由数控系统的倾斜面功能定，整机仿真没查；首件单段确认"})
    for c in checks:
        lines = c.pop("lines", None)
        if lines and len(lines) > 1:
            c["text"] += f"；同样的问题共 {len(lines)} 行"
    status = "error" if any(c["level"] == "error" for c in checks) else "unknown" if checks else "pass"
    tool_fp = {str(k): {"tool": v["tool"], "L": v["L"]} for k, v in specs.items()}
    return {"status": status, "checks": checks, "samples": n,
            "tool_d": {t: v["tool"].get("diameter_mm") for t, v in specs.items()},
            "fingerprint": fingerprint(machine, gcode, cfg, stock, tool_fp)}


def _unit3(v) -> tuple:
    v = np.asarray(v, float)
    return tuple(v / np.linalg.norm(v))


def _live_by_tool(machine: dict, parsed: dict) -> dict:
    """车铣：每把动力刀第一次插补用的朝向（轴向 / 径向），插补前的定位段也按这个朝向算"""
    lt = machine.get("live_tools") or {}
    out: dict = {}
    for mv in parsed["moves"]:
        if mv.get("mill") and mv["tool"] not in out:
            o = lt.get("axial" if mv["mill"] == "polar" else "radial")
            if o is not None:
                out[mv["tool"]] = o
    return out


def _translate(v) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = v
    return T


def _lathe_specs(cfg: dict, parsed: dict) -> tuple[dict, list[dict]]:
    """车刀：刀尖圆弧（刀片 nose_radius）；刀杆按 ISO 5608 代号与刀尖偏距 f 生成长方体（holders.py，ADR-0107），
    没有代号或没有 f 的报“未知”"""
    lib_path = cfg.get("tool_library")
    lib = TL.load(lib_path) if lib_path else TL.load()
    specs, checks = {}, []
    given = {int(k): v for k, v in (cfg.get("tools") or {}).items()}
    for t in sorted({mv["tool"] for mv in parsed["moves"]} - {0}):
        g = given.get(t)
        if not g or "tool" not in g:
            checks.append({"line": None, "level": "unknown", "text": f"T{t} 没对应到刀具库里的刀具，碰撞没查"})
            continue
        tool = TL.get(lib, g["tool"])
        r = float((tool.get("insert") or {}).get("nose_radius_mm", 0.0))
        specs[t] = {"tool": tool, "L": 0.0, "parts": [{"part": "cutter", "z0": 0.0, "z1": 0.0, "r": max(r, 1e-3)}], "boxes": []}
        holder = tool.get("holder") or {}
        if not holder.get("iso5608"):
            checks.append({"line": None, "level": "unknown", "text": f"T{t}（{tool['id']}）：刀具库里没写刀杆代号（ISO 5608），只查了刀尖"})
            continue
        try:
            bx, notes = HD.boxes(holder)
        except HD.HolderError as exc:
            checks.append({"line": None, "level": "unknown", "text": f"T{t}（{tool['id']}）：{exc}，只查了刀尖"})
            continue
        specs[t]["boxes"] = [{"part": "shank", "box": b} for b in bx]
        checks += [{"line": None, "level": "unknown", "text": f"T{t}（{tool['id']}）：{n}"} for n in notes]
    return specs, checks


def heightmap_hook(specs: dict, checks: list, tol: float = 0.05):
    """给 sim.simulate_mill 的 on_move：每段走刀切削之前，查刀杆、刀柄底面是否低于圆盘范围内剩下的材料"""
    seen: dict = {}

    def hook(mv, H, xs, ys):
        sp = specs.get(mv["tool"])
        if sp is None:
            return
        for pt in sp["parts"]:
            if pt["part"] == "cutter":
                continue
            r = pt["r"]
            for x, y, z in _samples(mv["a"], mv["b"], max(abs(xs[1] - xs[0]) * 2, 0.5)):
                ix = (xs >= x - r) & (xs <= x + r)
                iy = (ys >= y - r) & (ys <= y + r)
                if not ix.any() or not iy.any():
                    continue
                sub = H[np.ix_(ix, iy)]
                msk = ((xs[ix][:, None] - x) ** 2 + (ys[iy][None, :] - y) ** 2) <= r * r
                top = sub[msk].max() if msk.any() else -1e6
                if top > z + pt["z0"] + tol:
                    key = (mv["tool"], pt["part"])
                    dz = top - z - pt["z0"]
                    if key not in seen:
                        seen[key] = {"line": mv["line"], "level": "error", "n": 1, "dz": dz, "part": pt["part"], "tool": mv["tool"]}
                        checks.append(seen[key])
                    elif seen[key]["last"] != mv["line"]:
                        seen[key]["n"] += 1
                    seen[key]["last"] = mv["line"]
                    seen[key]["dz"] = max(seen[key]["dz"], dz)
                    seen[key]["text"] = (f"{PART_CN[pt['part']]}碰到工件：剩下的材料比{PART_CN[pt['part']]}底面最多高 {seen[key]['dz']:.2f} mm"
                                         f"（T{mv['tool']}，第 {seen[key]['line']} 行起，共 {seen[key]['n']} 行）——加长伸出或换刀")
                    break

    return hook
