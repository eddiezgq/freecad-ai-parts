"""问渠CAM 验证手册（ADR-0104 第 6 节；C1）：跑全部 CAM 标准题，把算出来的值与参考值逐题列成中英两版 Word / PDF。

题目清单在 `assist/cam_verification_cases.json`，每题对应 `tests/test_cam_benchmarks.py` 里的一个标准题测试；测试在断言之外用
`tests/verification.record` 记下算出来的值、参考值和容差。手册里的数字就是这一次测试算出来的，不另算、不手填。
跑测试、汇总、排版与有限元验证手册（`assist/fea_verification.py`）共用，这里只换题目清单、文字和运行环境。
实机记录（合作厂试切件的检测结果）在 C1 合作厂验收之后加进手册。

用法：python -m assist.cam_verification --out <目录> [--only CAM-01,CAM-02] [--no-pdf]
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

CASES = Path(__file__).with_name("cam_verification_cases.json")
TEXT = {
    **FV.TEXT,
    "title": {"zh": "问渠CAM 验证手册", "en": "WenQuest CAM Verification Manual"},
    "intro": {"zh": "本手册逐题列出数控编程标准题的参考值（手算公式、解析体积、标准尺寸、人工设定的错误程序）与本软件的计算值。"
                    "每题的数字都是这一次运行相应的自动测试时算出来的，不另算、不手填；测试代码与题目清单随软件发布。",
              "en": "This manual lists, problem by problem, the reference values of the CNC programming benchmark problems (hand "
                    "formulas, analytical volumes, standard dimensions and deliberately wrong programs) and the values computed by "
                    "this software. Every number was produced by running the corresponding automated test for this edition; "
                    "nothing is computed separately or typed in by hand. The test code and the problem list ship with the software."},
    "numerics": {"zh": "数值库", "en": "Numerical libraries"},
    "note_machine": {"zh": "标准题用的机床、刀具是仓库里的示例（虚构），只用来核对算法；用于真实加工前须换成企业自己的机床与刀具数据。"
                           "后处理还没有在实机上验证，程序头写明“未经实机验证”；合作厂实机空走与首件试切的检测结果，在 C1 合作厂验收后加进本手册。",
                     "en": "The machines and tools used by the benchmark problems are the fictional examples shipped with the software and "
                           "serve only to check the algorithms; real machining needs the company's own machine and tool data. The post "
                           "processors have not yet been verified on real machines and say so in the program header; dry-run and "
                           "first-part results from the partner shop will be added after the C1 shop acceptance."},
    "note_sim": {"zh": "材料去除按网格算：铣削三轴用高度图，任意刀轴与三维比对用三向 dexel（ADR-0106 Q2）；车削用半径网格，"
                       "刀尖圆弧按刀片的 rε 计入（没有刀片数据时按 0），螺纹按整圈切。体积与尺寸的容差按网格大小定。",
                 "en": "Material removal is computed on grids: a height map for 3-axis milling and a tri-dexel model for any tool "
                       "axis and the 3D comparison (ADR-0106 Q2); a radius grid for turning, with the insert nose radius taken into "
                       "account (zero when the insert has no data) and threads cut as full revolutions. Volume and size tolerances "
                       "follow the grid size."},
}
NOTES = ("note_machine", "note_sim")


def load_cases() -> dict:
    return json.loads(CASES.read_text(encoding="utf-8"))


def _env() -> dict:
    import numpy

    from assist.fea_report import code_version

    return {"code": code_version(), "date": datetime.now(UTC).date().isoformat(), "numerics": f"NumPy {numpy.__version__}",
            "python": f"Python {platform.python_version()} / {platform.system()} {platform.release()}"}


def build(summary: dict, env: dict, out: Path, lang: str) -> Path:
    return FV.build(summary, env, out, lang, text=TEXT, cats=load_cases()["categories"], notes=NOTES,
                    env_rows=[("numerics", env["numerics"])])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="问渠CAM 验证手册（中英两版）")
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

    for lang, name in (("zh", "问渠CAM验证手册.docx"), ("en", "WenQuest-CAM-Verification-Manual.docx")):
        d = build(summary, env, a.out / name, lang)
        if not a.no_pdf:
            to_pdf(d)
    print(json.dumps({k: summary[k] for k in ("n", "ok", "bad", "skip", "rows", "rows_ok")}, ensure_ascii=False))
    return 0 if summary["bad"] == 0 and summary["skip"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
