"""整机案例一条命令从需求跑到结果（ADR-0115 44.3 之二第 7 步）。

需求原话 → AI 出构型（回放录制，或真实调用）→ 选件 → 三维装配 → 复核多体动力学 → 支架有限元 → 报告与 BOM。
每步实测用时写进 `out/timing.json`（连同本机核数、内存），报告第 5 节用它。

    python -m assist.robot_case examples/robots/teaching-arm --replay tests/recordings/robot_design
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

STEPS = ("构型（AI 提、代码初筛）", "选件（代码）", "三维装配（代码）", "复核多体动力学（代码）", "支架有限元（代码）", "报告与 BOM（代码）")


def machine() -> str:
    cores = os.cpu_count()
    try:
        mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
        return f"{cores} 核、内存 {mem:.1f} GB"
    except (ValueError, OSError, AttributeError):
        return f"{cores} 核"


def plan(case_dir: Path, replay: Path | None, provider: str | None) -> list[tuple[str, str, Callable[[], int]]]:
    from assist import robot_build, robot_cad, robot_design, robot_fea, robot_report, robot_verify

    o = case_dir / "out"
    cr, br, cad, vr = o / "concept-result.json", o / "build-result.json", o / "cad", o / "verify-result.json"
    design = [str(case_dir / "requirement.txt"), "-o", str(cr)]
    design += ["--replay", str(replay)] if replay else (["--provider", provider] if provider else [])
    who = "AI（回放录制）+ 代码" if replay else "AI（真实调用）+ 代码"
    pp = case_dir / "plates.json"                        # 减薄定下的板厚（第 9 步）；没有就按设计缺省值
    plates = ["--plates", str(pp)] if pp.exists() else []
    return [
        (STEPS[0], who, lambda: robot_design.main(design)),
        (STEPS[1], "代码", lambda: robot_build.main([str(cr), "-o", str(br)])),
        (STEPS[2], "代码", lambda: robot_cad.main([str(cr), str(br), "-o", str(cad)] + plates)),
        (STEPS[3], "代码", lambda: robot_verify.main([str(cr), str(br), str(cad / "cad-result.json"), "-o", str(vr)])),
        (STEPS[4], "代码", lambda: robot_fea.main([str(o), "-o", str(o / "fea-result.json")])),
        (STEPS[5], "代码", lambda: robot_report.main([str(o)])),
    ]


def run(case_dir: str | Path, *, replay: str | Path | None = None, provider: str | None = None,
        steps=None, clock=time.perf_counter, ai: str | None = None) -> dict:
    """依次跑各步；某步失败就停在那一步（结果如实写进 timing.json），不往下跑。
    steps 给了就按它跑（案例 B 的 assist.gantry_case 用），ai 是 timing.json 里“AI 怎么来的”那一项。"""
    case_dir = Path(case_dir)
    (case_dir / "out").mkdir(exist_ok=True)
    timing = {"format": "robot-timing/1", "date": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
              "machine": machine(), "ai": ai or (f"回放 {replay}" if replay else f"真实调用（{provider or '缺省'}）"),
              "steps": [], "status": "pass"}
    path = case_dir / "out" / "timing.json"
    for name, who, fn in steps if steps is not None else plan(case_dir, Path(replay) if replay else None, provider):
        t0 = clock()
        rc = fn()
        timing["steps"].append({"step": name, "who": who, "seconds": round(clock() - t0, 1), "exit_code": rc})
        if rc:
            timing["status"] = "fail"
            timing["stopped_at"] = name
            break
        if name == STEPS[4]:                 # 报告要读 timing.json：在出报告之前先写一次
            path.write_text(json.dumps(timing, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    path.write_text(json.dumps(timing, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if timing["status"] == "pass" and steps is None:
        from assist import robot_report

        robot_report.write(case_dir / "out")        # 用时表补上“报告与 BOM”这一步
    return timing


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m assist.robot_case", description="整机案例：从需求跑到结果（ADR-0115 44.3）")
    ap.add_argument("case_dir", type=Path, help="案例目录（含 requirement.txt；结果写到 out/）")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path, help="回放录制目录（不调用真实 AI）")
    mode.add_argument("--provider", choices=("claude", "deepseek"), help="真实调用的 AI；密钥从环境变量读")
    a = ap.parse_args(argv)
    t = run(a.case_dir, replay=a.replay, provider=a.provider)
    for s in t["steps"]:
        print(f"{s['step']}：{s['seconds']:.1f} s" + ("" if not s["exit_code"] else f"（失败，退出码 {s['exit_code']}）"),
              file=sys.stderr)
    return 0 if t["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
