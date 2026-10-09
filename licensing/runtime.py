"""本机的授权状态（ADR-0066）：闭源模块调用 allows(功能名) 决定开不开。

授权文件位置：环境变量 FAP_LICENSE_FILE，或本机用户目录 ~/.freecad-ai-parts/license.json。
浮动席位（授权装在工厂服务器上）见第 6 项。
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from licensing import keys
from licensing.license import Verdict, verify

USER_LICENSE = Path.home() / ".freecad-ai-parts" / "license.json"


def license_path(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env["FAP_LICENSE_FILE"]) if env.get("FAP_LICENSE_FILE") else USER_LICENSE


def current(path: Path | None = None, today: dt.date | None = None, public_keys=None) -> Verdict:
    path = path or license_path()
    if not path.is_file():
        return Verdict(False, "没有授权文件：闭源功能未开放，公开功能照常可用")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Verdict(False, f"授权文件读不了：{exc}")
    node = None
    if isinstance(doc, dict) and isinstance(doc.get("license"), dict) and doc["license"].get("kind") == "node":
        from licensing.fingerprint import fingerprint

        try:
            node = fingerprint()
        except RuntimeError:
            node = None
    return verify(doc, keys.PUBLIC_KEYS if public_keys is None else public_keys,
                  today or dt.datetime.now().astimezone().date(), node)


def allows(feature: str) -> bool:
    return current().allows(feature)
