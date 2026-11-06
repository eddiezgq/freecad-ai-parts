# -*- coding: utf-8 -*-
"""晶圆图（第 103 轮，芯片封测厂）：一片 200 mm 晶圆在 CP（晶圆测试）后每颗芯片的分档。

只存“怎么生成的”（种子 + 参数），要看时再生成——一片约 4 万颗，不往数据库里存整张图。车间仿真用它算 CP 良率，
网关用同一个函数把图还原给“晶圆图”页，两边一定一致。

几何（示例值）：芯片 0.80 × 0.80 mm + 划片道 80 µm → 步距 0.88 mm；边缘去除 3 mm（有效半径 97 mm）。
探针卡 8 个测试位，一次扎 2 行 × 4 列：测试位号 = (行 % 2) × 4 + (列 % 4)。
分档：1 合格；2 功能失效（随机缺陷，部分成簇）；3 静态电流 IDDQ 超标（越靠边越多）；4 开路 / 接触不良（测试位的探针接触电阻偏高时，
这个测试位扎到的芯片被误判——芯片本身是好的，复测能过）。
概率与簇的参数都是示例值。只用标准库，不联网。"""
import math
import random

PITCH_MM = 0.88
R_MM = 100.0
EDGE_MM = 3.0
SITES = 8
RC_LIMIT = 2.5           # 接触电阻高于它开始误判（Ω，示例）
BINS = {1: "合格", 2: "功能失效（随机缺陷）", 3: "静态电流超标（边缘）", 4: "开路 / 接触不良"}


def grid():
    """有效芯片的 (行, 列) 列表与行列数"""
    n = int(math.ceil(2 * R_MM / PITCH_MM))
    r = R_MM - EDGE_MM
    dies = []
    for i in range(n):
        for j in range(n):
            x0, y0 = (j - n / 2) * PITCH_MM, (i - n / 2) * PITCH_MM
            if all((x0 + dx) ** 2 + (y0 + dy) ** 2 <= r * r for dx in (0, PITCH_MM) for dy in (0, PITCH_MM)):
                dies.append((i, j))
    return n, dies


_G = None


def _grid():
    global _G
    if _G is None:
        _G = grid()
    return _G


def site_of(i, j):
    return (i % 2) * 4 + (j % 4)


def generate(seed, site_rc, d0=0.07, edge=0.03, clusters=3.0):
    """返回 {n, bins: 每颗芯片的分档（与 grid() 的顺序一致）, yield_pct, by_bin, site_fail}。
    site_rc：8 个测试位的探针接触电阻（Ω）；d0：随机缺陷概率；edge：边缘处 IDDQ 失效概率；clusters：每片平均缺陷簇数。"""
    n, dies = _grid()
    rng = random.Random(int(seed))
    # 缺陷簇：中心、半径（芯片个数）
    k = 0
    lam, p, L = clusters, 1.0, math.exp(-clusters)
    while True:
        p *= rng.random()
        if p <= L:
            break
        k += 1
    cl = [(rng.uniform(-80, 80), rng.uniform(-80, 80), rng.uniform(2, 5) * PITCH_MM) for _ in range(k)]
    rmax = R_MM - EDGE_MM
    bins, by_bin, site_fail, site_n = [], {1: 0, 2: 0, 3: 0, 4: 0}, [0] * SITES, [0] * SITES
    for i, j in dies:
        x, y = (j - n / 2 + 0.5) * PITCH_MM, (i - n / 2 + 0.5) * PITCH_MM
        rr = math.hypot(x, y)
        s = site_of(i, j)
        site_n[s] += 1
        b = 1
        pc = min(0.95, max(0.0, (site_rc[s] - RC_LIMIT) / 1.5))
        if rng.random() < pc:
            b = 4
        elif rng.random() < d0 or any((x - cx) ** 2 + (y - cy) ** 2 < cr * cr and rng.random() < 0.7 for cx, cy, cr in cl):
            b = 2
        elif rng.random() < edge * math.exp((rr - rmax) / 6.0):
            b = 3
        bins.append(b)
        by_bin[b] += 1
        if b != 1:
            site_fail[s] += 1
    total = len(dies)
    return {"n": n, "bins": bins, "total": total, "yield_pct": round(100.0 * by_bin[1] / total, 3), "by_bin": by_bin,
            "site_fail_pct": [round(100.0 * f / max(1, m), 2) for f, m in zip(site_fail, site_n)]}


def render(desc):
    """网关用：按存下的参数重新生成，给页面紧凑的格式（每行一串分档数字，晶圆外为空格）"""
    g = generate(desc["seed"], desc["site_rc"], desc.get("d0", 0.07), desc.get("edge", 0.03), desc.get("clusters", 3.0))
    n, dies = _grid()
    rows = [[" "] * n for _ in range(n)]
    for (i, j), b in zip(dies, g["bins"]):
        rows[i][j] = str(b)
    return {"n": n, "rows": ["".join(r) for r in rows], "total": g["total"], "yield_pct": g["yield_pct"], "by_bin": g["by_bin"],
            "site_fail_pct": g["site_fail_pct"], "bins": BINS, "pitch_mm": PITCH_MM, "diameter_mm": 2 * R_MM, "edge_mm": EDGE_MM}
