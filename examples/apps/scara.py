"""典型应用二：SCARA 机器人（600 mm 臂展一类）。ADR-0061，M13 第二步。

需求 → 水平面动力学（不计重力）→ 大臂 j2、小臂 j3 关节选型 → 布局与校验 → BOM → 大臂拓扑优化 → 大臂板件有限元与
固有频率 → 大臂减重型腔数控铣 → 发布到工厂。

用法：python -m examples.apps.scara [--hub http://localhost:8100] [--quick]
"""

from __future__ import annotations

import argparse

import analysis
from examples.apps import common as C

SOURCES = [
    {"title": "Epson LS6-B SCARA Robot - 600mm 产品页", "url": "https://epson.com/For-Work/Robots/SCARA/Epson-LS6-B-SCARA-Robot---600mm/p/RLS6B602ST9B5",
     "note": "臂展 600 mm、负载额定 2 kg / 最大 6 kg、标准循环时间 0.40 s、自重 17 kg、许用惯量额定 0.01 / 最大 0.12 kg·m²"},
]
ASSUMPTIONS = [
    "臂长分配：大臂 325 mm、小臂 275 mm（产品页只给总臂展 600 mm）",
    "质量：大臂 3.0 kg（铝板与 j3 模组座）、小臂 3.5 kg（含第 3、4 轴的丝杠花键与电机）、末端额定负载 2 kg",
    "运动：大臂、小臂各转 90°。快：用时 0.30 s（按标准循环时间 0.40 s 的水平段粗估）；慢：用时 0.60 s。加减速各占 40%",
    "水平面运动不计重力；供电 200 V 三相、EtherCAT",
]
MADE = [
    {"code": "SC-ARM1", "name": "SCARA 大臂", "qty": 1, "material": "6061-T6",
     "raw": {"item_code": "RM-6061-P380", "name": "6061-T6 板材 380×120×20", "uom": "Nos", "supplier": "steel"}, "raw_qty": 1,
     "routing": [["铣结合面 Face milling", 30], ["钻攻螺纹孔 Drilling & tapping", 18], ["零件检验 Part inspection", 6]]},
    {"code": "SC-ARM2", "name": "SCARA 小臂", "qty": 1, "material": "6061-T6",
     "raw": {"item_code": "RM-6061-P330", "name": "6061-T6 板材 330×110×20", "uom": "Nos", "supplier": "steel"}, "raw_qty": 1,
     "routing": [["铣结合面 Face milling", 26], ["钻攻螺纹孔 Drilling & tapping", 16], ["零件检验 Part inspection", 6]]},
]
ASSEMBLY = [["总装 Final assembly", 60], ["跑合试验 Run-in test", 30], ["出厂检验 Final inspection", 15]]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args(argv)
    run = C.Run("scara", "SCARA 机器人（600 mm 臂展一类）", SOURCES, ASSUMPTIONS)
    out = {}

    def dyn(label, t):
        arm = {"kind": "arm", "base_height_mm": 0, "links": [{"length_mm": 325, "mass_kg": 3.0}, {"length_mm": 275, "mass_kg": 3.5}],
               "payload_kg": 2.0}
        r = analysis.run("mbd", {"model": arm, "gravity": False, "duration_s": t + 0.2, "sample_hz": 200, "drives": [
            {"joint": "j2", "kind": "move", "to": 90, "t0_s": 0.1, "t1_s": 0.1 + t, "accel_ratio": 0.4},
            {"joint": "j3", "kind": "move", "to": 90, "t0_s": 0.1, "t1_s": 0.1 + t, "accel_ratio": 0.4},
            {"joint": "j1", "kind": "hold"}]})
        d = {x["joint"]: x for x in r["data"]["drives"]}
        run.add(f"动力学（水平面，{label}）", "ok", f"90° 用时 {t:g} s：大臂 j2 峰值 {d['j2']['peak']:.1f} N·m、均方根 {d['j2']['rms']:.1f}、"
                f"最高 {d['j2']['speed_max']:.0f} rpm、最大等效惯量 {d['j2']['inertia_max_kgm2']:.3f} kg·m²；小臂 j3 峰值 {d['j3']['peak']:.1f} N·m",
                j2=d["j2"], j3=d["j3"])
        return r
    out["mbd_fast"] = run.guard("动力学（水平面，快）", dyn, "快", 0.3)
    out["mbd"] = run.guard("动力学（水平面，慢）", dyn, "慢", 0.6)

    base = {"safety_factor": 1.2, "supply": {"current_type": "ac", "voltage_v": 200, "phases": 3},
            "fieldbus_protocol": "ethercat", "ambient_temp_c": 25}

    def select():
        from analysis import mbd
        fast = mbd.requirement(out["mbd_fast"], "j2", base=base)
        if not C.compose(fast):
            run.add("选型（快）", "unknown", f"大臂按标准循环的快动作：峰值 {fast['output_torque_peak_nm']:.0f} N·m、{fast['output_speed_rpm']:.0f} rpm——"
                    "零件库里没有能满足的组合（100:1 时电机转速超限，50:1 的谐波减速器最大只到 CSF-20，扭矩不够）；"
                    "要做到 0.40 s 节拍需补 32 号以上的 50:1 谐波减速器或换减速方式，以下按慢动作选型", requirement=fast)
        for j in ("j2", "j3"):
            req = mbd.requirement(out["mbd"], j, base=base)
            req["id"] = f"scara-{j}"
            cands = C.compose(req)
            if not cands:
                run.add(f"选型 {j}", "fail", f"零件库里没有能满足的组合（需求 峰值 {req['output_torque_peak_nm']:.1f} N·m、"
                        f"{req['output_speed_rpm']:.0f} rpm）", requirement=req)
                continue
            best = cands[0]
            names = "、".join(c["component"].split(".")[-1].upper() for c in best.system["components"])
            run.add(f"选型 {j}", "ok" if best.report["overall"] == "pass" else "unknown",
                    f"连续 {req['output_torque_cont_nm']:.1f} / 峰值 {req['output_torque_peak_nm']:.1f} N·m、{req['output_speed_rpm']:.0f} rpm → {names}；"
                    f"{C.checks_text(best.report)}", requirement=req, system=best.system, report=best.report)
            out[j] = {"req": req, "system": best.system, "report": best.report}
    run.guard("选型", select)

    def lay():
        if a.quick or "j2" not in out:
            run.add("布局与干涉", "skip", "测试模式不开 FreeCAD" if a.quick else "大臂关节没有选出组合")
            return
        r = C.layout(out["j2"]["req"], run.out / "layout-j2")
        if r is None:
            run.add("布局与干涉", "skip", "没有设 FAP_FREECAD=headless（需要 FreeCAD）")
            return
        rep = (r["system"] or {}).get("report") or {}
        run.add("布局与干涉", "ok" if r["code"] == 0 else "unknown", f"{C.checks_text(rep) if rep else '见 layout-j2/README.md'}")
    run.guard("布局与干涉", lay)

    def bom():
        from engine import export
        rows = []
        for j in ("j2", "j3"):
            if j in out:
                rows += [f"{r['vendor']} {r['model']}" for r in export.bom_json(out[j]["system"], C.library().get)["rows"]]
        run.add("BOM", "ok" if rows else "unknown", "两个关节外购件：" + "、".join(rows))
    run.guard("BOM", bom)

    def topo():
        tpk = out["mbd"]["data"]["drives"][0]["peak"]
        f_tip = tpk / 0.325                                  # 大臂末端（j3 座）受的力，按 j2 峰值扭矩折算
        r = analysis.run("topo", {"preset": "cantilever", "nelx": 65, "nely": 24, "volfrac": 0.5, "length_mm": 325,
                                  "thickness_mm": 20})
        d = r["data"]
        step = analysis.topo.plate_step(d["outline"], 20, run.out / "SC-ARM1.step")
        fs = C.faces(step)
        root = C.face_ids(fs, C.plane_at(0, 0.0))
        tip = C.face_ids(fs, C.plane_at(0, 325.0))
        st = analysis.run("fea", {"step_path": step, "material": "6061-T6", "mesh": {"size_mm": 8 if a.quick else 5},
                                  "loads": [{"type": "fixed", "faces": root}, {"type": "force", "faces": tip, "vector_n": [0, -f_tip, 0]}]})
        mo = analysis.run("fea", {"analysis": "modal", "step_path": step, "material": "6061-T6", "n_modes": 3,
                                  "mesh": {"size_mm": 8 if a.quick else 5}, "loads": [{"type": "fixed", "faces": root}]})
        f1 = (mo["data"].get("freqs") or [{}])[0].get("hz") if mo["status"] == "ok" else None
        run.add("拓扑优化与有限元：大臂", "ok" if st["status"] == "ok" else "unknown",
                f"悬臂构形、材料用量 50%，柔度 {d['history'][0][1]:.0f} → {d['compliance']:.0f}；20 mm 铝板：末端 {f_tip:.0f} N 时最大应力 "
                f"{st['data'].get('vm_max_mpa', float('nan')):.1f} MPa、末端位移 {st['data'].get('u_max_mm', float('nan')):.3f} mm；"
                f"根部固定一阶固有频率 {f1 if f1 is None else round(f1)} Hz（不含小臂与负载的附加质量）",
                f1_hz=f1, vm=st["data"].get("vm_max_mpa"))
    run.guard("拓扑优化与有限元：大臂", topo)

    def cam():
        r = analysis.run("cam", {"mode": "mill", "machine": "EX-VMC", "kienzle": "MD22", "item": "SC-ARM1",
                                 "stock": {"box": [-12, -62, 352, 62]}, "features": [
                                     {"type": "contour", "rect": [-10, -60, 350, 60], "corner_r": 10, "depth": 20},
                                     {"type": "pocket", "rect": [70, -35, 250, 35], "corner_r": 10, "depth": 12},
                                     {"type": "holes", "d": 8.5, "points": [[15, -35], [15, 35], [320, -35], [320, 35]], "depth": 22}]})
        d = r["data"]
        for p in d["programs"]:
            (run.out / f"O{p['number']:04d}.nc").write_text(p["gcode"], encoding="utf-8")
        texts = "；".join(c["text"] for p in d["programs"] for c in p["checks"]) or "没有发现问题"
        run.add("数控编程：大臂", "ok" if d["verdict"] in ("ok", "warn") else "unknown",
                f"外轮廓、减重型腔、4 个安装孔：约 {d['total_time_s'] / 60:.1f} min；检查：{texts}")
    run.guard("数控编程：大臂", cam)
    run.add("热分析 / 流体 / 数字孪生", "na", "与协作机器人关节相同的做法，这里不重复（数字孪生同样缺谐波减速器额定寿命）")

    def pub():
        if not a.hub or "j2" not in out:
            run.add("发布到工厂", "skip", "没给 --hub" if not a.hub else "没有可发布的方案")
            return
        r = C.publish(a.hub, code="SCARA-600", name="SCARA 机器人大臂关节（600 mm 臂展一类）", system=out["j2"]["system"],
                      requirement=out["j2"]["req"], report=out["j2"]["report"], made_parts=MADE, assembly_routing=ASSEMBLY,
                      note="典型应用演练（ADR-0061）；小臂关节另见 report.json")
        run.add("发布到工厂", "ok", f"方案 {r['code']} 第 {r['revision']} 版")
    run.guard("发布到工厂", pub)
    return run.save()


if __name__ == "__main__":
    main()
