"""FEM 工作台里的三步：一句话起草、计算并核查、出报告（ADR-0093 补充十二第 3 步）。需要 FreeCAD，不需要界面。

界面（`freecad_addon/gui/fem_commands.py`）只管输入与显示，逻辑都在这里，便于测试：
- `draft_into`：选中的零件 + 一句话 → AI 起草、程序核对 → 在文档里建 FEM 分析（约束、载荷是 FEM 工作台的对象），追问、未采用的提议记在节点上；
- `confirm_analysis`：工程师确认（写确认人；追问须由人处理完）；
- `prepare_run` / `compute` / `finish_run`：读回算例 → 后台计算（带可信度核查，留下求解器文件）→ 结果进原生后处理；
- `make_report`：Word（与 PDF）报告，带审核清单与可追溯信息；算例在计算后改过就拒绝出报告，要先重算。

文档对象只能在界面线程里动：`compute` 不碰文档，可以放后台线程；其余在界面线程调用。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import FreeCAD

from freecad_addon.fc import fem_bridge as B


class FlowError(ValueError):
    pass


def work_dir(analysis) -> Path:
    """算例、结果、求解器文件、报告放在哪：文档存过盘就放在文档旁 <文档名>_fea/<分析名>/，否则放在 FreeCAD 用户目录下"""
    doc = analysis.Document
    if doc.FileName:
        base = Path(doc.FileName).with_suffix("")
        d = base.parent / f"{base.name}_fea" / analysis.Name
    else:
        d = Path(FreeCAD.getUserAppDataDir()) / "fap_fea" / doc.Name / analysis.Name
    d.mkdir(parents=True, exist_ok=True)
    return d


def part_step(obj, out_dir: Path) -> str:
    """零件对应的 STEP：零件是从 STEP 来的（FapStepPath）就用原文件；否则把形状导出成 STEP（面号由它定）"""
    p = getattr(obj, "FapStepPath", "") if "FapStepPath" in obj.PropertiesList else ""
    if p and Path(p).is_file():
        return p
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{obj.Name}.step"
    obj.Shape.exportStep(str(path))
    if "FapStepPath" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "FapStepPath", "Fap", "这个零件做有限元时用的 STEP 文件")
    obj.FapStepPath = str(path)
    return str(path)


def llm_client():
    """AI 客户端：设了 FAP_LLM_REPLAY（录制目录）就回放录制（演示、离线用，界面上会标明“回放”）；否则真实调用（要密钥）"""
    from ingest.llm_extract import AnthropicClient, RecordedClient

    replay = os.environ.get("FAP_LLM_REPLAY")
    return RecordedClient(Path(replay)) if replay else AnthropicClient()


def draft_steps(doc, statement: str, part_objs: list, tmp_dir: Path | None = None) -> list[str]:
    """起草前的准备（界面线程）：检查输入，零件对应的 STEP"""
    if not statement.strip():
        raise FlowError("先写一句话：零件、材料、怎么支承、受什么载荷、要算什么")
    if not part_objs:
        raise FlowError("先在三维视图或模型树里选中要算的零件")
    tmp = tmp_dir or Path(FreeCAD.getUserAppDataDir()) / "fap_fea" / doc.Name / "parts"
    return [part_step(o, tmp) for o in part_objs]


def draft_study(statement: str, steps: list[str], client) -> dict:
    """识别特征、AI 起草、程序核对（不碰文档，可在后台线程里调）"""
    from assist import fea_draft as D

    return D.draft(statement, steps, client)


def place_draft(doc, statement: str, part_objs: list, r: dict) -> dict:
    """把起草结果放进文档（界面线程）。返回 {"analysis", "questions", "rejected", "errors", "simulated", "replay"}"""
    study = r["study"]
    an = B.study_to_fem(doc, study, parts={b["id"]: part_objs[i] for i, b in enumerate(study["bodies"])})
    info = {"statement": statement, "questions": r["questions"], "rejected": r["rejected"], "errors": r["errors"],
            "simulated": r["simulated"], "replay": bool(os.environ.get("FAP_LLM_REPLAY")), "elapsed_s": r["elapsed_s"]}
    B._prop(an, "FapDraft", json.dumps(info, ensure_ascii=False))
    doc.recompute()
    return {"analysis": an, **info}


def draft_into(doc, statement: str, part_objs: list, client, tmp_dir: Path | None = None) -> dict:
    """三步合一（测试、脚本用）"""
    steps = draft_steps(doc, statement, part_objs, tmp_dir)
    return place_draft(doc, statement, part_objs, draft_study(statement, steps, client))


def confirm_analysis(analysis, by: str, questions_handled: bool) -> dict:
    """工程师确认。questions_handled：工程师声明追问都处理了（在 FEM 里补了约束 / 载荷，或判断不需要）"""
    from assist import fea_draft as D

    study, note = B.fem_to_study(analysis)
    if note["unsupported"]:
        raise FlowError("有对象本仓库算不了：" + "；".join(note["unsupported"]) + "（删掉或换成支持的约束再确认）")
    pv = study.get("provenance")
    if pv and pv.get("questions"):
        if not questions_handled:
            raise FlowError("还有追问没处理：" + "；".join(pv["questions"]))
        pv["questions"] = []
    try:
        s = D.confirm(study, by)
    except D.ConfirmRefused as e:
        raise FlowError(str(e)) from e
    B.commit(analysis, s, note["objects"])
    return s


def prepare_run(analysis) -> tuple[dict, Path]:
    """读回算例，核对能不能算。返回（算例, 工作目录）"""
    from analysis.fea.study import StudyInvalid, validate

    study, note = B.fem_to_study(analysis)
    if note["unsupported"]:
        raise FlowError("有对象本仓库算不了：" + "；".join(note["unsupported"]))
    try:
        validate(study)
    except StudyInvalid as e:
        raise FlowError(str(e)) from e
    return study, work_dir(analysis)


def compute(study: dict, wd: Path) -> dict:
    """计算（带可信度核查），可在后台线程里调；算例、结果写进工作目录"""
    from analysis.fea import run_study

    (wd / "study.json").write_text(json.dumps(study, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    res = run_study(study, keep_dir=str(wd / "solver"))
    (wd / "result.json").write_text(json.dumps(res, ensure_ascii=False) + "\n", encoding="utf-8")
    return res


def finish_run(analysis, result: dict, wd: Path) -> dict:
    """结果进原生后处理；旧的结果对象先删掉"""
    from freecad_addon.fc import fem_results

    doc = analysis.Document
    old = [o for o in analysis.Group if o.TypeId in ("Fem::FemResultObjectPython", "Fem::FemPostPipeline")]
    meshes = [o.Mesh for o in old if o.TypeId == "Fem::FemResultObjectPython" and o.Mesh]
    for o in old + [m for m in meshes if m not in old]:
        if doc.getObject(o.Name):
            doc.removeObject(o.Name)
    out = fem_results.results_to_fem(analysis, result, wd / "solver")
    B._prop(analysis, "FapWorkDir", str(wd))
    return out


def make_report(analysis, *, number: str | None, revision: str, reason: str, explain_client=None) -> dict:
    """出报告：用工作目录里这次计算的算例与结果；算例在计算后又改过（与 FEM 里现在的不一致）就拒绝，要先重算"""
    from assist import fea_report as R

    wd = Path(getattr(analysis, "FapWorkDir", "") or work_dir(analysis))
    sp, rp = wd / "study.json", wd / "result.json"
    if not rp.is_file():
        raise FlowError("还没有计算结果：先点“计算并核查”")
    study = json.loads(sp.read_text(encoding="utf-8"))
    result = json.loads(rp.read_text(encoding="utf-8"))
    now, _note = B.fem_to_study(analysis)
    if R.fingerprint(now) != R.fingerprint(study):
        raise FlowError("算例在计算之后改过：先重新“计算并核查”，再出报告")
    expl = R.explain(result, explain_client) if explain_client is not None else None
    try:
        got = R.build(study, result, wd / f"{study.get('name', 'fea')}-报告.docx", number=number, revision=revision,
                      reason=reason, explanation=expl, study_path=sp)
    except ValueError as e:
        raise FlowError(str(e)) from e
    pdf = R.to_pdf(Path(got["docx"]))
    return {"docx": str(got["docx"]), "pdf": str(pdf) if pdf else None, "ledger": str(got["ledger"]),
            "record": str(got["record"]), "explanation_rejected": (expl or {}).get("rejected", [])}
