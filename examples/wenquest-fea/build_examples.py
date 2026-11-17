"""问渠有限元的三个入门例子（ADR-0096 第 6 步）：在 FreeCAD 里从头走到结果和报告。不开界面，可在测试和 CI 里跑。

    <FreeCAD 的 python> examples/wenquest-fea/build_examples.py --out 目录 [--only 1,2,3] [--samples]
    （出样张时用 --out /tmp/WenQuest-FEA-examples：报告里记的零件路径就是这个目录）

1. 免费版 · 关节壳体 J2-HSG：只用 FEM 工作台的工具手建分析（底面固定、Ø110 减速器座受径向力），选材料库材料接管，计算并核查。
2. 专业版 · 肩关节空心轴 RJ-201：一句话起草（扭矩）→ 处理追问、确认 → 计算并核查 → 中英报告。
3. 专业版 · 大臂 ARM-UPPER：一句话起草（肘部扭矩）→ 处理追问、确认 → 计算并核查 → 中英报告。

例子 2、3 的 AI 回复用仓库里真实模型的录制回放（tests/recordings/fea_draft，不联网）；用户自己跑时用自己的 AI 密钥。
--samples：把例子 1 的 FreeCAD 文件（建好分析、没有结果）存进例子目录，把三个例子的中英报告 PDF 存成样张
（例子 1 的报告是专业版才出的，样张给免费版用户看专业版多了什么）。
载荷是演示用的示例工况，不是零件的规格参数。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXAMPLES = {
    1: {"dir": "01-j2-housing-free", "step": "J2-HSG.step", "material": "6061-T6"},
    2: {"dir": "02-rj201-shaft-sentence", "step": "RJ-201.step",
        "statement": "肩关节空心轴 RJ-201，45 钢调质。Ø70 法兰那一端的端面固定，在 Ø42.75 花键段上加峰值扭矩 92.5 N·m。"},
    3: {"dir": "03-arm-upper-sentence", "step": "ARM-UPPER.step",
        "statement": "大臂 ARM-UPPER，6061-T6。肩部 Ø138 减速器座固定；肘部 Ø107 减速器座上加 j3 峰值扭矩 46.4 N·m。"},
}
EX1_FORCE_N = 2000.0          # 例子 1 的示例载荷：减速器座受 2000 N 径向力（+x）


def _part(doc, step: Path, name: str):
    import Part

    s = Part.Shape()
    s.read(str(step))
    o = doc.addObject("Part::Feature", name)
    o.Shape = s
    doc.recompute()
    return o


def hand_built_j2(doc, step: Path):
    """例子 1：像用户那样只用 FEM 工作台的工具建分析。面按几何找：底面（z = 0）固定；Ø110 孔面受 +x 方向的力"""
    import FreeCAD
    import ObjectsFem

    part = _part(doc, step, "J2_HSG")
    faces = part.Shape.Faces
    bottom = next(i + 1 for i, f in enumerate(faces) if f.Surface.__class__.__name__ == "Plane"
                  and abs(f.CenterOfMass.z) < 1e-6)
    bore = next(i + 1 for i, f in enumerate(faces) if f.Surface.__class__.__name__ == "Cylinder"
                and abs(f.Surface.Radius - 55.0) < 1e-6)
    an = ObjectsFem.makeAnalysis(doc, "Analysis")
    an.Label = "J2-HSG"
    an.addObject(ObjectsFem.makeSolverCalculiXCcxTools(doc))
    fix = ObjectsFem.makeConstraintFixed(doc, "Fixed")
    fix.References = [(part, f"Face{bottom}")]
    an.addObject(fix)
    force = ObjectsFem.makeConstraintForce(doc, "Force")
    force.References = [(part, f"Face{bore}")]
    force.Force = FreeCAD.Units.Quantity(f"{EX1_FORCE_N} N")
    line = doc.addObject("Part::Line", "ForceDirection")
    line.X1, line.Y1, line.Z1, line.X2, line.Y2, line.Z2 = 0, 0, 45, 30, 0, 45
    line.Visibility = False
    doc.recompute()
    force.Direction = (line, ["Edge1"])
    force.Reversed = False
    an.addObject(force)
    doc.recompute()
    return an


def _show(doc, types: tuple, hide: tuple = ()) -> None:
    for o in doc.Objects:
        if "Visibility" not in o.PropertiesList:
            continue
        if o.TypeId.startswith(types):
            o.Visibility = True
        elif hide and o.TypeId.startswith(hide):
            o.Visibility = False


def _summary(res: dict) -> dict:
    d = res.get("data") or {}
    st = (d.get("steps") or [{}])[0]
    return {"status": res["status"], "trust": d.get("trust_verdict"), "u_max_mm": st.get("u_max_mm"),
            "vm_max_mpa": st.get("vm_max_mpa"), "safety_factor": st.get("safety_factor"), "messages": res.get("messages")}


def _reports(F, an, n: int, d: Path, samples: bool) -> dict:
    reps = {}
    for lang in ("zh", "en"):
        rep = F.make_report(an, number=f"EX-{n}", revision="A",
                            reason="入门例子" if lang == "zh" else "Getting-started example", lang=lang)
        reps[lang] = rep["docx"]
        if samples and rep["pdf"]:
            shutil.copyfile(rep["pdf"], d / f"sample-report.{lang}.pdf")
    return reps


def run(n: int, out: Path, samples: bool) -> dict:
    import FreeCAD

    from freecad_addon.fc import fem_flow as F

    ex = EXAMPLES[n]
    d = HERE / ex["dir"]
    work = out / ex["dir"]
    work.mkdir(parents=True, exist_ok=True)
    step = work / ex["step"]                              # 零件复制到输出目录：报告里记的是这里的路径
    shutil.copyfile(d / ex["step"], step)
    doc = FreeCAD.newDocument(f"ex{n}")
    t0 = time.time()
    if n == 1:
        an = hand_built_j2(doc, step)
        _show(doc, ("Part::Feature", "Fem::Constraint"))   # 不开界面存的文件里对象默认不显示：打开就要看得见零件和约束
        if samples:
            doc.saveAs(str(d / "J2-HSG.FCStd"))           # 给用户打开的文件：分析建好、没有结果、还没接管
            for bak in d.glob("*.FCBak"):
                bak.unlink()
        doc.saveAs(str(work / "J2-HSG.FCStd"))
        F.adopt(an, ex["material"])
        study, wd = F.prepare_run(an)
        res = F.compute(study, wd)
        out_ = {"example": n, **_summary(res)}
        if res["status"] == "ok":
            F.finish_run(an, res, wd)
            _show(doc, ("Fem::FemPostPipeline",), hide=("Part::Feature", "Fem::Constraint"))
            doc.save()
            out_["reports"] = _reports(F, an, n, d, samples)        # 专业版才出报告；样张给免费版用户看专业版多了什么
    else:
        doc.saveAs(str(work / f"{step.stem}.FCStd"))
        p = _part(doc, step, step.stem.replace("-", "_"))
        p.addProperty("App::PropertyString", "FapStepPath", "Fap", "")
        p.FapStepPath = str(step)                         # 用原 STEP 识别特征（与录制时同一个文件）
        r = F.draft_into(doc, ex["statement"], [p], F.llm_client(), tmp_dir=work / "parts")
        out_ = {"example": n, "questions": r["questions"], "rejected": r["rejected"], "errors": r["errors"],
                "replay": r["replay"]}
        F.confirm_analysis(r["analysis"], "示例 / Example", True)
        study, wd = F.prepare_run(r["analysis"])
        res = F.compute(study, wd)
        out_.update(_summary(res))
        if res["status"] == "ok":
            F.finish_run(r["analysis"], res, wd)
            doc.save()
            out_["reports"] = _reports(F, r["analysis"], n, d, samples)
    out_["seconds"] = round(time.time() - t0, 1)
    FreeCAD.closeDocument(doc.Name)
    return out_


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", default="1,2,3")
    ap.add_argument("--samples", action="store_true", help="存例子 1 的 FreeCAD 文件与例子 2、3 的报告样张（进仓库）")
    a = ap.parse_args(argv)
    os.environ.setdefault("FAP_LLM_REPLAY", str(ROOT / "tests/recordings/fea_draft"))
    os.environ.setdefault("FAP_AI_PROVIDER", "claude")
    a.out.mkdir(parents=True, exist_ok=True)
    got = [run(int(n), a.out.resolve(), a.samples) for n in a.only.split(",")]
    (a.out / "examples.json").write_text(json.dumps(got, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(got, ensure_ascii=False, indent=1, default=str))
    return 0 if all(g["status"] == "ok" for g in got) else 1


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    os._exit(rc)
