"""golden 运行器（issue #52）：用引擎跑 tests/golden/ 的全部用例，逐项对照预期。

预期由人手算并审定（CLAUDE.md）；本运行器只报告是否一致，`any` 项输出实际结果供人决定，绝不改写用例。
命令行：python -m engine.golden [--verbose]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from engine.validate import validate

GOLDEN = Path(__file__).resolve().parent.parent / "tests" / "golden"
VALID_EXPECTED = {"pass", "warn", "fail", "unknown", "not_applicable", "any"}


def load_fixtures(golden: Path = GOLDEN) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (golden / "fixtures").glob("*.json")}


def cases(golden: Path = GOLDEN) -> list[Path]:
    return sorted(golden.glob("*/*.yaml"))


def compare(expected: dict, report: dict) -> tuple[list[str], dict[str, str]]:
    """返回（不一致项说明, `any` 项的实际结果）。"""
    actual = {c["check"]: c["status"] for c in report["checks"]}
    problems: list[str] = []
    undecided: dict[str, str] = {}
    if report["overall"] != expected["overall"]:
        problems.append(f"整体结论：实际 {report['overall']}，预期 {expected['overall']}")
    checks = dict(expected.get("checks", {}))
    others = checks.pop("others", None)
    if others not in (None, "not_fail"):
        problems.append(f"预期中 others 只能是 not_fail，现为 {others!r}")
    for check, want in checks.items():
        if check not in actual:
            problems.append(f"预期中有未知的校验项 {check!r}")
        elif want not in VALID_EXPECTED:
            problems.append(f"{check} 的预期值 {want!r} 不合法")
    for check, status in actual.items():
        want = checks.get(check)
        if want not in VALID_EXPECTED and want is not None:
            continue
        if want == "any":
            undecided[check] = status
        elif want is not None:
            if status != want:
                problems.append(f"{check}：实际 {status}，预期 {want}")
        elif others == "not_fail" and status == "fail":
            problems.append(f"{check}：实际 fail，预期不得为 fail")
    return problems, undecided


def run(golden: Path = GOLDEN) -> list[dict]:
    fixtures = load_fixtures(golden)
    out = []
    for path in cases(golden):
        case = yaml.safe_load(path.read_text(encoding="utf-8"))
        report = validate(case["system"], fixtures.get)
        problems, undecided = compare(case["expected"], report)
        out.append({"id": case["id"], "ok": not problems, "problems": problems, "undecided": undecided,
                    "report": report})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用引擎跑全部 golden 用例")
    parser.add_argument("--verbose", action="store_true", help="打印每个用例的完整校验结果")
    args = parser.parse_args(argv)
    results = run()
    for r in results:
        mark = "✓" if r["ok"] else "✗"
        print(f"{mark} {r['id']}  整体 {r['report']['overall']}")
        for p in r["problems"]:
            print(f"    {p}")
        for check, status in r["undecided"].items():
            print(f"    {check} 预期为 any（待人决定），实际 {status}")
        if args.verbose:
            print(json.dumps(r["report"], ensure_ascii=False, indent=2))
    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} 个用例与预期一致")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
