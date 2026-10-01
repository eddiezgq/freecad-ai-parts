"""抽取准确率评测（issue #31）：对照模拟规格书答案逐字段评分，输出逐字段、逐品类报告。

评分（每个可抽取目标一次）：
- correct：抽到了，值相符（数值相对误差 ≤ 0.1%，因规格书印 4 位有效数字；文字、枚举、布尔须相等；列表不计顺序）
- wrong：抽到了，值不符
- missed：答案中有，抽取结果里没有（含被核对拒绝的）
- extra：抽取结果里有，答案中没有（多抽或编造）
工况（condition）单独计：答案有工况的目标，抽到的工况须与印出的原文一致。

关键字段准确率 = 关键字段 correct / 答案中的关键字段数。验收要求 ≥ 95%（实施细则第十节），
且只计真实 LLM 响应：模拟响应（simulated）只用于检验评测代码，报告中明确标注，不得作为验收依据。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from ingest.llm_extract import targets

THRESHOLD = 0.95
REL_TOL = 1e-3


def expected_targets(answer: dict) -> dict[str, dict]:
    """答案中每个可抽取目标的期望：{"expected": {...}, "condition": str | None, "key": bool}。"""
    tmap = targets(answer["category"])
    out = {}
    for e in answer["fields"]:
        for path in e["paths"]:
            if path in tmap:
                out[path] = {"expected": e["expected"], "condition": e.get("condition"), "key": tmap[path][0].key}
    return out


def _same(want, got) -> bool:
    if isinstance(want, bool) or isinstance(got, bool):
        return want is got
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        return math.isclose(want, got, rel_tol=REL_TOL, abs_tol=1e-12)
    if isinstance(want, list) and isinstance(got, list):
        return len(want) == len(got) and all(any(_same(w, g) for g in got) for w in want)
    return want == got


def score(answer: dict, result: dict) -> dict[str, dict]:
    """逐目标评分：target → {"outcome", "key", "condition_ok"(有工况时)}。"""
    exp = expected_targets(answer)
    got = {i["target"]: i["value"] for i in result["items"]}
    tmap = targets(answer["category"])
    out: dict[str, dict] = {}
    for t, e in exp.items():
        pv = got.get(t)
        if pv is None:
            row = {"outcome": "missed", "key": e["key"]}
        else:
            shape = set(pv) & {"value", "min", "max", "nominal", "tol_upper", "tol_lower"}
            ok = shape == set(e["expected"]) and all(_same(v, pv[k]) for k, v in e["expected"].items())
            row = {"outcome": "correct" if ok else "wrong", "key": e["key"]}
        if e["condition"]:
            row["condition_ok"] = pv is not None and pv.get("condition") == e["condition"]
        out[t] = row
    for t in got:
        if t not in exp:
            out[t] = {"outcome": "extra", "key": tmap[t][0].key if t in tmap else False}
    return out


def _bucket() -> dict:
    return {"expected": 0, "correct": 0, "wrong": 0, "missed": 0, "extra": 0,
            "key_expected": 0, "key_correct": 0, "condition_expected": 0, "condition_correct": 0}


def _add(b: dict, row: dict) -> None:
    o = row["outcome"]
    b[o] += 1
    if o != "extra":
        b["expected"] += 1
        if row["key"]:
            b["key_expected"] += 1
            b["key_correct"] += o == "correct"
    if "condition_ok" in row:
        b["condition_expected"] += 1
        b["condition_correct"] += row["condition_ok"]


def _rates(b: dict) -> dict:
    def r(n, d):
        return round(n / d, 4) if d else None

    found = b["correct"] + b["wrong"] + b["extra"]
    return {**b, "key_accuracy": r(b["key_correct"], b["key_expected"]), "recall": r(b["correct"], b["expected"]),
            "precision": r(b["correct"], found), "condition_accuracy": r(b["condition_correct"], b["condition_expected"])}


def aggregate(pairs: list[tuple[dict, dict]], *, threshold: float = THRESHOLD) -> dict:
    """汇总多份（答案, 抽取结果）：总体、逐品类、逐字段（品类/target），以及每份规格书。"""
    overall, by_cat, by_field, sheets = _bucket(), {}, {}, []
    simulated = False
    for answer, result in pairs:
        simulated |= bool(result["extractor"].get("simulated"))
        cat = answer["category"]
        sheet = _bucket()
        for t, row in score(answer, result).items():
            for b in (overall, sheet, by_cat.setdefault(cat, _bucket()), by_field.setdefault(f"{cat} {t}", _bucket())):
                _add(b, row)
        sheets.append({"datasheet": answer["datasheet_id"], "lang": answer["lang"], **_rates(sheet)})
    report = {
        "format": "extraction-eval/1",
        "simulated": simulated,
        "threshold": threshold,
        "sheets_count": len(pairs),
        "overall": _rates(overall),
        "by_category": {k: _rates(v) for k, v in sorted(by_cat.items())},
        "by_field": {k: _rates(v) for k, v in sorted(by_field.items())},
        "sheets": sheets,
    }
    acc = report["overall"]["key_accuracy"]
    report["passed"] = (not simulated) and acc is not None and acc >= threshold
    return report


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def render_markdown(report: dict) -> str:
    o = report["overall"]
    lines = ["# 抽取准确率评测", ""]
    if report["simulated"]:
        lines += ["> **模拟响应**：本报告只检验评测代码，不得作为验收依据。", ""]
    verdict = "通过" if report["passed"] else "未通过"
    lines += [
        f"- 规格书：{report['sheets_count']} 份",
        (f"- 关键字段准确率：{_pct(o['key_accuracy'])}（{o['key_correct']}/{o['key_expected']}），"
         f"门槛 {_pct(report['threshold'])}：**{verdict}**"),
        (f"- 全部字段：召回 {_pct(o['recall'])}，精确 {_pct(o['precision'])}；"
         f"错 {o['wrong']}，漏 {o['missed']}，多 {o['extra']}"),
        f"- 工况：{_pct(o['condition_accuracy'])}（{o['condition_correct']}/{o['condition_expected']}）",
        "", "## 逐品类", "",
        "| 品类 | 关键字段准确率 | 召回 | 精确 | 错 | 漏 | 多 |", "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cat, b in report["by_category"].items():
        lines.append(f"| {cat} | {_pct(b['key_accuracy'])} | {_pct(b['recall'])} | {_pct(b['precision'])} | "
                     f"{b['wrong']} | {b['missed']} | {b['extra']} |")
    lines += ["", "## 逐字段", "", "| 品类 target | 期望 | 对 | 错 | 漏 | 多 | 召回 |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for k, b in report["by_field"].items():
        lines.append(f"| {k} | {b['expected']} | {b['correct']} | {b['wrong']} | {b['missed']} | {b['extra']} | "
                     f"{_pct(b['recall'])} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="对模拟规格书运行抽取并评分（#31）")
    parser.add_argument("--variants", type=int, default=2, help="每个组件评测几种变体")
    parser.add_argument("--work", type=Path, default=Path("data/synthetic"), help="规格书 PDF 与答案目录（不入 git）")
    parser.add_argument("--out", type=Path, default=Path("data/eval"), help="报告目录（不入 git）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path, help="只回放此目录中的录制（默认 tests/recordings/llm）")
    mode.add_argument("--record", action="store_true", help="真实调用并录制（需要 ANTHROPIC_API_KEY）")
    mode.add_argument("--simulate", action="store_true", help="用模拟响应检验评测代码（结果不计入验收）")
    args = parser.parse_args(argv)

    from ingest.llm_extract import (
        RECORDINGS_DIR,
        AnthropicClient,
        RecordedClient,
        RecordingMissing,
        extract_document,
    )
    from ingest.llm_simulate import SimulatedClient, simulated_response
    from ingest.pdf_extract import extract
    from ingest.synthetic import datasheets
    from kb.sources import TEST_DOC

    live = AnthropicClient(record_dir=RECORDINGS_DIR) if args.record else None
    replay = RecordedClient(args.replay or RECORDINGS_DIR)
    pairs = []
    try:
        for v in range(args.variants):
            for sheet in datasheets(v):
                doc = extract(sheet.render(args.work / f"{sheet.id}.pdf"))
                client = SimulatedClient(simulated_response(sheet.answer)) if args.simulate else (live or replay)
                result = extract_document(doc, sheet.answer["category"], TEST_DOC, client)
                pairs.append((sheet.answer, result))
    except RecordingMissing as exc:
        print(f"{exc}\n（还没有真实录制：请先用 --record 在本地运行一次）", file=sys.stderr)
        return 2
    report = aggregate(pairs)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report).split("## 逐品类")[0])
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
