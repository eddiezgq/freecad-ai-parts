"""独立解释器核对（ADR-0106 E1）：把正式程序交给 LinuxCNC 的 RS274NGC 解释器（`rs274`，NIST RS274NGC 的后继，GPL，
作为外部程序调用，不入库）解释成刀具运动，与问渠CAM 自己的回读（`sim.parse`）逐点比——两个互不相干的解释器读同一份程序，
走出来的刀路一致，才说明程序的意思就是仿真里的那个意思。

- `find()`：rs274 在哪（环境变量 `FAP_RS274` 指到 rs274 可执行文件；缺省 `用户目录/.freecad-ai-parts/rs274/root/usr/bin/rs274`，
  `scripts/fetch_rs274.sh` 从 Debian 官方源下载解包到那里）。没有返回 None，标准题跳过。
- `to_ngc(text, lathe)`：FANUC 写法 → LinuxCNC 写法，只改两家**写法不同、意思相同**的几处（每条都有出处，见 ADR-0106 E1）：
  车床直径编程 G7；`G50 S` 限速 → `G96 D`；`T0101` → `T1 M6`；每转 / 每分进给 G99 / G98 → G95 / G94；车螺纹 G32 F → G33 K。
  其余原样交给解释器，解释器不认就报错。
- `run(ngc)` → 刀具运动（直线、圆弧），`compare(text, lathe, machine)` → {"ok", "max_dev_mm", "n_ref", "n_own", "why"}。
"""

from __future__ import annotations

import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

TOL = 1e-3


def find() -> Path | None:
    p = os.environ.get("FAP_RS274")
    cand = Path(p) if p else Path.home() / ".freecad-ai-parts" / "rs274" / "root" / "usr" / "bin" / "rs274"
    return cand if cand.is_file() else None


PECK = 0.5          # G83 啄钻退回后快速下到离上次深度多远：FANUC 由参数 5115 定、LinuxCNC 固定 0.254 mm、问渠CAM 仿真按 0.5 mm（只差空走）


def to_ngc(text: str, lathe: bool, start: tuple | None = None) -> str:
    """start：自家回读的起点（车 (X 直径, 0, Z)、铣 (X, Y, Z)），rs274 先快移到那里，两边从同一点起"""
    out = ["G7 G18"] if lathe else []
    if start is not None:
        out.append(f"G0 X{start[0]:.6f} Z{start[2]:.6f}" if lathe else f"G0 Z{start[2]:.6f}\nG0 X{start[0]:.6f} Y{start[1]:.6f}")
    lim = None
    for raw in text.splitlines():
        s = re.sub(r"\([^)]*\)", "", raw).strip()
        if not s or s == "%" or re.fullmatch(r"O\d+", s):
            continue
        if lathe:
            m = re.fullmatch(r"(?:N\d+ )?T(\d\d)(\d\d)", s)
            if m:
                s = f"T{int(m.group(1))} M6"
            m = re.fullmatch(r"(?:N\d+ )?G50 S(\d+)", s)
            if m:
                lim = m.group(1)
                continue
            if lim is not None:
                s = re.sub(r"G96 S(\d+)", rf"G96 D{lim} S\1", s)
            s = re.sub(r"\bG99\b", "G95", s)
            s = re.sub(r"\bG98\b", "G94", s)
            if re.search(r"\bG32\b", s):
                s = re.sub(r"\bG32\b", "G33", s)
                s = re.sub(r"\bF(-?\d)", r"K\1", s)
        out.append(s)
    return "\n".join(out) + "\n"


_CALL = re.compile(r"(STRAIGHT_TRAVERSE|STRAIGHT_FEED|ARC_FEED|STRAIGHT_PROBE|RIGID_TAP)\(([^)]*)\)")


def run(ngc: str, exe: Path | None = None, g28: tuple | None = None) -> list[dict]:
    """→ [{"t": "line" | "arc", "b": 终点 (x, y, z), 圆弧另有 "c": 圆心, "plane": "XY" | "XZ", "cw"}]；解释器报错 → RuntimeError"""
    exe = exe or find()
    if exe is None:
        raise RuntimeError("没有 rs274（scripts/fetch_rs274.sh）")
    root = exe.parent.parent
    env = {**os.environ, "LD_LIBRARY_PATH": f"{root / 'lib'}:{root / 'lib' / 'x86_64-linux-gnu'}"}
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        (dp / "p.ngc").write_text(ngc, encoding="ascii")
        (dp / "t.tbl").write_text("".join(f"T{n} P{n} Z0 D0\n" for n in range(1, 100)), encoding="ascii")
        var = []
        if g28:                                  # G28 回的参考点（参数 5161 ~ 5163）：与自家回读用的机床参考点相同
            var = ["-v", str(dp / "p.var")]
            (dp / "p.var").write_text("".join(f"{5161 + i} {v / 25.4:.9f}\n" for i, v in enumerate(g28)), encoding="ascii")   # 参数文件按英寸存
        r = subprocess.run([str(exe), "-t", str(dp / "t.tbl"), *var, "-n", "2", str(dp / "p.ngc"), str(dp / "o.txt")],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120, env=env, check=False)
        log = r.stdout + r.stderr
        txt = (dp / "o.txt").read_text(encoding="ascii", errors="replace") if (dp / "o.txt").is_file() else ""
    after = log.split("executing", 1)[1] if "executing" in log else log
    bad = [ln.strip() for ln in after.splitlines() if ln.strip()]           # 解释器的报错印在“executing”之后
    if r.returncode != 0 or bad or not txt:
        raise RuntimeError("rs274 解释不了：" + "；".join(bad[:3] or [log.strip()[-200:]]))
    plane, out = "XY", []
    for ln in txt.splitlines():
        if "SELECT_PLANE(CANON_PLANE_XZ)" in ln:
            plane = "XZ"
        elif "SELECT_PLANE(CANON_PLANE_XY)" in ln:
            plane = "XY"
        m = _CALL.search(ln)
        if not m:
            continue
        v = [float(x) for x in m.group(2).split(",")]
        if m.group(1) != "ARC_FEED":
            out.append({"t": "rapid" if m.group(1) == "STRAIGHT_TRAVERSE" else "line", "b": (v[0], v[1], v[2])})
            continue
        e1, e2, c1, c2, rot, ax = v[:6]
        if plane == "XY":
            out.append({"t": "arc", "plane": plane, "b": (e1, e2, ax), "c": (c1, c2), "cw": rot < 0})
        else:                                    # XZ：第一轴 Z、第二轴 X
            out.append({"t": "arc", "plane": plane, "b": (e2, ax, e1), "c": (c2, c1), "cw": rot < 0})
    return out


def _on_line(p, a, b) -> float:
    ab = [y - x for x, y in zip(a, b, strict=True)]
    L2 = sum(x * x for x in ab)
    if L2 < 1e-18:
        return math.dist(p, a)
    t = max(0.0, min(1.0, sum((p[i] - a[i]) * ab[i] for i in range(3)) / L2))
    return math.dist(p, [a[i] + t * ab[i] for i in range(3)])


def _on_arc(p, a, mv) -> float:
    i, j, k = (0, 1, 2) if mv["plane"] == "XY" else (0, 2, 1)
    c = mv["c"]
    r = math.hypot(a[i] - c[0], a[j] - c[1])
    rp = math.hypot(p[i] - c[0], p[j] - c[1])
    return abs(rp - r) + (abs(p[k] - a[k]) if mv["plane"] == "XZ" else 0.0)


def compare(text: str, lathe: bool, machine: dict, own_text: str | None = None) -> dict:
    """正式程序（FANUC 写法）：rs274 的刀路 ↔ sim.parse 的刀路（own_text：给了就读它，例如整机仿真用的程序），都按顺序走。车床按半径比（rs274 出半径）。
    ① rs274 的每个终点按顺序在自家刀路的顶点里找得到；② 自家的每个顶点按顺序落在 rs274 当前或后面的一段上。偏差都 < TOL"""
    from analysis.cam import sim

    hx, hz = machine.get("home", (machine["x"][1], machine["z"][1]))
    start = (hx, 0.0, hz) if lathe else (0.0, 0.0, machine["z"][1])
    ref = run(to_ngc(text, lathe, start), g28=(hx / 2.0, 0.0, hz) if lathe else start)
    own = [m["b"] for m in sim.parse(own_text or text, machine)["moves"]]
    if lathe:
        own = [(x / 2.0, y, z) for x, y, z in own]
    # 原地不动的段（回参考点时已经在那里、换刀点上重复定位）两边都不算
    ref = [mv for k, mv in enumerate(ref) if k == 0 or math.dist(mv["b"], ref[k - 1]["b"]) >= TOL]
    own = [p for k, p in enumerate(own) if k == 0 or math.dist(p, own[k - 1]) >= TOL]
    s0 = (start[0] / 2.0, 0.0, start[2]) if lathe else start
    ref = [mv for mv in ref if math.dist(mv["b"], s0) >= TOL or mv is not ref[0]]   # 开头快移到起点那一段（上面加的）不比
    res = {"ok": False, "max_dev_mm": None, "n_ref": len(ref), "n_own": len(own), "why": ""}
    j, pecks = 0, 0
    for k, mv in enumerate(ref):
        j0 = j
        while j < len(own) and math.dist(own[j], mv["b"]) >= TOL:
            j += 1
        nxt = ref[k + 1] if k + 1 < len(ref) else None
        if j >= len(own) and mv["t"] == "rapid" and nxt and nxt["t"] == "line" and math.dist(nxt["b"][:2], mv["b"][:2]) < TOL:
            j = j0                               # 啄钻回到孔里：下到多深是数控系统参数，按 PECK 内认
            while j < len(own) and not (math.dist(own[j][:2], mv["b"][:2]) < TOL and abs(own[j][2] - mv["b"][2]) <= PECK + TOL):
                j += 1
            pecks += j < len(own)
        if j >= len(own):
            res["why"] = f"rs274 的终点 {tuple(round(v, 4) for v in mv['b'])} 在自家回读里按顺序找不到"
            return res
    segs = [(ref[k - 1]["b"], ref[k]) for k in range(1, len(ref))]

    def dev(p, sg):
        a, mv = sg
        return _on_arc(p, a, mv) if mv["t"] == "arc" else _on_line(p, a, mv["b"])

    worst, k = 0.0, 0
    for p in own:
        if not segs:
            break
        while k < len(segs) and dev(p, segs[k]) >= TOL:
            k += 1
        if k >= len(segs):
            res["why"] = f"自家回读的点 {tuple(round(v, 4) for v in p)} 不在 rs274 的刀路上"
            return res
        worst = max(worst, dev(p, segs[k]))
    res.update({"ok": True, "max_dev_mm": round(worst, 6), "peck_points": pecks})
    return res
