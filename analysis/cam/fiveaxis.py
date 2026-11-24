"""五轴联动（ADR-0104 C3、ADR-0106 C3a）：刀位计算、沿刀路逐点逆解与检查、线性化。

刀位 = 刀尖点（工件坐标，mm）+ 刀轴（单位向量，从刀尖指向主轴）。纯 numpy，不调用 FreeCAD。

- `swarf`：直纹面侧刃铣。直纹面由底边、顶边两条等点数折线给出（第 i 点连成一条直纹线），
  刀轴沿直纹线（底 → 顶），刀尖在底边沿曲面法向往外偏一个刀具半径（平底刀侧刃贴住曲面），可再沿刀轴往下伸 `below`。
- `densify`：相邻两刀位刀轴夹角大于 `max_angle` 时插点（刀尖直线插值、刀轴球面插值）。
- `solve`：逐点逆解，回转轴取离上一点最近的解；查超程（错误）、回转轴突变（错误）、奇异点附近（提示）。
"""

from __future__ import annotations

import itertools
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


def rotary_path(machine: dict, axes, prefer: dict | None = None, flip_deg: float = 30.0, breaks=()) -> list[dict]:
    """只按刀轴逐点解回转轴（刀尖跟随时程序只要回转轴角度，直线轴由数控系统算）。
    刀路按 breaks（快移的点的序号）分段；每段第一点的几组解都试：往下逐点取行程内、离上一点最近的解，
    挑一步转超过 flip_deg 的次数最少、再离上一段末尾最近、再总转角最小的那一路（只看第一点挑“离 0 最近”的解，
    走到半路回转轴撞行程头就得换一组解，一步甩 180°；换组放在快移里做）。
    给了 prefer 就从离它最近的那组起步。达不到或回转轴超程 → FiveAxisError（带第几个刀位）"""
    rots = _rotaries(machine)
    W = [_unit(w) for w in np.asarray(axes, float)]

    def cands(i, pref):
        try:
            cs = K._rotary_solutions(machine, W[i], pref)
        except K.KinematicsError as exc:
            raise FiveAxisError(f"第 {i + 1} 个刀位的刀轴机床达不到：{exc}") from exc
        ok = [c for c in cs if not K.in_limits({"axes": rots}, c)]
        if not ok:
            raise FiveAxisError(f"第 {i + 1} 个刀位回转轴超程：" + "；".join(K.in_limits({"axes": rots}, cs[0])) if cs
                                else f"第 {i + 1} 个刀位的刀轴机床达不到")
        return ok

    def dist(a, b):
        return sum(abs(a[k] - b.get(k, 0.0)) for k in a)

    cuts = sorted({0, *[int(b) for b in breaks if 0 < int(b) < len(W)]}) + [len(W)]
    out: list[dict] = []
    for s0, s1 in itertools.pairwise(cuts):
        prev = out[-1] if out else dict(prefer or {})
        starts = cands(s0, prev)
        if not out and prefer:
            starts = [min(starts, key=lambda c: dist(c, prefer))]
        best = None
        for st in starts:
            seg, flips, total = [st], 0, 0.0
            for i in range(s0 + 1, s1):
                q = min(cands(i, seg[-1]), key=lambda c: dist(c, seg[-1]))
                flips += max(abs(q[k] - seg[-1][k]) for k in q) > flip_deg
                total += dist(q, seg[-1])
                seg.append(q)
            key = (flips, dist(st, prev) if prev else 0.0, total)
            if best is None or key < best[0]:
                best = (key, seg)
        out += best[1]
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


def ball_surface(contacts, normals, radius: float, lead: float = 0.0, tilt: float = 0.0, lead_dir=None) -> tuple[np.ndarray, np.ndarray]:
    """球头刀曲面多轴精加工：接触点（曲面上）+ 曲面法向（指向刀具一侧）→ 刀位。
    球心 = 接触点 + R·n（球面与曲面在接触点相切，跟刀轴怎么倒无关）；刀轴按前倾、侧倾倒；刀尖 = 球心 − R·刀轴。
    lead_dir：给了就往这个固定方向前倾（不跟走刀方向，之字形来回走刀轴不变向，ADR-0106 C3c）"""
    c, nn = np.asarray(contacts, float), np.asarray(normals, float)
    if c.shape != nn.shape:
        raise FiveAxisError("接触点和法向的个数要一样")
    tips, axes = [], []
    for p, n, f in zip(c, nn, _feed_dirs(c)):
        n = _unit(n)
        w = tilt_axis(n, f if lead_dir is None else lead_dir, lead, tilt)
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


# ---------------------------------------------------------------- 刀轴控制（ADR-0106 C3c）
def pole(machine: dict) -> np.ndarray | None:
    """机床的极轴（刀轴贴着它就是奇异点）：工件一侧最外的回转轴，没有就刀具一侧最里的回转轴；方向在工件坐标里不随轴动。没有回转轴返回 None"""
    work = [a for a in machine["axes"] if a["type"] == "rotary" and a["carrier"] == "workpiece"]
    tool = [a for a in machine["axes"] if a["type"] == "rotary" and a["carrier"] == "tool"]
    if work:
        return _unit(work[-1]["direction"])
    if tool:
        return _unit(tool[0]["direction"])
    return None


def _horiz(a, pz):
    return a - pz * float(np.dot(a, pz))


def avoid_pole(axes, pz, min_deg: float = 3.0) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """刀轴离极轴 pz 不到 2·min_deg 的连续一段：往与这段刀轴水平走向垂直的侧向推，离极轴不到 min_deg 的推满（tan(min_deg)），
    min_deg 到 2·min_deg 之间逐渐减到 0。返回 (新刀轴, 改过的段 [(起, 止)])。刀轴绕过极轴时回转轴在这一段里慢慢转过去，不再一步甩"""
    A = np.array([_unit(a) for a in axes])
    pz = _unit(pz)
    ang = np.array([angle_deg(a, pz) for a in A])
    near = ang < 2 * min_deg
    runs, i = [], 0
    while i < len(A):
        if near[i]:
            j = i
            while j + 1 < len(A) and near[j + 1]:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    lam0 = math.tan(math.radians(min_deg)) * 1.05
    out = A.copy()
    kept = []
    for i, j in runs:
        seg = A[max(i - 1, 0):min(j + 2, len(A))]
        if max(angle_deg(seg[0], x) for x in seg) < 0.1:      # 刀轴这一段基本不变（例如一直竖着）：回转轴不用动，不推
            continue
        kept.append((i, j))
        h0, h1 = _horiz(A[max(i - 1, 0)], pz), _horiz(A[min(j + 1, len(A) - 1)], pz)
        d = h1 - h0
        if np.linalg.norm(d) < 1e-9:
            hm = np.mean([_horiz(a, pz) for a in A[i:j + 1]], axis=0)
            side = hm if np.linalg.norm(hm) > 1e-9 else _horiz(np.array([1.0, 0.0, 0.0]), pz)
        else:
            side = np.cross(pz, d)
            if np.linalg.norm(side) < 1e-12:
                side = _horiz(np.array([1.0, 0.0, 0.0]), pz)
        side = _unit(side)
        hm = np.mean([_horiz(a, pz) for a in A[i:j + 1]], axis=0)
        if float(np.dot(hm, side)) < 0:              # 往这段本来就偏的那一侧推（反过来推会把偏移抵掉，反而贴到极轴上）
            side = -side
        for k in range(i, j + 1):
            w = min(1.0, max(0.0, (2 * min_deg - ang[k]) / min_deg))
            out[k] = _unit(A[k] + lam0 * w * side)
    return out, kept


def ball_reaxis(tips, axes, new_axes, radius: float) -> np.ndarray:
    """球头刀换刀轴：球心不动（与曲面仍相切），刀尖 = 球心 − R·新刀轴"""
    t, a, b = np.asarray(tips, float), np.asarray(axes, float), np.asarray(new_axes, float)
    return t + radius * a - radius * b


def _rotate_toward(a, u, deg):
    a = _unit(a)
    u = np.asarray(u, float) - a * float(np.dot(u, a))
    if np.linalg.norm(u) < 1e-12:
        return a
    u = _unit(u)
    t = math.radians(deg)
    return _unit(math.cos(t) * a + math.sin(t) * u)


def shank_clear(center, axis, parts, dist_fn, clearance: float) -> float:
    """刀杆、刀柄（parts：[(离球心的起高, 止高, 半径)]）离零件最近还剩多少（mm，负数是碰了）"""
    worst = math.inf
    for z0, z1, r in parts:
        n = max(2, math.ceil((z1 - z0) / max(r / 2, 0.5)) + 1)
        pts = np.array([center + z * axis for z in np.linspace(z0, z1, n)])
        worst = min(worst, float(np.min(dist_fn(pts))) - r - clearance)
    return worst


def avoid_collision(tips, axes, radius: float, parts, dist_fn, clearance: float = 1.0, max_tilt: float = 45.0,
                    step: float = 2.0, dirs: int = 8) -> dict:
    """球头刀：刀杆、刀柄碰零件的点，绕球心把刀轴往某个侧向加大倾角（每次 step 度，到 max_tilt 为止），刀轴连续。
    dist_fn(点 k×3) → 到零件表面的距离（不带符号也行，刀杆不会在零件里面）。
    同一段连着碰的点用同一个侧向（dirs 个方向里，让这段最大倾角最小的那个）；倾角沿刀路平滑（相邻点差不超过 step）。
    返回 {"tips", "axes", "tilt": 每点加的倾角, "issues": [到 max_tilt 还碰的点]}"""
    T, A = np.asarray(tips, float), np.array([_unit(a) for a in axes])
    C = T + radius * A
    n = len(A)
    hit = np.array([shank_clear(C[k], A[k], parts, dist_fn, clearance) < 0 for k in range(n)])
    tilt = np.zeros(n)
    side = [None] * n
    issues = []
    k = 0
    while k < n:
        if not hit[k]:
            k += 1
            continue
        j = k
        while j + 1 < n and hit[j + 1]:
            j += 1
        best = None
        for m in range(dirs):
            th = 2 * math.pi * m / dirs
            need = []
            for i in range(k, j + 1):
                a = A[i]
                e1 = _unit(np.cross(a, [0.0, 0.0, 1.0])) if abs(a[2]) < 0.99 else _unit(np.cross(a, [1.0, 0.0, 0.0]))
                e2 = np.cross(a, e1)
                u = math.cos(th) * e1 + math.sin(th) * e2
                g = step
                while g <= max_tilt + 1e-9 and shank_clear(C[i], _rotate_toward(a, u, g), parts, dist_fn, clearance) < 0:
                    g += step
                need.append((g, u))
            worst = max(g for g, _ in need)
            if best is None or worst < best[0]:
                best = (worst, need)
        for i, (g, u) in zip(range(k, j + 1), best[1]):
            tilt[i], side[i] = g, u
            if g > max_tilt + 1e-9:
                issues.append({"i": i, "level": "error",
                               "text": f"第 {i + 1} 个刀位刀轴倒到 {max_tilt:g}° 刀杆、刀柄还碰零件：换更长、更细的刀，或改刀路"})
        k = j + 1
    # 平滑：倾角从碰撞段往两边每点减 step 延伸；没碰的点取前、后两个方向延伸过来的大的那个（连侧向一起），
    # 两个碰撞段的延伸在中间相遇时倾角已经减到 0 或很小，刀轴不跳
    fw_t, fw_s = tilt.copy(), list(side)
    for i in range(1, n):
        if fw_t[i - 1] - step > fw_t[i]:
            fw_t[i], fw_s[i] = fw_t[i - 1] - step, (fw_s[i] if hit[i] else fw_s[i - 1])
    bw_t, bw_s = tilt.copy(), list(side)
    for i in range(n - 2, -1, -1):
        if bw_t[i + 1] - step > bw_t[i]:
            bw_t[i], bw_s[i] = bw_t[i + 1] - step, (bw_s[i] if hit[i] else bw_s[i + 1])
    for i in range(n):
        if hit[i]:                                   # 碰撞段里也限住相邻点的差（侧向是这段自己的）
            tilt[i] = max(fw_t[i], bw_t[i])
        else:
            tilt[i], side[i] = (fw_t[i], fw_s[i]) if fw_t[i] >= bw_t[i] else (bw_t[i], bw_s[i])
    newA = np.array([_rotate_toward(A[i], side[i], min(tilt[i], max_tilt)) if side[i] is not None and tilt[i] > 0 else A[i]
                     for i in range(n)])
    return {"tips": C - radius * newA, "axes": newA, "tilt": tilt, "issues": issues}


# ---------------------------------------------------------------- 非 RTCP 输出（ADR-0106 C3c-2）
def machine_points(machine: dict, tips, axes, rots, tool_length: float, offset, chord: float = 0.01,
                   max_depth: int = 8) -> list[tuple[dict, np.ndarray, np.ndarray, int]]:
    """刀位 → 机床轴位置（逐点逆解，回转轴取 rots 那一组）。机床各轴直线插补时刀尖在两点间走弯：
    中点处刀尖离两点连线超过 chord 就在中间插一个刀位（刀尖直线插值、刀轴球面插值），一直分到不超过为止。
    返回 [(各轴位置, 刀尖, 刀轴, 原来第几个刀位)]"""
    off = np.asarray(offset, float)
    T, A = np.asarray(tips, float), np.array([_unit(a) for a in axes])

    def q_of(p, w, pref):
        try:
            return K.inverse(machine, p + off, w, tool_length, prefer=pref)
        except K.KinematicsError as exc:
            raise FiveAxisError(f"机床走不到：{exc}") from exc

    def mid_dev(qa, qb, pa, pb):
        qm = {k: 0.5 * (qa[k] + qb[k]) for k in qa}
        tm, _ = K.forward(machine, qm, tool_length)
        return float(np.linalg.norm(tm - off - 0.5 * (pa + pb)))

    out = []
    q_prev = None
    for i in range(len(T)):
        q = q_of(T[i], A[i], {**(q_prev or {}), **rots[i]})
        if q_prev is not None:
            stack = [(0.0, 1.0, q_prev, q, 0)]
            ins = []
            while stack:
                s0, s1, qa, qb, d = stack.pop()
                pa = T[i - 1] + s0 * (T[i] - T[i - 1])
                pb = T[i - 1] + s1 * (T[i] - T[i - 1])
                if d < max_depth and mid_dev(qa, qb, pa, pb) > chord:
                    sm = 0.5 * (s0 + s1)
                    pm, wm = T[i - 1] + sm * (T[i] - T[i - 1]), slerp(A[i - 1], A[i], sm)
                    qm = q_of(pm, wm, {k: 0.5 * (qa[k] + qb[k]) for k in qa})
                    stack.append((sm, s1, qm, qb, d + 1))
                    stack.append((s0, sm, qa, qm, d + 1))
                    continue
                if s1 < 1.0:
                    ins.append((qb, T[i - 1] + s1 * (T[i] - T[i - 1]), slerp(A[i - 1], A[i], s1), i))
            out += ins
        out.append((q, T[i], A[i], i))
        q_prev = q
    return out
