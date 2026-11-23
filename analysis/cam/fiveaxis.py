"""五轴联动（ADR-0104 C3、ADR-0106 C3a）：刀位计算、沿刀路逐点逆解与检查、线性化。

刀位 = 刀尖点（工件坐标，mm）+ 刀轴（单位向量，从刀尖指向主轴）。纯 numpy，不调用 FreeCAD。

- `swarf`：直纹面侧刃铣。直纹面由底边、顶边两条等点数折线给出（第 i 点连成一条直纹线），
  刀轴沿直纹线（底 → 顶），刀尖在底边沿曲面法向往外偏一个刀具半径（平底刀侧刃贴住曲面），可再沿刀轴往下伸 `below`。
- `densify`：相邻两刀位刀轴夹角大于 `max_angle` 时插点（刀尖直线插值、刀轴球面插值）。
- `solve`：逐点逆解，回转轴取离上一点最近的解；查超程（错误）、回转轴突变（错误）、奇异点附近（提示）。
"""

from __future__ import annotations

import math

import numpy as np

from analysis.cam import kinematics as K


class FiveAxisError(ValueError):
    pass


def _unit(v) -> np.ndarray:
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise FiveAxisError("方向向量长度为 0")
    return v / n


def angle_deg(a, b) -> float:
    """两单位向量的夹角（度）"""
    return math.degrees(math.atan2(float(np.linalg.norm(np.cross(a, b))), float(np.dot(a, b))))


def slerp(a, b, t: float) -> np.ndarray:
    a, b = _unit(a), _unit(b)
    om = math.atan2(float(np.linalg.norm(np.cross(a, b))), float(np.dot(a, b)))
    if om < 1e-12:
        return a.copy()
    return (math.sin((1 - t) * om) * a + math.sin(t * om) * b) / math.sin(om)


# ---------------------------------------------------------------- 刀位
def swarf(bottom, top, radius: float, side: int = 1, below: float = 0.0, closed: bool = False,
          normals=None) -> tuple[np.ndarray, np.ndarray]:
    """直纹面侧刃铣的刀位：返回 (刀尖点 N×3, 刀轴 N×3)。
    side = 1：刀具在 (底边走向 × 直纹线方向) 那一侧（逆时针绕一圈的外侧）；−1 反过来。closed：底边首尾相连（求切向用）。
    normals：底边各点的曲面法向（指向刀具一侧，如 FreeCAD 面的外法向）；给了就按它定刀具在哪一侧（去掉沿直纹线的分量），side 不用"""
    b = np.asarray(bottom, float)
    t_ = np.asarray(top, float)
    if b.shape != t_.shape or b.ndim != 2 or b.shape[1] != 3 or len(b) < 2:
        raise FiveAxisError("直纹面的底边、顶边要是点数相同的三维折线（至少 2 点）")
    n = len(b)
    tips, axes = [], []
    for i in range(n):
        u = _unit(t_[i] - b[i])
        if closed:
            tg = b[(i + 1) % n] - b[(i - 1) % n]
        else:
            tg = b[min(i + 1, n - 1)] - b[max(i - 1, 0)]
        if normals is not None:
            g = np.asarray(normals[i], float)
            nrm = g - u * float(np.dot(g, u))
            sgn = 1
        else:
            nrm, sgn = np.cross(tg, u), side
        nn = float(np.linalg.norm(nrm))
        if nn < 1e-12:
            raise FiveAxisError(f"第 {i + 1} 点：底边走向与直纹线平行，定不了曲面法向")
        nrm = sgn * nrm / nn
        tips.append(b[i] + radius * nrm - below * u)
        axes.append(u)
    return np.array(tips), np.array(axes)


def densify(tips, axes, max_angle: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """相邻两刀位刀轴夹角大于 max_angle（度）时等分插点"""
    tips, axes = np.asarray(tips, float), np.asarray(axes, float)
    out_t, out_a = [tips[0]], [_unit(axes[0])]
    for i in range(1, len(tips)):
        a0, a1 = _unit(axes[i - 1]), _unit(axes[i])
        k = max(1, math.ceil(angle_deg(a0, a1) / max_angle - 1e-9))
        for j in range(1, k + 1):
            s = j / k
            out_t.append(tips[i - 1] + s * (tips[i] - tips[i - 1]))
            out_a.append(slerp(a0, a1, s))
    return np.array(out_t), np.array(out_a)


# ---------------------------------------------------------------- 逐点逆解
def _rotaries(machine: dict) -> list[dict]:
    return [a for a in machine["axes"] if a["type"] == "rotary"]


def singular_margin(machine: dict, q: dict) -> tuple[float, str | None]:
    """刀轴对各回转轴的灵敏度：某根回转轴转 1° 刀轴几乎不动（刀轴贴着这根轴）就是奇异点附近。
    返回 (最小灵敏度换成的角度（度），那根轴)；没有回转轴返回 (180, None)"""
    _, v0 = K.forward(machine, q)
    best, which = 180.0, None
    for ax in _rotaries(machine):
        q1 = dict(q)
        q1[ax["id"]] = float(q.get(ax["id"], 0.0)) + 1.0
        _, v1 = K.forward(machine, q1)
        s = float(np.linalg.norm(v1 - v0)) / math.radians(1.0)       # = |刀轴 × 回转轴方向| = sin(两者夹角)
        ang = math.degrees(math.asin(min(1.0, s)))
        if ang < best:
            best, which = ang, ax["id"]
    return best, which


def solve(machine: dict, tips, axes, tool_length: float = 0.0, offset=(0.0, 0.0, 0.0), prefer: dict | None = None,
          flip_deg: float = 30.0, singular_deg: float = 1.0, lines=None) -> dict:
    """沿刀路逐点逆解 → {"q": [各点轴位置], "issues": [{"i", "line", "level", "text"}]}。
    offset：工件零点在机床坐标里的位置（G54），刀尖加上它再逆解。lines：每点的程序行号（报问题用，可不给）。
    回转轴取离上一点最近的解；超程、达不到 → 错误，从这点起不再往下解；回转轴一步转过 flip_deg 以上 → 错误；
    刀轴离某根回转轴不到 singular_deg → 提示（同一段只报一次）"""
    off = np.asarray(offset, float)
    pref = dict(prefer or {})
    qs, issues = [], []
    near_sing = False
    for i, (p, w) in enumerate(zip(np.asarray(tips, float), np.asarray(axes, float))):
        ln = None if lines is None else lines[i]
        try:
            q = K.inverse(machine, p + off, _unit(w), tool_length, prefer=pref)
        except K.KinematicsError as exc:
            issues.append({"i": i, "line": ln, "level": "error", "text": f"第 {i + 1} 个刀位机床走不到：{exc}"})
            break
        if qs:
            jumps = [(a["id"], q[a["id"]] - qs[-1][a["id"]]) for a in _rotaries(machine) if a["id"] in q and a["id"] in qs[-1]]
            big = [(k, d) for k, d in jumps if abs(d) > flip_deg]
            if big:
                k, d = max(big, key=lambda x: abs(x[1]))
                issues.append({"i": i, "line": ln, "level": "error",
                               "text": f"第 {i + 1} 个刀位回转轴 {k} 一步转了 {d:+.1f}°（超过 {flip_deg:g}°）：多半是过了奇异点或换了一组解，"
                                       "刀尖会在工件上乱走；改刀轴避开奇异点"})
        m, which = singular_margin(machine, q)
        if m < singular_deg:
            if not near_sing:
                issues.append({"i": i, "line": ln, "level": "warn",
                               "text": f"第 {i + 1} 个刀位刀轴离回转轴 {which} 只有 {m:.2f}°（奇异点附近）：{which} 转多少刀轴都差不多，"
                                       "机床可能在这里猛转；刀轴别贴着回转轴"})
            near_sing = True
        else:
            near_sing = False
        qs.append(q)
        pref = q
    return {"q": qs, "issues": issues}


def rotary_words(machine: dict, q: dict, nd: int = 3) -> list[tuple[str, float]]:
    """程序里写的回转轴（按机床文件顺序）与角度"""
    return [(a["id"], round(float(q[a["id"]]), nd)) for a in _rotaries(machine) if a["id"] in q]


def axis_from_rotary(machine: dict, rot: dict) -> np.ndarray:
    """回转轴角度 → 工件坐标里的刀轴（只看回转轴，直线轴取 0）"""
    q = {a["id"]: float(rot.get(a["id"], 0.0)) for a in _rotaries(machine)}
    return K.forward(machine, q)[1]


def rotary_path(machine: dict, axes, prefer: dict | None = None) -> list[dict]:
    """只按刀轴逐点解回转轴（刀尖跟随时程序只要回转轴角度，直线轴由数控系统算）：每点取回转轴行程内、离上一点最近的解。
    达不到或回转轴超程 → FiveAxisError（带第几个刀位）"""
    pref = dict(prefer or {})
    rots = _rotaries(machine)
    out = []
    for i, w in enumerate(np.asarray(axes, float)):
        try:
            cands = K._rotary_solutions(machine, _unit(w), pref)
        except K.KinematicsError as exc:
            raise FiveAxisError(f"第 {i + 1} 个刀位的刀轴机床达不到：{exc}") from exc
        ok = [c for c in cands if not K.in_limits({"axes": rots}, c)]
        if not ok:
            raise FiveAxisError(f"第 {i + 1} 个刀位回转轴超程：" + "；".join(K.in_limits({"axes": rots}, cands[0])) if cands
                                else f"第 {i + 1} 个刀位的刀轴机床达不到")
        q = min(ok, key=lambda c: sum(abs(c[k] - pref.get(k, 0.0)) for k in c))
        out.append(q)
        pref = q
    return out


# ---------------------------------------------------------------- 曲面多轴精加工、沿曲线（ADR-0106 C3b）
def _frame(n, f):
    """接触点的局部标架：法向 n、走刀方向 t（f 投到切平面）、侧向 s = n × t"""
    n = _unit(n)
    t = np.asarray(f, float) - n * float(np.dot(f, n))
    if np.linalg.norm(t) < 1e-12:
        raise FiveAxisError("走刀方向与曲面法向平行，定不了前倾、侧倾")
    t = _unit(t)
    return n, t, np.cross(n, t)


def tilt_axis(n, f, lead: float = 0.0, tilt: float = 0.0) -> np.ndarray:
    """刀轴 = 曲面法向按前倾角、侧倾角（度）倒过去：前倾角为正时刀轴往走刀方向倒（刀柄在前、刀尖落后），
    侧倾角为正时往走刀方向的左侧（n × t 一侧）倒。先前倾再侧倾"""
    n, t, s = _frame(n, f)
    a, b = math.radians(lead), math.radians(tilt)
    return _unit(math.cos(b) * (math.cos(a) * n + math.sin(a) * t) + math.sin(b) * s)


def _feed_dirs(pts):
    p = np.asarray(pts, float)
    if len(p) < 2:
        raise FiveAxisError("刀路至少要 2 个点")
    d = np.empty_like(p)
    d[0], d[-1] = p[1] - p[0], p[-1] - p[-2]
    d[1:-1] = p[2:] - p[:-2]
    return d


def ball_surface(contacts, normals, radius: float, lead: float = 0.0, tilt: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """球头刀曲面多轴精加工：接触点（曲面上）+ 曲面法向（指向刀具一侧）→ 刀位。
    球心 = 接触点 + R·n（球面与曲面在接触点相切，跟刀轴怎么倒无关）；刀轴按前倾、侧倾倒；刀尖 = 球心 − R·刀轴"""
    c, nn = np.asarray(contacts, float), np.asarray(normals, float)
    if c.shape != nn.shape:
        raise FiveAxisError("接触点和法向的个数要一样")
    tips, axes = [], []
    for p, n, f in zip(c, nn, _feed_dirs(c)):
        n = _unit(n)
        w = tilt_axis(n, f, lead, tilt)
        ctr = p + radius * n
        tips.append(ctr - radius * w)
        axes.append(w)
    return np.array(tips), np.array(axes)


def curve_follow(points, normals, depth: float = 0.0, lead: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """沿曲线加工（刻线、去毛刺、沿边倒角）：刀轴取曲面法向（可再前倾），刀尖在曲线上往曲面里进 depth"""
    p, nn = np.asarray(points, float), np.asarray(normals, float)
    if p.shape != nn.shape:
        raise FiveAxisError("曲线点和法向的个数要一样")
    tips, axes = [], []
    for q, n, f in zip(p, nn, _feed_dirs(p)):
        n = _unit(n)
        tips.append(q - depth * n)
        axes.append(tilt_axis(n, f, lead, 0.0) if lead else n)
    return np.array(tips), np.array(axes)


def zigzag(rows: list) -> list:
    """一行一行的点（每行一串点，或 (点, 法向) 这样几组等长数组）→ 之字形：奇数行（从 0 数）反过来走"""
    def rev(r):
        return tuple(np.asarray(x)[::-1] for x in r) if isinstance(r, tuple) else np.asarray(r)[::-1]
    return [r if i % 2 == 0 else rev(r) for i, r in enumerate(rows)]


def link_moves(segments, f: float, safe_dist: float = 5.0, link: str = "lift", clear_z: float | None = None) -> list[dict]:
    """几段刀位（[(tips, axes), …]）→ 中间格式走刀（simul5）。每段开头沿刀轴退 safe_dist 快移到位、进给切入，结尾沿刀轴退出；
    link = "direct" 时相邻两段之间直接进给连过去（行距小、曲面连续的之字形精加工）。
    clear_z：给了就沿刀轴退到高于这个 Z（毛坯顶面以上）再快移，切入、退出都用进给（中间可能有材料）"""
    def up(p, a):
        a = np.asarray(a, float)
        d = safe_dist
        if clear_z is not None and a[2] > 0.05:
            d = max(d, (clear_z - p[2]) / a[2])
        return p + d * a

    def mv_(t, p, a, **kw):
        return {"t": t, "x": float(p[0]), "y": float(p[1]), "z": float(p[2]), "axis": [float(v) for v in a], **kw}

    out = []
    for k, (tips, axes) in enumerate(segments):
        tips, axes = np.asarray(tips, float), np.asarray(axes, float)
        if k == 0 or link != "direct":
            u0 = up(tips[0], axes[0])
            out.append(mv_("rapid", u0, axes[0]))
        for p, a in zip(tips, axes):
            out.append(mv_("feed", p, a, f=float(f)))
        if k == len(segments) - 1 or link != "direct":
            u1 = up(tips[-1], axes[-1])
            out.append(mv_("feed", u1, axes[-1], f=float(f)) if clear_z is not None else mv_("rapid", u1, axes[-1]))
    return out
