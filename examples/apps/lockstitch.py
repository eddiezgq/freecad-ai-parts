"""典型应用三：工业直驱平缝机（JUKI DDL-9000C 一类）。ADR-0061，M13 第二步。

需求 → 针杆曲柄滑块动力学（5000 针/分）→ 主轴直联伺服选型（引擎逐对校验电机 + 驱动器）→ 上轴 LS-101 固有频率（临界转速）、
扭转强度、疲劳 → 上轴数控车 → 控制箱散热器流体（强制风冷）→ 电机支架拓扑优化 → 发布到工厂。

用法：python -m examples.apps.lockstitch [--hub http://localhost:8100] [--quick]
"""

from __future__ import annotations

import argparse

import analysis
from examples.apps import common as C

SOURCES = [
    {"title": "JUKI DDL-9000C 系列样本（经销商发布的 PDF）", "url": "https://www.sewingmachinesplus.com/media/products/juki/juki-9000c/brochure.pdf",
     "note": "最高缝速 5000 针/分（半干式）；针杆行程 35.0 mm（厚料）/ 30.7 mm（薄料）；400 W 小型交流伺服电机直联主轴（直驱）"},
    {"title": "问渠《机械设计》第 33.11 节案例：平缝机上轴 LS-101", "url":
     "https://github.com/eddiezgq/freecad-ai-parts/blob/main/factory/digital/hub/case_parts.py",
     "note": "上轴各段直径、长度：Ø10×22（针杆曲柄座）、Ø12×10、Ø16×215、Ø12×10、Ø10×40"},
]
ASSUMPTIONS = [
    "针杆机构按曲柄滑块：曲柄半径 17.5 mm（行程 35 mm）、连杆 60 mm、杆宽 8 mm、厚 5 mm、45 钢；不计挑线、旋梭、送布机构，未加平衡块",
    "主轴恒速 5000 rpm；缝制阻力、摩擦零件库与样本都没有，未计（实际扭矩会更大）",
    "供电按缝纫车间 200 V 三相（零件库的 SGD7S 驱动器要求三相；只有单相 220 V 时要换驱动器）",
    "上轴两个轴承位按径向支承；表面系数 β = 0.92、尺寸系数 ε = 0.85（问渠数字工厂实验 8 的示例值）",
    "控制箱散热器：铝底板 120×80×6 mm、8 片直翅高 30 mm；风扇风速 2 m/s、空气 35 °C、散热器 60 °C",
]
LS_SEGS = [(10, 22), (12, 10), (16, 215), (12, 10), (10, 40)]
MADE = [
    {"code": "LS-101", "name": "平缝机上轴", "qty": 1, "material": "45 钢调质", "raw": {"item_code": "RM-45-D50"}, "datum": "毛坯外圆（粗基准）",
     "clamping": "三爪卡盘 + 尾座顶尖（细长轴）", "raw_qty": 0.6,
     "routing": [["下料 Sawing", 2], ["粗车 Rough turning", 10], ["调质 Quench & temper", 10], ["精车 Finish turning", 9],
                 ["磨外圆 Cylindrical grinding", 8], ["零件检验 Part inspection", 4]]},
    {"code": "LS-HS", "name": "控制箱散热器", "qty": 1, "material": "6061-T6",
     "raw": {"item_code": "RM-6061-B125", "name": "6061-T6 方料 125×85×40", "uom": "Nos", "supplier": "steel"},
     "datum": "毛坯底面（粗基准）", "clamping": "平口钳", "raw_qty": 1,
     "routing": [["铣结合面 Face milling", 25], ["钻攻螺纹孔 Drilling & tapping", 8], ["零件检验 Part inspection", 4]]},
]
ASSEMBLY = [["总装 Final assembly", 50], ["跑合试验 Run-in test", 15], ["出厂检验 Final inspection", 10], ["清洗包装 Cleaning & packing", 8]]
RPM = 5000


def _amps(drive):
    """驱动器 motor_out 端口的额定电流（A），没有数据时 0（只用于排序和说明）。"""
    port = next((p for p in drive.get("ports", []) if p["id"] == "motor_out"), {})
    return ((port.get("spec") or {}).get("rated_current_a") or {}).get("value", 0)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-cfd", action="store_true", help="跳过流体（没装 OpenFOAM 或测试时）")
    a = ap.parse_args(argv)
    run = C.Run("lockstitch", "工业直驱平缝机（JUKI DDL-9000C 一类）", SOURCES, ASSUMPTIONS)
    out = {}

    def dyn():
        r = analysis.run("mbd", {"model": {"kind": "mechanism", "id": "C-LNK-SLIDER", "params": {
            "crank_m": 0.0175, "rod_m": 0.06, "link_width_m": 0.008, "link_thickness_m": 0.005}},
            "duration_s": 0.3, "sample_hz": 200, "drives": [{"joint": "crank", "kind": "speed", "value": RPM}]})
        d = r["data"]["drives"][0]
        run.add("动力学：针杆机构", "ok", f"主轴 {RPM} rpm：驱动扭矩峰值 {d['peak']:.2f} N·m、均方根 {d['rms']:.2f} N·m（主要是针杆往复惯性力，"
                f"未加平衡块）；最大等效惯量 {d['inertia_max_kgm2']:.2e} kg·m²", drive=d)
        out["mbd"] = r
    run.guard("动力学：针杆机构", dyn)

    def select():
        d = out["mbd"]["data"]["drives"][0]
        req = {"id": "lockstitch", "statement": "平缝机主轴直驱：5000 rpm，扭矩按针杆机构动力学",
               "output_torque_cont_nm": round(d["rms"], 3), "output_torque_peak_nm": round(d["peak"], 3),
               "output_speed_rpm": RPM, "safety_factor": 1.2, "supply": {"current_type": "ac", "voltage_v": 200, "phases": 3},
               "ambient_temp_c": 25}
        lib = C.library()
        motors = sorted((c for c in lib.all() if c["category"] == "servo_motor" and not c["id"].endswith("-6")),
                        key=lambda c: c["params"]["rated_power_w"]["value"])
        drives = sorted((c for c in lib.all() if c["category"] == "drive"),
                        key=lambda c: -_amps(c))
        tried, best, near = [], None, None
        for m in motors:
            for dv in drives:
                sysd = {"id": "lockstitch", "requirement": req, "components": [
                    {"instance": "motor", "component": m["id"]}, {"instance": "drive", "component": dv["id"]}],
                    "connections": [{"a": "drive.motor_out", "b": "motor.power_in"}, {"a": "motor.encoder", "b": "drive.encoder_in"}]}
                rep = C.verify(sysd)
                bad = sorted({c["check"] for c in rep["checks"] if c["status"] == "fail"})
                tried.append((m["model"], dv["model"], rep["overall"], bad))
                if rep["overall"] == "pass" and best is None:
                    best = (sysd, rep)
                # 只差驱动器（C9）的组合里取驱动器电流最大的那组，用来说明缺什么
                if bad == ["C9"] and near is None:
                    near = (m, sysd, rep)
        n_pass = sum(1 for t in tried if t[2] == "pass")
        if best is not None:
            sysd, rep = best
            names = "、".join(c["component"].split(".")[-1].upper() for c in sysd["components"])
            run.add("选型：主轴直驱电机", "ok", f"直驱（无减速器）：引擎逐对校验 {len(tried)} 组、通过 {n_pass} 组，取功率最小的 {names}；"
                    f"{C.checks_text(rep)}", requirement=req, system=sysd, report=rep, tried=tried)
            out["sel"] = {"req": req, "system": sysd, "report": rep}
            return
        motor_ok = sorted({t[0] for t in tried if "C4" not in t[3] and "C5" not in t[3]})
        msg = (f"直驱（无减速器）：引擎逐对校验 {len(tried)} 组电机 + 驱动器，没有全部通过的。"
               f"电机扭矩、转速够的有 {'、'.join(motor_ok) or '无'}；"
               f"但零件库里最大的驱动器 {drives[0]['model']} 额定电流 {_amps(drives[0])} A，"
               "带不动这些电机（C9）——要补更大驱动器的数据。另：针杆机构未加平衡块、扭矩偏大；JUKI 实机用 400 W，"
               "差距可能来自平衡块等这里没建模的因素")
        run.add("选型：主轴直驱电机", "fail", msg, requirement=req, tried=tried)
        if near:
            m, sysd, rep = near
            out["sel"] = {"req": req, "system": sysd, "report": rep, "near": True}
    run.guard("选型：主轴直驱电机", select)

    def bom():
        from engine import export
        if "sel" not in out:
            run.add("BOM", "skip", "没有选出电机")
            return
        b = export.bom_json(out["sel"]["system"], C.library().get)
        run.add("BOM", "ok", ("（按最接近的组合，驱动器待换）" if out["sel"].get("near") else "") + "外购件：" + "、".join(f"{r['vendor']} {r['model']}" for r in b["rows"])
                + f"；总质量 {b['total_mass_kg']} kg")
    run.guard("BOM", bom)
    run.add("布局与干涉", "na", "直驱电机直接装在机头上，没有电机—减速器的端口配合要摆（V1 的布局针对关节模组）")

    mesh = 3 if a.quick else 2

    def shaft():
        step = C.shaft_step(run.out / "LS-101.step", LS_SEGS)
        fs = C.faces(step)
        bearings = C.face_ids(fs, C.cyl_d(12))
        sup = [{"type": "cyl_support", "faces": [f], "axis": {"origin": [0, 0, 0], "dir": [0, 0, 1]}, "dofs": ["radial"]}
               for f in bearings]
        mo = analysis.run("fea", {"analysis": "modal", "step_path": step, "material": "45-QT", "n_modes": 4,
                                  "mesh": {"size_mm": mesh}, "loads": sup + [{"type": "fixed", "faces": C.face_ids(fs, C.plane_at(2, 297.0))}]})
        fr = [f for f in (mo["data"].get("freqs") or [])]
        f1 = fr[0]["hz"] if fr else None
        n_hz = RPM / 60
        run.add("固有频率：上轴 LS-101", "ok" if f1 else "unknown",
                f"两轴承位径向支承、电机端固定：一阶 {f1} Hz（{fr[0]['rpm'] if fr else '—'} rpm），工作 {RPM} rpm = {n_hz:.1f} Hz，"
                f"比值 {f1 / n_hz if f1 else float('nan'):.1f}——远离共振（不计装在轴上的曲柄、带轮、转子的质量）", freqs=fr)
        d = out["mbd"]["data"]["drives"][0]
        st = analysis.run("fea", {"step_path": step, "material": "45-QT", "mesh": {"size_mm": mesh}, "loads": [
            {"type": "fixed", "faces": C.face_ids(fs, C.plane_at(2, 297.0))},
            {"type": "torque", "faces": C.face_ids(fs, C.cyl_d(10, z1=22)), "value_nm": d["peak"],
             "axis": {"origin": [0, 0, 0], "dir": [0, 0, 1]}}]})
        sd = st["data"]
        hand = 16 * d["peak"] * 1000 / (3.14159265 * 10 ** 3)
        run.add("有限元：上轴扭转", "ok" if st["status"] == "ok" else "fail",
                f"针杆端加峰值扭矩 {d['peak']:.2f} N·m：最大 Von Mises {sd['vm_max_mpa']:.1f} MPa、安全系数 {sd['safety_factor']:.1f}；"
                f"Ø10 段手算 τ = 16T/πd³ = {hand:.1f} MPa（等效 {hand * 3 ** 0.5:.1f}）", vm=sd["vm_max_mpa"])
        f = analysis.run("fatigue", {"material": "45-QT", "stress_ref_mpa": sd["vm_max_mpa"], "load_ref": d["peak"],
                                     "load_series": out["mbd"]["data"]["series"]["crank"]["drive"], "block_seconds": 0.3,
                                     "surface_factor": 0.92, "size_factor": 0.85})
        fd = f["data"]
        life = "无限寿命" if fd.get("infinite") or (fd.get("life_hours") or 0) > 1e9 else f"{fd['life_hours']:.3g} 小时"
        run.add("疲劳：上轴", "ok" if f["status"] == "ok" else "fail",
                f"5000 rpm 下每转一个扭矩循环（0.3 s 记录 {fd['cycles_per_block']} 个循环）：{life}")
    run.guard("上轴分析", shaft)

    def cam():
        r = analysis.run("cam", {"mode": "turn", "machine": "EX-LATHE", "segments": LS_SEGS, "chamfer_mm": 0.5, "kienzle": "C45E",
                                 "item": "LS-101", "stock_d_mm": 20})
        d = r["data"]
        for p in d["programs"]:
            (run.out / f"O{p['number']:04d}.nc").write_text(p["gcode"], encoding="utf-8")
        texts = "；".join(c["text"] for p in d["programs"] for c in p["checks"]) or "没有发现问题"
        run.add("数控编程：上轴", "ok" if d["verdict"] in ("ok", "warn") else "unknown",
                f"Ø20 棒料、两次装夹 {len(d['programs'])} 个程序、约 {d['total_time_s'] / 60:.1f} min；检查：{texts}"
                "（细长轴 L/d ≈ 30，实际要顶尖、跟刀架，仿真不计让刀）")
    run.guard("数控编程：上轴", cam)

    def cfd():
        if a.no_cfd:
            run.add("流体：控制箱散热器", "skip", "按参数跳过")
            return
        st = analysis.modules()
        if not next(m for m in st if m["id"] == "cfd")["available"]:
            run.add("流体：控制箱散热器", "skip", "本机没装 OpenFOAM")
            return
        step = C.heatsink_step(run.out / "LS-HS.step", (120, 80, 6), 8, 30, 2)
        r = analysis.run("cfd", {"step_path": step, "flow": {"velocity_ms": 2, "direction": "+x", "air_t_c": 35},
                                 "heat": {"wall_t_c": 60}, "domain": {"ground": True},
                                 "mesh": {"cells_target": 30000 if a.quick else 80000, "level": 2},
                                 "solver": {"iterations": 300 if a.quick else 600}})
        if r["status"] != "ok":
            run.add("流体：控制箱散热器", "fail", "；".join(r["messages"]))
            return
        d = r["data"]
        run.add("流体：控制箱散热器", "ok", f"风速 2 m/s、散热器比空气高 25 K：散热 {d['heat_w']:.1f} W、平均散热系数 {d['h_mean']:.1f} W/(m²·K)、"
                f"压降对应阻力 {d['drag_n']:.3f} N；驱动器损耗零件库无数据，待确认够不够", heat_w=d["heat_w"], h=d["h_mean"])
    run.guard("流体：控制箱散热器", cfd)

    def topo():
        r = analysis.run("topo", {"preset": "bracket", "nelx": 60, "nely": 40, "volfrac": 0.4, "length_mm": 90, "thickness_mm": 8})
        d = r["data"]
        run.add("拓扑优化：电机支架", "ok", f"支架构形（左边固定、右下角受力）、材料用量 40%：柔度 {d['history'][0][1]:.0f} → {d['compliance']:.0f}，"
                f"{d['iterations']} 次迭代；板面积 {d['area_mm2']:.0f} mm²")
    run.guard("拓扑优化：电机支架", topo)
    run.add("热分析 / 数字孪生", "na", "直驱没有减速器、零件库也没有轴承，孪生无可算的零件；电机温升需要电机损耗数据")

    def pub():
        if not a.hub or "sel" not in out:
            run.add("发布到工厂", "skip", "没给 --hub" if not a.hub else "没有选出电机")
            return
        sysd = out["sel"]["system"]
        note = "典型应用演练（ADR-0061）"
        if out["sel"].get("near"):
            note += "；校验 C9 未过：驱动器电流不够，需换更大的驱动器（零件库暂无数据），工厂先按此方案备料、驱动器待定"
        r = C.publish(a.hub, code="LOCKSTITCH-DD", name="工业直驱平缝机主轴驱动（DDL-9000C 一类）", system=sysd,
                      requirement=out["sel"]["req"], report=out["sel"]["report"], made_parts=MADE, assembly_routing=ASSEMBLY,
                      note=note)
        run.add("发布到工厂", "ok", f"方案 {r['code']} 第 {r['revision']} 版，带自制件 LS-101、LS-HS；校验结论 {out['sel']['report']['overall']} 随方案一起发出")
    run.guard("发布到工厂", pub)
    return run.save()


if __name__ == "__main__":
    main()
