"""问渠有限元 Windows 安装包的验收（ADR-0096 第 5 步）：用装好的 FreeCAD 自带 Python 运行。

    <安装目录>\\bin\\python.exe installer\\windows\\acceptance_fea.py <安装目录> <仓库目录>

代码一律来自安装目录（FreeCAD 启动时由 Mod 里的 InitGui 加载）；仓库只提供零件 STEP 和 AI 回复的录制（回放，不联网）。
1. 安装：版本是问渠有限元（验收用的测试版），没有零件库工作台，FEM 工作台的“求解”菜单有三个按钮和热分析 · 疲劳，
   “帮助”菜单有授权、设置、关于
2. 免费版：只用 FEM 工作台的工具手建的悬臂梁静力，选材料库材料接管后算完，挠度与 PL³/3EI 相差 < 3 %；
   AI 起草、正式报告、专业版算例（求解器设了几何非线性）拒绝并说明；欧拉压杆屈曲算两遍准确且相同
（起草、计算、报告在不开界面的子进程里做，见 core()）
3. 专业版：CI 临时生成测试密钥、签发授权，从“授权”对话框导入 → AI 一句话起草（录制回放）→ 确认 → 计算并核查
   → 出中文、英文两份 Word 报告，两份的结果指纹相同
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

STATEMENT = "肩关节空心轴 RJ-201，45 钢调质。Ø70 法兰那一端的端面固定，在 Ø42.75 花键段上加峰值扭矩 92.5 N·m。"


def hand_built(doc, solver_type: str, nonlinear: bool = False):
    """像用户那样只用 FEM 工作台的工具建分析：悬臂方梁 100×10×10，x = 0 面固定，x = 100 面受 100 N 的力（-z）"""
    import FreeCAD
    import ObjectsFem
    import Part

    box = doc.addObject("Part::Feature", "Beam")
    box.Shape = Part.makeBox(100, 10, 10)
    doc.recompute()
    faces = {round(f.CenterOfMass.x, 3): i + 1 for i, f in enumerate(box.Shape.Faces) if abs(f.normalAt(0, 0).x) > 0.99}
    an = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc)
    solver.AnalysisType = solver_type
    if nonlinear:
        solver.GeometricalNonlinearity = "nonlinear"
    an.addObject(solver)
    fix = ObjectsFem.makeConstraintFixed(doc, "Fixed")
    fix.References = [(box, f"Face{faces[0.0]}")]
    an.addObject(fix)
    force = ObjectsFem.makeConstraintForce(doc, "Force")
    force.References = [(box, f"Face{faces[100.0]}")]
    force.Force = FreeCAD.Units.Quantity("100 N")
    line = doc.addObject("Part::Line", "Dir")
    line.X1, line.Y1, line.Z1, line.X2, line.Y2, line.Z2 = 0, 0, 0, 0, 0, -10
    doc.recompute()
    force.Direction = (line, ["Edge1"])
    force.Reversed = False
    an.addObject(force)
    doc.recompute()
    return an


def pump(sec: float) -> None:
    from PySide import QtWidgets

    app = QtWidgets.QApplication.instance()
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def refused(fn, word: str) -> str | None:
    """fn() 要以说明里含 word 的 FlowError 拒绝；返回说明，没拒绝或说法不对返回 None"""
    from freecad_addon.fc import fem_flow as F

    try:
        fn()
    except F.FlowError as e:
        return str(e) if word in str(e) else None
    return None


def part(doc, step: Path):
    import Part

    s = Part.Shape()
    s.read(str(step))
    o = doc.addObject("Part::Feature", "RJ_201")
    o.Shape = s
    o.addProperty("App::PropertyString", "FapStepPath", "Fap", "")
    o.FapStepPath = str(step)
    doc.recompute()
    return o


def core(phase: str, app: Path, repo: Path, work: Path) -> dict:
    """文档里的工作（起草、计算、报告）在不开界面的 FreeCAD 进程里做：GitHub 的 Windows 机器没有 OpenGL，开着界面新建文档
    （三维视图）会崩（2026-11-17 CI 发现）。代码照样来自安装目录。返回 {"results", "checks"}"""
    sys.path.insert(0, str(app / "Mod" / "FreeCADAIParts" / "lib"))
    import FreeCAD

    from freecad_addon.fc import fem_flow as F

    R: dict[str, object] = {}
    ok: dict[str, bool] = {}
    step = repo / "examples/apps/out/cobot_joint/RJ-201.step"
    if phase == "free":
        # 免费版的主路径：只用 FEM 工作台自己的工具手建分析（不经 AI），选材料库材料接管，再“计算并核查”
        doc = FreeCAD.newDocument("wq_free")
        doc.saveAs(str(work / "free.FCStd"))
        p = part(doc, step)
        R["refuse_draft"] = refused(lambda: F.draft_steps(doc, STATEMENT, [p]), "专业版")
        an = hand_built(doc, "static")
        F.adopt(an, "45-QT")
        study, wd = F.prepare_run(an)
        study["mesh"] = {"size_mm": 2.5}
        t0 = time.time()
        res = F.compute(study, wd)
        R["free_compute_s"] = round(time.time() - t0, 1)
        R["free_status"], R["free_messages"] = res["status"], res.get("messages")
        from analysis.common import materials

        e = materials.get("45-QT")["elastic_modulus_mpa"]
        theory = 100 * 100 ** 3 / (3 * e * 10 * 10 ** 3 / 12)
        if res["status"] == "ok":
            F.finish_run(an, res, wd)
            R["free_trust"] = res["data"].get("trust_verdict")
            R["free_u_max_mm"] = res["data"]["steps"][0].get("u_max_mm")
            R["free_theory_mm"] = round(theory, 5)
        ok["free_static"] = res["status"] == "ok" and R.get("free_trust") in ("pass", "fail", "unknown") \
            and abs(R["free_u_max_mm"] / theory - 1) < 0.03
        R["refuse_report"] = refused(lambda: F.make_report(an, number=None, revision="A", reason="首次出稿"), "正式报告")
        an2 = hand_built(doc, "static", nonlinear=True)
        F.adopt(an2, "45-QT")
        R["refuse_pro_study"] = refused(lambda: F.prepare_run(an2), "大变形")
        ok["free_refusals"] = all(R[k] for k in ("refuse_draft", "refuse_report", "refuse_pro_study"))
        R["euler"] = euler(work)
        ok["buckling_repeatable"] = R["euler"]["ok"]
        return {"results": R, "checks": ok}

    doc2 = FreeCAD.newDocument("wq_pro")
    doc2.saveAs(str(work / "pro.FCStd"))
    p2 = part(doc2, step)
    out = F.draft_into(doc2, STATEMENT, [p2], F.llm_client(), tmp_dir=work / "parts")
    R["draft"] = {"questions": out["questions"], "rejected": out["rejected"], "errors": out["errors"], "replay": out["replay"]}
    ok["ai_draft"] = out["replay"] and not out["errors"] and not out["rejected"]
    F.confirm_analysis(out["analysis"], "CI 验收", True)
    study2, wd2 = F.prepare_run(out["analysis"])
    res2 = F.compute(study2, wd2)
    R["pro_status"], R["pro_messages"] = res2["status"], res2.get("messages")
    ok["pro_compute"] = res2["status"] == "ok"
    ok["reports"] = False
    if ok["pro_compute"]:
        F.finish_run(out["analysis"], res2, wd2)
        reps = {lang: F.make_report(out["analysis"], number="CI-1", revision="A", reason="CI 验收", lang=lang)
                for lang in ("zh", "en")}
        R["reports"] = {k: v["docx"] for k, v in reps.items()}
        fps = {k: json.loads(Path(v["record"]).read_text(encoding="utf-8"))["history"][-1]["result_fingerprint"]
               for k, v in reps.items()}
        R["result_fingerprints"] = fps
        ok["reports"] = all(Path(v["docx"]).is_file() and Path(v["docx"]).stat().st_size > 10000 for v in reps.values()) \
            and fps["zh"] == fps["en"]
    return {"results": R, "checks": ok}


def euler(work: Path) -> dict:
    """欧拉压杆（10×10×200 方截面，一端固定一端自由）算两遍：临界载荷与 π²EI/(4L²) 相差 < 1 %，两遍结果完全相同。
    Linux CI 上屈曲结果曾不可重复（issue #543），这里在用户会用的这套求解器上查一遍"""
    import gmsh

    import analysis
    from analysis.common import materials
    from analysis.fea.geometry import faces

    step = work / "col.step"
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("col")
    gmsh.model.occ.addBox(0, 0, 0, 10, 10, 200)
    gmsh.model.occ.synchronize()
    gmsh.write(str(step))
    gmsh.finalize()
    fs = faces(str(step))[0]

    def plane(z):
        return next(f["id"] for f in fs if f["kind"] == "plane" and abs(f["center"][2] - z) < 1e-6)

    st = {"format": "fea-study/1", "name": "euler", "bodies": [{"id": "c", "step_path": str(step), "material": "45-QT"}],
          "supports": [{"type": "fixed", "body": "c", "faces": [plane(0)]}],
          "loads": [{"type": "force", "body": "c", "faces": [plane(200)], "vector_n": [0, 0, -1000]}],
          "steps": [{"id": "b", "type": "buckling", "n_modes": 2}], "mesh": {"size_mm": 5.0}, "checks": {"convergence": False}}
    e = materials.get("45-QT")["elastic_modulus_mpa"]
    pcr = 3.141592653589793 ** 2 * e * (10 ** 4 / 12) / (4 * 200 ** 2)
    got = []
    for _ in range(2):
        r = analysis.run("fea", json.loads(json.dumps(st)))
        got.append(r["data"]["steps"][0]["load_factors"][0] * 1000 if r["status"] == "ok" else None)
    good = None not in got and got[0] == got[1] and abs(got[0] / pcr - 1) < 0.01
    return {"pcr_n": round(pcr, 1), "runs_n": got, "ok": good}


def run_core(phase: str, app: Path, repo: Path, work: Path) -> dict:
    import subprocess

    out = work / f"{phase}.json"
    p = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--core", phase, str(app), str(repo), str(work)],
                       env=dict(os.environ), timeout=3600, check=False)
    if not out.is_file():
        return {"results": {f"{phase}_exit": p.returncode}, "checks": {f"{phase}_ran": False}}
    return json.loads(out.read_text(encoding="utf-8"))


def main(app: Path, repo: Path) -> int:
    work = Path(tempfile.mkdtemp(prefix="wq-fea-acc-"))
    os.environ["FAP_LANG"] = "zh"                                   # 拒绝说明按中文核对；英文报告另出
    os.environ["FAP_LICENSE_FILE"] = str(work / "user" / "license.json")
    os.environ.pop("FAP_LICENSE_TEST_KEY", None)
    os.environ.pop("FAP_LLM_REPLAY", None)
    R: dict[str, object] = {}
    ok: dict[str, bool] = {}

    import FreeCADGui

    FreeCADGui.showMainWindow()

    import freecad_addon
    from assist import fea_edition
    from freecad_addon.gui import fea_brand

    lib = app / "Mod" / "FreeCADAIParts" / "lib"
    R["addon_file"] = freecad_addon.__file__
    ok["from_install_dir"] = str(Path(freecad_addon.__file__).resolve()).lower().startswith(str(lib.resolve()).lower())
    R["edition"] = fea_edition.info()
    ok["edition"] = R["edition"] == {"edition": "fea", "test_build": True}
    ok["no_parts_workbench"] = "AiPartsWorkbench" not in FreeCADGui.listWorkbenches()
    FreeCADGui.activateWorkbench("FemWorkbench")
    pump(1.0)
    menus = {a.text(): [x.text() for x in a.menu().actions()]
             for a in FreeCADGui.getMainWindow().menuBar().actions() if a.menu()}
    R["solve_menu"], R["help_menu"] = menus.get("&Solve"), menus.get("&Help")
    ok["menus"] = {"一句话起草（AI）", "计算并核查", "出报告", "热分析 · 疲劳"} <= set(menus.get("&Solve") or []) \
        and {"问渠有限元：授权…", "问渠有限元：设置 AI 密钥…", "关于问渠有限元"} <= set(menus.get("&Help") or [])

    # 2. 免费版
    ok["free_tier"] = not fea_edition.pro_allowed() and "免费版" in fea_brand.tier_text()
    got = run_core("free", app, repo, work)
    R.update(got["results"])
    ok.update(got["checks"])

    # 3. 专业版：测试密钥签发、从授权对话框导入
    from licensing.issue import keygen
    from licensing.license import sign

    priv, pub = keygen()
    today = dt.datetime.now().astimezone().date()
    lic = sign({"id": "CI-ACC", "key_id": "test-ci", "licensee": "CI 验收", "issued": today.isoformat(),
                "expires": (today + dt.timedelta(days=7)).isoformat(), "kind": "floating", "seats": 1,
                "features": [fea_edition.PRO]}, priv)
    lic_file = work / "ci.license.json"
    lic_file.write_text(json.dumps(lic, ensure_ascii=False), encoding="utf-8")
    os.environ["FAP_LICENSE_TEST_KEY"] = f"test-ci:{pub}"
    ok["license_import"] = fea_brand.LicenseDialog().import_file(str(lic_file)) and fea_edition.pro_allowed()
    R["tier"] = fea_brand.tier_text()
    os.environ["FAP_LLM_REPLAY"] = str(repo / "tests/recordings/fea_draft")
    os.environ["FAP_AI_PROVIDER"] = "claude"
    got = run_core("pro", app, repo, work)
    R.update(got["results"])
    ok.update(got["checks"])

    print(json.dumps({"results": R, "checks": ok}, ensure_ascii=False, indent=2, default=str))
    passed = all(ok.values())
    print("验收通过" if passed else "验收不通过：" + "、".join(k for k, v in ok.items() if not v))
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        if sys.argv[1] == "--core":
            phase, app_dir, repo_dir, work_dir = sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5])
            got = core(phase, app_dir, repo_dir, work_dir)
            (work_dir / f"{phase}.json").write_text(json.dumps(got, ensure_ascii=False, default=str), encoding="utf-8")
            rc = 0
        else:
            rc = main(Path(sys.argv[1]), Path(sys.argv[2]))
    except Exception:  # noqa: BLE001 — 验收脚本：把错误打印出来再判不通过
        traceback.print_exc()
        rc = 1
    sys.stdout.flush()
    os._exit(rc)                             # 不等 Qt 拆界面（拆的时候可能崩，退出码就不对了）
