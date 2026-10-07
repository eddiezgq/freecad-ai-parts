"""典型应用一：协作机器人肩关节（UR5e 一类）。ADR-0061，M13 第二步。

需求 → 动力学（参数化串联臂）→ 选型（肩关节 j2、肘关节 j3）→ 布局与校验 → BOM → 自制件：关节空心轴 RJ-201 有限元、疲劳、
数控车；关节壳体 J2-HSG 热分析、数控铣；大臂侧板拓扑优化 → 减速器数字孪生 → 发布到工厂。

用法：python -m examples.apps.cobot_joint [--hub http://localhost:8100] [--quick]
"""

from __future__ import annotations

import argparse
import math

import analysis
from examples.apps import common as C

SOURCES = [
    {"title": "Universal Robots UR5e 数据表", "url": "https://www.universal-robots.com/manuals/latest/en/datasheets/ur5e/",
     "note": "负载 5 kg、臂展 850 mm、自重 20.7 kg、各关节最高 ±180°/s"},
    {"title": "UR 论坛：UR5e Plant Model for MPC（引 ROS-Industrial universal_robot 的 DH 与质量）",
     "url": "https://forum.universal-robots.com/t/ur5e-plant-model-for-mpc-matlab/19067",
     "note": "大臂 a2 = 425 mm、小臂 a3 = 392.25 mm；质量 3.70 / 8.393 / 2.275 / 1.219 / 1.219 / 0.1879 kg（外部测量，可能与实物不同）"},
    {"title": "问渠《机械设计》第 33.10 节案例：协作机器人肩关节空心轴 RJ-201",
     "url": "https://github.com/eddiezgq/freecad-ai-parts/blob/main/factory/digital/hub/case_parts.py",
     "note": "空心轴各段直径、长度与 Ø30 贯通内孔"},
]
ASSUMPTIONS = [
    "肩关节最不利工况：大臂、小臂水平伸直（重力矩最大），满载 5 kg + 腕部三个模组 2.626 kg 集中在小臂末端",
    "运动：肩、肘各转 90°，用时 1.0 s，加减速各占 25%（最高 120°/s，低于数据表的 180°/s）",
    "供电按控制柜 200 V 三相交流、EtherCAT 总线（零件库里的伺服是 200 V 交流；真实协作臂多用 48 V 直流关节）",
    "工作制：每天 16 小时，按动力学这一段动作重复（数字孪生的运行记录是仿真工况，不是现场数据）",
    "表面系数 β = 0.92（磨削）、尺寸系数 ε = 0.85：取问渠数字工厂实验 8 的示例值，实际按教材图表查",
    "关节壳体自然对流散热系数 8 W/(m²·K)（自然对流常见范围 5–10），环境 25 °C",
]
RJ_SEGS = [(70, 10), (50, 16), (50, 24), (50, 16), (42.75, 20), (42, 10)]   # 第 33.10 节；内孔 Ø30
RJ_BORE = 30.0
MADE = [
    {"code": "RJ-201", "name": "肩关节空心轴", "qty": 1, "material": "45 钢调质", "raw": {"item_code": "RM-45-D50"},
     "raw_qty": 1.6, "routing": [["下料 Sawing", 3], ["粗车 Rough turning", 16], ["调质 Quench & temper", 12],
                                 ["精车 Finish turning", 14], ["磨外圆 Cylindrical grinding", 10], ["零件检验 Part inspection", 6]]},
    {"code": "J2-HSG", "name": "肩关节壳体", "qty": 1, "material": "6061-T6",
     "raw": {"item_code": "RM-6061-B140", "name": "6061-T6 方料 140×140×90", "uom": "Nos", "supplier": "steel"},
     "raw_qty": 1, "routing": [["铣结合面 Face milling", 22], ["钻攻螺纹孔 Drilling & tapping", 16], ["零件检验 Part inspection", 5]]},
]
ASSEMBLY = [["总装 Final assembly", 40], ["跑合试验 Run-in test", 20], ["出厂检验 Final inspection", 10], ["清洗包装 Cleaning & packing", 5]]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub")
    ap.add_argument("--quick", action="store_true", help="网格粗一些、跳过布局（测试用）")
    a = ap.parse_args(argv)
    run = C.Run("cobot_joint", "协作机器人肩关节（UR5e 一类）", SOURCES, ASSUMPTIONS)
    out = {}

    # 1 需求 + 动力学
    def dyn():
        arm = {"kind": "arm", "base_height_mm": 89, "links": [{"length_mm": 425, "mass_kg": 8.393},
                                                              {"length_mm": 392.25, "mass_kg": 2.275}],
               "payload_kg": 5 + 1.219 + 1.219 + 0.1879}
        r = analysis.run("mbd", {"model": arm, "duration_s": 1.4, "sample_hz": 100, "drives": [
            {"joint": "j2", "kind": "move", "to": -90, "t0_s": 0.2, "t1_s": 1.2, "accel_ratio": 0.25},
            {"joint": "j3", "kind": "move", "to": 90, "t0_s": 0.2, "t1_s": 1.2, "accel_ratio": 0.25},
            {"joint": "j1", "kind": "hold"}]})
        d = {x["joint"]: x for x in r["data"]["drives"]}
        g = r["data"]["static"]["gravity_torque_nm"]
        hand = 9.81 * (8.393 * 0.2125 + 2.275 * (0.425 + 0.392 / 2) + 7.626 * (0.425 + 0.39225))
        run.add("动力学", "ok", f"肩 j2 峰值 {d['j2']['peak']:.1f} N·m、均方根 {d['j2']['rms']:.1f} N·m、最高 {d['j2']['speed_max']:.1f} rpm；"
                f"肘 j3 峰值 {d['j3']['peak']:.1f} N·m；水平伸直重力矩 {g['j2']:.1f} N·m（手算 Σm·g·r {hand:.1f}）",
                j2=d["j2"], j3=d["j3"], gravity=g, hand_gravity_j2=hand)
        out["mbd"] = r
    run.guard("动力学", dyn)

    # 2 选型
    base = {"safety_factor": 1.2, "supply": {"current_type": "ac", "voltage_v": 200, "phases": 3},
            "fieldbus_protocol": "ethercat", "ambient_temp_c": 25}

    def select():
        from analysis import mbd
        for j in ("j2", "j3"):
            req = mbd.requirement(out["mbd"], j, base=base)
            req["id"] = f"cobot-{j}"
            cands = C.compose(req)
            if not cands:
                run.add(f"选型 {j}", "fail", "零件库里没有能满足的组合")
                continue
            best = cands[0]
            names = "、".join(c["component"].split(".")[-1].upper() for c in best.system["components"])
            run.add(f"选型 {j}", "ok" if best.report["overall"] == "pass" else "unknown",
                    f"需求 连续 {req['output_torque_cont_nm']:.1f} / 峰值 {req['output_torque_peak_nm']:.1f} N·m、{req['output_speed_rpm']:.1f} rpm → "
                    f"{names}；{C.checks_text(best.report)}；共 {len(cands)} 个候选",
                    requirement=req, system=best.system, report=best.report)
            out[j] = {"req": req, "system": best.system, "report": best.report}
    run.guard("选型", select)

    # 3 布局与校验、BOM
    def lay():
        if a.quick:
            run.add("布局与干涉", "skip", "测试模式不开 FreeCAD")
            return
        r = C.layout(out["j2"]["req"], run.out / "layout-j2")
        if r is None:
            run.add("布局与干涉", "skip", "没有设 FAP_FREECAD=headless（需要 FreeCAD）")
            return
        rep = (r["system"] or {}).get("report") or {}
        run.add("布局与干涉", "ok" if r["code"] == 0 else "unknown",
                f"FreeCAD 按端口摆放、检查干涉并按布局复核：{C.checks_text(rep) if rep else '见 layout-j2/README.md'}；"
                f"截图 {'有' if r['png'] else '无'}（layout-j2/）")
    run.guard("布局与干涉", lay)

    def bom():
        from engine import export
        b = export.bom_json(out["j2"]["system"], C.library().get)
        mass = b["total_mass_kg"]
        run.add("BOM", "ok", f"肩关节外购件 {len(b['rows'])} 种：" + "、".join(f"{r['vendor']} {r['model']}" for r in b["rows"])
                + f"；外购件总质量 {'未知（有零件缺质量数据）' if mass is None else f'{mass:g} kg'}", rows=b["rows"])
    run.guard("BOM", bom)

    # 4 自制件 RJ-201：有限元（扭矩加在花键段，减速器法兰端面固定）→ 疲劳
    mesh = 5 if a.quick else 3

    def fea():
        step = C.shaft_step(run.out / "RJ-201.step", RJ_SEGS, RJ_BORE)
        fs = C.faces(step)
        fix = C.face_ids(fs, C.plane_at(2, 0.0))
        spline = C.face_ids(fs, C.cyl_d(42.75))
        tpk = out["mbd"]["data"]["drives"][0]["peak"]
        r = analysis.run("fea", {"step_path": step, "material": "45-QT", "mesh": {"size_mm": mesh}, "loads": [
            {"type": "fixed", "faces": fix},
            {"type": "torque", "faces": spline, "value_nm": tpk, "axis": {"origin": [0, 0, 0], "dir": [0, 0, 1]}}]})
        d = r["data"]
        D = 42.75                                    # 扭矩经花键段传入，最小受扭截面
        J = math.pi * (D ** 4 - RJ_BORE ** 4) / 32
        hand = tpk * 1000 * (D / 2) / J
        run.add("有限元：空心轴 RJ-201", "ok" if r["status"] == "ok" else "fail",
                f"峰值扭矩 {tpk:.1f} N·m：最大 Von Mises {d['vm_max_mpa']:.1f} MPa，安全系数 {d['safety_factor']:.2f}；"
                f"花键段（按小径 Ø42.75、内孔 Ø30）手算 τ = T·r/Iₚ = {hand:.1f} MPa（等效 √3·τ = {hand * math.sqrt(3):.1f}；"
                f"有限元最大值在台阶与加载面附近，含应力集中）",
                vm_max=d["vm_max_mpa"], sf=d["safety_factor"], hand_tau=hand)
        out["rj_fea"] = (step, d["vm_max_mpa"], tpk)
    run.guard("有限元：空心轴 RJ-201", fea)

    def fat():
        _step, vm, tpk = out["rj_fea"]
        series = out["mbd"]["data"]["series"]["j2"]["drive"]
        r = analysis.run("fatigue", {"material": "45-QT", "stress_ref_mpa": vm, "load_ref": tpk, "load_series": series,
                                     "block_seconds": 1.4, "surface_factor": 0.92, "size_factor": 0.85})
        d = r["data"]
        if d.get("infinite") or (d.get("life_hours") or 0) > 1e9:
            life = "远超设计寿命（应力远低于疲劳极限，按 Haibach 外推 {:.2g} 小时）".format(d["life_hours"]) if d.get("life_hours") else "无限寿命"
        else:
            life = f"{d['life_hours']:.3g} 小时（{d['life_blocks']:.3g} 个动作）"
        run.add("疲劳：空心轴 RJ-201", "ok" if r["status"] == "ok" else "fail",
                f"按动力学的扭矩记录（每个动作 {d['cycles_per_block']} 个循环）：{life}", **{k: d.get(k) for k in
                                                                                            ("life_hours", "infinite", "damage_per_block")})
    run.guard("疲劳：空心轴 RJ-201", fat)

    # 5 自制件 J2-HSG：热（减速器损耗按零件库效率曲线）
    def heat():
        from engine.efficiency import lookup
        sysd = out["j2"]["system"]
        red = C.library().get(next(c["component"] for c in sysd["components"] if c["instance"] == "reducer"))
        ratio = red["params"]["ratio"]["value"]
        s = out["mbd"]["data"]["series"]["j2"]
        p_out = C.mean(abs(t * w * 2 * math.pi / 60) for t, w in zip(s["drive"], s["speed"], strict=True))
        n_in = out["mbd"]["data"]["drives"][0]["speed_max"] * ratio
        eff = lookup(red["params"]["efficiency_curve"], n_in, 25)
        if eff is None:
            run.add("热分析：关节壳体 J2-HSG", "unknown", "零件库的效率曲线查不到这个输入转速，减速器损耗待确认")
            return
        loss = p_out * (1 / eff[0] - 1)
        step = C.housing_step(run.out / "J2-HSG.step", (140, 140, 90), 110)
        fs = C.faces(step)
        bore = C.face_ids(fs, lambda f: f["kind"] == "cylinder")
        r = analysis.run("thermal", {"step_path": step, "material": "6061-T6", "mesh": {"size_mm": 8 if a.quick else 6},
                                     "thermal": [{"type": "heat_flux", "faces": bore, "power_w": loss},
                                                 {"type": "convection", "faces": "rest", "h_w_m2k": 8, "t_inf_c": 25}]})
        d = r["data"]
        run.add("热分析：关节壳体 J2-HSG", "ok" if r["status"] == "ok" else "fail",
                f"平均输出功率 {p_out:.1f} W，{eff[2]}，减速器损耗约 {loss:.1f} W（电机损耗零件库无数据，未计）；"
                f"按连续往复运动估算（偏保守），壳体最高 {d['t_max_c']:.1f} °C——温升偏高，实际要有停顿或加散热", loss_w=loss, t_max=d["t_max_c"])
    run.guard("热分析：关节壳体 J2-HSG", heat)

    # 6 大臂侧板：拓扑优化 → 板件 → 有限元
    def topo():
        r = analysis.run("topo", {"preset": "cantilever", "nelx": 64, "nely": 24, "volfrac": 0.45, "length_mm": 425,
                                  "thickness_mm": 6})
        d = r["data"]
        step = analysis.topo.plate_step(d["outline"], 6, run.out / "upper-arm-plate.step")
        fs = C.faces(step)
        left = C.face_ids(fs, C.plane_at(0, 0.0))
        right = C.face_ids(fs, C.plane_at(0, 425.0))
        f_tip = 9.81 * (2.275 + 7.626) / 2          # 两块侧板分担小臂与末端的重量
        r2 = analysis.run("fea", {"step_path": step, "material": "6061-T6", "mesh": {"size_mm": 6 if a.quick else 4},
                                  "loads": [{"type": "fixed", "faces": left},
                                            {"type": "force", "faces": right, "vector_n": [0, -f_tip, 0]}]})
        run.add("拓扑优化：大臂侧板", "ok" if r2["status"] == "ok" else "unknown",
                f"悬臂构形、材料用量 45%：柔度 {d['history'][0][1]:.0f} → {d['compliance']:.0f}；板面积 {d['area_mm2']:.0f} mm²；"
                f"拉伸 6 mm 板件做有限元（末端 {f_tip:.0f} N）：最大应力 {r2['data'].get('vm_max_mpa', float('nan')):.1f} MPa、"
                f"最大位移 {r2['data'].get('u_max_mm', float('nan')):.3f} mm")
    run.guard("拓扑优化：大臂侧板", topo)

    # 7 数控编程
    def cam():
        r = analysis.run("cam", {"mode": "turn", "machine": "EX-LATHE", "segments": RJ_SEGS, "chamfer_mm": 1, "kienzle": "C45E",
                                 "item": "RJ-201"})
        d = r["data"]
        r2 = analysis.run("cam", {"mode": "mill", "machine": "EX-VMC", "kienzle": "MD22", "item": "J2-HSG",
                                  "stock": {"box": [-72, -72, 72, 72]}, "features": [
                                      {"type": "contour", "rect": [-70, -70, 70, 70], "corner_r": 8, "depth": 20},
                                      {"type": "holes", "d": 6.8, "points": [[-60, -60], [60, -60], [60, 60], [-60, 60]], "depth": 15}]})
        d2 = r2["data"]
        for p in d["programs"] + d2["programs"]:
            (run.out / f"O{p['number']:04d}.nc").write_text(p["gcode"], encoding="utf-8")
        run.add("数控编程", "ok" if d["verdict"] != "error" and d2["verdict"] != "error" else "unknown",
                f"RJ-201 车外圆两次装夹 {len(d['programs'])} 个程序、约 {d['total_time_s'] / 60:.1f} min，检查 {d['verdict']}"
                f"（Ø30 内孔另钻镗，本模块不编）；J2-HSG 外轮廓与 4 个螺纹底孔约 {d2['total_time_s'] / 60:.1f} min，检查 {d2['verdict']}；"
                f"程序存 O*.nc（示例机床虚构）")
    run.guard("数控编程", cam)

    # 8 数字孪生：减速器（运行记录由动力学工况生成）
    def twin():
        sysd = out["j2"]["system"]
        lib = C.library()
        parts = analysis.twin.parts_from_system(sysd, lib.get)
        d = out["mbd"]["data"]["drives"][0]
        recs = [{"instance": "reducer", "hours": 16, "output_torque_avg_nm": d["rms"], "output_torque_max_nm": d["peak"],
                 "output_speed_rpm": d["speed_max"] / 2} for _ in range(30)]
        r = analysis.run("twin", {"parts": parts, "records": recs})
        p = r["data"]["parts"][0]
        if p["status"] == "unknown":
            run.add("数字孪生：减速器", "unknown", f"{p['model']}：{p['note']}——零件库的谐波减速器还没有额定寿命，补录后即可算剩余寿命",
                    missing=p.get("missing"))
        else:
            run.add("数字孪生：减速器", "ok", f"{p['model']} 已用 {p['used_ratio']:.1%}，剩余约 {p['remaining_h']:.0f} 小时")
    run.guard("数字孪生：减速器", twin)
    run.add("流体分析", "na", "关节是封闭结构、靠壳体自然散热，没有需要算的流场（流体用在平缝机控制箱散热器）")

    # 9 发布到工厂
    def pub():
        if not a.hub:
            run.add("发布到工厂", "skip", "没给 --hub")
            return
        r = C.publish(a.hub, code="COBOT-J2", name="协作机器人肩关节（UR5e 一类）", system=out["j2"]["system"],
                      requirement=out["j2"]["req"], report=out["j2"]["report"], made_parts=MADE, assembly_routing=ASSEMBLY,
                      note="典型应用演练（ADR-0061）")
        run.add("发布到工厂", "ok", f"方案 {r['code']} 第 {r['revision']} 版，带自制件 RJ-201、J2-HSG 与总装工艺")
    run.guard("发布到工厂", pub)
    return run.save()


if __name__ == "__main__":
    main()
