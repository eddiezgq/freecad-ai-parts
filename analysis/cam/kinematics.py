"""机床运动学（ADR-0104 C1 / C2；机床模型见 ADR-0105）。

约定（ADR-0105）：
- 轴按 carrier 分两条链：带刀具一侧、带工件一侧；每条链按“从机床底座往外”的顺序。
- 轴的 `direction`、`point_mm` 都是所有轴零位时、在机床坐标里的值；`direction` 是正向指令时被带动部件的实际运动方向。
- 于是每条链的位姿 = 各轴运动依次相乘（指数积公式）：G = M(q1)·M(q2)·…，直线轴是平移 q·d，回转轴是绕过 point、方向 d 的
  右手转 q 度。车床直径编程的 X 轴，位移 = 指令值 / 2。
- 工件坐标 = 所有轴零位时的机床坐标（随工件一侧的轴一起动）。工件零点偏置（G54 等）由调用方另加。
- 刀具：零位时刀轴方向 `tool.direction`（刀尖指向主轴）、主轴端面基准点 `tool.gauge_point_mm`；刀长 L 时刀尖 = 基准点 − L·方向。
  车床没有 `tool` 时，刀尖取机床原点（刀补由调用方处理）。

正解：`forward(machine, q, tool_length)` → 工件坐标里的刀尖点和刀轴方向。
逆解：`inverse(machine, tip, axis, tool_length, prefer=…)` → 各轴位置。回转轴（0–2 个）先按刀轴方向解（两个回转轴最多两组解，
按行程和离 `prefer` 最近选），直线轴再按刀尖点解（刀尖对直线轴是仿射的，按列求解）。刀轴方向正好落在回转轴上（奇异点）时，
那根轴取 `prefer` 里的值（没有就取 0），保持连续。
"""

from __future__ import annotations

import math
from itertools import product

import numpy as np

EPS = 1e-12


class KinematicsError(ValueError):
    pass


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if n < EPS:
        raise KinematicsError("方向向量长度为 0")
    return v / n


def rot(axis, deg: float) -> np.ndarray:
    """绕单位向量 axis 右手转 deg 度的 3×3 旋转矩阵（罗德里格斯公式）"""
    k = _unit(axis)
    t = math.radians(deg)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * (K @ K)


def _motion(ax: dict, q: float) -> np.ndarray:
    """一个轴走到指令值 q 时的 4×4 齐次变换（机床坐标、零位定义）"""
    T = np.eye(4)
    d = _unit(ax["direction"])
    if ax["type"] == "linear":
        T[:3, 3] = d * (q / 2.0 if ax.get("diameter_mode") else q)
    else:
        R = rot(d, q)
        p = np.asarray(ax["point_mm"], dtype=float)
        T[:3, :3] = R
        T[:3, 3] = p - R @ p
    return T


def chains(machine: dict) -> tuple[list[dict], list[dict]]:
    """(刀具一侧, 工件一侧)，各按底座往外的顺序（即文件里的顺序）"""
    axes = machine["axes"]
    return [a for a in axes if a["carrier"] == "tool"], [a for a in axes if a["carrier"] == "workpiece"]


def axis_ids(machine: dict) -> list[str]:
    return [a["id"] for a in machine["axes"]]


def _chain(axes: list[dict], q: dict) -> np.ndarray:
    T = np.eye(4)
    for a in axes:
        T = T @ _motion(a, float(q.get(a["id"], 0.0)))
    return T


def _tool0(machine: dict, tool_length: float) -> tuple[np.ndarray, np.ndarray]:
    t = machine.get("tool")
    if not t:
        return np.zeros(3), np.array([0.0, 0.0, 1.0])
    d = _unit(t["direction"])
    return np.asarray(t["gauge_point_mm"], dtype=float) - tool_length * d, d


def relative(machine: dict, q: dict) -> np.ndarray:
    """刀具一侧相对工件一侧的 4×4 变换：工件坐标 = relative · 零位刀具坐标"""
    tool, work = chains(machine)
    return np.linalg.inv(_chain(work, q)) @ _chain(tool, q)


def forward(machine: dict, q: dict, tool_length: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """各轴位置 q（{轴号: 指令值}，没写的按 0）→ 工件坐标里的刀尖点（mm）与刀轴方向（单位向量，刀尖指向主轴）"""
    tip0, d0 = _tool0(machine, tool_length)
    T = relative(machine, q)
    return T[:3, :3] @ tip0 + T[:3, 3], T[:3, :3] @ d0


# ---------------- 逆解 ----------------

def _sp1(w, p, q) -> float | None:
    """Paden–Kahan 子问题 1：绕过原点的单位轴 w 转 θ 把 p 转到 q；返回角度（度），p 在轴上时返回 None"""
    w = _unit(w)
    pp = p - w * (w @ p)
    qq = q - w * (w @ q)
    if np.linalg.norm(pp) < 1e-12 or np.linalg.norm(qq) < 1e-12:
        return None
    return math.degrees(math.atan2(w @ np.cross(pp, qq), pp @ qq))


def _sp2(w1, w2, p, q) -> list[tuple[float, float]]:
    """Paden–Kahan 子问题 2：rot(w1,θ1)·rot(w2,θ2)·p = q（单位向量，轴过原点）。返回 [(θ1, θ2) 度]，可能 0、1、2 组。
    奇异（p 或 q 在某根轴上）时那根轴的角度返回 None，由调用方按连续性取值。"""
    w1, w2 = _unit(w1), _unit(w2)
    p, q = _unit(p), _unit(q)
    c12 = w1 @ w2
    if abs(abs(c12) - 1) < 1e-12:
        raise KinematicsError("两根回转轴平行，定不了刀轴方向")
    # 中间向量 c = rot(w2,θ2) p = rot(w1,-θ1) q：c·w2 = p·w2，c·w1 = q·w1，|c| = 1
    a = ((c12 * (w2 @ p)) - (w1 @ q)) / (c12 ** 2 - 1)
    b = ((c12 * (w1 @ q)) - (w2 @ p)) / (c12 ** 2 - 1)
    n = np.cross(w1, w2)
    g2 = (1 - a * a - b * b - 2 * a * b * c12) / (n @ n)
    if g2 < -1e-12:
        return []
    gs = [0.0] if g2 < 1e-24 else [math.sqrt(max(g2, 0.0)), -math.sqrt(max(g2, 0.0))]
    out = []
    for g in gs:
        c = a * w1 + b * w2 + g * n
        t2 = _sp1(w2, p, c)
        t1 = _sp1(w1, c, q)
        out.append((t1, t2))
    return out


def _wrap(deg: float, ax: dict, near: float | None) -> list[float]:
    """回转角的候选：连续轴取离 near 最近的整圈；有行程的轴列出行程内的 ±360° 等价角"""
    cands = [deg + 360.0 * k for k in range(-3, 4)]
    if ax.get("continuous"):
        ref = 0.0 if near is None else near
        return [min(cands, key=lambda x: abs(x - ref))]
    lo, hi = float(ax["min"]), float(ax["max"])
    inside = [x for x in cands if lo - 1e-9 <= x <= hi + 1e-9]
    # 行程内没有：留下 (-180, 180] 里的那个，让调用方报“超程”而不是“达不到”
    return inside or [(deg + 180.0) % 360.0 - 180.0]


def _rotary_solutions(machine: dict, axis_w: np.ndarray, prefer: dict) -> list[dict]:
    """满足刀轴方向的回转轴角度组（未检查直线轴）"""
    tool, work = chains(machine)
    rots = [a for a in machine["axes"] if a["type"] == "rotary"]
    d0 = _unit((machine.get("tool") or {}).get("direction", [0, 0, 1]))
    v = _unit(axis_w)
    if not rots:
        if np.linalg.norm(np.cross(d0, v)) > 1e-9:
            raise KinematicsError("这台机床没有回转轴，刀轴方向只能是 " + str(d0.tolist()))
        return [{}]
    # 方向只受回转轴影响：v = Rw⁻¹·Rt·d0，Rw、Rt 是两侧回转轴旋转的乘积（按链顺序）
    # 写成 rot(w1,α)·rot(w2,β)·p = q 的形式（α、β 对应的真实轴角带正负号）
    tr = [a for a in tool if a["type"] == "rotary"]
    wr = [a for a in work if a["type"] == "rotary"]
    if len(rots) > 2:
        raise KinematicsError("超过两个回转轴的机床（C4 阶段）还没有逆解")
    if len(rots) == 1:
        ax = rots[0]
        w = _unit(ax["direction"])
        # 刀具一侧：rot(w,θ)·d0 = v；工件一侧：rot(w,-θ)·d0 = v  →  rot(w,θ)·v = d0
        t = _sp1(w, d0, v) if ax["carrier"] == "tool" else _sp1(w, v, d0)
        if t is None:  # 刀轴与回转轴平行（车铣中心端面加工）：方向与 θ 无关，θ 自由
            if abs(abs(w @ d0) - 1) > 1e-9 or np.linalg.norm(np.cross(d0, v)) > 1e-9:
                raise KinematicsError("刀轴方向达不到")
            t = float(prefer.get(ax["id"], 0.0))
        elif abs((w @ d0) - (w @ v)) > 1e-9:
            raise KinematicsError("刀轴方向达不到（与回转轴夹角不对）")
        return [{ax["id"]: x} for x in _wrap(t, ax, prefer.get(ax["id"]))]
    if len(tr) == 2:      # 摆头：v = rot(a1,θ1)·rot(a2,θ2)·d0
        (a1, s1), (a2, s2), p, q = (tr[0], 1), (tr[1], 1), d0, v
    elif len(wr) == 2:    # 摇篮：v = rot(a2,-θ2)·rot(a1,-θ1)·d0 → rot(a1,θ1)·rot(a2,θ2)·v = d0
        (a1, s1), (a2, s2), p, q = (wr[0], 1), (wr[1], 1), v, d0
    else:                 # 一头一台：v = rot(w,-θw)·rot(t,θt)·d0 → rot(t,-θt)·rot(w,θw)·v = d0
        (a1, s1), (a2, s2), p, q = (tr[0], -1), (wr[0], 1), v, d0
    w1, w2 = _unit(a1["direction"]), _unit(a2["direction"])
    out = []
    for t1, t2 in _sp2(w1, w2, p, q):
        if t2 is None:   # 奇异：p 在 w2 上，θ2 自由，取 prefer 保持连续，再解 θ1
            t2 = s2 * float(prefer.get(a2["id"], 0.0))
            t1 = _sp1(w1, rot(w2, t2) @ p, q)
        if t1 is None:
            t1 = s1 * float(prefer.get(a1["id"], 0.0))
        for x1, x2 in product(_wrap(s1 * t1, a1, prefer.get(a1["id"])), _wrap(s2 * t2, a2, prefer.get(a2["id"]))):
            out.append({a1["id"]: x1, a2["id"]: x2})
    return out


def _linear_solve(machine: dict, qr: dict, tip_w, tool_length: float, prefer: dict) -> dict | None:
    """回转轴定了以后，刀尖点对直线轴是仿射的：f(q) = f(0) + J·q，按列求 J 再解；残差 > 1e-9 mm 视为达不到"""
    lin = [a for a in machine["axes"] if a["type"] == "linear"]
    base = dict(qr)
    for a in lin:
        base[a["id"]] = 0.0
    f0, _ = forward(machine, base, tool_length)
    J = np.zeros((3, len(lin)))
    for i, a in enumerate(lin):
        qq = dict(base)
        qq[a["id"]] = 1.0
        J[:, i] = forward(machine, qq, tool_length)[0] - f0
    rhs = np.asarray(tip_w, dtype=float) - f0
    if len(lin) > 3 or np.linalg.matrix_rank(J, tol=1e-12) < len(lin):
        # 冗余（例如车铣中心 X、Y、Z + C）：按 prefer 固定多余的轴不在这里处理，交给调用方
        raise KinematicsError("直线轴冗余或共线，逆解不唯一")
    x, *_ = np.linalg.lstsq(J, rhs, rcond=None)
    if np.linalg.norm(J @ x - rhs) > 1e-9:
        return None
    out = dict(qr)
    for a, v in zip(lin, x):
        out[a["id"]] = float(v)
    return out


def in_limits(machine: dict, q: dict, tol: float = 1e-9) -> list[str]:
    """超程的轴（中文说明）；空 = 都在行程内"""
    bad = []
    for a in machine["axes"]:
        if a.get("continuous") or a["id"] not in q:
            continue
        v = q[a["id"]]
        if v < float(a["min"]) - tol or v > float(a["max"]) + tol:
            bad.append(f"{a['id']} = {v:.4f} 超出行程 [{float(a['min']):g}, {float(a['max']):g}]")
    return bad


def inverse_all(machine: dict, tip, axis=None, tool_length: float = 0.0, prefer: dict | None = None) -> list[dict]:
    """全部解（回转角已按行程展开），未按行程筛选直线轴"""
    prefer = prefer or {}
    if axis is None:
        axis = _unit((machine.get("tool") or {}).get("direction", [0, 0, 1]))
    sols = []
    for qr in _rotary_solutions(machine, np.asarray(axis, dtype=float), prefer):
        s = _linear_solve(machine, qr, tip, tool_length, prefer)
        if s is not None:
            sols.append(s)
    return sols


def _distance(a: dict, b: dict, machine: dict) -> float:
    d = 0.0
    for ax in machine["axes"]:
        if ax["id"] in b:
            w = 1.0 if ax["type"] == "rotary" else 1e-3   # 回转轴的跳变（度）比直线轴（mm）更要紧
            d += w * abs(a.get(ax["id"], 0.0) - b[ax["id"]])
    return d


def inverse(machine: dict, tip, axis=None, tool_length: float = 0.0, prefer: dict | None = None) -> dict:
    """刀尖点（工件坐标，mm）+ 刀轴方向 → 各轴位置。几组解里先要都在行程内的，再取离 prefer（上一点）最近的"""
    prefer = prefer or {}
    sols = inverse_all(machine, tip, axis, tool_length, prefer)
    if not sols:
        raise KinematicsError("这个刀尖点和刀轴方向，机床的轴达不到")
    ok = [s for s in sols if not in_limits(machine, s)]
    if not ok:
        raise KinematicsError("有解但超程：" + "；".join(in_limits(machine, sols[0])))
    return min(ok, key=lambda s: _distance(s, prefer, machine))
