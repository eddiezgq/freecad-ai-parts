"""命令行入口（ADR-0093 补充十一 §4）：python -m assist.fea draft|confirm|eval|report|explain-eval …"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["report"]:
        from assist.fea_report import main as report

        return report(argv)
    if argv[:1] == ["explain-eval"]:
        from assist.fea_report import main as report

        return report(["eval", *argv[1:]])
    from assist.fea_draft import main as draft

    return draft(argv)


if __name__ == "__main__":
    sys.exit(main())
