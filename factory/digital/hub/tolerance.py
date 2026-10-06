"""尺寸链与定位误差计算库（第 13 轮 7.3（4）N4）：教材第 51、53、57、59–69 章的算例和 AI 工艺评审员共用。

尺寸链
- `Link`：组成环（基本尺寸、上下偏差、增环 +1 / 减环 −1）；
- `extreme(links)`：极值法求封闭环（完全互换）；
- `statistical(links, k=1.0)`：概率法（各环正态、对称分布于公差带中点时 k = 1；偏态时 k > 1）；
- `monte_carlo(links, n, dist)`：蒙特卡罗模拟核对；
- `solve_link(links, closing, unknown)`：已知封闭环要求，反求一个组成环（工序尺寸换算、“中间计算”）。

工艺尺寸跟踪图（tolerance chart）
- `ToleranceChart`：按工序顺序登记每一刀“以哪个面为基准、加工哪个面、工序尺寸多少”，程序把每个面在各工序的“版本”连成一棵树；
  任两个面（例如图纸尺寸的两端、某面相邻两次加工的版本）之间的路径就是尺寸链，自动求出图纸尺寸能否保证、每次加工的余量最小最大值。

定位误差
- V 形块、心轴（定位销）、一面两销、顶尖与中心孔，以及基准不重合误差；`v_block_mc` 用蒙特卡罗核对公式。

单位：mm；角度：度。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


# ---------------------------------------------------------------- 尺寸链
@dataclass
class Link:
    name: str
    nominal: float
    es: float = 0.0
    ei: float = 0.0
    sense: int = +1           # +1 增环，−1 减环

    @property
    def T(self):
        return self.es - self.ei

    @property
    def mid(self):            # 中间偏差
        return (self.es + self.ei) / 2

    @property
    def max(self):
        return self.nominal + self.es

    @property
    def min(self):
        return self.nominal + self.ei


@dataclass
class Result:
    nominal: float
    es: float
    ei: float
    method: str
    detail: dict = field(default_factory=dict)

    @property
    def T(self):
        return self.es - self.ei

    @property
    def max(self):
        return self.nominal + self.es

    @property
    def min(self):
        return self.nominal + self.ei

    def text(self, nd=3):
        def s(x):
            return "0" if abs(x) < 10 ** -(nd + 1) else f"{x:+.{nd}f}".rstrip("0").rstrip(".").replace("-", "−")
        if abs(self.es + self.ei) < 10 ** -(nd + 1) and abs(self.es) > 10 ** -(nd + 1):
            return f"{self.nominal:g} ± {s(self.es)[1:]}"
        return f"{self.nominal:g}（{s(self.es)}/{s(self.ei)}）"


def extreme(links) -> Result:
    """极值法：A0 = Σ增 − Σ减；ES0 = Σ增ES − Σ减EI；EI0 = Σ增EI − Σ减ES；T0 = ΣTi。"""
    A0 = sum(l.sense * l.nominal for l in links)
    es = sum(l.es if l.sense > 0 else -l.ei for l in links)
    ei = sum(l.ei if l.sense > 0 else -l.es for l in links)
    return Result(A0, es, ei, "极值法", {"T_sum": sum(l.T for l in links)})


def statistical(links, k=1.0) -> Result:
    """概率法：封闭环中间偏差 Δ0 = Σ(±Δi)，公差 T0 = k·√ΣTi²（各环正态、公差带 = ±3σ 时 k = 1）。"""
    A0 = sum(l.sense * l.nominal for l in links)
    d0 = sum(l.sense * l.mid for l in links)
    T0 = k * math.sqrt(sum(l.T ** 2 for l in links))
    return Result(A0, d0 + T0 / 2, d0 - T0 / 2, "概率法", {"k": k, "mid": d0})


def monte_carlo(links, n=200_000, dist="normal", seed=1) -> Result:
    """蒙特卡罗：各环按正态（公差带 = ±3σ，截尾于公差带）、均匀、三角或偏态分布抽样，返回封闭环的 ±3σ 区间与实际极值。
    dist 可以是一个分布名（所有环相同），也可以是与 links 对应的列表。"""
    rng = random.Random(seed)
    dl = dist if isinstance(dist, (list, tuple)) else [dist] * len(links)
    vals = []
    for _ in range(n):
        s = 0.0
        for l, dist in zip(links, dl):
            if dist == "uniform":
                x = rng.uniform(l.min, l.max)
            elif dist == "triangle":
                x = rng.triangular(l.min, l.max)
            elif dist in ("skew_out", "skew_in"):           # 偏态：beta(3.23, 1.90) 或 beta(1.90, 3.23)，k ≈ 1.17、e ≈ ±0.26，与 DIST_KE 一致
                b = rng.betavariate(*SKEW_BETA) if dist == "skew_out" else rng.betavariate(*SKEW_BETA[::-1])
                x = l.min + b * l.T
            else:
                while True:
                    x = rng.gauss(l.nominal + l.mid, l.T / 6)
                    if l.min <= x <= l.max:
                        break
            s += l.sense * x
        vals.append(s)
    A0 = sum(l.sense * l.nominal for l in links)
    mu = sum(vals) / n
    sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / (n - 1))
    return Result(A0, mu - A0 + 3 * sd, mu - A0 - 3 * sd, "蒙特卡罗",
                  {"n": n, "dist": dl, "mean": mu, "sd": sd, "min": min(vals), "max": max(vals), "values": vals if n <= 50_000 else None})


# 各种分布的相对分布系数 k 与相对不对称系数 e（国内工艺尺寸链教材常用的取值，以 GB/T 5847 和所用手册为准）：
# 正态 k = 1、e = 0；三角 k ≈ 1.22；均匀 k ≈ 1.73；瑞利（如跳动、偏心）k ≈ 1.14、e ≈ −0.28；
# 偏态（试切法加工，外尺寸偏向最大实体）k ≈ 1.17、e ≈ +0.26，内尺寸 e ≈ −0.26。
SKEW_BETA = (3.23, 1.90)   # 均值 0.63（e = +0.26）、标准差 0.195 个公差（k = 6σ/T ≈ 1.17）的 beta 分布，蒙特卡罗用它模拟偏态
DIST_KE = {"normal": (1.0, 0.0), "triangle": (1.22, 0.0), "uniform": (1.73, 0.0), "rayleigh": (1.14, -0.28),
           "skew_out": (1.17, 0.26), "skew_in": (1.17, -0.26)}


def statistical_general(links, dists=None, k0: float = 1.0) -> Result:
    """概率法的一般形式：T0 = (1/k0)·√Σ(ki·Ti)²，封闭环的中间偏差 Δ0 = Σ ±(Δi + ei·Ti/2)。
    dists：与 links 一一对应的分布名（DIST_KE 的键）或 (k, e)；缺省全按正态（即 statistical）。
    e 的正负：分布中心偏向公差带上限为正。"""
    dists = dists or ["normal"] * len(links)
    ke = [DIST_KE[d] if isinstance(d, str) else d for d in dists]
    A0 = sum(l.sense * l.nominal for l in links)
    d0 = sum(l.sense * (l.mid + e * l.T / 2) for l, (k, e) in zip(links, ke))
    T0 = math.sqrt(sum((k * l.T) ** 2 for l, (k, e) in zip(links, ke))) / k0
    return Result(A0, d0 + T0 / 2, d0 - T0 / 2, "概率法（一般式）", {"mid": d0, "ke": ke})


SIZE_STEPS = (1, 3, 6, 10, 18, 30, 50, 80, 120, 180, 250, 315, 400, 500)   # GB/T 1800.1 的主段落（≤ 500 mm）


def tolerance_unit(D: float, by_step: bool = True) -> float:
    """标准公差因子 i = 0.45·∛D + 0.001·D（µm）。D 取尺寸所在段落两端的几何平均值（by_step=True，与 GB/T 1800.1 一致），
    by_step=False 时直接用 D。"""
    if by_step:
        lo = max(x for x in SIZE_STEPS if x < D) if D > SIZE_STEPS[0] else 0
        hi = min(x for x in SIZE_STEPS if x >= D)
        D = math.sqrt(lo * hi) if lo else math.sqrt(1 * 3)
    return 0.45 * D ** (1 / 3) + 0.001 * D


def allocate(T0: float, nominals: list, method: str = "equal_precision") -> list:
    """把封闭环公差 T0 分给各组成环（极值法）：equal_tolerance 等公差，equal_precision 等精度（各环公差与公差因子成正比）。"""
    n = len(nominals)
    if method == "equal_tolerance":
        return [T0 / n] * n
    iu = [tolerance_unit(max(D, 1.0)) for D in nominals]
    a = T0 / sum(iu)
    return [a * u for u in iu]


def solve_link(links, closing: tuple, unknown: str, sense: int = +1) -> Link:
    """反计算：已知封闭环 (A0, ES0, EI0) 和其余组成环，求名为 unknown 的组成环（极值法）。

    unknown 在 links 里可以不出现；sense 是它作为增环（+1）还是减环（−1）。"""
    A0, ES0, EI0 = closing
    others = [l for l in links if l.name != unknown]
    a = sum(l.sense * l.nominal for l in others)
    es_o = sum(l.es if l.sense > 0 else -l.ei for l in others)
    ei_o = sum(l.ei if l.sense > 0 else -l.es for l in others)
    nom = sense * (A0 - a)
    if sense > 0:
        es, ei = ES0 - es_o, EI0 - ei_o
    else:
        es, ei = -(EI0 - ei_o), -(ES0 - es_o)
    if es < ei - 1e-12:
        raise ValueError(f"封闭环公差 {ES0 - EI0:.4f} 小于其余组成环公差之和 {es_o - ei_o:.4f}：极值法下无解，要压缩其他环的公差或改用概率法")
    return Link(unknown, nom, es, ei, sense)


# ---------------------------------------------------------------- 工艺尺寸跟踪图
@dataclass
class Cut:
    seq: int                  # 工序号（或工序号.工步号）
    ref: str                  # 工序基准面（测量起点）
    surf: str                 # 本工序加工的面
    nominal: float            # 工序尺寸（从 ref 到 surf，沿坐标正向为正）
    es: float = 0.0
    ei: float = 0.0
    label: str = ""


class ToleranceChart:
    """一维（轴向）工艺尺寸跟踪图。

    每个面在毛坯上有一个初始版本（surf@0）；每次加工产生新版本（surf@seq），并通过这一刀的工序尺寸连到当时的基准面版本。
    所有版本组成一棵树（毛坯面之间由毛坯尺寸相连），任两个版本之间的路径就是一条尺寸链。
    坐标：面的位置 x 沿轴向；工序尺寸 = x(surf) − x(ref)。
    """

    def __init__(self, blank: list[tuple]):
        """blank: [(面A, 面B, 基本尺寸 x(B)−x(A), es, ei)]，毛坯上各面之间的尺寸（构成树）。"""
        self.edges = {}       # 版本 → [(邻接版本, Link 方向)]
        self.cur = {}         # 面 → 当前版本
        self.cuts = []
        for a, b, nom, es, ei in blank:
            va, vb = self._ver(a, 0), self._ver(b, 0)
            self._edge(va, vb, nom, es, ei, f"毛坯 {a}–{b}")

    def _ver(self, s, k):
        v = f"{s}@{k}"
        self.edges.setdefault(v, [])
        self.cur.setdefault(s, v)
        return v

    def _edge(self, va, vb, nom, es, ei, label):
        self.edges[va].append((vb, (nom, es, ei, label, +1)))
        self.edges[vb].append((va, (nom, es, ei, label, -1)))

    def cut(self, c: Cut):
        ref = self.cur[c.ref]
        v = f"{c.surf}@{c.seq}"
        self.edges.setdefault(v, [])
        prev = self.cur.get(c.surf)
        self._edge(ref, v, c.nominal, c.es, c.ei, c.label or f"工序 {c.seq} {c.ref}→{c.surf}")
        self.cur[c.surf] = v
        self.cuts.append((c, prev, v))
        return self

    def _path(self, va, vb):
        """树上 va → vb 的路径（BFS），返回 [(nom, es, ei, label, 方向)]，方向 +1 表示沿 x 正向累加。"""
        from collections import deque
        prev = {va: None}
        dq = deque([va])
        while dq:
            u = dq.popleft()
            if u == vb:
                break
            for w, e in self.edges[u]:
                if w not in prev:
                    prev[w] = (u, e)
                    dq.append(w)
        if vb not in prev:
            raise ValueError(f"{va} 与 {vb} 之间没有尺寸联系")
        out, u = [], vb
        while prev[u]:
            p, e = prev[u]
            out.append(e)
            u = p
        return list(reversed(out))

    def chain(self, a: str, b: str, version_a=None, version_b=None) -> list[Link]:
        """面 a（当前或指定版本）到面 b 的尺寸链：x(b) − x(a) = Σ(±组成环)。"""
        va = version_a or self.cur[a]
        vb = version_b or self.cur[b]
        return [Link(lab, nom, es, ei, d) for nom, es, ei, lab, d in self._path(va, vb)]

    def resultant(self, a, b, method="extreme") -> Result:
        links = self.chain(a, b)
        return extreme(links) if method == "extreme" else statistical(links)

    def allowances(self, cut_dir: dict | None = None) -> list[dict]:
        """每次加工的余量（切除厚度）：上一版本到新版本之间的尺寸链 r = x(新) − x(旧)。
        cut_dir：每个面加工时向哪个方向移动（+1 向 x 正向，如左端面、朝左的轴肩；−1 向负向，如右端面、朝右的轴肩）。
        给出时余量 = cut_dir·r，可以是负值（车过头、车不到）；不给时按名义值的正负判断方向（旧的做法，判断不了车过头）。"""
        out = []
        for c, prev, v in self.cuts:
            if not prev:
                continue
            links = [Link(lab, nom, es, ei, d) for nom, es, ei, lab, d in self._path(prev, v)]
            r = extreme(links)
            sign = (cut_dir or {}).get(c.surf) or (-1 if r.nominal < 0 else 1)
            zmin, zmax = sorted((sign * r.min, sign * r.max))
            out.append({"seq": c.seq, "surface": c.surf, "nominal": sign * r.nominal, "min": zmin, "max": zmax,
                        "links": [l.name for l in links]})
        return out


def chart_from_plan(tc: dict) -> dict:
    """从工艺规程数据里的 tolerance_chart 建立工艺尺寸跟踪图，核算图纸轴向尺寸和每次加工的余量。
    tc = {blank: [[A, B, nom, es, ei]], cuts: [{seq, ref, surf, nominal, es, ei, label?}], drawing: [{a, b, nominal, tol 或 es/ei}],
          min_allowance}。返回 {chart, drawing: [{a, b, spec, result, ok}], allowances: [... ok]}。"""
    ch = ToleranceChart([tuple(b) for b in tc["blank"]])
    for c in tc["cuts"]:
        ch.cut(Cut(c["seq"], c["ref"], c["surf"], c["nominal"], c.get("es", 0.0), c.get("ei", 0.0), c.get("label", "")))
    dr = []
    for d in tc.get("drawing", []):
        es, ei = (d["tol"], -d["tol"]) if "tol" in d else (d["es"], d["ei"])
        r = ch.resultant(d["a"], d["b"])
        ok = r.max <= d["nominal"] + es + 1e-9 and r.min >= d["nominal"] + ei - 1e-9      # 只比较极限尺寸：名义值写法不同不算错
        dr.append({"a": d["a"], "b": d["b"], "nominal": d["nominal"], "es": es, "ei": ei, "result": r, "ok": ok,
                   "links": [l.name for l in ch.chain(d["a"], d["b"])]})
    zmin = tc.get("min_allowance", 0.0)
    al = [a | {"ok": a["min"] >= zmin - 1e-9} for a in ch.allowances(tc.get("cut_dir"))]
    return {"chart": ch, "drawing": dr, "allowances": al, "min_allowance": zmin}


# ---------------------------------------------------------------- 定位误差
def v_block(Td: float, alpha_deg: float = 90.0, measure: str = "center") -> float:
    """外圆在 V 形块上定位，工件直径公差 Td 引起的定位误差（工序尺寸方向垂直于 V 形块对称面……竖直方向）。

    measure：工序基准是轴心 "center"、上母线 "top"、下母线 "bottom"。
    ΔY（轴心）= Td / (2 sin(α/2))；上母线 = ΔY + Td/2；下母线 = ΔY − Td/2。"""
    s = math.sin(math.radians(alpha_deg) / 2)
    dy = Td / (2 * s)
    return {"center": dy, "top": dy + Td / 2, "bottom": dy - Td / 2}[measure]


def v_block_contact(points, alpha_deg=90.0, wear_left=0.0, wear_right=0.0, radius=None):
    """按接触几何求工件在 V 形块上的位置（不用 V 形块公式）。

    points：工件轮廓上的点（相对工件自身中心，mm），可以是任意形状（圆、带圆度误差的多棱圆）；为 None 时按半径 radius 的理想圆计算；
    V 形块顶点在原点、对称面为 y 轴，两工作面与对称面夹 α/2；wear_left/right：两个工作面的磨损量（工作面沿法向后退）。
    工件靠重力落到两个工作面上：每个工作面上轮廓的最低接触点与工作面距离为零，两个条件解出工件中心 (cx, cy)。"""
    h = math.radians(alpha_deg) / 2
    nL = (math.cos(h), math.sin(h))           # 左工作面的内法向
    nR = (-math.cos(h), math.sin(h))          # 右工作面的内法向
    if points is None:                          # 理想圆：轮廓沿任一方向的最小投影就是 −r
        mL = mR = -radius
    else:
        mL = min(nL[0] * x + nL[1] * y for x, y in points)
        mR = min(nR[0] * x + nR[1] * y for x, y in points)
    # nL·c + mL = −wear_left，nR·c + mR = −wear_right
    bL, bR = -wear_left - mL, -wear_right - mR
    det = nL[0] * nR[1] - nL[1] * nR[0]
    cx = (bL * nR[1] - nL[1] * bR) / det
    cy = (nL[0] * bR - bL * nR[0]) / det
    return cx, cy


def circle_points(d, n=360, lobes=0, roundness=0.0):
    """直径 d 的轮廓点；lobes、roundness：等直径多棱形的棱数和圆度误差（峰谷值）。"""
    pts = []
    for k in range(n):
        t = 2 * math.pi * k / n
        r = d / 2 + (roundness / 2) * math.cos(lobes * t) if lobes else d / 2
        pts.append((r * math.cos(t), r * math.sin(t)))
    return pts


def v_block_mc(d_nom, es, ei, alpha_deg=90.0, measure="center", n=20_000, seed=2, lobes=0, roundness=0.0, n_pts=720):
    """蒙特卡罗核对 V 形块定位误差：直径在公差带内均匀抽样，按接触几何（v_block_contact）求每件的位置，
    返回工序基准（轴心、上母线、下母线）竖直位置的变动范围。可以加圆度误差，看公式不能反映的影响。"""
    rng = random.Random(seed)
    ys = []
    for _ in range(n):
        d = rng.uniform(d_nom + ei, d_nom + es)
        if lobes:
            pts = circle_points(d, n_pts, lobes, roundness * rng.random() if roundness else 0.0)
            ph = rng.uniform(0, 2 * math.pi)       # 工件放上 V 形块时的转角随机
            pts = [(x * math.cos(ph) - y * math.sin(ph), x * math.sin(ph) + y * math.cos(ph)) for x, y in pts]
            top, bot = max(q[1] for q in pts), min(q[1] for q in pts)
        else:                                       # 理想圆：接触点解析求出，不受离散点数的影响
            pts = None
            top, bot = d / 2, -d / 2
        cx, cy = v_block_contact(pts, alpha_deg, radius=d / 2)
        y = {"center": cy, "top": cy + top, "bottom": cy + bot}[measure]
        ys.append(y)
    return max(ys) - min(ys)


def pin_clearance(D: tuple, d: tuple, contact: str = "any") -> float:
    """孔套在心轴或定位销上（间隙配合）的基准位移误差。D = (孔基本尺寸, ES, EI)，d = (销, es, ei)。

    contact="any"：间隙方向任意（工件可在任意方向靠紧），ΔY = Xmax = Dmax − dmin；
    contact="one"：工件总靠向同一侧（如重力或夹紧力单向），ΔY = (TD + Td)/2。"""
    TD, Td = D[1] - D[2], d[1] - d[2]
    if contact == "one":
        return (TD + Td) / 2
    return (D[0] + D[1]) - (d[0] + d[2])


def two_pins(L: float, hole1: tuple, pin1: tuple, hole2: tuple, pin2_width_clear: float) -> dict:
    """一面两销（圆柱销 + 削边销）的定位误差。

    hole/pin = (基本尺寸, 上偏差, 下偏差)；pin2_width_clear：削边销方向上的最大间隙 X2max（削边销只在两孔连线的垂直方向起作用）。
    返回：圆柱销处的移动误差 X1max，以及最大转角误差 Δθ = arctan((X1max + X2max) / (2L))（两孔偏向相反时）。"""
    X1 = pin_clearance(hole1, pin1)
    th = math.degrees(math.atan((X1 + pin2_width_clear) / (2 * L)))
    return {"X1max": X1, "X2max": pin2_width_clear, "rot_deg": th, "rot_mm_per_100": math.tan(math.radians(th)) * 100}


def two_pins_point(x: float, L: float, X1: float, X2: float) -> dict:
    """一面两销定位时，两销连线上离圆柱销 x 处一点的位置变动范围。

    垂直于连线方向：圆柱销处偏移 u1 ∈ [−X1/2, X1/2]，削边销处 u2 ∈ [−X2/2, X2/2]，该点偏移 u1(1 − x/L) + u2·x/L，
    变动范围 = X1·|1 − x/L| + X2·|x/L|；沿连线方向削边销不起作用，变动范围 = X1。"""
    perp = X1 * abs(1 - x / L) + X2 * abs(x / L)
    return {"perp": perp, "along": X1}


def diamond_pin(D2: tuple, b: float, dLK: float, dLJ: float, T_pin: float) -> dict:
    """削边销的设计：D2 = (孔基本尺寸, ES, EI)；b 削边销圆柱部分宽度（查 JB/T 8014.3）；
    ±dLK 工件两孔中心距公差、±dLJ 夹具两销中心距公差（一般取 dLK 的 1/3–1/5）；T_pin 销的直径公差。
    削边销与孔的最小间隙 X2min = 2b(dLK + dLJ)/D2，销的最大直径 d2max = D2min − X2min。"""
    D, ES, EI = D2
    X2min = 2 * b * (dLK + dLJ) / D
    d2max = D + EI - X2min
    d2min = d2max - T_pin
    return {"X2min": X2min, "d2max": d2max, "d2min": d2min, "X2max": (D + ES) - d2min}


def center_hole_axial(dD: float, cone_deg: float = 60.0) -> float:
    """两顶尖装夹：中心孔锥面直径的变动 dD 引起的工件轴向位移（锥角 60° 时 Δz = dD / (2 tan 30°)）。"""
    return dD / (2 * math.tan(math.radians(cone_deg) / 2))


def datum_mismatch(links) -> float:
    """基准不重合误差 ΔB：联系设计基准与定位基准的尺寸的公差之和（极值法）。"""
    return sum(l.T for l in links)


def locate_error(dB: float, dY: float, same_dir: bool = True) -> float:
    """定位误差 ΔD = ΔB ± ΔY：两者引起的工序基准位移同向时相加，反向时相减（取绝对值）。"""
    return dB + dY if same_dir else abs(dB - dY)


def ok_against(tol: float, error: float, fraction: float = 1 / 3) -> bool:
    """经验判据：定位误差不超过工序公差的 1/3（留出加工与测量误差的空间）。"""
    return error <= tol * fraction + 1e-12


# ---------------------------------------------------------------- 自由度分析（第 51 章）
DOF = ("x", "y", "z", "rx", "ry", "rz")       # 沿 x、y、z 的移动，绕 x、y、z 的转动
DOF_ZH = {"x": "沿 x 移动", "y": "沿 y 移动", "z": "沿 z 移动", "rx": "绕 x 转动", "ry": "绕 y 转动", "rz": "绕 z 转动"}


def dof_analysis(locators: list[tuple[str, set]], required: set) -> dict:
    """定位方案的自由度分析。

    locators：[(定位元件名称, 它限制的自由度集合)]；required：按工序要求必须限制的自由度。
    返回限制了哪些、重复限制了哪些（过定位）、该限没限的（欠定位），以及结论：
    完全定位（六个都限制且无重复）、不完全定位（限制了要求的全部、但不足六个）、欠定位、过定位。"""
    count = {d: 0 for d in DOF}
    for _, ds in locators:
        for d in ds:
            count[d] += 1
    limited = {d for d, n in count.items() if n > 0}
    repeated = {d for d, n in count.items() if n > 1}
    missing = set(required) - limited
    if missing:
        verdict = "欠定位"
    elif repeated:
        verdict = "过定位"
    elif len(limited) == 6:
        verdict = "完全定位"
    else:
        verdict = "不完全定位"
    return {"limited": sorted(limited, key=DOF.index), "repeated": sorted(repeated, key=DOF.index),
            "missing": sorted(missing, key=DOF.index), "n": len(limited), "verdict": verdict}


def chuck_runout_error(tir: float) -> float:
    """自定心卡盘的定心精度常以径向跳动读数 TIR 表示，偏心 e = TIR/2。
    对称度、同轴度的公差带宽度对应中心偏移的两倍，所以一批工件对称度方面的定位误差 = 2e = TIR。"""
    return tir


def offset_to_zone(e: float) -> float:
    """中心偏移 e 换算到对称度、同轴度、位置度公差带（直径或宽度）上的占用量：2e。"""
    return 2 * e
