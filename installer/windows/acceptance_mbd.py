"""问渠多体动力学 Windows 安装包的验收（ADR-0102 第 4 步）：用装好的 FreeCAD 自带 Python 运行。

    <安装目录>\\bin\\python.exe installer\\windows\\acceptance_mbd.py <安装目录> <仓库目录>

代码一律来自安装目录（FreeCAD 启动时由 Mod 里的 InitGui 加载）；仓库只提供挑线机构 STEP、模型样例和 AI 回答的录制（回放，不联网）。
1. 安装：版本是问渠多体动力学（验收用的测试版），没有零件库工作台；有“问渠多体动力学”工作台，菜单里有装配体多体动力学、授权、设置、关于
2. 免费版：导入挑线机构 STEP，规则起草 4 个转动副，建装配、给钢材，上轴 600 rpm 算运动学，约束残差核查通过；
   曲柄滑块样例（模型文件）照算；装好的入门例子 1 打开就能算、与样张数字一致；AI 挑运动副、柔性体、线性化、正式报告拒绝并说明
3. 专业版：CI 临时生成测试密钥、签发授权，从“授权”对话框导入 → AI 挑运动副（录制回放）收全 4 个、机架选机壳
   → 铝杆摆设成实体柔性体（gmsh + CalculiX 缩减）算动力学，有应力 → 出中文、英文两份 Word 报告，两份的结果指纹相同
（文档里的工作在不开界面的子进程里做，见 core()）
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

STEEL = "06ae5c92-de7b-46c9-984d-4dd87964bc5c"          # FreeCAD 材料库的钢（Steel-C15，同 tests/test_fc_mbd_study.py）


def pump(sec: float) -> None:
    from PySide import QtWidgets

    app = QtWidgets.QApplication.instance()
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def refused(fn, word: str) -> str | None:
    """fn() 要以说明里含 word 的 NeedsPro 拒绝；返回说明，没拒绝或说法不对返回 None"""
    from assist import mbd_edition

    try:
        fn()
    except mbd_edition.NeedsPro as e:
        return str(e) if word in str(e) else None
    return None


def fixture(repo: Path, name: str) -> dict:
    d = json.loads((repo / "tests/fixtures/mbd-model/valid" / name).read_text(encoding="utf-8"))
    return d.get("instance", d)


def takeup(doc, step: Path, client=None):
    """导入挑线机构 STEP、起草运动副、建装配、给钢材 → (零件, 草稿, 装配)"""
    import Materials

    from freecad_addon.core import mbd_study as ST

    objs, _parts, found, draft = ST.draft_from_step(str(step), doc, client)
    asm = ST.build(doc, objs, found, draft["accept"], draft["ground"])
    mat = Materials.MaterialManager().getMaterial(STEEL)
    for o in objs:
        o.ShapeMaterial = mat
    doc.recompute()
    return objs, draft, asm


def kinematic(objs, asm):
    from freecad_addon.core import mbd_study as ST

    lab = {o.Name: o.Label for o in objs}
    model0, _ = ST.make_model(asm, [], {"type": "kinematic"})
    drive = next(j["id"] for j in model0["joints"] if j["body_i"] == "ground" and lab.get(j["body_j"]) == "上轴挑线曲柄")
    model, _ = ST.make_model(asm, [{"joint": drive, "kind": "speed", "value": 600}],
                             {"type": "kinematic", "end_time_s": 0.1, "output_steps": 20})
    data, _ = ST.run(model)
    return model, data


def residual_ok(data) -> bool:
    v = [x for x in data["verification"] if x["key"] == "constraint_residual"]
    return bool(v) and all(x["status"] == "pass" for x in v)


def flex_bar(doc):
    """6061-T6 铝杆 200×10×10，一端 φ6 孔挂转动副（摆），设成实体柔性体（同 tests/test_fc_mbd_flex.py）"""
    import FreeCAD as App
    import Part

    from freecad_addon.fc import mbd_flex as MF

    s = Part.makeBox(200, 10, 10, App.Vector(-10, -5, -5)).cut(Part.makeCylinder(3, 10, App.Vector(0, 0, -5)))
    o = doc.addObject("Part::Feature", "Bar")
    o.Shape = s
    doc.recompute()
    model = {"format": "mbd-model/1", "name": "柔性摆", "gravity_mm_s2": [0, -9810, 0],
             "analysis": {"type": "dynamic", "end_time_s": 0.01, "output_steps": 10},
             "bodies": [{"id": "Bar", "mass_kg": 1.0, "cm_mm": [90, 0, 0], "inertia_kg_m2": [[1e-4, 0, 0], [0, 1e-3, 0], [0, 0, 1e-3]],
                         "source": "FreeCAD Bar，验收"}],
             "joints": [{"id": "pin", "type": "revolute", "body_i": "ground", "body_j": "Bar", "point_mm": [0, 0, 0],
                         "axis": [0, 0, 1]}]}
    MF.make_flexible(model, {"Bar": o}, {"Bar": {"material": "6061-T6", "size_mm": 5}})
    return model


def example1(app: Path) -> dict:
    """装好的入门例子 1（ADR-0102 第 5 步）：打开 slider-crank.FCStd，用文档里的装配体，曲柄 1200 rpm 算运动学；
    驱动力矩峰值与例子目录里的 results.json 相差 < 1e-6"""
    import FreeCAD

    from freecad_addon.core import mbd_study as ST
    from freecad_addon.fc import mbd_assembly as MA

    ex = app / "examples" / "01-slider-crank-free"
    doc = FreeCAD.openDocument(str(ex / "slider-crank.FCStd"))
    asm = MA.find_assembly(doc)
    lab = {o.Name: o.Label for o in doc.Objects}
    m0, _ = ST.make_model(asm, [], {"type": "kinematic"})
    drive = next(j["id"] for j in m0["joints"] if j["body_i"] == "ground" and lab.get(j["body_j"]) == "曲柄")
    model, _ = ST.make_model(asm, [{"joint": drive, "kind": "speed", "value": 1200}],
                             {"type": "kinematic", "end_time_s": 0.05, "output_steps": 200})
    data, _ = ST.run(model)
    peak = max(abs(x) for m in data["motions"].values() for x in m["effort"])
    ref = json.loads((ex / "results.json").read_text(encoding="utf-8"))["drive_torque_peak_n_m"]
    return {"peak_n_m": peak, "reference_n_m": ref, "ok": residual_ok(data) and abs(peak / ref - 1) < 1e-6}


def core(phase: str, app: Path, repo: Path, work: Path) -> dict:
    """文档里的工作在不开界面的 FreeCAD 进程里做：GitHub 的 Windows 机器没有 OpenGL，开着界面新建文档会崩（问渠有限元验收发现）。
    代码照样来自安装目录。返回 {"results", "checks"}"""
    sys.path.insert(0, str(app / "Mod" / "FreeCADAIParts" / "lib"))
    import FreeCAD

    from assist.mbd_mates import FakeClient
    from freecad_addon.core import mbd_study as ST

    R: dict[str, object] = {}
    ok: dict[str, bool] = {}
    step = repo / "tests/fixtures/mbd-step/takeup.step"
    if phase == "free":
        doc = FreeCAD.newDocument("wq_free")
        R["refuse_ai"] = refused(lambda: ST.draft_from_step(str(step), doc, FakeClient({})), "AI 帮着挑运动副")
        objs, draft, asm = takeup(doc, step)
        R["free_draft"] = {"by": draft["by"], "joints": len(draft["accept"])}
        t0 = time.time()
        model, data = kinematic(objs, asm)
        R["free_compute_s"] = round(time.time() - t0, 1)
        R["free_drive_max"] = max(abs(x) for m in data["motions"].values() for x in m["effort"])
        ok["free_kinematic"] = len(draft["accept"]) == 4 and residual_ok(data)
        sc, _ = ST.run(fixture(repo, "slider_crank_all_d1.json"))
        ok["free_slider_crank"] = residual_ok(sc)
        R["example1"] = example1(app)
        ok["free_example1"] = R["example1"]["ok"]
        lin = dict(model, analysis={"type": "static_then_linear"})
        R["refuse_flex"] = refused(lambda: ST.run(fixture(repo, "d6_flex_pendulum.json")), "柔性体")
        R["refuse_linear"] = refused(lambda: ST.run(lin), "线性化与模态")
        R["refuse_report"] = refused(lambda: ST.write_report(model, data, work / "free-rep"), "正式报告")
        ok["free_refusals"] = all(R[k] for k in ("refuse_ai", "refuse_flex", "refuse_linear", "refuse_report")) \
            and not (work / "free-rep").exists()
        return {"results": R, "checks": ok}

    from freecad_addon.fc import fem_flow as F

    doc = FreeCAD.newDocument("wq_pro")
    objs, draft, asm = takeup(doc, step, F.llm_client())
    R["ai_draft"] = {k: draft[k] for k in ("by", "ground", "notes")} | {"joints": [a["name"] for a in draft["accept"]]}
    ok["ai_draft"] = draft["by"].startswith("AI") and not draft["notes"] and len(draft["accept"]) == 4 \
        and draft["ground"] == "Part__Feature"
    _, data = kinematic(objs, asm)
    ok["ai_assembly_runs"] = residual_ok(data)
    doc2 = FreeCAD.newDocument("wq_flex")
    t0 = time.time()
    model = flex_bar(doc2)
    data, _ = ST.run(model)
    R["flex_s"] = round(time.time() - t0, 1)
    R["flex_peak_mpa"] = data["flex"]["Bar"]["stress"]["peak_mpa"]
    ok["flex_pendulum"] = R["flex_peak_mpa"] > 0
    reps = {lang: ST.write_report(model, data, work / f"rep-{lang}", lang=lang) for lang in ("zh", "en")}
    R["reports"] = {k: str(v["docx"]) for k, v in reps.items()}
    fps = {k: json.loads(Path(v["record"]).read_text(encoding="utf-8"))["history"][-1]["result_fingerprint"] for k, v in reps.items()}
    R["result_fingerprints"] = fps
    ok["reports"] = all(Path(v["docx"]).is_file() and Path(v["docx"]).stat().st_size > 10000 for v in reps.values()) \
        and fps["zh"] == fps["en"]
    return {"results": R, "checks": ok}


def run_core(phase: str, app: Path, repo: Path, work: Path) -> dict:
    import subprocess

    out = work / f"{phase}.json"
    p = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--core", phase, str(app), str(repo), str(work)],
                       env=dict(os.environ), timeout=3600, check=False)
    if not out.is_file():
        return {"results": {f"{phase}_exit": p.returncode}, "checks": {f"{phase}_ran": False}}
    return json.loads(out.read_text(encoding="utf-8"))


def main(app: Path, repo: Path) -> int:
    work = Path(tempfile.mkdtemp(prefix="wq-mbd-acc-"))
    os.environ["FAP_LANG"] = "zh"                                   # 拒绝说明按中文核对；英文报告另出
    os.environ["FAP_LICENSE_FILE"] = str(work / "user" / "license.json")
    os.environ.pop("FAP_LICENSE_TEST_KEY", None)
    os.environ.pop("FAP_LLM_REPLAY", None)
    R: dict[str, object] = {}
    ok: dict[str, bool] = {}

    import FreeCADGui

    FreeCADGui.showMainWindow()

    import freecad_addon
    from assist import fea_edition, mbd_edition
    from freecad_addon.gui import fea_brand, mbd_brand

    lib = app / "Mod" / "FreeCADAIParts" / "lib"
    R["addon_file"] = freecad_addon.__file__
    ok["from_install_dir"] = str(Path(freecad_addon.__file__).resolve()).lower().startswith(str(lib.resolve()).lower())
    R["edition"] = fea_edition.info()
    ok["edition"] = R["edition"] == {"edition": "mbd", "test_build": True}
    wbs = FreeCADGui.listWorkbenches()
    ok["workbenches"] = "AiPartsWorkbench" not in wbs and mbd_brand.WORKBENCH in wbs
    FreeCADGui.activateWorkbench(mbd_brand.WORKBENCH)
    pump(1.0)
    menus = {a.text(): [x.text() for x in a.menu().actions()]
             for a in FreeCADGui.getMainWindow().menuBar().actions() if a.menu()}
    R["mbd_menu"] = menus.get("问渠多体动力学")
    ok["menus"] = {"装配体多体动力学", "授权…", "设置 AI 密钥…", "关于问渠多体动力学"} <= set(R["mbd_menu"] or [])

    # 2. 免费版
    ok["free_tier"] = not mbd_edition.pro_allowed() and "免费版" in mbd_brand.tier_text()
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
                "features": [mbd_edition.PRO]}, priv)
    lic_file = work / "ci.license.json"
    lic_file.write_text(json.dumps(lic, ensure_ascii=False), encoding="utf-8")
    os.environ["FAP_LICENSE_TEST_KEY"] = f"test-ci:{pub}"
    ok["license_import"] = fea_brand.LicenseDialog(None, mbd_brand.Product).import_file(str(lic_file)) and mbd_edition.pro_allowed()
    R["tier"] = mbd_brand.tier_text()
    os.environ["FAP_LLM_REPLAY"] = str(repo / "tests/recordings/mbd_mates")
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
