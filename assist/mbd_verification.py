"""问渠多体动力学验证手册（ADR-0102 第 3 步）：跑全部多体标准题，把算出来的值与参考值逐题列成中英两版 Word / PDF。

题目清单在 `assist/mbd_verification_cases.json`，每题对应一个标准题测试；测试在断言之外用 `tests/verification.record`
记下算出来的值、参考值和容差。手册里的数字就是这一次测试算出来的，不另算、不手填。
跑测试、汇总、排版与有限元验证手册（`assist/fea_verification.py`）共用，这里只换题目清单、文字和运行环境。

用法：python -m assist.mbd_verification --out <目录> [--only MB-01,MB-02] [--no-pdf]
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from assist import fea_verification as FV

CASES = Path(__file__).with_name("mbd_verification_cases.json")
TEXT = {
    **FV.TEXT,
    "title": {"zh": "问渠多体动力学验证手册", "en": "WenQuest MBD Verification Manual"},
    "intro": {"zh": "本手册逐题列出多体动力学标准题的参考值（解析解、教材公式、文献基准解或独立程序的结果）与本软件的计算值。"
                    "每题的数字都是这一次运行相应的自动测试时算出来的，不另算、不手填；测试代码与题目清单随软件发布。",
              "en": "This manual lists, problem by problem, the reference values of the multibody benchmark problems (analytical "
                    "solutions, textbook formulas, published benchmark solutions or results of independent codes) and the values "
                    "computed by this software. Every number was produced by running the corresponding automated test for this "
                    "edition; nothing is computed separately or typed in by hand. The test code and the problem list ship with "
                    "the software."},
    "numerics": {"zh": "数值库", "en": "Numerical libraries"},
    "fe": {"zh": "柔性体缩减（有限元）", "en": "Flexible-body reduction (FE)"},
    "note_tol": {"zh": "缺省积分器为 DOP853（显式 8 阶）。有冲击接触、阶跃设定值或输出限幅的题，若改用隐式 HHT 积分器，"
                       "容差要收紧到 rtol 1e-8 才与 DOP853 的结果一致到本手册的容差；软件里的“自动”积分器按此规则选（使用说明“积分器怎么选”）。",
                 "en": "The default integrator is DOP853 (explicit, 8th order). For problems with impact contact, step set-points or "
                       "output limits, the implicit HHT integrator agrees with DOP853 to the tolerances of this manual only with "
                       "rtol tightened to 1e-8; the software's automatic integrator choice follows this rule (see the user guide, "
                       "'Choosing an integrator')."},
    "note_spinup": {"zh": "旋转梁升速（Kane、Ryan、Banerjee 1987：L = 10 m，EI = 14000 N·m²，ρA = 1.2 kg/m，15 s 升到 6 rad/s）单次要几分钟，"
                          "不放进自动测试，由脚本 scripts/mbd_spinup_check.py 验证：大变形梁梁端最大横向挠度 −0.5752 m（10 单元）与 "
                          "−0.5724 m（20 单元）相差 0.5 %，升速结束后回到 5 mm 以内并保持；线性模态柔性体最大 −0.680 m，偏大 18 %"
                          "（没有发散），所以高速旋转的细长件应选大变形梁。",
                    "en": "The spin-up beam (Kane, Ryan and Banerjee 1987: L = 10 m, EI = 14000 N·m², ρA = 1.2 kg/m, spun up to "
                          "6 rad/s in 15 s) takes several minutes per run, so it is not part of the automated tests; it is checked "
                          "with scripts/mbd_spinup_check.py. Large-deformation beam: maximum tip deflection −0.5752 m (10 elements) "
                          "and −0.5724 m (20 elements), 0.5 % apart, returning to within 5 mm after spin-up and staying there. "
                          "Linear modal flexible body: maximum −0.680 m, 18 % too large (it does not diverge); slender parts "
                          "spinning fast should therefore be modelled as large-deformation beams."},
    "note_mujoco": {"zh": "“独立程序”的参考值（MuJoCo 等）是事先用该程序算好、写在测试里的数，测试运行时不调用它。",
                    "en": "Reference values from independent codes (MuJoCo and others) were computed beforehand with that code and are "
                          "written into the test; the code is not called when the test runs."},
}
NOTES = ("note_tol", "note_spinup", "note_mujoco")


def load_cases() -> dict:
    return json.loads(CASES.read_text(encoding="utf-8"))


def _env() -> dict:
    import numpy
    import scipy

    from assist.fea_report import code_version

    fe = FV._env()
    return {"code": code_version(), "date": datetime.now(UTC).date().isoformat(),
            "numerics": f"NumPy {numpy.__version__} / SciPy {scipy.__version__}",
            "fe": f"{fe['solver']} / Gmsh {fe['gmsh']}",
            "python": f"Python {platform.python_version()} / {platform.system()} {platform.release()}"}


def build(summary: dict, env: dict, out: Path, lang: str) -> Path:
    return FV.build(summary, env, out, lang, text=TEXT, cats=load_cases()["categories"], notes=NOTES,
                    env_rows=[("numerics", env["numerics"]), ("fe", env["fe"])])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="问渠多体动力学验证手册（中英两版）")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", default="", help="只跑这些编号（逗号分隔），调试用")
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    cases = load_cases()["cases"]
    if a.only:
        keep = set(a.only.split(","))
        cases = [c for c in cases if c["id"] in keep]
    with tempfile.TemporaryDirectory() as tmp:
        rows, outcome = FV.run_tests(cases, Path(tmp))
    summary = FV.summarize(cases, rows, outcome)
    env = _env()
    (a.out / "verification.json").write_text(json.dumps({"env": env, **summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    from assist.fea_report import to_pdf

    for lang, name in (("zh", "问渠多体动力学验证手册.docx"), ("en", "WenQuest-MBD-Verification-Manual.docx")):
        d = build(summary, env, a.out / name, lang)
        if not a.no_pdf:
            to_pdf(d)
    print(json.dumps({k: summary[k] for k in ("n", "ok", "bad", "skip", "rows", "rows_ok")}, ensure_ascii=False))
    return 0 if summary["bad"] == 0 and summary["skip"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
