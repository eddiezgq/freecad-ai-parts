"""录制 AI 起草运动副的回答（ADR-0102 第 4 步）：问渠多体动力学安装包验收要回放“AI 挑运动副”，不联网。

用 tests/fixtures/mbd-step/takeup.found.json（挑线机构 STEP 导入后程序找出的零件与候选）向 AI 要草稿，经模型网关只用指定的一家，
回答写进 tests/recordings/mbd_mates/（按请求哈希存）。要对应的密钥，由 .github/workflows/mbd-ai-record.yml 在 demo 环境里跑。
草稿逐条核对（assist.mbd_mates.draft）：AI 收了不存在的候选、改了不允许的类型、选错机架都算不达标，退出码 1。

    python scripts/mbd_ai_record.py --provider claude|deepseek
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOUND = ROOT / "tests" / "fixtures" / "mbd-step" / "takeup.found.json"
RECORDINGS = ROOT / "tests" / "recordings" / "mbd_mates"


def main(argv=None) -> int:
    sys.path.insert(0, str(ROOT))
    from assist import mbd_mates as AM
    from assist.llm import GatewayClient

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--provider", choices=("claude", "deepseek"), default="claude")
    a = ap.parse_args(argv)
    fx = json.loads(FOUND.read_text(encoding="utf-8"))
    client = GatewayClient(a.provider, record_dir=RECORDINGS)
    d = AM.draft(fx["parts"], fx["found"], client)
    ids = {c["id"] for c in fx["found"]["candidates"]}
    ok = not d["notes"] and {x["id"] for x in d["accept"]} == ids and d["ground"] == "Part__Feature"
    print(json.dumps({"passed": ok, "draft": d}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
