"""龙门取放机器人（案例 B）一条命令从需求跑到结果（ADR-0115 44.5.5 第三步）。

需求原话 → AI 出构型并初筛（回放录制，或真实调用）→ 选件与节拍多体动力学 → 三维装配、按真实质量复核选件、门架有限元 → 报告与 BOM。
每步实测用时写进 `out/timing.json`（连同本机核数、内存），报告第 5 节用它。和案例 A 的 `assist.robot_case` 同一种用时格式。

    python -m assist.gantry_case examples/robots/sewing-loader --replay tests/recordings/robot_design
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from assist.robot_case import run as _run

STEPS = ("构型（AI 提、代码初筛）", "选件与节拍多体动力学（代码）", "三维装配、复核选件与门架有限元（代码）", "报告与 BOM（代码）")


def plan(case_dir: Path, replay: Path | None, provider: str | None) -> list[tuple[str, str, Callable[[], int]]]:
    from assist import gantry_build, gantry_cad, gantry_report, robot_design

    o = case_dir / "out"
    cr, br = o / "concept-result.json", o / "build-result.json"
    design = [str(case_dir / "requirement.txt"), "--screen-only", "-o", str(cr)]
    design += ["--replay", str(replay)] if replay else (["--provider", provider] if provider else [])
    who = "AI（回放录制）+ 代码" if replay else "AI（真实调用）+ 代码"
    return [
        (STEPS[0], who, lambda: robot_design.main(design)),
        (STEPS[1], "代码", lambda: gantry_build.main([str(cr), "-o", str(br)])),
        (STEPS[2], "代码", lambda: gantry_cad.main([str(cr), str(br), "-o", str(o)])),
        (STEPS[3], "代码", lambda: gantry_report.main([str(o)])),
    ]


def run(case_dir: str | Path, *, replay: str | Path | None = None, provider: str | None = None) -> dict:
    """依次跑各步；某步失败就停在那一步（如实写进 timing.json）。跑完再出一次报告，让用时表带上“报告与 BOM”这一步。"""
    from assist import gantry_report

    case_dir = Path(case_dir)
    (case_dir / "out").mkdir(exist_ok=True)
    t = _run(case_dir, steps=plan(case_dir, Path(replay) if replay else None, provider),
             ai=f"回放 {replay}" if replay else f"真实调用（{provider or '缺省'}）")
    if t["status"] == "pass":
        gantry_report.write(case_dir / "out")
    return t


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m assist.gantry_case", description="龙门取放机器人：从需求跑到结果（ADR-0115 44.5.5）")
    ap.add_argument("case_dir", type=Path, help="案例目录（含 requirement.txt；结果写到 out/）")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path, help="回放录制目录（不调用真实 AI）")
    mode.add_argument("--provider", choices=("claude", "deepseek"), help="真实调用的 AI；密钥从环境变量读")
    a = ap.parse_args(argv)
    t = run(a.case_dir, replay=a.replay, provider=a.provider)
    for s in t["steps"]:
        print(f"{s['step']}：{s['seconds']:.1f} s" + ("" if not s["exit_code"] else f"（失败，退出码 {s['exit_code']}）"), file=sys.stderr)
    return 0 if t["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
