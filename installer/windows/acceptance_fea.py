"""问渠有限元 Windows 安装包的验收（ADR-0096 第 5 步）：用装好的 FreeCAD 自带 Python 运行。

    <安装目录>\\bin\\python.exe installer\\windows\\acceptance_fea.py <安装目录> <仓库目录>

代码一律来自安装目录（FreeCAD 启动时由 Mod 里的 InitGui 加载）；仓库只提供零件 STEP 和 AI 回复的录制（回放，不联网）。
1. 安装：版本是问渠有限元（验收用的测试版），没有零件库工作台，FEM 工作台的“求解”菜单有三个按钮和热分析 · 疲劳，
   “帮助”菜单有授权、设置、关于
2. 免费版：手建的单实体静力（RJ-201 端面固定、花键段扭矩）能算完，可信度核查有结论；AI 起草、正式报告、专业版算例
   （大变形）拒绝并说明
3. 专业版：CI 临时生成测试密钥、签发授权，从“授权”对话框导入 → AI 一句话起草（录制回放）→ 确认 → 计算并核查
   → 出中文、英文两份 Word 报告，两份的结果指纹相同
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

STATEMENT = "肩关节空心轴 RJ-201，45 钢调质。Ø70 法兰那一端的端面固定，在 Ø42.75 花键段上加峰值扭矩 92.5 N·m。"


def free_study(step: Path) -> dict:
    """工程师在 FEM 里手建的算例（与 AI 无关）：同 RJ-201 起草样例的面号"""
    return {"format": "fea-study/1", "name": "RJ-201-free",
            "bodies": [{"id": "b1", "step_path": str(step), "material": "45-QT"}],
            "supports": [{"type": "fixed", "body": "b1", "faces": [3]}],
            "loads": [{"type": "torque", "body": "b1", "faces": [8], "value_nm": 92.5,
                       "axis": {"origin_mm": [0.0, 0.0, 76.453], "dir": [0.0, 0.0, 1.0]}}],
            "steps": [{"id": "s1", "type": "static"}]}


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


def main(app: Path, repo: Path) -> int:
    work = Path(tempfile.mkdtemp(prefix="wq-fea-acc-"))
    os.environ["FAP_LANG"] = "zh"                                   # 拒绝说明按中文核对；英文报告另出
    os.environ["FAP_LICENSE_FILE"] = str(work / "user" / "license.json")
    os.environ.pop("FAP_LICENSE_TEST_KEY", None)
    os.environ.pop("FAP_LLM_REPLAY", None)
    R: dict[str, object] = {}
    ok: dict[str, bool] = {}

    import FreeCAD
    import FreeCADGui

    FreeCADGui.showMainWindow()

    import freecad_addon
    from assist import fea_edition
    from freecad_addon.fc import fem_bridge as B
    from freecad_addon.fc import fem_flow as F
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
    ok["menus"] = {"一句话起草（AI）", "计算并核查（零件库）", "出报告（零件库）", "热分析 · 疲劳"} <= set(menus.get("&Solve") or []) \
        and {"问渠有限元：授权…", "问渠有限元：设置 AI 密钥…", "关于问渠有限元"} <= set(menus.get("&Help") or [])

    # 2. 免费版
    step = repo / "examples/apps/out/cobot_joint/RJ-201.step"
    doc = FreeCAD.newDocument("wq_free")
    doc.saveAs(str(work / "free.FCStd"))
    p = part(doc, step)
    ok["free_tier"] = not fea_edition.pro_allowed() and "免费版" in fea_brand.tier_text()
    R["refuse_draft"] = refused(lambda: F.draft_steps(doc, STATEMENT, [p]), "专业版")
    an = B.study_to_fem(doc, free_study(step), parts={"b1": p})
    study, wd = F.prepare_run(an)
    t0 = time.time()
    res = F.compute(study, wd)
    R["free_compute_s"] = round(time.time() - t0, 1)
    R["free_status"], R["free_messages"] = res["status"], res.get("messages")
    if res["status"] == "ok":
        F.finish_run(an, res, wd)
        R["free_trust"] = res["data"].get("trust_verdict")
        R["free_vm_max_mpa"] = (res["data"].get("steps") or [{}])[0].get("vm_max_mpa")
    ok["free_static"] = res["status"] == "ok" and R.get("free_trust") in ("pass", "fail", "unknown")
    R["refuse_report"] = refused(lambda: F.make_report(an, number=None, revision="A", reason="首次出稿"), "正式报告")
    pro_study = copy.deepcopy(free_study(step))
    pro_study["steps"] = [{"id": "s1", "type": "static", "large_deformation": True}]
    an2 = B.study_to_fem(doc, pro_study, parts={"b1": p})
    R["refuse_pro_study"] = refused(lambda: F.prepare_run(an2), "大变形")
    ok["free_refusals"] = all(R[k] for k in ("refuse_draft", "refuse_report", "refuse_pro_study"))

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
    else:
        ok["reports"] = False

    print(json.dumps({"results": R, "checks": ok}, ensure_ascii=False, indent=2, default=str))
    passed = all(ok.values())
    print("验收通过" if passed else "验收不通过：" + "、".join(k for k, v in ok.items() if not v))
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        rc = main(Path(sys.argv[1]), Path(sys.argv[2]))
    except Exception:  # noqa: BLE001 — 验收脚本：把错误打印出来再判不通过
        traceback.print_exc()
        rc = 1
    sys.stdout.flush()
    os._exit(rc)                             # 不等 Qt 拆界面（拆的时候可能崩，退出码就不对了）
