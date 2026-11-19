"""问渠CAM Windows 安装包的验收（ADR-0104 产品化第 3 步）：用装好的 FreeCAD 自带 Python 运行。

    <安装目录>\\bin\\python.exe installer\\windows\\acceptance_cam.py <安装目录> <仓库目录>

代码一律来自安装目录（FreeCAD 启动时由 Mod 里的 InitGui 加载）。
1. 安装：版本是问渠CAM（验收用的测试版），没有零件库工作台；有“问渠CAM”工作台，菜单里有数控编程、检查 G 代码、授权、设置、关于
2. 免费版：装好的入门例子 1（阶梯轴）从 STEP 读轮廓、规则起草、整机仿真、出 FANUC 程序，时间与样张一致；
   例子 2（块）走 FreeCAD CAM 出 FANUC 程序；西门子后处理、AI 起草、工艺卡拒绝并说明
3. 专业版：CI 临时生成测试密钥、签发授权，从“授权”对话框导入 → 西门子、广数程序出得来，回读与仿真一致；中英工艺卡出得来
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


def pump(sec: float) -> None:
    from PySide import QtWidgets

    app = QtWidgets.QApplication.instance()
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def refused(fn, word: str) -> str | None:
    from assist import cam_edition

    try:
        fn()
    except cam_edition.NeedsPro as e:
        return str(e) if word in str(e) else None
    return None


def core(phase: str, app: Path, repo: Path, work: Path) -> dict:
    """文档里的工作在不开界面的 FreeCAD 进程里做（GitHub 的 Windows 机器没有 OpenGL）。返回 {"results", "checks"}"""
    import FreeCAD  # noqa: F401

    ex = app / "examples"
    sys.path.insert(0, str(repo / "examples" / "wenquest-cam"))
    import build_examples as B  # 安装目录的例子里不带 .py：例子的零件构造从仓库借（它导入时把仓库根放进 sys.path）
    sys.path.insert(0, str(app / "Mod" / "FreeCADAIParts" / "lib"))   # 再把安装目录放到最前：问渠CAM 的代码一律来自安装目录
    from freecad_addon import core as _core
    ok_src = str(Path(_core.__file__).resolve()).lower().startswith(str((app / "Mod").resolve()).lower())

    from freecad_addon.core import cam_study as S

    R: dict[str, object] = {}
    ok: dict[str, bool] = {f"{phase}_code_from_install_dir": ok_src}
    _ft, d1, r1 = B.example1()
    sample = json.loads((ex / "01-shaft-turning/results.json").read_text(encoding="utf-8"))
    R["ex1_total_s"] = r1["data"]["total_time_s"]
    ok["ex1_matches_sample"] = abs(r1["data"]["total_time_s"] - sample["total_time_s"]) < 0.05 \
        and all(p.get("release") for p in r1["data"]["programs"])
    _plan, _d2, r2 = B.example2()
    ok["ex2_released"] = bool(r2["data"]["programs"][0].get("release"))
    if phase == "free":
        R["refuse_post"] = refused(lambda: S.run({**d1["setup"], "post": "siemens"}), "FANUC 以外的后处理")
        R["refuse_ai"] = refused(lambda: S.draft(d1["setup"], client=object()), "AI 起草工艺")
        R["refuse_card"] = refused(lambda: S.save(r1, work / "free-out", draft_doc=d1, pdf=False), "工艺卡")
        ok["free_refusals"] = all(R[k] for k in ("refuse_post", "refuse_ai", "refuse_card"))
        files = S.save(r1, work / "free-nc", draft_doc=None)
        ok["free_saves_nc"] = len([f for f in files if f.suffix == ".nc"]) == 2
        return {"results": R, "checks": ok}
    for ctl in ("siemens", "gsk"):
        r = S.run({**d1["setup"], "post": ctl})
        ok[f"pro_{ctl}"] = all(p.get("release") and p["release"]["controller"] == ctl for p in r["data"]["programs"])
    files = S.save(r1, work / "pro-zh", draft_doc=d1, lang="zh", pdf=False) + S.save(r1, work / "pro-en", draft_doc=d1, lang="en", pdf=False)
    cards = [f for f in files if f.suffix == ".docx"]
    R["cards"] = [str(f) for f in cards]
    ok["pro_cards"] = len(cards) == 2 and all(f.stat().st_size > 10000 for f in cards)
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
    work = Path(tempfile.mkdtemp(prefix="wq-cam-acc-"))
    os.environ["FAP_LANG"] = "zh"
    os.environ["FAP_LICENSE_FILE"] = str(work / "user" / "license.json")
    os.environ.pop("FAP_LICENSE_TEST_KEY", None)
    R: dict[str, object] = {}
    ok: dict[str, bool] = {}

    import FreeCADGui

    FreeCADGui.showMainWindow()

    import freecad_addon
    from assist import cam_edition, fea_edition
    from freecad_addon.gui import cam_brand, fea_brand

    lib = app / "Mod" / "FreeCADAIParts" / "lib"
    R["addon_file"] = freecad_addon.__file__
    ok["from_install_dir"] = str(Path(freecad_addon.__file__).resolve()).lower().startswith(str(lib.resolve()).lower())
    R["edition"] = fea_edition.info()
    ok["edition"] = R["edition"] == {"edition": "cam", "test_build": True}
    wbs = FreeCADGui.listWorkbenches()
    ok["workbenches"] = "AiPartsWorkbench" not in wbs and cam_brand.WORKBENCH in wbs
    FreeCADGui.activateWorkbench(cam_brand.WORKBENCH)
    pump(2.0)
    menus = {a.text(): [x.text() for x in a.menu().actions()]
             for a in FreeCADGui.getMainWindow().menuBar().actions() if a.menu()}
    R["cam_menu"] = menus.get("问渠CAM")
    ok["menus"] = {"数控编程", "检查 G 代码…", "授权…", "设置 AI 密钥…", "关于问渠CAM"} <= set(R["cam_menu"] or [])

    ok["free_tier"] = not cam_edition.pro_allowed() and "免费版" in cam_brand.tier_text()
    got = run_core("free", app, repo, work)
    R.update(got["results"])
    ok.update({f"free_{k}" if not k.startswith("free") else k: v for k, v in got["checks"].items()})

    from licensing.issue import keygen
    from licensing.license import sign

    priv, pub = keygen()
    today = dt.datetime.now().astimezone().date()
    lic = sign({"id": "CI-ACC", "key_id": "test-ci", "licensee": "CI 验收", "issued": today.isoformat(),
                "expires": (today + dt.timedelta(days=7)).isoformat(), "kind": "floating", "seats": 1,
                "features": [cam_edition.PRO]}, priv)
    lic_file = work / "ci.license.json"
    lic_file.write_text(json.dumps(lic, ensure_ascii=False), encoding="utf-8")
    os.environ["FAP_LICENSE_TEST_KEY"] = f"test-ci:{pub}"
    ok["license_import"] = fea_brand.LicenseDialog(None, cam_brand.Product).import_file(str(lic_file)) and cam_edition.pro_allowed()
    R["tier"] = cam_brand.tier_text()
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
    os._exit(rc)
