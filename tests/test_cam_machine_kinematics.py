"""问渠CAM C1：机床模型加载、旧格式转换、运动学正解逆解、刀具库（ADR-0104、ADR-0105）。"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

from analysis.cam import kinematics as K
from analysis.cam import machine_model as MM
from analysis.cam import machines
from analysis.cam import tools as TL

FIX = Path(__file__).resolve().parent / "fixtures"
AC = machines.model("EX-5AX-AC")
VMC = machines.model("EX-VMC")
LATHE = machines.model("EX-LATHE")
MT = machines.model("EX-MT-CY")


def _bc_head() -> dict:
    """摆头 BC（虚构，测试用）：工作台不动，刀具一侧 X Y Z 后先 C（绕 Z）再 B（绕 Y，摆动中心在主轴端面上方 150 mm）"""
    return MM.check({
        "format": "cam-machine/1", "id": "T-BC", "name": "测试摆头 BC（虚构）", "example": True, "source": "测试", "kind": "mill",
        "controller": {"family": "heidenhain"}, "spindle": {"max_rpm": 18000},
        "axes": [{"id": "X", "type": "linear", "carrier": "tool", "direction": [1, 0, 0], "min": -800, "max": 800},
                 {"id": "Y", "type": "linear", "carrier": "tool", "direction": [0, 1, 0], "min": -600, "max": 600},
                 {"id": "Z", "type": "linear", "carrier": "tool", "direction": [0, 0, 1], "min": -600, "max": 400},
                 {"id": "C", "type": "rotary", "carrier": "tool", "direction": [0, 0, 1], "point_mm": [0, 0, 0], "min": -360, "max": 360},
                 {"id": "B", "type": "rotary", "carrier": "tool", "direction": [0, 1, 0], "point_mm": [0, 0, 450], "min": -110, "max": 110}],
        "tool": {"direction": [0, 0, 1], "gauge_point_mm": [0, 0, 300]}})


def _head_table() -> dict:
    """一头一台（虚构，测试用）：刀具一侧摆头 B（绕 Y），工件一侧转台 C（绕 Z，转台中心偏 [20, -10]）"""
    return MM.check({
        "format": "cam-machine/1", "id": "T-BC-HT", "name": "测试摆头加转台（虚构）", "example": True, "source": "测试", "kind": "mill",
        "controller": {"family": "fanuc"}, "spindle": {"max_rpm": 12000},
        "axes": [{"id": "X", "type": "linear", "carrier": "tool", "direction": [1, 0, 0], "min": -800, "max": 800},
                 {"id": "Y", "type": "linear", "carrier": "workpiece", "direction": [0, -1, 0], "min": -600, "max": 600},
                 {"id": "Z", "type": "linear", "carrier": "tool", "direction": [0, 0, 1], "min": -600, "max": 400},
                 {"id": "B", "type": "rotary", "carrier": "tool", "direction": [0, 1, 0], "point_mm": [0, 0, 380], "min": -95, "max": 95},
                 {"id": "C", "type": "rotary", "carrier": "workpiece", "direction": [0, 0, 1], "point_mm": [20, -10, 0], "continuous": True}],
        "tool": {"direction": [0, 0, 1], "gauge_point_mm": [0, 0, 250]}})


# ---------------- 机床文件 ----------------

def test_example_machines_load_and_legacy_view_matches_old_yaml():
    assert {m["id"] for m in machines.models()} >= {"EX-LATHE", "EX-VMC", "EX-5AX-AC", "EX-MT-CY"}
    for m in machines.models():
        assert MM.validate(m) == [] and m["example"] is True and "虚构" in m["name"]
    # 旧格式 machines_example.yaml 里的数，转换后一个不差（ADR-0105 第 3 节：旧数据不作废）
    old = {"EX-LATHE": {"max_rpm": 4000, "power_kw": 11.0, "eff": 0.8, "x": [-2.0, 320.0], "z": [-600.0, 250.0],
                        "rapid": {"x": 12000.0, "z": 15000.0}, "home": [200.0, 150.0], "tool_change_s": 1.5, "kind": "lathe"},
           "EX-VMC": {"max_rpm": 8000, "power_kw": 15.0, "eff": 0.8, "x": [-400.0, 400.0], "y": [-250.0, 250.0],
                      "z": [-400.0, 150.0], "rapid": {"x": 24000.0, "y": 24000.0, "z": 20000.0}, "tool_change_s": 4.0, "kind": "mill"}}
    for mid, o in old.items():
        v = machines.get(mid)
        for k, val in o.items():
            assert v[k] == val, (mid, k)
    # 3+2 五轴、车铣中心进旧视图（ADR-0106 C2a、C2b：带回转轴列表）
    assert {m["id"] for m in machines.all_machines()} == {"EX-LATHE", "EX-VMC", "EX-5AX-AC", "EX-MT-CY"}
    assert machines.get("EX-5AX-AC")["rotary"] == ["A", "C"] and machines.get("EX-MT-CY")["rotary"] == ["C"]


def test_legacy_yaml_converts_and_new_format_in_yaml_and_folder(tmp_path):
    f = tmp_path / "machines.yaml"
    f.write_text("machines:\n  - {id: MY-L, kind: lathe, name: 我的车床, max_rpm: 2500, power_kw: 7.5, eff: 0.85,\n"
                 "     x: [0, 300], z: [-500, 200], rapid: {x: 8000, z: 10000}, home: [150, 100], tool_change_s: 2}\n",
                 encoding="utf-8")
    m = machines.model("MY-L", {"FAP_MACHINES": str(f)})
    assert m["format"] == "cam-machine/1" and m["controller"] == {"family": "other"} and "转换" in m["source"]
    x = next(a for a in m["axes"] if a["id"] == "X")
    assert x["diameter_mode"] is True and x["carrier"] == "tool"
    # 新格式写进 yaml
    ac = copy.deepcopy(AC)
    ac["id"], ac["example"] = "MY-AC", False
    f.write_text(json.dumps({"machines": [ac]}, ensure_ascii=False), encoding="utf-8")
    assert machines.model("MY-AC", {"FAP_MACHINES": str(f)})["axes"][3]["id"] == "A"
    # 文件夹：每个 JSON 一台；格式不对的报出来是哪一台
    d = tmp_path / "ms"
    d.mkdir()
    (d / "a.json").write_text(json.dumps(ac, ensure_ascii=False), encoding="utf-8")
    assert "MY-AC" in {m["id"] for m in machines.models({"FAP_MACHINES": str(d)})}
    bad = dict(ac, axes=[{"id": "X", "type": "linear", "carrier": "tool", "direction": [1, 0, 0]}])
    (d / "b.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(machines.MachineError, match="b.json"):
        machines.models({"FAP_MACHINES": str(d)})


def test_machine_without_power_makes_power_check_unknown():
    from analysis.cam import power

    vmc = copy.deepcopy(VMC)
    del vmc["spindle"]["power_kw"]
    v = MM.legacy_view(vmc)
    checks, detail = power.check("C45", v, [("铣槽", "mill", {"fz": 0.05, "ap": 5, "ae": 10, "d": 10, "vf": 800})])
    assert detail["status"] == "unknown" and checks[0]["level"] == "unknown"


# ---------------- 运动学 ----------------

def test_forward_by_hand():
    # 三轴：工作台带工件的 X 方向 [-1,0,0]，指令 X10 → 刀具相对工件在 +10（ISO 841 的含义）
    tip, d = K.forward(VMC, {"X": 10, "Y": -5, "Z": -100}, tool_length=100)
    assert np.allclose(tip, [10, -5, 500 - 100 - 100]) and np.allclose(d, [0, 0, 1])
    # 车床：X 直径编程，X40 → 刀尖半径 20
    tip, _ = K.forward(LATHE, {"X": 40, "Z": -30})
    assert np.allclose(tip, [20, 0, -30])
    # 摇篮 AC：A = -90°（工件绕 X 转 -90°），竖直刀轴在工件坐标里是 rot(X, +90°)·Z = [0, -1, 0]
    _, d = K.forward(AC, {"A": -90})
    assert np.allclose(d, [0, -1, 0])
    # A 轴回转中心在 z = -100：A = -90° 时，机床坐标里 (0,0,-100+h) 处的刀尖对应工件上 (0, -h, -100)... 取 h = 50
    tip, _ = K.forward(AC, {"A": -90, "Z": -350}, tool_length=0)     # 刀尖在机床坐标 (0,0,50)
    assert np.allclose(tip, [0, -150, -100])
    # C = 90°：工件绕 Z 转 90°，机床 +X 处的刀尖在工件坐标里是 −Y
    tip, _ = K.forward(AC, {"C": 90, "X": 30, "Z": -400})
    assert np.allclose(tip, [0, -30, 0])
    # 摆头 BC：B = 90°，刀轴绕 Y 转到 +X；刀尖绕摆动中心 (0,0,450) 转：(0,0,300) → (-150,0,450)
    tip, d = K.forward(_bc_head(), {"B": 90})
    assert np.allclose(d, [1, 0, 0]) and np.allclose(tip, [-150, 0, 450])


def _random_q(m: dict, rng) -> dict:
    q = {}
    for a in m["axes"]:
        if a.get("continuous"):
            q[a["id"]] = float(rng.uniform(-170, 170))
        else:
            lo, hi = float(a["min"]), float(a["max"])
            q[a["id"]] = float(rng.uniform(lo + 0.05 * (hi - lo), hi - 0.05 * (hi - lo)))
    return q


@pytest.mark.parametrize("make", [lambda: AC, _bc_head, _head_table, lambda: VMC, lambda: LATHE],
                         ids=["cradle-AC", "head-BC", "head-B-table-C", "vmc", "lathe"])
def test_inverse_round_trip_below_1e9_mm(make):
    """ADR-0104 C2 验收：逆解往返误差 < 1e-9 mm。随机 200 个位姿：正解 → 逆解（上一点 = 原值）→ 各轴回到原值；
    不给上一点时，逆解出来的轴位置正解回去，刀尖与刀轴也对得上"""
    m = make()
    rng = np.random.default_rng(20261118)
    L = 0.0 if m["kind"] == "lathe" else 80.0
    worst = 0.0
    for _ in range(200):
        q = _random_q(m, rng)
        tip, d = K.forward(m, q, L)
        back = K.inverse(m, tip, d, L, prefer=q)
        for k in q:
            assert back[k] == pytest.approx(q[k], abs=1e-7), (k, q, back)
        for s in K.inverse_all(m, tip, d, L):
            t2, d2 = K.forward(m, s, L)
            worst = max(worst, float(np.linalg.norm(t2 - tip)))
            assert np.allclose(d2, d, atol=1e-12)
    assert worst < 1e-9


def test_two_solutions_and_limits_pick():
    """摇篮 AC：刀轴倾斜时有两组解（A 正负、C 差 180°）；A 行程 [-120, 30]，只有 A 为负的一组可用"""
    v = np.array([0.5, 0.0, math.sqrt(3) / 2])            # 刀轴与 Z 成 30°
    sols = K.inverse_all(AC, [10, 20, 60], v, 50)
    a_vals = sorted(round(s["A"], 9) for s in sols)
    assert -30.0 in a_vals and 30.0 in a_vals
    q = K.inverse(AC, [10, 20, 60], v, 50)
    assert q["A"] == pytest.approx(-30.0) and K.in_limits(AC, q) == []
    tip, d = K.forward(AC, q, 50)
    assert np.allclose(tip, [10, 20, 60], atol=1e-9) and np.allclose(d, v)


def test_singular_keeps_previous_rotary():
    """刀轴竖直（与 C 轴平行）是奇异点：C 不定，取上一点的值保持连续，不乱跳"""
    q = K.inverse(AC, [5, 6, 7], [0, 0, 1], 60, prefer={"C": 123.4})
    assert q["A"] == pytest.approx(0.0, abs=1e-12) and q["C"] == pytest.approx(123.4)
    q = K.inverse(_bc_head(), [5, 6, 7], [0, 0, 1], 60, prefer={"C": -40.0})
    assert q["B"] == pytest.approx(0.0, abs=1e-12) and q["C"] == pytest.approx(-40.0)


def test_continuous_axis_takes_nearest_turn():
    """连续回转轴取离上一点最近的整圈：上一点 C = 350°，新方向对应 C = 10° 时给 370°，不倒转 340°"""
    m = _head_table()
    q0 = {"X": 0, "Y": 0, "Z": 0, "B": 30, "C": 10}
    tip, d = K.forward(m, q0, 50)
    q = K.inverse(m, tip, d, 50, prefer={"B": 30, "C": 350})
    assert q["C"] == pytest.approx(370.0)


def test_unreachable_and_overtravel_are_reported():
    with pytest.raises(K.KinematicsError, match="刀轴方向只能是"):
        K.inverse(VMC, [0, 0, 0], [1, 0, 0])
    with pytest.raises(K.KinematicsError, match="超程"):
        K.inverse(VMC, [1000, 0, 0], [0, 0, 1])
    with pytest.raises(K.KinematicsError, match="达不到"):
        K.inverse(LATHE, [10, 5, 0])        # 车床刀尖只能在 XZ 平面
    # 摇篮 A 行程 [-120, 30]：刀轴要与 Z 成 150°，两组解的 A 都超程
    with pytest.raises(K.KinematicsError, match="超程"):
        K.inverse(AC, [0, 0, 0], [0.5, 0, -math.sqrt(3) / 2])


def test_mill_turn_radial_tool_solves_c():
    """车铣中心径向动力刀（刀轴 +X 指向主轴）：在工件坐标里要求刀轴 −Y 方向（刀从 −Y 侧指向… 即刀具在 +Y 一侧）由 C 转出来"""
    want = np.array([0.0, 1.0, 0.0])
    q = K.inverse(MT, [0, 30, -20], want, 40, prefer={"C": 0})
    tip, d = K.forward(MT, q, 40)
    assert np.allclose(d, want) and np.allclose(tip, [0, 30, -20], atol=1e-9)
    assert q["C"] == pytest.approx(-90.0) and q["Y"] == pytest.approx(0.0, abs=1e-9)


# ---------------- 刀具库 ----------------

def test_tool_library_and_cutting_range():
    lib = TL.load()
    assert lib["example"] is True and {"EM10", "TR-CNMG", "GR3", "TH15"} <= {t["id"] for t in lib["tools"]}
    em = TL.get(lib, "EM10")
    ok = TL.check_cutting(em, "P", vc=120, fz=0.05, ap=10, ae=2)
    assert TL.verdict(ok) == "pass"
    bad = TL.check_cutting(em, "P", vc=200, fz=0.05)
    assert TL.verdict(bad) == "error" and "超出刀具样本范围" in bad[0]["text"]
    assert TL.verdict(TL.check_cutting(em, "S", vc=50)) == "unknown"          # 样本没有 S 组：未知，不算通过
    th = TL.get(lib, "TH15")
    assert TL.verdict(TL.check_cutting(th, "M", vc=100)) == "unknown"
    with pytest.raises(TL.ToolError, match="id 重复"):
        TL.check({**lib, "tools": lib["tools"] + [lib["tools"][0]]})


def test_freecad_tool_import():
    lib, skipped = TL.from_freecad(FIX / "cam-tool" / "freecad" / "Library" / "demo.fctl")
    by = {t["number"]: t for t in lib["tools"]}
    assert set(by) == {1, 2, 5} and len(skipped) == 1 and "probe" in skipped[0]
    assert by[1]["kind"] == "flat_endmill" and by[1]["diameter_mm"] == 8.0 and by[1]["flutes"] == 3
    assert by[2]["kind"] == "bull_endmill" and by[2]["corner_radius_mm"] == pytest.approx(1.0)
    assert by[5]["kind"] == "drill" and by[5]["tip_angle_deg"] == 118.0
    assert all("cutting" not in t and "holder" not in t for t in lib["tools"])   # FreeCAD 里没有的不编
