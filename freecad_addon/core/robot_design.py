"""问渠 CAD「AI 设计整机」面板背后的逻辑（ADR-0115 44.4）：不依赖 FreeCAD 界面，普通 pytest 可测。

- run：需求原话 → 六步（构型 → 选件 → 三维装配 → 复核多体动力学 → 支架有限元 → 报告与 BOM），和 `assist.robot_case` 同一套步骤，
  结果写到临时目录（不写仓库里的 examples/）；某步失败就停在那一步，前面各步的结果照样能看。
- 回放示例：需求原话与案例 A 的 `requirement.txt` 一字不差才回放录制；支架有限元按指纹复用案例已算的结果，指纹不一样的现算。
- 不做有限元：这一步记“没做”，报告里支架强度是待确认，不是通过。
- 页签内容取报告（`assist.robot_report`）的各节，面板不另算。
- confirm：人确认后把装配 STEP、报告、BOM、各步结果登记为企业资料；录制回放的示例不入库。

显示的文字照旧写中文，按界面语言在显示时翻（assist.i18n.tr）；报告正文这一步只出中文。
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import io
import json
import shutil
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "examples" / "robots" / "teaching-arm"
EXAMPLE_NAME = "教学桌面机械臂"
STEPS = ("构型（AI 提、代码初筛）", "选件（代码）", "三维装配（代码）", "复核多体动力学（代码）", "支架有限元（代码）", "报告与 BOM（代码）")
STATUS = {"waiting": "等待", "running": "进行中", "pass": "通过", "unknown": "待确认", "fail": "不通过", "skipped": "没做"}
COLORS = {"pass": "#1b7f3b", "unknown": "#a26b00", "fail": "#b3261e", "skipped": "#a26b00", "running": "#1f5fbf", "waiting": "#777"}
# 报告的哪几节放进哪个页签（报告的二级、三级标题）
TABS = (("条件", ("需求原话",)), ("构型", ("1 整机方案",)),
        ("校核", ("选件", "杆件强度", "关节与支架装得下", "三维装配")),
        ("仿真", ("3 仿真数字与需求逐条对照", "支架强度有限元")),
        ("BOM", ("4 三维模型与 BOM",)), ("用时与卡点", ("5 用时", "6 卡在哪里")))
CASE_FILES = ("plates.json",)                 # 回放示例时一起带上的案例文件（第 9 步定的板厚）
RESULT_FILES = ("concept-result.json", "build-result.json", "cad/cad-result.json", "verify-result.json", "fea-result.json",
                "timing.json", "bom.json", "bom.csv", "report.md")


class ConfirmError(ValueError):
    pass


def example_text() -> str:
    """示例原话；Windows 上 git 检出可能是 \\r\\n，录制按 \\n 录的，统一成 \\n"""
    return (CASE / "requirement.txt").read_text(encoding="utf-8").replace("\r\n", "\n")


def is_example(statement: str) -> bool:
    return statement.replace("\r\n", "\n").strip() == example_text().strip()


def example_client():
    """没有密钥时用的录制回放（只对示例原话有效）"""
    from assist import robot_design
    from ingest.llm_extract import RecordedClient

    c = RecordedClient(robot_design.RECORDINGS_DIR)
    c.model = robot_design.DEFAULT_MODEL
    return c


def example_reuse() -> dict:
    """案例 A 已算的支架有限元：{指纹: 结果项}"""
    p = CASE / "out" / "fea-result.json"
    if not p.exists():
        return {}
    return {i["fingerprint"]: i for i in json.loads(p.read_text(encoding="utf-8"))["items"] if i.get("fingerprint")}


def _status(x) -> str:
    return x if x in ("pass", "unknown", "fail") else "unknown"


def _read(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _tail(text: str, n: int = 3) -> str:
    lines = [x.strip() for x in text.splitlines() if x.strip() and not x.lstrip().startswith(("*", "\x1b"))]
    return "；".join(lines[-n:])


def run(statement: str, client, *, replay: bool = False, out_dir: str | Path | None = None, do_fea: bool = True,
        progress=None, reuse: dict | None = None, steps: dict | None = None, clock=time.perf_counter,
        fea_log: str | Path | None = None) -> dict:
    """依次跑六步。progress(步骤表, 说明, 已做, 总数) 每有变化就回调（步骤表是 [{step, who, status, seconds, note}]）。
    steps：测试替换某几步的实现（{步名: 函数(out_dir) -> (状态, 说明)}）；fea_log：本机有限元用时记录（面板显示预计用时）。返回 {out_dir, steps, status, stopped_at, replay, do_fea}"""
    from assist import robot_design, robot_report

    statement = statement.replace("\r\n", "\n")
    case = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="wq-robot-"))
    o = case / "out"
    (o / "cad").mkdir(parents=True, exist_ok=True)
    (case / "requirement.txt").write_text(statement, encoding="utf-8")
    if replay:
        for f in CASE_FILES:
            if (CASE / f).exists():
                shutil.copy(CASE / f, case / f)
        if (CASE / "out" / "thin-result.json").exists():
            shutil.copy(CASE / "out" / "thin-result.json", o / "thin-result.json")
        if reuse is None:
            reuse = example_reuse()
    who0 = "AI（回放录制）+ 代码" if replay else "AI（真实调用）+ 代码"
    table = [{"step": s, "who": who0 if k == 0 else "代码", "status": "waiting", "seconds": None, "note": ""}
             for k, s in enumerate(STEPS)]

    def tell(text, done=None, total=None):
        if progress is not None:
            progress([dict(r) for r in table], text, done, total)

    cr, br, cad, vr = o / "concept-result.json", o / "build-result.json", o / "cad", o / "verify-result.json"
    plates = case / "plates.json"

    def s_concept(_):
        from assist.robot_build import build_check

        model = getattr(client, "model", None) or robot_design.DEFAULT_MODEL
        res = robot_design.design(statement, client, model=model, after_screen=build_check)
        cr.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if res.get("status") != "pass":
            miss = "；".join((res.get("missing") or []) + (res.get("rejected") or []))
            return "fail", f"构型循环没有通过（{len(res.get('rounds') or [])} 轮）" + (f"：{miss}" if miss else "")
        return "pass", f"{len(res['rounds'])} 轮；采用第 {res['chosen_round']} 轮的“{res['chosen'].get('name')}”"

    def via_main(fn, argv, result):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(err):
            rc = fn(argv)
        if rc:
            return "fail", _tail(err.getvalue()) or f"退出码 {rc}"
        r = _read(result)
        return _status(r.get("status")), _tail(err.getvalue(), 1)

    def s_build(_):
        from assist import robot_build

        r = via_main(robot_build.main, [str(cr), "-o", str(br)], br)
        if r[0] != "fail":
            b = _read(br)
            r = (r[0], "；".join(f"{'、'.join(v.get('joints') or [])} 选 {'、'.join(v['components'])}" for v in b["picks"].values())
                 + f"（{len(b['rounds'])} 轮收敛）")
        return r

    def s_cad(_):
        from assist import robot_cad

        r = via_main(robot_cad.main, [str(cr), str(br), "-o", str(cad)] + (["--plates", str(plates)] if plates.exists() else []),
                     cad / "cad-result.json")
        if r[0] != "fail":
            c = _read(cad / "cad-result.json")
            r = (r[0], f"{len(c['parts'])} 个零件，整机 {c['mass_kg']} kg，干涉 {len(c['interferences'])} 处")
        return r

    def s_verify(_):
        from assist import robot_verify

        r = via_main(robot_verify.main, [str(cr), str(br), str(cad / "cad-result.json"), "-o", str(vr)], vr)
        if r[0] != "fail":
            v = _read(vr)
            r = (r[0], f"会动的部分 {v.get('moving_mass_kg')} kg；按真实零件重算力矩、重新校核所选模组"
                 + ("（有待确认项，见“仿真”页签）" if r[0] == "unknown" else ""))
        return r

    def s_fea(_):
        from assist import robot_fea

        if not do_fea:
            return "skipped", "没勾“做支架有限元”：支架强度待确认"
        c = _read(cr)
        counted = {"reused": 0}

        def started(k, n, name):
            tell(f"支架有限元：{name}", k, n)

        def finished(item):
            counted["reused"] += bool(item.get("reused"))
            counted["computed"] = counted.get("computed", 0) + (not item.get("reused") and "load" in item)

        t0 = clock()

        r = robot_fea.analyse(c["chosen"], _read(br), _read(cad / "cad-result.json"), _read(vr), cad / "assembly.step",
                              float(c["conditions"]["payload"]), on_start=started, on_item=finished, reuse=reuse)
        (o / "fea-result.json").write_text(json.dumps(r, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if fea_log and counted.get("computed"):
            record_fea_time(fea_log, clock() - t0, counted["computed"], len(r["items"]))
        n = len(r["items"])
        note = f"{n} 个支架" + (f"；回放：{counted['reused']} 个用案例已算的有限元结果" if counted["reused"] else "")
        return _status(r["status"]), note

    def s_report(_):
        robot_report.write(o)
        return "pass", "report.md、bom.csv、bom.json"

    impl = dict(zip(STEPS, (s_concept, s_build, s_cad, s_verify, s_fea, s_report)))
    impl.update(steps or {})
    timing = {"format": "robot-timing/1", "date": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
              "machine": _machine(), "ai": "回放录制" if replay else f"真实调用（{getattr(client, 'model', None) or '缺省'}）",
              "steps": [], "status": "pass"}
    stopped = None
    for row in table:
        name = row["step"]
        row["status"] = "running"
        tell(name)
        t0 = clock()
        try:
            st, note = impl[name](case)
        except Exception as exc:  # noqa: BLE001 — 写明停在哪一步、为什么
            st, note = "fail", f"{type(exc).__name__}：{exc}"
        row.update(status=st, seconds=round(clock() - t0, 1), note=note)
        timing["steps"].append({"step": name, "who": row["who"], "seconds": row["seconds"], "exit_code": int(st == "fail")}
                               | ({"note": note} if st == "skipped" else {}))
        if st == "fail":
            stopped = name
            timing["status"] = "fail"
            timing["stopped_at"] = name
        (o / "timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tell(name)
        if stopped:
            break
    if not stopped and (o / "report.md").exists():
        robot_report.write(o)                  # 用时表补上“报告与 BOM”这一步
    sts = {r["status"] for r in table}
    status = "fail" if stopped else "unknown" if sts & {"unknown", "skipped"} else "pass"
    return {"out_dir": str(case), "steps": table, "status": status, "stopped_at": stopped, "replay": replay, "do_fea": do_fea}


def record_fea_time(path: str | Path, seconds: float, computed: int, brackets: int) -> None:
    """记下本机这次现算的有限元：每个支架平均用时、共几个支架"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"seconds_per_bracket": round(seconds / computed, 1), "brackets": brackets,
                             "date": _dt.datetime.now().astimezone().date().isoformat()}, ensure_ascii=False), encoding="utf-8")


def fea_estimate(path: str | Path | None) -> str:
    """“做支架有限元”旁边的预计用时：按本机上一次的记录；没有记录就不写数"""
    try:
        r = json.loads(Path(path).read_text(encoding="utf-8"))
        per, n = float(r["seconds_per_bracket"]), int(r["brackets"])
    except (OSError, ValueError, KeyError, TypeError):
        return "本机还没有现算过，用时不知道（案例 A 在 2 核的机器上约 2 小时）"
    return f"本机上次每个支架约 {per / 60:.0f} 分钟，{n} 个支架约 {per * n / 60:.0f} 分钟"


def _machine() -> str:
    from assist.robot_case import machine

    return machine()


# ---------------------------------------------------------------- 页签（报告的各节，Markdown）


def sections(md: str) -> dict[str, str]:
    """报告按二级、三级标题切开：{标题: 本节文字（含标题，到下一个同级或更高一级标题为止）}"""
    lines = md.splitlines()
    heads = [(i, len(x) - len(x.lstrip("#")), x.lstrip("#").strip()) for i, x in enumerate(lines) if x.startswith(("## ", "### "))]
    out = {}
    for k, (i, lvl, title) in enumerate(heads):
        end = next((j for j, lv, _ in heads[k + 1:] if lv <= lvl), len(lines))
        key = title.split("（")[0].strip()
        out.setdefault(key, "\n".join(lines[i:end]).strip())
    return out


def tabs(out_dir: str | Path) -> list[tuple[str, str]]:
    """[(页签名, Markdown)]；报告还没出时，用已有的结果文件说明到了哪一步"""
    p = Path(out_dir) / "out" / "report.md"
    if not p.exists():
        return [(t, "") for t, _ in TABS]
    sec = sections(p.read_text(encoding="utf-8"))
    return [(t, "\n\n".join(sec[k] for k in keys if k in sec)) for t, keys in TABS]


def steps_html(table: list[dict]) -> str:
    from html import escape

    from assist.i18n import tr as T

    rows = []
    for r in table:
        sec = "" if r["seconds"] is None else f"{r['seconds']:.1f} s"
        rows.append(f"<tr><td>{escape(T(r['step']))}</td><td>{escape(T(r['who']))}</td>"
                    f"<td style='color:{COLORS.get(r['status'], '#000')}'>{escape(T(STATUS.get(r['status'], r['status'])))}</td>"
                    f"<td>{sec}</td><td>{escape(T(r['note']) if r['note'] else '')}</td></tr>")
    head = "".join(f"<th>{escape(T(h))}</th>" for h in ("步骤", "谁做", "结论", "用时", "说明"))
    return f"<table border='1' cellspacing='0' cellpadding='3'><tr>{head}</tr>{''.join(rows)}</table>"


# ---------------------------------------------------------------- 确认入企业库


def confirm(enterprise_lib, run_out: dict, *, drawing_no: str, name: str, enterprise: str, actor: str) -> list[dict]:
    """人确认后入企业库：装配 STEP、报告、BOM 与各步结果登记为企业资料（带 SHA-256）。自制件这一步不逐个建组件。返回登记的资料"""
    drawing_no, name, enterprise, actor = (x.strip() for x in (drawing_no, name, enterprise, actor))
    if not drawing_no or not actor or not enterprise:
        raise ConfirmError("图号、企业、确认人都要填")
    if run_out.get("replay"):
        raise ConfirmError("这是录制回放的示例，不入企业库")
    if run_out.get("stopped_at") or run_out.get("status") == "fail":
        raise ConfirmError("没有跑完或有不通过的项，不能入库")
    o = Path(run_out["out_dir"]) / "out"
    files = [("cad/assembly.step", "整机三维装配（STEP）")] + [(f, f) for f in RESULT_FILES]
    docs = []
    for f, what in files:
        if (o / f).exists():
            docs.append(enterprise_lib.register_document(o / f, f"{drawing_no} {name} {what}（AI 设计整机，{enterprise}）", actor))
    return docs
