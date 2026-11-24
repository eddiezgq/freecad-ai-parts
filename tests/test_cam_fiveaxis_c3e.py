"""问渠CAM C3e S 形薄壁试件仿真（ADR-0106 C3e）：两面都是扭曲直纹面（不可展）的 S 形薄壁，圆柱侧刃铣两面。

试件是自定的 S 形（不是 ISO 10791-7 原尺寸，原尺寸在付费标准里）：底边 y = 20·sin(2πt)、顶边 y = 24·sin(2πt + 0.3)，
x 从 −60 到 60（顶边整体往 +x 偏 8 mm，刀轴两个方向都斜，两个回转轴都动），高 30，壁厚 3（另一面按平面偏 3 mm），
平底刀 Φ10。量的是：刀位贴哪个法向、过切多少、推出来以后剩料多少；两台示例机床出程序、回转轴不突变；dexel 去料核对。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from analysis import cam
from analysis.cam import dexel as DX
from analysis.cam import fiveaxis as FA
from analysis.cam import machines, post, sim
from tests.verification import record_verdict

H, R, W, N = 30.0, 5.0, 3.0, 121
OFFSET = {"EX-5AX-AC": [0, 0, 100], "EX-5AX-BC": [0, 0, 40]}


def _curve(amp, ph, z, dx=0.0, n=N):
    t = np.linspace(0.0, 1.0, n)
    return np.c_[-60 + 120 * t + dx, amp * np.sin(2 * math.pi * t + ph), np.full(n, z)]


def _offset(c, d):
    tg = np.gradient(c[:, :2], axis=0)
    nr = np.c_[-tg[:, 1], tg[:, 0]]
    nr /= np.linalg.norm(nr, axis=1, keepdims=True)
    o = c.copy()
    o[:, :2] += d * nr
    return o


def _faces(n=N):
    ba, ta = _curve(20, 0.0, -H, n=n), _curve(24, 0.3, 0.0, 8.0, n=n)
    return (ba, ta, -1), (_offset(ba, W), _offset(ta, W), 1)          # 第三项：刀具在左法向的哪一侧（A 面在 −，B 面在 +）


def _side(b, t, away):
    tips, _ = FA.swarf(b, t, R, side=1)
    m = len(b) // 2
    lft = _offset(b, 1.0)[m] - b[m]
    return 1 if np.dot(tips[m] - b[m], away * lft) > 0 else -1


def _passes():
    out = []
    for b, t, away in _faces():
        tips, axes = FA.swarf(b, t, R, side=_side(b, t, away))
        tips, axes, chk = FA.swarf_clear(b, t, tips, axes, R)
        out.append((b, t, tips, axes, chk))
    return out


def _prog():
    segs = [FA.densify(p[2], p[3], 1.0) for p in _passes()]
    mv = FA.link_moves(segs, 600.0, safe_dist=5.0, clear_z=5.0)
    return {"number": 7301, "title": "S 形试件", "ops": [{"tool": {"n": 1, "d": 2 * R, "kind": "endmill"}, "spindle": {"rpm": 8000},
                                                       "safe": 10.0, "title": "S 形两面侧刃", "simul5": True, "moves": mv}]}


def test_mid_normal_and_clear():
    """扭曲直纹面上按底边法向贴刀，两端啃进去 0.4 mm 多；按中间高度的法向贴，只剩约四分之一；再把啃进去的刀位推出来：
    过切 ≤ 0.001 mm（折线曲面上），剩料 ≤ 0.15 mm（扭曲直纹面圆柱侧刃铣本身的偏差，换成了剩料）；
    拿 4 倍密的真曲面再量一遍，过切 ≤ 0.01 mm（输入折线本身的弦差）"""
    for b, t, away in _faces():
        s = _side(b, t, away)
        tb, ab = FA.swarf(b, t, R, side=s, at=0.0)
        tm, am = FA.swarf(b, t, R, side=s)
        ob = FA.swarf_check(b, t, tb, ab, R, skip=5)["overcut_mm"]
        om = FA.swarf_check(b, t, tm, am, R, skip=5)["overcut_mm"]
        assert ob > 0.4 and om < 0.3 * ob
        tc, ac, chk = FA.swarf_clear(b, t, tm, am, R)
        assert chk["overcut_mm"] <= 0.001 and chk["leftover_mm"] <= 0.15
    fine = _faces(4 * N)
    for (b, t, tc, ac, _c), (bf, tf, _a) in zip(_passes(), fine):
        dt, da = FA.densify(tc, ac, 1.0)
        cf = FA.swarf_check(bf, tf, dt, da, R, skip=20)
        assert cf["overcut_mm"] <= 0.01 and cf["leftover_mm"] <= 0.15
    record_verdict(("五轴联动：S 形试件侧刃中间法向贴刀、推出后不过切", "5-axis: S-test swarf mid-normal positioning and clearing, no overcut"),
                   "pass", "pass")


def _run(machine, ctl, prog):
    st = {"mode": "program", "machine": machine, "program": prog, "stock": {"box": [-70, -50, 70, 50], "height": H}, "post": ctl,
          "machine_sim": {"work_offset_mm": OFFSET[machine], "tools": {"1": {"tool": "EM10", "length_mm": 120.0}}}}
    r = cam.run(st)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"][0]


@pytest.mark.parametrize("machine,ctl", [("EX-5AX-AC", "fanuc"), ("EX-5AX-AC", "siemens"), ("EX-5AX-AC", "heidenhain"),
                                         ("EX-5AX-BC", "fanuc"), ("EX-5AX-BC", "hnc")])
def test_release_on_both_machines(machine, ctl):
    """两台示例五轴（摇篮 AC、摆头 BC）四种系统：整机仿真通过、出正式程序，没有回转轴突变、奇异点提示；
    切削中回转轴每段最多转 4°（刀轴每段 ≤ 1°，刀轴斜 15° 以上，C 每段 ≤ 1°/sin15° ≈ 3.9°）"""
    prog = _prog()
    p = _run(machine, ctl, prog)
    bad = [c["text"] for c in p["checks"] if c["level"] in ("error", "warning")]
    assert p["machine_sim"]["status"] in ("pass", "unknown") and p["release"] is not None and not bad, bad
    mach = machines.get(machine)
    for _b, _t, tips, axes, _c in _passes():
        rots = FA.rotary_path(mach["model"], FA.densify(tips, axes, 1.0)[1])
        for k in rots[0]:
            assert max(abs(rots[i + 1][k] - rots[i][k]) for i in range(len(rots) - 1)) < 4.0
    record_verdict((f"五轴联动：S 形试件 {machine} {ctl} 出程序、回转轴不突变", f"5-axis: S-test {machine} {ctl} released, no rotary flip"),
                   "pass", "pass")


def test_dexel_wall():
    """dexel 去料（网格 0.25）：两面往壁里 0.3 mm 处都还有料（不过切，网格 0.25 量得出），往外 0.5 mm 起没料（剩料 < 0.5），
    往外 3、6、9 mm 都没料（刀扫过的带）；两头 10 条直纹线不量（切入、切出）"""
    prog = _prog()
    mach = machines.get("EX-5AX-AC")
    parsed = sim.parse(post.post_mill(prog, mach), mach)
    dx = DX.Dexel.box([-70, -50, -H], [70, 50, 0], 0.25, pad=8)
    DX.simulate(parsed, dx, {1: {"kind": "endmill", "d": 2 * R}})
    xs, ys = dx.c[0], dx.c[1]

    def material(p):
        i, j = int(np.argmin(np.abs(xs - p[0]))), int(np.argmin(np.abs(ys - p[1])))
        s, e = dx.S[2][i, j], dx.E[2][i, j]
        return bool(np.any((s <= p[2]) & (p[2] < e)))

    bad_in = bad_out = 0
    for b, t, tips, axes, _c in _passes():
        for i in range(10, N - 10, 3):
            u = axes[i]
            g = tips[i] - b[i]
            nv = (g - u * np.dot(g, u)) / np.linalg.norm(g - u * np.dot(g, u))
            for f in (0.1, 0.3, 0.5, 0.7, 0.9):
                p = b[i] + f * (t[i] - b[i])
                bad_in += not material(p - 0.3 * nv)
                bad_out += sum(material(p + d * nv) for d in (0.5, 3.0, 6.0, 9.0))
    assert bad_in == 0 and bad_out == 0
    record_verdict(("五轴联动：S 形薄壁 dexel 不过切、不剩料", "5-axis: S-shaped thin wall dexel no overcut, no leftover"), "pass", "pass")
