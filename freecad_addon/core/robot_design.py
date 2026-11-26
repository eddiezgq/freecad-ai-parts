"""问渠 CAD「AI 设计整机」面板背后的逻辑（ADR-0115 44.4）：不依赖 FreeCAD 界面，普通 pytest 可测。

- run：需求原话 → 六步（构型 → 选件 → 三维装配 → 复核多体动力学 → 支架有限元 → 报告与 BOM），和 `assist.robot_case` 同一套步骤，
  结果写到临时目录（不写仓库里的 examples/）；某步失败就停在那一步，前面各步的结果照样能看。
- 回放示例：需求原话与案例 A 的 `requirement.txt` 一字不差才回放录制；支架有限元按指纹复用案例已算的结果，指纹不一样的现算。
- 不做有限元：这一步记“没做”，报告里支架强度是待确认，不是通过。
- 页签内容取报告（`assist.robot_report`）的各节，面板不另算。
- 案例 B（龙门取放，ADR-0115 44.5.5 第三步之二）：构型全是移动关节时，后面换成龙门的五步（选件与节拍 → 三维装配与复核 →
  门架有限元 → 报告与 BOM，`assist.gantry_*`）；回放示例时门架有限元按指纹复用案例 B 已算的结果。
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
GANTRY_CASE = ROOT / "examples" / "robots" / "sewing-loader"
GANTRY_NAME = "缝纫车间裁片上下料机器人"
GANTRY_STEPS = ("构型（AI 提、代码初筛）", "选件与节拍多体动力学（代码）", "三维装配与复核选件（代码）", "门架有限元（代码）",
                "报告与 BOM（代码）")
EXAMPLES = {EXAMPLE_NAME: ("arm", CASE), GANTRY_NAME: ("gantry", GANTRY_CASE)}
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
GANTRY_TABS = (("条件", ("需求原话",)), ("构型", ("1 整机方案",)),
               ("校核", ("节拍", "选件", "抓手", "重复定位精度", "三维装配")),
               ("仿真", ("3 仿真数字与需求逐条对照", "门架有限元")),
               ("BOM", ("4 三维模型与 BOM",)), ("用时与卡点", ("5 用时", "6 卡在哪里")))
GANTRY_RESULT_FILES = ("concept-result.json", "build-result.json", "cad-result.json", "timing.json", "bom.json", "bom.csv",
                       "report.md")


class ConfirmError(ValueError):
    pass


def example_text(name: str = EXAMPLE_NAME) -> str:
    """示例原话；Windows 上 git 检出可能是 \\r\\n，录制按 \\n 录的，统一成 \\n"""
    return (EXAMPLES[name][1] / "requirement.txt").read_text(encoding="utf-8").replace("\r\n", "\n")


def which_example(statement: str) -> str | None:
    """和哪个示例的原话一字不差（只有一字不差才回放录制）；都不是就 None"""
    s = statement.replace("\r\n", "\n").strip()
    return next((n for n in EXAMPLES if s == example_text(n).strip()), None)


def is_example(statement: str) -> bool:
    return which_example(statement) is not None


def is_gantry(concept) -> bool:
    """构型的关节全是移动关节：走龙门的步骤（案例 B）"""
    js = (concept or {}).get("joints") or []
    return bool(js) and all(j.get("type") == "prismatic" for j in js)


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


def gantry_reuse() -> dict | None:
    """案例 B 已算的门架有限元（带指纹）"""
    p = GANTRY_CASE / "out" / "cad-result.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8")).get("frame_fea")


def _status(x) -> str:
    return x if x in ("pass", "unknown", "fail") else "unknown"


def _read(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _tail(text: str, n: int = 3) -> str:
    lines = [x.strip() for x in text.splitlines() if x.strip() and not x.lstrip().startswith(("*", "\x1b"))]
    return "；".join(lines[-n:])


def run(statement: str, client, *, replay: bool = False, out_dir: str | Path | None = None, do_fea: bool = True,
        progress=None, reuse=None, steps: dict | None = None, clock=time.perf_counter,
        fea_log: str | Path | None = None, kind: str | None = None) -> dict:
    """依次跑各步（机械臂六步；构型全是移动关节时换成龙门的五步）。progress(步骤表, 说明, 已做, 总数) 每有变化就回调
    （步骤表是 [{step, who, status, seconds, note}]）。steps：测试替换某几步的实现（{步名: 函数(out_dir) -> (状态, 说明)}）；
    kind：测试时直接指定 "arm" / "gantry"，不指定就按 AI 采用的构型定；fea_log：本机有限元用时记录（面板显示预计用时）。
    返回 {out_dir, steps, status, stopped_at, replay, do_fea, kind}"""
    from assist import robot_design, robot_report

    statement = statement.replace("\r\n", "\n")
    case = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="wq-robot-"))
    o = case / "out"
    (o / "cad").mkdir(parents=True, exist_ok=True)
    (case / "requirement.txt").write_text(statement, encoding="utf-8")
    ex = which_example(statement) if replay else None
    guess = kind or (EXAMPLES[ex][0] if ex else "arm")
    if ex == EXAMPLE_NAME:
        for f in CASE_FILES:
            if (CASE / f).exists():
                shutil.copy(CASE / f, case / f)
        if (CASE / "out" / "thin-result.json").exists():
            shutil.copy(CASE / "out" / "thin-result.json", o / "thin-result.json")
        if reuse is None:
            reuse = example_reuse()
    elif ex == GANTRY_NAME and reuse is None:
        reuse = gantry_reuse()
    who0 = "AI（回放录制）+ 代码" if replay else "AI（真实调用）+ 代码"

    def rows(names, start=0):
        return [{"step": n, "who": who0 if k + start == 0 else "代码", "status": "waiting", "seconds": None, "note": ""}
                for k, n in enumerate(names[start:], start)]

    table = rows(GANTRY_STEPS if guess == "gantry" else STEPS)
    state = {"kind": guess}

    def tell(text, done=None, total=None):
        if progress is not None:
            progress([dict(r) for r in table], text, done, total)

    cr, br, cad, vr = o / "concept-result.json", o / "build-result.json", o / "cad", o / "verify-result.json"
    plates = case / "plates.json"

    def screen_then_build(concept, cond):
        """龙门构型初筛通过就采用（选件是下一步 assist.gantry_build，同 --screen-only）；机械臂照旧做选件与装配校核"""
        from assist.robot_build import build_check

        if is_gantry(concept):
            return {"ok": True, "items": [], "summary": "龙门：选件在下一步"}
        return build_check(concept, cond)

    def s_concept(_):
        model = getattr(client, "model", None) or robot_design.DEFAULT_MODEL
        after = None if (kind == "gantry" or ex == GANTRY_NAME) else screen_then_build
        res = robot_design.design(statement, client, model=model, after_screen=after)
        cr.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if res.get("status") != "pass":
            miss = "；".join((res.get("missing") or []) + (res.get("rejected") or []))
            return "fail", f"构型循环没有通过（{len(res.get('rounds') or [])} 轮）" + (f"：{miss}" if miss else "")
        if kind is None:
            state["kind"] = "gantry" if is_gantry(res["chosen"]) else "arm"
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

    # ---- 龙门（案例 B）
    gcad = o / "cad-result.json"

    def g_build(_):
        from assist import gantry_build

        r = via_main(gantry_build.main, [str(cr), "-o", str(br)], br)
        if r[0] != "fail":
            b = _read(br)
            r = (r[0], "；".join(f"{j} 选 {p.get('model')}" for j, p in b["picks"].items())
                 + f"；抓手 {(b.get('gripper') or {}).get('model')}；节拍 {(b.get('cycle_time') or {}).get('total_s')} s")
        return r

    def g_cad(_):
        from assist import gantry_cad

        res = gantry_cad.run(_read(cr), _read(br), o, fea=False)
        gcad.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if res.get("status") == "fail" and "cad" not in res:
            return "fail", res.get("note") or "复核选件没通过"
        c, rv = res["cad"], res["reverify"]
        same = "与上一步相同" if all(rv["same_as_step1"].values()) else "与上一步不同"
        return _status(res["status"]), (f"{len(c['parts'])} 个零件，干涉 {len(c['interferences'])} 处，进取放区 {len(c['keepout_hits'])} 处；"
                                        f"按真实质量复核选件{same}")

    def g_fea(_):
        from assist import gantry_cad

        if not do_fea:
            return "skipped", "没勾“做门架有限元”：放料定位精度待确认"
        res, c, b = _read(gcad), _read(cr), _read(br)
        tell("门架有限元：两层网格")
        gantry_cad.add_fea(res, c.get("conditions") or {}, b["cycle"], o, reuse=reuse if isinstance(reuse, dict) else None)
        gcad.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        fr, jd = res["frame_fea"], res["judge"]
        note = f"跨中变形 {fr['result']['u_pad_abs_mm']:g} mm，一阶 {fr['result']['freqs_hz'][0]:.3g} Hz"
        if fr.get("reused"):
            note += "；回放：用案例已算的有限元结果"
        return _status(jd["deflection"]["status"]), note

    def g_report(_):
        from assist import gantry_report

        gantry_report.write(o)
        return "pass", "report.md、bom.csv、bom.json" + ("、comparison.md" if (o / "comparison.md").exists() else "")

    impls = {"arm": dict(zip(STEPS, (s_concept, s_build, s_cad, s_verify, s_fea, s_report))),
             "gantry": dict(zip(GANTRY_STEPS, (s_concept, g_build, g_cad, g_fea, g_report)))}
    for v in impls.values():
        v.update(steps or {})
    timing = {"format": "robot-timing/1", "date": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
              "machine": _machine(), "ai": "回放录制" if replay else f"真实调用（{getattr(client, 'model', None) or '缺省'}）",
              "steps": [], "status": "pass"}
    stopped = None
    k = 0
    while k < len(table):
        row = table[k]
        name = row["step"]
        row["status"] = "running"
        tell(name)
        t0 = clock()
        try:
            st, note = impls[state["kind"]][name](case)
        except Exception as exc:  # noqa: BLE001 — 写明停在哪一步、为什么
            st, note = "fail", f"{type(exc).__name__}：{exc}"
        row.update(status=st, seconds=round(clock() - t0, 1), note=note)
        timing["steps"].append({"step": name, "who": row["who"], "seconds": row["seconds"], "exit_code": int(st == "fail")}
                               | ({"note": note} if st == "skipped" else {}))
        if k == 0 and st != "fail":                    # 构型定了：后面按机械臂还是龙门的步骤走
            names = GANTRY_STEPS if state["kind"] == "gantry" else STEPS
            if [r["step"] for r in table[1:]] != list(names[1:]):
                table[1:] = rows(names, 1)
        if st == "fail":
            stopped = name
            timing["status"] = "fail"
            timing["stopped_at"] = name
        (o / "timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tell(name)
        if stopped:
            break
        k += 1
    if not stopped and (o / "report.md").exists():
        if state["kind"] == "gantry":                  # 用时表补上“报告与 BOM”这一步
            from assist import gantry_report

            gantry_report.write(o)
        else:
            robot_report.write(o)
    sts = {r["status"] for r in table}
    status = "fail" if stopped else "unknown" if sts & {"unknown", "skipped"} else "pass"
    return {"out_dir": str(case), "steps": table, "status": status, "stopped_at": stopped, "replay": replay, "do_fea": do_fea,
            "kind": state["kind"]}


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


def tabs(out_dir: str | Path, kind: str = "arm") -> list[tuple[str, str]]:
    """[(页签名, Markdown)]；报告还没出时，用已有的结果文件说明到了哪一步。页签名两种整机一样，取报告里的哪几节不同"""
    spec = GANTRY_TABS if kind == "gantry" else TABS
    p = Path(out_dir) / "out" / "report.md"
    if not p.exists():
        return [(t, "") for t, _ in spec]
    sec = sections(p.read_text(encoding="utf-8"))
    return [(t, "\n\n".join(sec[k] for k in keys if k in sec)) for t, keys in spec]


def cad_result(run_out: dict) -> Path:
    """三维装配的结果文件：机械臂在 out/cad/，龙门在 out/"""
    o = Path(run_out["out_dir"]) / "out"
    return o / "cad-result.json" if run_out.get("kind") == "gantry" else o / "cad" / "cad-result.json"


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
    names = GANTRY_RESULT_FILES + ("comparison.md",) if run_out.get("kind") == "gantry" else RESULT_FILES
    files = [("cad/assembly.step", "整机三维装配（STEP）")] + [(f, f) for f in names]
    docs = []
    for f, what in files:
        if (o / f).exists():
            docs.append(enterprise_lib.register_document(o / f, f"{drawing_no} {name} {what}（AI 设计整机，{enterprise}）", actor))
    return docs
