"""录制 AI 起草运动副的回答（ADR-0102 第 4、5 步）：安装包验收、入门例子 2、用户手册截图回放“AI 挑运动副”，不联网。

对 tests/fixtures/mbd-step/ 下每个 *.found.json（某个 STEP 导入后程序找出的零件与候选：挑线机构、两关节机械臂）向 AI 要草稿，
经模型网关只用指定的一家，回答写进 tests/recordings/mbd_mates/（按请求哈希存；已有录制的跳过，不重问）。
要对应的密钥，由 .github/workflows/mbd-ai-record.yml 在 demo 环境里跑。
草稿逐条核对（assist.mbd_mates.draft）：AI 收了不存在的候选、改了不允许的类型、丢掉候选、机架没选体积最大的零件都算不达标，退出码 1。

    python scripts/mbd_ai_record.py --provider claude|deepseek
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "mbd-step"
RECORDINGS = ROOT / "tests" / "recordings" / "mbd_mates"


def main(argv=None) -> int:
    sys.path.insert(0, str(ROOT))
    from assist import mbd_mates as AM
    from assist.llm import GatewayClient

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--provider", choices=("claude", "deepseek"), default="claude")
    a = ap.parse_args(argv)
    from ingest.llm_extract import RecordedClient, RecordingMissing

    client = GatewayClient(a.provider, record_dir=RECORDINGS)
    replay = RecordedClient(RECORDINGS)
    replay.model = client.model
    out, ok = {}, True
    for path in sorted(FIXTURES.glob("*.found.json")):
        fx = json.loads(path.read_text(encoding="utf-8"))
        try:
            d = AM.draft(fx["parts"], fx["found"], replay)            # 已经录过：不重问
        except RecordingMissing:
            d = AM.draft(fx["parts"], fx["found"], client)
        good = draft_ok(fx, d)
        ok = ok and good
        out[path.name] = {"passed": good, "draft": d}
    print(json.dumps({"passed": ok, "fixtures": out}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def draft_ok(fx: dict, d: dict) -> bool:
    ids = {c["id"] for c in fx["found"]["candidates"]}
    return not d["notes"] and {x["id"] for x in d["accept"]} == ids and d["ground"] == fx["found"]["ground"]["part"]


if __name__ == "__main__":
    sys.exit(main())
