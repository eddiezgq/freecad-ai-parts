"""问渠CAM C3a 五轴联动骨架（ADR-0106 C3a）：直纹面侧刃铣刀位、逐点逆解、刀尖跟随（RTCP）程序与回读、dexel 去料、整机仿真。

NAS 979 圆锥台（简化）：半锥角 15°、底 Ø150（Z −15）、顶在 Z0；Ø10 平底刀侧刃贴锥面走，刀尖再往下伸 1 mm。
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from analysis import cam
from analysis.cam import dexel as DX
from analysis.cam import fiveaxis as FA
from analysis.cam import machines, post, postproc, sim
from tests.verification import record_verdict

RB, H, HALF = 75.0, 15.0, 15.0
RT = RB - H * math.tan(math.radians(HALF))
R_TOOL = 5.0


def _cone(a0=0.0, a1=360.0, n=120):
    th = np.radians(np.linspace(a0, a1, n + 1))
    bot = np.c_[RB * np.cos(th), RB * np.sin(th), np.full(n + 1, -H)]
    top = np.c_[RT * np.cos(th), RT * np.sin(th), np.zeros(n + 1)]
    return bot, top


def _prog(a0=0.0, a1=360.0, n=120, f=600.0):
    bot, top = _cone(a0, a1, n)
    tips, axes = FA.swarf(bot, top, R_TOOL, below=1.0)
    p0, a_0, pe, a_e = tips[0], axes[0], tips[-1], axes[-1]
    out0 = p0 + 30 * np.array([math.cos(math.radians(a0)), math.sin(math.radians(a0)), 0.0])
    oute = pe + 30 * np.array([math.cos(math.radians(a1)), math.sin(math.radians(a1)), 0.0])
    mv = [{"t": "rapid", "x": out0[0], "y": out0[1], "z": 10.0, "axis": list(a_0)},
          {"t": "rapid", "x": out0[0], "y": out0[1], "z": p0[2], "axis": list(a_0)},
          {"t": "feed", "x": p0[0], "y": p0[1], "z": p0[2], "axis": list(a_0), "f": f}]
    mv += [{"t": "feed", "x": p[0], "y": p[1], "z": p[2], "axis": list(a), "f": f} for p, a in zip(tips[1:], axes[1:])]
    mv += [{"t": "feed", "x": oute[0], "y": oute[1], "z": pe[2], "axis": list(a_e), "f": f},
           {"t": "rapid", "x": oute[0], "y": oute[1], "z": 10.0, "axis": list(a_e)}]
    return {"number": 7101, "title": "NAS 979 圆锥台", "ops": [{"tool": {"n": 1, "d": 2 * R_TOOL, "kind": "endmill"}, "spindle": {"rpm": 6000},
                                                             "safe": 10.0, "title": "锥面侧刃", "simul5": True, "moves": mv}]}, tips, axes


OFFSET = {"EX-5AX-AC": [0, 0, 100], "EX-5AX-BC": [0, 0, 40]}


def _run(machine, ctl, prog):
    st = {"mode": "program", "machine": machine, "program": prog, "stock": {"box": [-90, -90, 90, 90], "height": 30}, "post": ctl,
          "machine_sim": {"work_offset_mm": OFFSET[machine], "tools": {"1": {"tool": "EM10", "length_mm": 120}}}}
    r = cam.run(st)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"][0]


def test_swarf_positions_on_cone():
    """刀轴沿直纹线；刀尖到直纹线的距离 = 刀具半径（侧刃贴锥面），在锥面外侧；误差 < 0.001 mm"""
    bot, top = _cone()
    tips, axes = FA.swarf(bot, top, R_TOOL)
    for p, a, b, t in zip(tips, axes, bot, top):
        u = (t - b) / np.linalg.norm(t - b)
        assert FA.angle_deg(a, u) < 1e-9
        d = np.linalg.norm(np.cross(p - b, u))
        assert d == pytest.approx(R_TOOL, abs=1e-3)
        assert math.hypot(p[0], p[1]) > math.hypot(b[0], b[1])                         # 外侧
    record_verdict(("五轴联动：直纹面侧刃铣刀位贴锥面", "5-axis: swarf tool positions on the cone"), "pass", "pass")


@pytest.mark.parametrize("machine,ctl,a1", [("EX-5AX-AC", "fanuc", 360.0), ("EX-5AX-AC", "siemens", 360.0), ("EX-5AX-AC", "heidenhain", 360.0),
                                            ("EX-5AX-BC", "fanuc", 150.0), ("EX-5AX-BC", "hnc", 150.0)])
def test_rtcp_release_and_readback(machine, ctl, a1):
    """刀尖跟随程序：整机仿真通过、出正式程序（回读与仿真刀路一致才出）；仿真刀路的刀尖、刀轴与刀位逐点一致"""
    prog, tips, axes = _prog(a1=a1)
    p = _run(machine, ctl, prog)
    assert p["machine_sim"]["status"] in ("pass", "unknown") and p["release"] is not None, [c["text"] for c in p["checks"]]
    t = p["release"]["text"]
    on, off = {"fanuc": ("G43.4 H01", "G49"), "hnc": ("G43.4 H01", "G49"), "siemens": ("TRAORI", "TRAFOOF"),
               "heidenhain": ("FUNCTION TCPM F TCP AXIS POS PATHCTRL AXIS", "FUNCTION RESET TCPM")}[ctl]
    assert on in t and off in t and t.index(on) < t.rindex(off)
    mach = machines.get(machine)
    parsed = sim.parse(post.post_mill(prog, mach), mach)
    feeds = [m for m in parsed["moves"] if m["t"] == "feed"][1:len(tips)]               # 第一段是从外面切入
    for m_, p_, a_ in zip(feeds, tips[1:], axes[1:]):
        assert np.linalg.norm(np.subtract(m_["b"], p_)) < 0.01 and FA.angle_deg(m_["axis_b"], a_) < 0.01
    back = sim.parse(postproc.to_fanuc(t, ctl, False), mach)
    bf = [m for m in back["moves"] if m["t"] == "feed"][1:len(tips)]
    for m_, p_, a_ in zip(bf, tips[1:], axes[1:]):
        assert np.linalg.norm(np.subtract(m_["b"], p_)) < 0.01 and FA.angle_deg(m_["axis_b"], a_) < 0.01
    record_verdict((f"五轴联动：{machine} {ctl} 刀尖跟随程序回读一致", f"5-axis: {machine} {ctl} RTCP read-back matches"), "pass", "pass")


def test_continuous_c_does_not_wrap():
    """AC 机床刀轴绕一圈：C 连续走 360°，没有 ±180° 的跳变"""
    _bot, _top = _cone()
    _tips, axes = FA.swarf(_bot, _top, R_TOOL)
    rots = FA.rotary_path(machines.get("EX-5AX-AC")["model"], axes)
    c = [r["C"] for r in rots]
    assert max(abs(b - a) for a, b in itertools.pairwise(c)) < 3.01 and abs(c[-1] - c[0]) == pytest.approx(360.0, abs=1e-6)
    assert all(abs(r["A"] + HALF) < 1e-9 for r in rots)
    record_verdict(("五轴联动：连续回转轴不绕远", "5-axis: continuous rotary axis does not wrap"), "pass", "pass")


def test_dexel_no_overcut_no_leftover():
    """dexel 去料后：锥面里面 1 mm 处都还有料（不过切），锥面外 1.5–8 mm 的带里都没料了（不剩料）；网格 0.5"""
    prog, _t, _a = _prog()
    mach = machines.get("EX-5AX-AC")
    parsed = sim.parse(post.post_mill(prog, mach), mach)
    st = DX.Dexel.box([-90, -90, -30], [90, 90, 0], 0.5, pad=12)
    DX.simulate(parsed, st, {1: {"kind": "endmill", "d": 10.0}})
    k = 2
    xs, ys = st.c[0], st.c[1]

    def material(x, y, z):
        i, j = int(np.argmin(np.abs(xs - x))), int(np.argmin(np.abs(ys - y)))
        s, e = st.S[k][i, j], st.E[k][i, j]
        return bool(np.any((s <= z) & (z < e)))

    bad_in = bad_out = 0
    for ang in np.radians(np.arange(0, 360, 7.5)):
        for z in (-13.0, -9.0, -5.0, -2.0):
            rc = RB - (z + H) * math.tan(math.radians(HALF))
            bad_in += not material((rc - 1.0) * math.cos(ang), (rc - 1.0) * math.sin(ang), z)
            for dr in (1.5, 4.0, 8.0):
                bad_out += material((rc + dr) * math.cos(ang), (rc + dr) * math.sin(ang), z)
    assert bad_in == 0 and bad_out == 0
    record_verdict(("五轴联动：圆锥台侧刃 dexel 不过切、不剩料", "5-axis: cone swarf dexel no overcut, no leftover"), "pass", "pass")


def test_full_loop_on_bc_flips_and_is_refused():
    """BC 摆头 C 只有 ±220°：锥面绕一整圈中途换一组解，回转轴突变报错，不出程序"""
    prog, _t, _a = _prog()
    p = _run("EX-5AX-BC", "fanuc", prog)
    assert p["release"] is None
    assert any(c["level"] == "error" and "一步转了" in c["text"] for c in p["checks"])


def test_singular_point_warning():
    """AC 机床刀轴从 −X 一侧摆到 +X 一侧、离竖直（C 轴方向）只差 0.57°：报奇异点附近；C 在两步里转了近 180°，报突变不出程序。
    （正好穿过竖直反而不用转 C：A 过 0 就行）"""
    mv = []
    for k, x in enumerate(np.linspace(-0.2, 0.2, 21)):
        a = [float(x), 0.01, 1.0]
        mv.append({"t": "rapid" if k == 0 else "feed", "x": 100 * float(x), "y": 0.0, "z": 5.0, "axis": a, "f": 500.0})
    prog = {"number": 7102, "title": "过奇异点", "ops": [{"tool": {"n": 1, "d": 10.0}, "spindle": {"rpm": 5000}, "simul5": True, "moves": mv}]}
    p = _run("EX-5AX-AC", "fanuc", prog)
    texts = [c["text"] for c in p["checks"]]
    assert any("奇异点附近" in x for x in texts) and any("一步转了" in x for x in texts)
    assert p["release"] is None
    record_verdict(("五轴联动：过奇异点报警、回转轴突变不出程序", "5-axis: singular point warned, rotary flip refused"), "pass", "pass")


def test_three_axis_gsk_and_overtravel_refused():
    prog, _t, _a = _prog(a1=90.0)
    r = cam.run({"mode": "program", "machine": "EX-VMC", "program": prog, "stock": {"box": [-90, -90, 90, 90], "height": 30}})
    assert r["status"] != "ok" and any("没有回转轴" in m for m in r["messages"])
    p = _run("EX-5AX-AC", "gsk", prog)
    assert p["release"] is None and any("正式程序没有输出" in c["text"] and "gsk" in c["text"] for c in p["checks"])   # 广数没有铣床后处理
    # AC 的 A 只能 −120 ~ +30：刀轴往 +Y 倒 60°（A 要 +60 或 C 转 180° 配 A −60）——把 A 行程卡死到 −10 ~ +10 看超程
    mach = machines.get("EX-5AX-AC")
    model = {**mach["model"], "axes": [dict(a, min=-10.0, max=10.0) if a["id"] == "A" else a for a in mach["model"]["axes"]]}
    with pytest.raises(FA.FiveAxisError, match="超程"):
        FA.rotary_path(model, [[0.0, -math.sin(math.radians(30)), math.cos(math.radians(30))]])


def test_rotary_rate_warning():
    """进给太快、回转轴跟不上：提示会降速（AC 的 C 轴 10800°/分；每段转 3°、只走 0.1 mm 时要 F × 30 °/分）"""
    mv = []
    for k in range(10):
        th = math.radians(3 * k)
        a = [math.sin(math.radians(15)) * math.cos(th), math.sin(math.radians(15)) * math.sin(th), math.cos(math.radians(15))]
        mv.append({"t": "rapid" if k == 0 else "feed", "x": 0.1 * k, "y": 0.0, "z": 5.0, "axis": a, "f": 1000.0})
    prog = {"number": 7103, "title": "快转", "ops": [{"tool": {"n": 1, "d": 10.0}, "spindle": {"rpm": 5000}, "simul5": True, "moves": mv}]}
    p = _run("EX-5AX-AC", "fanuc", prog)
    assert any("会降进给" in c["text"] and "回转轴 C" in c["text"] for c in p["checks"])
