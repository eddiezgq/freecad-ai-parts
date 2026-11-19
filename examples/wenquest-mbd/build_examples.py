"""问渠多体动力学的三个入门例子（ADR-0102 第 5 步）：在 FreeCAD 里从零件走到结果和报告。不开界面，可在测试和 CI 里跑。

    <FreeCAD 的 python> examples/wenquest-mbd/build_examples.py --out 目录 [--only 1,2,3] [--samples]

1. 免费版 · 曲柄滑块：导入 STEP，程序按几何起草 3 个转动副 + 1 个移动副（不用 AI），给钢材（Steel-Generic），曲柄 1200 rpm 匀速转一圈，
   算运动学：曲柄要的驱动力矩、各运动副的反力。
2. 专业版 · 两关节机械臂：导入 STEP，AI 挑运动副（录制回放），给铝材（Aluminum-6061-T6），肩关节 1 s 内转 60°、肘关节转 −90°（摆线规律），
   算运动学：两个关节电机要的力矩；出中英报告。
3. 专业版 · 细长推杆（大变形梁，模型文件）：两端铰支的钢杆 φ20 × 1000 mm，在不同轴向压力下先静平衡再线性化，
   一阶弯曲频率的平方对压力连成直线，外推到零频率得屈曲载荷，对欧拉公式；出中英报告。
例子 2 的 AI 回复用仓库里真实模型的录制回放（tests/recordings/mbd_mates，不联网）；用户自己跑时用自己的 AI 密钥。
--samples：把例子 1、2 建好装配体的 FreeCAD 文件、三个例子的结果摘要（results.json）和中英报告 PDF 存进例子目录
（例子 1 的报告是专业版才出的，样张给免费版用户看专业版多了什么）。尺寸、材料、运动都是演示用的示例。
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import shutil
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT, HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

STEEL = "90bbd8ef-8623-4d78-b3bf-e0bdb9b74dd3"          # FreeCAD 材料库：Steel-Generic
ALU = "68b152b2-fd5e-4f10-8db0-1a2df3fe0fda"            # FreeCAD 材料库：Aluminum-6061-T6
DIRS = {1: "01-slider-crank-free", 2: "02-arm-ai", 3: "03-pushrod-buckling"}
CYCLOID = "{a}*(time - sin(2*pi*time)/(2*pi))"          # 1 s 内从 0 到 a（°），起止速度、加速度为零
TODAY = date(2026, 11, 18)


def _materials(objs, uuid):
    import Materials

    mat = Materials.MaterialManager().getMaterial(uuid)
    for o in objs:
        o.ShapeMaterial = mat


def _assembly(doc, step: Path, client, mat):
    from freecad_addon.core import mbd_study as ST

    objs, _parts, found, draft = ST.draft_from_step(str(step), doc, client)
    asm = ST.build(doc, objs, found, draft["accept"], draft["ground"])
    _materials(objs, mat)
    doc.recompute()
    return objs, draft, asm


def _joint(model, objs, label_i, label_j):
    lab = {o.Name: o.Label for o in objs}
    lab["ground"] = "ground"
    return next(j["id"] for j in model["joints"]
                if {lab.get(j["body_i"]), lab.get(j["body_j"])} == {label_i, label_j})


def _pair(model, labels, jid):
    """运动副 id → “零件–零件”（读结果时好认）"""
    j = next(x for x in model["joints"] if x["id"] == jid)
    lab = {**labels, "ground": "机架"}
    return f"{lab.get(j['body_i'], j['body_i'])}–{lab.get(j['body_j'], j['body_j'])}"


def _peak(xs):
    return max(abs(x) for x in xs)


def example1(out: Path):
    import FreeCAD as App

    from freecad_addon.core import mbd_study as ST

    doc = App.newDocument("SliderCrank")
    objs, draft, asm = _assembly(doc, HERE / DIRS[1] / "slider-crank.step", None, STEEL)
    m0, _ = ST.make_model(asm, [], {"type": "kinematic"})
    labels = {o.Name: o.Label for o in objs}
    drive = _joint(m0, objs, "ground", "曲柄")
    model, _ = ST.make_model(asm, [{"joint": drive, "kind": "speed", "value": 1200}],
                             {"type": "kinematic", "end_time_s": 0.05, "output_steps": 200})
    data, _ = ST.run(model)
    j = data["joints"]
    summary = {"draft_by": draft["by"], "joints": [{"name": a["name"], "type": a["type"]} for a in draft["accept"]],
               "drive_joint": drive, "speed_rpm": 1200,
               "drive_torque_peak_n_m": _peak(next(iter(data["motions"].values()))["effort"]),
               "reaction_peak_n": {_pair(model, labels, jid): _peak([math.sqrt(sum(x * x for x in f)) for f in v["force_n"]])
                                   for jid, v in j.items()},
               "verification": {v["key"]: v["status"] for v in data["verification"]},
               "parts": labels}
    return doc, model, data, summary


def example2(out: Path):
    import FreeCAD as App

    from freecad_addon.core import mbd_study as ST
    from freecad_addon.fc import fem_flow as F

    doc = App.newDocument("Arm")
    objs, draft, asm = _assembly(doc, HERE / DIRS[2] / "arm.step", F.llm_client(), ALU)
    m0, _ = ST.make_model(asm, [], {"type": "kinematic"})
    shoulder = _joint(m0, objs, "ground", "大臂")
    elbow = _joint(m0, objs, "大臂", "小臂")
    drives = [{"joint": shoulder, "kind": "function", "value": CYCLOID.format(a=60)},
              {"joint": elbow, "kind": "function", "value": CYCLOID.format(a=-90)}]
    model, _ = ST.make_model(asm, drives, {"type": "kinematic", "end_time_s": 1.0, "output_steps": 100})
    data, _ = ST.run(model)
    mot = data["motions"]
    summary = {"draft_by": draft["by"], "ground": draft["ground"], "notes": draft["notes"],
               "joints": [{"name": a["name"], "type": a["type"], "reason": a.get("reason", "")} for a in draft["accept"]],
               "shoulder_torque_peak_n_m": _peak(mot[f"drive_{shoulder}"[:64]]["effort"]),
               "elbow_torque_peak_n_m": _peak(mot[f"drive_{elbow}"[:64]]["effort"]),
               "verification": {v["key"]: v["status"] for v in data["verification"]}}
    return doc, model, data, summary


# ------------------------------------------------------------------ 例子 3：细长推杆（模型文件）
L, D, E, G = 1000.0, 20.0, 206000.0, 79000.0
AREA, INERTIA = math.pi * D ** 2 / 4, math.pi * D ** 4 / 64
EI = E * 1e6 * INERTIA * 1e-12
PCR = math.pi ** 2 * EI / (L * 1e-3) ** 2
FRACTIONS = (-0.4, 0.0, 0.2, 0.4, 0.6)                  # 轴力 / 欧拉载荷；负的是拉力


def pushrod(force_n: float) -> dict:
    """两端铰支（面内）的钢推杆：根部转动副，端部转动副连滑块，滑块沿杆轴移动并受压力 force_n（N，正为压）"""
    return {"format": "mbd-model/1", "name": "细长推杆", "gravity_mm_s2": [0, 0, 0],
            "bodies": [{"id": "rod", "flex": {"type": "nonlinear_beam", "from_mm": [0, 0, 0], "to_mm": [L, 0, 0], "y_axis": [0, 1, 0],
                                              "youngs_modulus_mpa": E, "shear_modulus_mpa": G, "density_kg_m3": 7850,
                                              "area_mm2": AREA, "iyy_mm4": INERTIA, "izz_mm4": INERTIA, "ixx_mm4": 2 * INERTIA,
                                              "elements": 20, "fiber_y_mm": D / 2, "fiber_z_mm": D / 2}},
                       {"id": "slider", "mass_kg": 0.01, "cm_mm": [L, 0, 0], "inertia_kg_m2": {"ixx": 1e-6, "iyy": 1e-6, "izz": 1e-6}}],
            "joints": [{"id": "root", "type": "revolute", "body_i": "ground", "body_j": "rod", "point_mm": [0, 0, 0], "axis": [0, 0, 1]},
                       {"id": "tip", "type": "revolute", "body_i": "rod", "body_j": "slider", "point_mm": [L, 0, 0], "axis": [0, 0, 1]},
                       {"id": "guide", "type": "translational", "body_i": "ground", "body_j": "slider", "point_mm": [L, 0, 0],
                        "axis": [1, 0, 0]}],
            "forces": [{"id": "push", "type": "force", "body": "slider", "point_mm": [L, 0, 0], "fx_n": -force_n}],
            "analysis": {"type": "static_then_linear", "load_steps": 2}}


def example3(out: Path):
    import numpy as np

    from freecad_addon.core import mbd_study as ST

    rows, models = [], {}
    for frac in FRACTIONS:
        m = pushrod(round(frac * PCR, 1))
        d, _ = ST.run(copy.deepcopy(m))
        f1 = min(x["frequency_hz"] for x in d["linear"]["modes"] if x["frequency_hz"] > 1)
        rows.append({"force_n": round(frac * PCR, 1), "f1_hz": f1})
        models[frac] = (m, d)
    k, b = np.polyfit([r["force_n"] for r in rows], [r["f1_hz"] ** 2 for r in rows], 1)
    summary = {"euler_load_n": PCR, "rows": rows, "buckling_load_n": -b / k, "error": -b / k / PCR - 1,
               "f0_hz": math.sqrt(b), "f0_formula_hz": math.pi / 2 * math.sqrt(EI / (7850 * AREA * 1e-6)) / (L * 1e-3) ** 2}
    model, data = models[0.6]
    return None, model, data, summary


def pushrod_name(frac: float) -> str:
    """模型文件名：push60 = 压力 0.6 倍欧拉载荷，pull40 = 拉力 0.4 倍"""
    return f"pushrod-{'pull' if frac < 0 else 'push'}{abs(round(frac * 100)):02d}.json"


def _save_fcstd(doc, path: Path):
    doc.saveAs(str(path))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="问渠多体动力学入门例子")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", default="1,2,3")
    ap.add_argument("--samples", action="store_true", help="把 FreeCAD 文件、结果摘要、中英报告样张存进例子目录")
    a = ap.parse_args(argv)
    os.environ.setdefault("FAP_LLM_REPLAY", str(ROOT / "tests/recordings/mbd_mates"))
    os.environ.setdefault("FAP_AI_PROVIDER", "claude")
    from assist.fea_report import to_pdf
    from freecad_addon.core import mbd_study as ST

    a.out.mkdir(parents=True, exist_ok=True)
    runs = {1: example1, 2: example2, 3: example3}
    allsum = {}
    for n in [int(x) for x in a.only.split(",")]:
        doc, model, data, summary = runs[n](a.out)
        d = a.out / DIRS[n]
        d.mkdir(parents=True, exist_ok=True)
        if n == 3:
            for frac in FRACTIONS:
                (d / pushrod_name(frac)).write_text(
                    json.dumps(pushrod(round(frac * PCR, 1)), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (HERE / DIRS[n]).mkdir(exist_ok=True)
        for lang in ("zh", "en"):
            got = ST.write_report(model, data, d / f"report-{lang}", lang=lang)
            pdf = to_pdf(got["docx"])
            if a.samples and pdf:
                shutil.copyfile(pdf, HERE / DIRS[n] / f"sample-report.{lang}.pdf")
        (d / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
        if a.samples:
            (HERE / DIRS[n] / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str) + "\n",
                                                         encoding="utf-8")
            if n == 3:
                for frac in FRACTIONS:
                    name = pushrod_name(frac)
                    shutil.copyfile(d / name, HERE / DIRS[n] / name)
            if doc is not None:
                _save_fcstd(doc, HERE / DIRS[n] / {1: "slider-crank.FCStd", 2: "arm.FCStd"}[n])
        allsum[n] = summary
        print(f"例子 {n}：", json.dumps(summary, ensure_ascii=False, default=str)[:600], flush=True)
    (a.out / "summary.json").write_text(json.dumps(allsum, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    os._exit(rc)
