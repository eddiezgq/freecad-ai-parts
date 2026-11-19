"""关节空心轴设计 → 三维模型 → 测量回读 → 二维图、BOM（ADR-0100 42.5 第 7 步）。

与阶梯轴（assist.shaft_model）同一套：模型用 OCCT 写 STEP，回读用 41.4 的测量逐段核对，回读一致才出图和 BOM。不同之处：
- 轴段照校核的结构（法兰、两个轴承位与隔套段、花键段、螺纹段），开贯通内孔（方案的内孔直径）；
- 花键段按外花键大径 D_ee 的圆柱建（齿不建模，图上注花键参数）；螺纹段按公称直径建（不建螺纹，注 M×1.5）；
- 法兰台阶按方案圆角，另两处台阶不倒圆（方案格式里没有，校核也不算它们的应力集中，花键段按小径算静强度）；
- 回读另核对内孔：直径 ±0.01 mm，贯通全长 ±0.05 mm；
- 质量取回读的体积 × 密度（花键齿槽没去除，比校核用的质量略大，BOM 写明）。

纯计算与本机几何内核：不联网、不调用 AI。
"""

from __future__ import annotations

import json
from pathlib import Path

from assist import shaft_model as SM

ModelError = SM.ModelError


def _chosen(result: dict) -> dict:
    from assist.design import chosen

    return chosen(result)


def model_segments(result: dict) -> tuple[list[dict], dict]:
    """采用那一轮的轴段 → 建模用的段 [{name, d, L, r}] 与说明 {bore, bearing, spline, thread}"""
    from analysis.shaft import joint as J

    rd = _chosen(result)
    p = rd["proposal"]
    segs = rd.get("segments") or []
    if not segs:
        raise ModelError("采用的那一轮没有轴段")
    seat = next(s["d"] for s in segs if s["name"].startswith("轴承位"))
    sp = J.spline(seat)
    out = []
    for s in segs:
        d = sp["D_ee_mm"] if s["name"] == "花键段" else s["d"]
        out.append({"name": s["name"], "d": float(d), "L": float(s["L"]), "r": 0.0})
    # 方案里的圆角写在台阶左边那一段（shaft_model.runs 的约定）：法兰台阶在法兰与内侧轴承位之间，圆角在小径（轴承位）一侧
    out[0]["r"] = float(p["fillet_mm"])
    thread = next((s for s in segs if s["name"].startswith("螺纹段")), None)
    info = {"bore_mm": float(p["bore_mm"]), "bearing": p["bearing"], "spline": sp,
            "thread": thread["name"].replace("螺纹段 ", "") if thread else None}
    return out, info


def notes(info: dict) -> list[str]:
    sp = info["spline"]
    out = [f"花键 m{sp['module_mm']:g} z{sp['z']} 30° 平齿根（GB/T 3478.1）：大径 Ø{sp['D_ee_mm']:g}，小径 Ø{sp['D_ie_mm']:g}",
           "花键段模型按大径圆柱，齿不建"]
    if info.get("thread"):
        out.append(f"螺纹 {info['thread']}，模型按公称直径，螺纹不建")
    return out


def readback(segs: list[dict], info: dict, step: str | Path, material: str | None) -> dict:
    from assist import measure

    m = measure.measure(step, material=material)
    res = SM.compare(SM.expected_faces(segs), m["segments"])
    total = sum(s["L"] for s in segs)
    bores = m.get("bores") or []
    want = {"diameter_mm": info["bore_mm"], "start_mm": 0.0, "length_mm": total}
    if len(bores) != 1:
        res["problems"].append(f"内孔：设计 1 个贯通孔，模型量出 {len(bores)} 个")
    else:
        b = bores[0]
        dd, ds, dl = b["diameter_mm"] - want["diameter_mm"], b["start_mm"], b["length_mm"] - total
        ok = abs(dd) <= SM.D_TOL_MM and abs(ds) <= SM.L_TOL_MM and abs(dl) <= SM.L_TOL_MM
        res["rows"].append({"segment": "内孔", "design": want, "measured": b,
                            "diff_mm": {"diameter": round(dd, 4), "start": round(ds, 4), "length": round(dl, 4)}, "ok": ok})
        if not ok:
            res["problems"].append(f"内孔：直径差 {dd:+.3f}、起点差 {ds:+.3f}、长度差 {dl:+.3f} mm")
    res["overall"] = "fail" if res["problems"] else "pass"
    res["measurement"] = {k: m[k] for k in ("file", "sha256", "envelope_mm", "volume_mm3", "mass_kg", "material",
                                            "density_kg_m3", "geometry_check") if k in m}
    return res


def bom(info: dict, rb: dict, *, drawing_no: str, name: str, get) -> list[dict]:
    """自制件一行（质量取回读）+ 选用的轴承（两个同型号）；圆螺母、隔套不在零件库，不列"""
    rows = SM.bom([{"bearing": info["bearing"]}, {"bearing": info["bearing"]}], rb, drawing_no=drawing_no, name=name, get=get)
    if rows[0].get("mass_kg") is not None:
        rows[0]["mass_source"] = "回读模型的体积 × 材料密度（花键按大径圆柱，齿槽未去除）"
    return rows


def generate(result: dict, out_dir: str | Path, get, *, drawing_no: str = "AI-JOINT-1", name: str = "关节输出轴（AI 设计）") -> dict:
    """joint_design.design() 的结果（status pass）→ out_dir 下 shaft.step、readback.json、drawing.svg、bom.json；返回摘要"""
    if not str(result.get("status", "")).startswith("pass"):
        raise ModelError(f"设计没有通过（{result.get('status')}），不生成模型")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    segs, info = model_segments(result)
    material = result["conditions"].get("material")
    step = SM.build_step(segs, out_dir / "shaft.step", bore=info["bore_mm"])
    rb = readback(segs, info, step, material)
    (out_dir / "readback.json").write_text(json.dumps(rb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summary = {"readback": rb["overall"], "problems": rb["problems"], "step": "shaft.step", "readback_rows": len(rb["rows"]),
               "mass_kg": rb["measurement"].get("mass_kg"), "volume_mm3": rb["measurement"].get("volume_mm3")}
    if rb["overall"] != "pass":
        summary["delivered"] = False
        return summary
    (out_dir / "drawing.svg").write_text(SM.drawing_svg(segs, title=name, drawing_no=drawing_no, material=material or "未定",
                                                        bore=info["bore_mm"], notes=notes(info)), encoding="utf-8")
    rows = bom(info, rb, drawing_no=drawing_no, name=name, get=get)
    (out_dir / "bom.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summary.update(delivered=True, drawing="drawing.svg", bom=rows)
    return summary
