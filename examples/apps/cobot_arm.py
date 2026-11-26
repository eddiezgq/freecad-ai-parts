"""典型应用：一整台六轴协作机械臂（UR5e 一类：负载 5 kg、臂展 850 mm）。ADR-0094。

需求 → 六关节动力学与选型（两轮：第二轮带上第一轮选出的模组质量）→ 结构设计取值（铝管、关节壳体）→ 整臂多体有限元
（重力 + 满载：末端下垂、应力；模态；急停瞬态）→ 关节刚度（减速器扭转折线、输出轴承力矩刚度）叠加到末端下垂与频率 →
输出交叉滚子轴承寿命（样本公式）→ 减速器寿命（数字孪生）→ BOM。

尺寸里凡是“设计取值”的都是本案例定的（管径、壁厚、壳体壁厚），由有限元验算；外购件参数只用零件库里有出处的。

用法：python -m examples.apps.cobot_arm [--quick]
"""

from __future__ import annotations

import argparse
import math

import analysis
from examples.apps import common as C

SOURCES = [
    {"title": "Universal Robots UR5e 数据表", "url": "https://www.universal-robots.com/manuals/latest/en/datasheets/ur5e/",
     "note": "负载 5 kg、臂展 850 mm、各关节最高 ±180°/s"},
    {"title": "Universal Robots：DH Parameters for calculations of kinematics and dynamics（UR5e 表）",
     "url": "https://www.universal-robots.com/articles/ur/application-installation/dh-parameters-for-calculations-of-kinematics-and-dynamics/",
     "note": "d1 = 0.1625 m、a2 = −0.425 m、a3 = −0.3922 m、d4 = 0.1333 m、d5 = 0.0997 m、d6 = 0.0996 m"},
    {"title": "Harmonic Drive：CSG/CSF Gear Units 样本（零件库已登记 src-hd-csg-csf-gear-units）",
     "url": "https://www.harmonicdrive.net/_hd/content/documents/CSG-CSF_GearUnits.pdf",
     "note": "扭转刚度第 130–131 页；输出轴承规格第 136 页；输出轴承寿命公式第 31–33 页（公式 031-4、032-1、032-2、033-1）"},
    {"title": "Thomson《Theory of Vibration with Applications》：Dunkerley 公式",
     "url": "https://doi.org/10.1201/9780203718292", "note": "串联柔度的系统一阶频率下限 1/f² ≈ Σ 1/fᵢ²"},
]
ASSUMPTIONS = [
    "姿态：大臂、小臂水平伸直（重力矩最大），满载 5 kg；关节轴都沿 y，末端在 x = a2 + a3 = 817.2 mm",
    "运动：j1–j5 各转 90°，用时 1.0 s，加减速各占 25%（最高 120°/s，低于数据表的 180°/s）；j6 的负载按 5 kg 质点在半径 50 mm 处（偏心工具，偏保守）",
    "供电按控制柜 200 V 三相交流、EtherCAT 总线（零件库里的伺服是 200 V 交流；真实协作臂多用 48 V 直流关节）",
    "结构设计取值：大臂铝管 Ø90×4、小臂铝管 Ø70×3、底座铝管 Ø130×6，6061-T6；关节壳体壁厚 6 mm、端板 6 mm，内径按减速器包络外径；"
    + "管子输入端的法兰毂外径同上一关节的壳体，法兰盘厚 10 mm；第二版：法兰毂远端加 6 mm 封板（防止椭圆化，第一版末端结构下垂 0.855 mm → 0.673 mm）",
    "输出轴承摆动寿命下限 35,000 h：取减速器本身的平均寿命 L50（样本表 012-1），轴承不先于减速器坏；选型时 j1 按此筛选",
    "模组（电机 + 减速器）的质量按样本质量挂在壳体内孔上；结构里不计电缆、盖板、电子板的质量",
    "急停：底座 j1 以 180°/s 转动、0.1 s 内停住，整臂按末端处的切向减速度均匀受力（偏保守）；结构阻尼比 0.02（示例值，按试验修正）",
    "输出轴承载荷系数 fw = 1.5（样本表 032-3“normal operation”上限）；工作制每天 16 小时，j1 每分钟往返 30 次、摆角 90°",
]
D1, A2, A3 = 162.5, 425.0, 392.2
UPPER, FORE, BASE = (90.0, 4.0), (70.0, 3.0), (130.0, 6.0)        # 设计取值：外径、壁厚
WALL, PLATE, DISC = 6.0, 6.0, 10.0
HUB_WALL, HUB_CAP = 6.0, True                                          # 法兰毂壁厚、远端是否封板（第二版改，见 ADR-0094 施工记录）
BASE_CFG = {"safety_factor": 1.2, "supply": {"current_type": "ac", "voltage_v": 200, "phases": 3},
            "fieldbus_protocol": "ethercat", "ambient_temp_c": 25}
BEARING_LIFE_H = 35000.0       # 输出轴承摆动寿命下限：取减速器本身的平均寿命 L50（样本表 012-1，CSF 系列 35,000 h），轴承不先于减速器坏
DUTY = (30, 45)                # 每分钟往返 30 次、摆角 90°（半角 45°）——见假设
MOVE = {"kind": "move", "to": -90, "t0_s": 0.2, "t1_s": 1.2, "accel_ratio": 0.25}


def _comp(system, inst):
    return C.library().get(next(c["component"] for c in system["components"] if c["instance"] == inst))


def _pv(comp, k):
    v = (comp.get("params") or {}).get(k)
    return v.get("value") if isinstance(v, dict) else None


def module_mass(system):
    """电机 + 减速器的样本质量（kg）；缺任何一项返回 None（不估）"""
    m = [_pv(_comp(system, i), "mass_kg") for i in ("motor", "reducer")]
    return None if any(x is None for x in m) else sum(m)


def reducer_od(system):
    for p in (_comp(system, "reducer").get("envelope") or {}).get("parts", []):
        d = (p.get("diameter_mm") or {}).get("value")
        if d:
            return float(d)
    return None


def twist_rad(red, torque_nm):
    """减速器扭转折线（样本表 130-4 / 131-1）：0–T₁ 刚度 K₁、T₁–T₂ 为 K₂、T₂ 以上为 K₃ → 扭转角（rad）"""
    t1, t2 = _pv(red, "torsion_t1_nm"), _pv(red, "torsion_t2_nm")
    k = [_pv(red, f"torsional_stiffness_k{i}_nm_per_arcmin") for i in (1, 2, 3)]
    if None in (t1, t2, *k):
        return None
    T = abs(torque_nm)
    arcmin = min(T, t1) / k[0] + max(0.0, min(T, t2) - t1) / k[1] + max(0.0, T - t2) / k[2]
    return math.radians(arcmin / 60)


def tangent_k_nm_per_rad(red, torque_nm):
    """工作扭矩处的切线扭转刚度（N·m/rad），算关节扭振频率用"""
    t1, t2 = _pv(red, "torsion_t1_nm"), _pv(red, "torsion_t2_nm")
    T = abs(torque_nm)
    i = 1 if T <= t1 else 2 if T <= t2 else 3
    return _pv(red, f"torsional_stiffness_k{i}_nm_per_arcmin") * 60 * 180 / math.pi


def bearing_life(red, fr, fa, m_nm, n_per_min, half_angle_deg, fw=1.5):
    """输出交叉滚子轴承摆动寿命（样本公式 031-4、032-2、033-1）：Pc = X(Fr + 2M/dp) + Y·Fa，
    Loc = 10⁶/(60·n₁) · 90/θ · (C/(fw·Pc))^(10/3)。M 已含 Fr(Lr + R) + Fa·La。返回 (小时, Pc, X, Y)"""
    c, dp = _pv(red, "output_bearing_dynamic_load_rating_n"), _pv(red, "output_bearing_pitch_diameter_mm")
    if None in (c, dp):
        return None
    dp_m = dp / 1000
    ratio = fa / (fr + 2 * m_nm / dp_m) if fr + m_nm > 0 else 0.0
    x, y = (1.0, 0.45) if ratio <= 1.5 else (0.67, 0.67)
    pc = x * (fr + 2 * m_nm / dp_m) + y * fa
    hours = 1e6 / (60 * n_per_min) * 90 / half_angle_deg * (c / (fw * pc)) ** (10 / 3)
    return hours, pc, x, y


def beam_sag_mm(lm, mods, E=68900.0):
    """梁理论估算（核对有限元用）：两段管子组成的悬臂（壳体、法兰当刚性），杆的质量沿长度均布，模组与负载集中；
    末端挠度 = ∫ M(x)(L − x)/EI dx，数值积分。返回 mm"""
    def I(od, t):
        return math.pi / 64 * (od ** 4 - (od - 2 * t) ** 4)
    L = A2 + A3
    tip = mods["j4"] + lm["wrist"] + mods["j5"] + mods["j6"] + 5.0
    g = 9.81e-3                                                              # kg → N/(mm 的力臂按 mm)：M 单位 N·mm
    n = 4000
    tot = 0.0
    for i in range(n):
        x = (i + 0.5) * L / n
        m = tip * g * (L - x) * 1000                                         # N·mm
        if x < A2:
            m += mods["j3"] * g * (A2 - x) * 1000
            m += lm["upper"] / A2 * g * 1000 * (A2 - x) ** 2 / 2
        m += lm["fore"] / A3 * g * 1000 * (min(L - x, A3)) * ((L - x) - min(L - x, A3) / 2)
        ei = E * (I(*UPPER) if x < A2 else I(*FORE))
        tot += m * (L - x) / ei * L / n
    return tot


# ---------------------------------------------------------------- 结构几何（gmsh OCC，关节轴沿 y）


def _ring_y(occ, x, z, y0, y1, ro, ri):
    c = occ.addCylinder(x, y0, z, 0, y1 - y0, 0, ro)
    if ri:
        occ.cut([(3, c)], [(3, occ.addCylinder(x, y0 - 1, z, 0, y1 - y0 + 2, 0, ri))])
    return (3, c)


def _tube_x(occ, x0, x1, y, z, od, t):
    c = occ.addCylinder(x0, y, z, x1 - x0, 0, 0, od / 2)
    occ.cut([(3, c)], [(3, occ.addCylinder(x0 - 1, y, z, x1 - x0 + 2, 0, 0, od / 2 - t))])
    return (3, c)


def _housing(occ, x, z, y0, y1, d_in):
    """关节壳体的外形：沿 y 的实心圆柱（外径 = 减速器包络外径 + 2 × 壁厚）；与管子合并后再挖减速器座孔（_bore）"""
    return (3, occ.addCylinder(x, y0, z, 0, y1 - y0, 0, d_in / 2 + WALL))


def _bore(occ, body, x, z, y0, y1, d_in):
    """挖减速器座孔：从 y0 一侧挖到离 y1 端面还剩端板厚处（端板是接下一节的结合面）"""
    occ.cut(body, [(3, occ.addCylinder(x, y0 - 1, z, 0, y1 - PLATE - y0 + 1, 0, d_in / 2))])


def _fuse(occ, parts):
    return occ.fuse(parts[:1], parts[1:])[0] if len(parts) > 1 else parts


def arm_steps(out, od):
    """四个实体：底座（含 j2 壳体）、大臂（j2 法兰盘 + 铝管 + j3 壳体）、小臂（j3 法兰盘 + 铝管 + j4 壳体）、腕部（j4 法兰盘 + j5/j6 壳体）。
    od：各关节减速器包络外径 {j2, j3, j4, j5}。结合面都是垂直于 y 的平面。返回 {名字: STEP 路径} 与结合面的 y 值"""
    ys = {}
    h2 = 60.0                                                            # 底座上 j2 壳体沿 y 的长度（设计取值）
    ys["j2"] = 0.0
    ys["j3"] = DISC + UPPER[0] + DISC                                     # 大臂管放在法兰盘外侧
    ys["j4"] = ys["j3"] + DISC + FORE[0] + DISC

    def base(occ):
        ro = od["j2"] / 2 + WALL
        col = occ.addCylinder(0, -h2 / 2, 0, 0, 0, D1 - ro + WALL, BASE[0] / 2)
        occ.cut([(3, col)], [(3, occ.addCylinder(0, -h2 / 2, -1, 0, 0, D1 - ro + WALL + 2, BASE[0] / 2 - BASE[1]))])
        cap = occ.addCylinder(0, -h2 / 2, D1 - ro - PLATE, 0, 0, PLATE + 2 * WALL, BASE[0] / 2)   # 立柱顶板，托住 j2 壳体
        body = _fuse(occ, [(3, col), (3, cap), _housing(occ, 0, D1, -h2, 0, od["j2"])])
        _bore(occ, body, 0, D1, -h2, 0, od["j2"])

    def hub(occ, x, y0, length, d_in):
        """输入端的法兰毂：沿 y 的圆筒，y0 一端是实心法兰盘（接上一个关节的输出法兰），另一端敞开；把管子的端头包住"""
        return (3, occ.addCylinder(x, y0, D1, 0, length, 0, d_in / 2 + HUB_WALL)), \
            (x, y0 + DISC, y0 + length - PLATE if HUB_CAP else y0 + length + 1, d_in)

    def open_bore(occ, body, x, ya, yb, d_in):
        occ.cut(body, [(3, occ.addCylinder(x, ya, D1, 0, yb - ya, 0, d_in / 2))])

    def upper(occ):
        y0 = ys["j2"]
        h, cut = hub(occ, 0, y0, DISC + UPPER[0], od["j2"])
        tube = _tube_x(occ, 0, A2, y0 + DISC + UPPER[0] / 2, D1, *UPPER)
        body = _fuse(occ, [h, tube, _housing(occ, A2, D1, y0 + DISC, ys["j3"], od["j3"])])
        _bore(occ, body, A2, D1, y0 + DISC, ys["j3"], od["j3"])
        open_bore(occ, body, cut[0], cut[1], cut[2], cut[3])

    def fore(occ):
        y0 = ys["j3"]
        h, cut = hub(occ, A2, y0, DISC + FORE[0], od["j3"])
        tube = _tube_x(occ, A2, A2 + A3, y0 + DISC + FORE[0] / 2, D1, *FORE)
        body = _fuse(occ, [h, tube, _housing(occ, A2 + A3, D1, y0 + DISC, ys["j4"], od["j4"])])
        _bore(occ, body, A2 + A3, D1, y0 + DISC, ys["j4"], od["j4"])
        open_bore(occ, body, cut[0], cut[1], cut[2], cut[3])

    def wrist(occ):
        y0 = ys["j4"]
        disc = (3, occ.addCylinder(A2 + A3, y0, D1, 0, DISC, 0, od["j4"] / 2 + WALL))
        body = _fuse(occ, [disc, _housing(occ, A2 + A3, D1, y0 + DISC * 0.5, y0 + DISC + 100.0, od["j5"])])   # j5、j6 模组装在这一段
        _bore(occ, body, A2 + A3, D1, y0 + DISC, y0 + DISC + 100.0, od["j5"])

    paths = {}
    for name, fn in (("base", base), ("upper", upper), ("fore", fore), ("wrist", wrist)):
        paths[name] = C._occ(name, out / f"ARM-{name.upper()}.step", fn)
    ys["tcp"] = ys["j4"] + DISC + 100.0
    return paths, ys


def volume_mm3(step):
    from analysis.fea.geometry import _LOCK, _gmsh

    with _LOCK:
        g = _gmsh()
        g.clear()
        g.model.occ.importShapes(step)
        g.model.occ.synchronize()
        v = sum(g.model.occ.getMass(3, t) for _d, t in g.model.getEntities(3))
        g.clear()
    return v


# ---------------------------------------------------------------- 主流程


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="网格粗一些、不做网格收敛核查（测试用）")
    a = ap.parse_args(argv)
    run = C.Run("cobot_arm", "六轴协作机械臂整臂（UR5e 一类：负载 5 kg、臂展 850 mm）", SOURCES, ASSUMPTIONS)
    out = {"modules": {}}
    joints = ("j1", "j2", "j3", "j4", "j5", "j6")

    def dyn_and_select(mods, link_mass):
        """一轮：六个关节的动力学（mods：各关节模组质量，第一轮全 0）→ 选型。返回 {关节: (需求, 方案, 报告, 候选数)}"""
        from analysis import mbd

        res = {}
        jm = [mods.get("j3", 0.0), mods.get("j4", 0.0) + mods.get("j5", 0.0) + mods.get("j6", 0.0)]
        arm = {"kind": "arm", "base_height_mm": D1, "links": [{"length_mm": A2, "mass_kg": link_mass["upper"]},
                                                             {"length_mm": A3, "mass_kg": link_mass["fore"]}],
               "joint_masses_kg": [0.0, jm[0]], "payload_kg": 5 + link_mass["wrist"] + jm[1]}
        r = analysis.run("mbd", {"model": arm, "duration_s": 1.4, "sample_hz": 100, "drives": [
            {"joint": "j1", **MOVE}, {"joint": "j2", **MOVE}, {"joint": "j3", **dict(MOVE, to=90)}]})
        res["j1"] = res["j2"] = res["j3"] = r
        w = analysis.run("mbd", {"model": {"kind": "arm", "base_height_mm": 0,
                                           "links": [{"length_mm": 99.7 + 99.6, "mass_kg": max(link_mass["wrist"], 1e-3)}],
                                           "joint_masses_kg": [0.0], "payload_kg": 5 + mods.get("j5", 0.0) + mods.get("j6", 0.0)},
                                 "duration_s": 1.4, "sample_hz": 100, "drives": [{"joint": "j2", **MOVE}, {"joint": "j1", "kind": "hold"}]})
        w5 = analysis.run("mbd", {"model": {"kind": "arm", "base_height_mm": 0, "links": [{"length_mm": 99.6, "mass_kg": 1e-3}],
                                            "joint_masses_kg": [0.0], "payload_kg": 5 + mods.get("j6", 0.0)},
                                  "duration_s": 1.4, "sample_hz": 100, "drives": [{"joint": "j2", **MOVE}, {"joint": "j1", "kind": "hold"}]})
        w6 = analysis.run("mbd", {"model": {"kind": "arm", "base_height_mm": 0, "links": [{"length_mm": 50.0, "mass_kg": 5.0}],
                                            "payload_kg": 0}, "duration_s": 1.4, "sample_hz": 100,
                                  "drives": [{"joint": "j1", **MOVE}, {"joint": "j2", "kind": "hold"}]})
        # j1 输出轴承的载荷：整臂重力矩当倾覆力矩、j1 以上的全部重量当轴向力（ADR-0094 第二版：选型时就查寿命）
        g = r["data"]["static"]["gravity_torque_nm"]["j2"]
        w_up = (link_mass["base"] + link_mass["upper"] + link_mass["fore"] + link_mass["wrist"]
                + sum(mods.get(k, 0.0) for k in ("j2", "j3", "j4", "j5", "j6")) + 5.0) * 9.81
        picks = {}
        for j, rr, jj in (("j1", r, "j1"), ("j2", r, "j2"), ("j3", r, "j3"), ("j4", w, "j2"), ("j5", w5, "j2"), ("j6", w6, "j1")):
            req = mbd.requirement(rr, jj, base=BASE_CFG)
            req["id"] = f"arm-{j}"
            cands = C.compose(req, top=30)
            # 协作臂在意重量：在没有“不通过”的候选里取外购件最轻、且电机与减速器都有样本质量的
            ok = [c for c in cands if c.report["overall"] != "fail" and module_mass(c.system) is not None]
            if j == "j1":                                                   # 选型引擎不查输出轴承寿命：这里补上
                ok = [c for c in ok if (bearing_life(_comp(c.system, "reducer"), 0.0, w_up, g, *DUTY) or (0,))[0] >= BEARING_LIFE_H]
            best = min(ok, key=lambda c: module_mass(c.system)) if ok else (cands[0] if cands else None)
            picks[j] = (req, best, len(cands))
        return picks, {"arm": r, "j4": w, "j5": w5, "j6": w6}

    # 1–2 两轮动力学与选型（第一轮模组质量为 0、结构质量按第一版几何；第二轮带上第一轮选出的模组质量）
    def dyn():
        from analysis.common import materials
        rho = materials.get("6061-T6")["density_kg_m3"] * 1e-9                  # kg/mm³
        od = {"j2": 138.0, "j3": 107.0, "j4": 85.0, "j5": 85.0}                 # 第一轮几何的壳体内径（之后按选型更新）
        mods = {}
        for rnd in (1, 2, 3, 4):
            paths, _ys = arm_steps(run.out, od)                                  # 结构质量随壳体尺寸变
            link_mass = {k: volume_mm3(p) * rho for k, p in paths.items()}
            picks, res = dyn_and_select(mods, link_mass)
            new = {j: module_mass(p[1].system) if p[1] else None for j, p in picks.items()}
            if None in new.values():
                run.add("动力学与选型", "fail", f"第 {rnd} 轮有关节选不出带质量数据的组合：{[j for j, v in new.items() if v is None]}")
                return
            od_new = {j: reducer_od(picks[j][1].system) for j in ("j2", "j3", "j4", "j5")}
            same = all(abs(new[j] - mods.get(j, -1)) < 1e-9 for j in joints) and od_new == od
            mods, od = new, od_new
            if same:
                break
        out.update(picks=picks, res=res, mods=mods, link_mass=link_mass, rounds=rnd)
        d = {x["joint"]: x for x in res["arm"]["data"]["drives"]}
        g = res["arm"]["data"]["static"]["gravity_torque_nm"]
        run.add("动力学", "ok", f"{rnd} 轮收敛（模组质量随选型更新）：j1 峰值 {d['j1']['peak']:.1f} N·m；肩 j2 峰值 {d['j2']['peak']:.1f} N·m、"
                f"水平伸直重力矩 {g['j2']:.1f} N·m；肘 j3 峰值 {d['j3']['peak']:.1f} N·m；"
                f"结构质量（铝，按最后一轮几何）底座 {link_mass['base']:.2f}、大臂 {link_mass['upper']:.2f}、小臂 {link_mass['fore']:.2f}、"
                f"腕部 {link_mass['wrist']:.2f} kg", gravity=g, link_mass_kg=link_mass)
        for j in joints:
            req, best, n = picks[j]
            names = "、".join(c["component"].split(".")[-1].upper() for c in best.system["components"])
            run.add(f"选型 {j}", "ok" if best.report["overall"] == "pass" else "unknown",
                    f"需求 连续 {req['output_torque_cont_nm']:.2f} / 峰值 {req['output_torque_peak_nm']:.2f} N·m、{req['output_speed_rpm']:.1f} rpm → "
                    f"{names}（电机 + 减速器 {mods[j]:.2f} kg）；{C.checks_text(best.report)}；{n} 个候选里取外购件最轻的",
                    requirement=req, system=best.system, report=best.report)
    run.guard("动力学", dyn)
    if "picks" not in out:
        return run.save()
    picks, mods = out["picks"], out["mods"]
    red = {j: _comp(picks[j][1].system, "reducer") for j in joints}

    # 3 BOM（六个关节的外购件）
    def bom():
        from engine import export
        rows, total = [], 0.0
        for j in joints:
            b = export.bom_json(picks[j][1].system, C.library().get)
            rows += [dict(r, joint=j) for r in b["rows"]]
            total = None if total is None or b["total_mass_kg"] is None else total + b["total_mass_kg"]
        lm = sum(out["link_mass"].values())
        run.add("BOM", "ok", f"外购件 {len(rows)} 件（6 个关节 × 电机、减速器、驱动器）；外购件 {total:.2f} kg + 铝结构 {lm:.2f} kg"
                f" = {total + lm:.1f} kg（驱动器在控制柜，算在外购件里但不在臂上）", rows=rows, total_mass_kg=total)
    run.guard("BOM", bom)

    # 3b 电机法兰的定制要求（ADR-0045、ADR-0053）：CSF-2UH 的电机侧法兰由厂商按所配电机做，
    #    订货时把电机法兰的规格（照录电机样本，带页码）给厂商；C3 在厂商确认前保持“待确认”（ADR-0046 第 1 条）
    def flanges():
        from engine.custom import custom_requirements
        rows, missing = [], []
        for j in joints:
            reqs = custom_requirements(picks[j][1].system, C.library().get)
            for r in reqs:
                spec = "、".join(f"{i['name']} {i['value']}" for i in r["items"])
                rows.append(f"{j}：{r['model']} 的 {r['port']} 按 {r['mate']['model']} 定制（{spec}）")
                missing += [f"{j} {m}" for m in r["missing"]]
        run.add("电机法兰定制要求", "ok" if not missing else "unknown",
                f"{len(rows)} 条，随减速器订货发给厂商：" + "；".join(rows)
                + (f"；电机样本缺：{'、'.join(missing)}" if missing else "")
                + "。C3 在厂商确认前按规定记“待确认”，不是缺设计", rows=rows, missing=missing, mentions_ok=True)
    run.guard("电机法兰定制要求", flanges)

    # 4 整臂多体有限元：重力 + 满载
    mesh = 8.0 if a.quick else 7.0                                   # 7 GB 内存：6 mm 带网格收敛核查会超内存

    def geometry():
        od = {j: reducer_od(picks[j][1].system) for j in ("j2", "j3", "j4", "j5")}
        paths, ys = arm_steps(run.out, od)
        out.update(paths=paths, ys=ys, od=od)
        run.add("结构设计", "ok", "关节壳体内径按所选减速器的包络外径：" + "、".join(f"{j} Ø{d:g}" for j, d in od.items())
                + f"；大臂 Ø{UPPER[0]:g}×{UPPER[1]:g}、小臂 Ø{FORE[0]:g}×{FORE[1]:g}、底座 Ø{BASE[0]:g}×{BASE[1]:g}（6061-T6，设计取值）；"
                "STEP：ARM-BASE / UPPER / FORE / WRIST", od=od)
    run.guard("结构设计", geometry)
    if "paths" not in out:
        return run.save()

    def study(loads_extra, steps, gravity=(0, 0, -9.81), **kw):
        P, ys, od = out["paths"], out["ys"], out["od"]
        fs = {k: C.faces(p) for k, p in P.items()}

        def bore(body, x, d):
            return C.face_ids(fs[body], lambda f: f["kind"] == "cylinder" and abs(f.get("radius_mm", 0) - d / 2) < 0.05
                              and abs(f["center"][0] - x) < d / 2)
        def plane(body):
            return lambda ax, v: C.face_ids(fs[body], C.plane_at(ax, v))
        pl = {k: plane(k) for k in P}
        bodies = [{"id": k, "step_path": p, "material": "6061-T6"} for k, p in P.items()]
        sup = [{"type": "fixed", "body": "base", "faces": pl["base"](2, 0.0)}]
        conns = [{"type": "bonded", "a": {"body": "upper", "faces": pl["upper"](1, ys["j2"])}, "b": {"body": "base", "faces": pl["base"](1, ys["j2"])}},
                 {"type": "bonded", "a": {"body": "fore", "faces": pl["fore"](1, ys["j3"])}, "b": {"body": "upper", "faces": pl["upper"](1, ys["j3"])}},
                 {"type": "bonded", "a": {"body": "wrist", "faces": pl["wrist"](1, ys["j4"])}, "b": {"body": "fore", "faces": pl["fore"](1, ys["j4"])}}]
        loads = [{"type": "gravity", "body": k, "acceleration_m_s2": list(gravity)} for k in P]
        loads += [{"type": "mass", "body": "base", "faces": bore("base", 0, od["j2"]), "mass_kg": mods["j2"], "label": "j2 模组（样本质量）"},
                  {"type": "mass", "body": "upper", "faces": bore("upper", A2, od["j3"]), "mass_kg": mods["j3"], "label": "j3 模组"},
                  {"type": "mass", "body": "fore", "faces": bore("fore", A2 + A3, od["j4"]), "mass_kg": mods["j4"], "label": "j4 模组"},
                  {"type": "mass", "body": "wrist", "faces": bore("wrist", A2 + A3, od["j5"]), "mass_kg": mods["j5"] + mods["j6"],
                   "label": "j5、j6 模组"},
                  {"type": "mass", "body": "wrist", "faces": pl["wrist"](1, ys["tcp"]), "mass_kg": 5.0, "label": "负载 5 kg"}]
        st = {"format": "fea-study/1", "name": "cobot-arm", "bodies": bodies, "supports": sup, "loads": loads + loads_extra,
              "connections": conns, "steps": steps, "mesh": {"size_mm": mesh},
              "checks": {"convergence": not a.quick}, "probes": [{"id": "tcp", "point_mm": [A2 + A3, ys["tcp"], D1]}]}
        st.update(kw)
        r = analysis.run("fea", st)
        if r["status"] != "ok":
            raise RuntimeError("；".join(r["messages"]))
        return r["data"]

    def fea_static():
        d = study([], [{"id": "s", "type": "static"}])
        s = d["steps"][0]
        tcp = s["probes"][0]["u_mm"]
        out["static"] = s
        bodies = "；".join(f"{b['id']} {b['vm_max_mpa']:.1f} MPa" for b in s.get("bodies") or [])
        sf = s.get("safety_factor")
        hand = beam_sag_mm(out["link_mass"], mods)
        out["hand_sag"] = hand
        run.add("有限元：整臂静力", "ok" if s["trust"]["verdict"] == "pass" else "unknown",
                f"重力 + 满载、水平伸直：结构使末端下垂 {-tcp[2]:.3f} mm（梁理论估算 {hand:.3f} mm，只算两根管子的弯曲；"
                f"有限元多出的是壳体、法兰毂的变形和偏置引起的扭转）；各段最大应力 {bodies}；"
                + (f"安全系数 {sf:.1f}（{s.get('safety_body')}）" if sf else "安全系数未给（可信度没有判“通过”）")
                + "；可信度 " + "、".join(f"{i['name']} {C.STATUS_TEXT.get(i['verdict'], i['verdict'])}" for i in s["trust"]["items"]),
                tcp_u_mm=tcp, trust=s["trust"]["verdict"], items=s["trust"]["items"], hand_sag_mm=hand)
    run.guard("有限元：整臂静力", fea_static)

    # 5 关节刚度叠加：j2、j3 减速器扭转 + j1 输出轴承受倾覆力矩
    def joint_stiffness():
        lm, g = out["link_mass"], 9.81
        x_tcp = A2 + A3
        # 各质量（kg）与到 j2 的水平距离（mm）
        items = [(lm["upper"], A2 / 2), (mods["j3"], A2), (lm["fore"], A2 + A3 / 2), (mods["j4"], x_tcp),
                 (lm["wrist"] + mods["j5"] + mods["j6"] + 5.0, x_tcp)]
        T2 = sum(m * g * x for m, x in items) / 1000
        T3 = sum(m * g * (x - A2) for m, x in items if x > A2) / 1000
        th2, th3 = twist_rad(red["j2"], T2), twist_rad(red["j3"], T3)
        ks = _pv(red["j1"], "output_bearing_moment_stiffness_nm_per_arcmin")
        th1 = math.radians(T2 / ks / 60) if ks else None                       # 整臂重力矩作为倾覆力矩压在 j1 的输出轴承上
        if None in (th1, th2, th3):
            run.add("关节刚度", "unknown", "减速器的扭转刚度或输出轴承力矩刚度缺数据")
            return
        dj = (th2 * x_tcp + th3 * A3 + th1 * x_tcp)
        ds = -out["static"]["probes"][0]["u_mm"][2] if "static" in out else None
        out["joint"] = {"T2": T2, "T3": T3}
        run.add("关节刚度", "ok", f"j2 扭矩 {T2:.1f} N·m → 扭转 {math.degrees(th2) * 60:.2f}′，j3 扭矩 {T3:.1f} N·m → {math.degrees(th3) * 60:.2f}′"
                f"（样本扭转折线）；j1 输出轴承受倾覆力矩 {T2:.1f} N·m → 倾角 {math.degrees(th1) * 60:.2f}′；关节使末端下垂 {dj:.3f} mm"
                + (f"；加上结构的 {ds:.3f} mm，末端共下垂 {dj + ds:.3f} mm（结构占 {ds / (dj + ds):.0%}）" if ds else "")
                + "。样本注明刚度为参考值，最小约为表值的 80 %：最不利时关节部分 ×1.25",
                T2_nm=T2, T3_nm=T3, joint_sag_mm=dj, structure_sag_mm=ds)
    run.guard("关节刚度", joint_stiffness)

    def fea_modal():
        d = study([], [{"id": "m", "type": "modal", "n_modes": 6}], gravity=(0, 0, -9.81), checks={"convergence": False})
        m = d["steps"][0]
        f_struct = m["freqs"][0]["hz"]
        # 关节扭振：j2 绕 y 的转动惯量（质点 + 均布杆）与工作扭矩处的切线刚度
        lm = out["link_mass"]
        x_tcp = A2 + A3
        J2 = (lm["upper"] * A2 ** 2 / 3 + mods["j3"] * A2 ** 2 + lm["fore"] * (A3 ** 2 / 12 + (A2 + A3 / 2) ** 2)
              + (mods["j4"] + lm["wrist"] + mods["j5"] + mods["j6"] + 5.0) * x_tcp ** 2) * 1e-6
        J3 = (lm["fore"] * A3 ** 2 / 3 + (mods["j4"] + lm["wrist"] + mods["j5"] + mods["j6"] + 5.0) * A3 ** 2) * 1e-6
        T = out.get("joint", {"T2": 0, "T3": 0})
        f2 = math.sqrt(tangent_k_nm_per_rad(red["j2"], T["T2"]) / J2) / (2 * math.pi)
        f3 = math.sqrt(tangent_k_nm_per_rad(red["j3"], T["T3"]) / J3) / (2 * math.pi)
        f_all = 1 / math.sqrt(1 / f_struct ** 2 + 1 / f2 ** 2 + 1 / f3 ** 2)
        run.add("模态：整臂", "ok", f"结构（模组、负载按样本质量挂上）一阶 {f_struct:.1f} Hz；j2 关节扭振 {f2:.1f} Hz、j3 {f3:.1f} Hz"
                f"（切线刚度按工作扭矩取折线段）；按 Dunkerley 公式合成，整臂竖直方向一阶约 {f_all:.1f} Hz（下限估计）。"
                f"动作的加减速时间 0.25 s，对应激励主要在 4 Hz 以下，离一阶远", freqs=m["freqs"], f_j2=f2, f_j3=f3, f_dunkerley=f_all)
    run.guard("模态：整臂", fea_modal)

    def estop():
        a_t = math.radians(180) * (A2 + A3) / 1000 / 0.1                      # 末端切向减速度 m/s²
        amp = [{"time_s": 0, "factor": 0}, {"time_s": 0.002, "factor": 1}, {"time_s": 0.1, "factor": 1}, {"time_s": 0.102, "factor": 0}]
        d = study([], [{"id": "t", "type": "transient", "end_time_s": 0.25, "time_step_s": 2e-4, "damping_ratio": 0.02,
                        "amplitude": amp, "n_modes": 20}], gravity=(0, a_t, 0), checks={"convergence": False})
        t = d["steps"][0]
        run.add("急停瞬态", "ok" if t["trust"]["verdict"] != "fail" else "unknown",
                f"j1 以 180°/s 在 0.1 s 内停住，末端切向减速度 {a_t:.1f} m/s²（整臂按此均匀受力，偏保守）：结构最大位移 {t['u_max_mm']:.3f} mm"
                f"（{t['u_max_time_s'] * 1000:.0f} ms 时），最大应力 {t['vm_max_mpa']:.1f} MPa；关节柔度没计入（模态叠加只含结构）",
                u_max_mm=t["u_max_mm"], vm_max_mpa=t["vm_max_mpa"], a_t=a_t)
    run.guard("急停瞬态", estop)

    # 6 输出轴承寿命（j1 受倾覆力矩最大；j2 受整臂重量的径向力）
    def bearings():
        T = out.get("joint")
        lm = out["link_mass"]
        W = (lm["upper"] + lm["fore"] + lm["wrist"] + sum(mods[j] for j in ("j3", "j4", "j5", "j6")) + 5.0) * 9.81
        rows = []
        for j, fr, fa, m in (("j1", 0.0, W + (lm["base"] + mods["j2"]) * 9.81, T["T2"]), ("j2", W, 0.0, 0.0)):
            mc = _pv(red[j], "output_bearing_moment_load_rating_nm")
            life = bearing_life(red[j], fr, fa, m, *DUTY)
            if life is None:
                rows.append(f"{j} 缺数据")
                continue
            h, pc, x, y = life
            rows.append(f"{j}（{red[j]['model']}）径向 {fr:.0f} N、轴向 {fa:.0f} N、倾覆力矩 {m:.1f} N·m（许用 {mc} N·m）："
                        f"Pc = {pc:.0f} N（X = {x:g}、Y = {y:g}），摆动寿命 {h:.3g} 小时（每天 16 小时约 {h / 16 / 365:.3g} 年），"
                        + ("满足" if h >= BEARING_LIFE_H else "不满足") + f" {BEARING_LIFE_H:.0f} h 的下限")
            out.setdefault("bearing_h", {})[j] = h
        # j1 换大一号的减速器时输出轴承寿命（零件库里同系列、减速比相同的下一个规格）
        lib = C.library()
        cur = red["j1"]
        same = [c for c in lib.all() if c.get("category") == "reducer" and _pv(c, "ratio") == _pv(cur, "ratio")
                and (_pv(c, "output_bearing_dynamic_load_rating_n") or 0) > (_pv(cur, "output_bearing_dynamic_load_rating_n") or 0)]
        if same:
            nxt = min(same, key=lambda c: _pv(c, "output_bearing_dynamic_load_rating_n"))
            alt = bearing_life(nxt, 0.0, W + (lm["base"] + mods["j2"]) * 9.81, T["T2"], *DUTY)
            if alt:
                rows.append(f"j1 换 {nxt['model']}（输出轴承 C = {_pv(nxt, 'output_bearing_dynamic_load_rating_n'):.0f} N）时摆动寿命 {alt[0]:.3g} 小时"
                            f"（约 {alt[0] / 16 / 365:.3g} 年）")
        run.add("输出轴承寿命", "ok", "；".join(rows) + "。按样本公式 031-4、032-2、033-1，fw = 1.5；选型引擎不查输出轴承寿命，这一项由本步补上")
    run.guard("输出轴承寿命", bearings)

    # 7 减速器寿命（数字孪生）：j2 按动力学的扭矩记录
    def twin():
        sysd = picks["j2"][1].system
        parts = analysis.twin.parts_from_system(sysd, C.library().get)
        d = next(x for x in out["res"]["arm"]["data"]["drives"] if x["joint"] == "j2")
        recs = [{"instance": "reducer", "hours": 16, "output_torque_avg_nm": d["rms"], "output_torque_max_nm": d["peak"],
                 "output_speed_rpm": d["speed_max"] / 2} for _ in range(30)]
        r = analysis.run("twin", {"parts": parts, "records": recs})
        p = r["data"]["parts"][0]
        if p["status"] == "unknown":
            run.add("减速器寿命：j2", "unknown", f"{p['model']}：{p['note']}", missing=p.get("missing"))
        else:
            run.add("减速器寿命：j2", "ok", f"{p['model']} 按每天 16 小时、30 天的动作记录：已用 {p['used_ratio']:.2%}，"
                    f"按这个强度剩余约 {p['remaining_h']:.0f} 小时（样本 L10 = 7000 h 在额定扭矩、2000 rpm 下）")
    run.guard("减速器寿命：j2", twin)
    return run.save()


if __name__ == "__main__":
    main()
