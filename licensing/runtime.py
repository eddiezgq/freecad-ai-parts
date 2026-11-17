"""本机的授权状态（ADR-0066）：闭源模块调用 allows(功能名) 决定开不开。

授权文件位置：环境变量 FAP_LICENSE_FILE，或本机用户目录 ~/.freecad-ai-parts/license.json。
浮动席位（授权装在工厂服务器上）见第 6 项。

测试密钥（ADR-0096 第 5 步，2026-11-17 项目负责人定“先用测试密钥”）：只有安装包根目录的 edition.json 写了
"test_build": true（CI 验收用的安装包）时，才另认环境变量 FAP_LICENSE_TEST_KEY 给的公钥（"test-编号:公钥 base64"，
编号必须以 test- 开头）。正式发版的安装包没有这个标记，设了环境变量也不认。
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from licensing import keys
from licensing.license import Verdict, verify

USER_LICENSE = Path.home() / ".freecad-ai-parts" / "license.json"
EDITION_FILE = Path(__file__).resolve().parents[1] / "edition.json"
TEST_PREFIX = "test-"


def test_build(path: Path | None = None) -> bool:
    try:
        return json.loads((path or EDITION_FILE).read_text(encoding="utf-8")).get("test_build") is True
    except (OSError, ValueError, AttributeError):
        return False


def known_keys(env=None, edition_file: Path | None = None) -> dict[str, str]:
    """认的公钥：正式公钥；验收用的安装包另加环境变量里的测试公钥"""
    env = os.environ if env is None else env
    out = dict(keys.PUBLIC_KEYS)
    raw = (env.get("FAP_LICENSE_TEST_KEY") or "").strip()
    if raw and test_build(edition_file):
        kid, _, pub = raw.partition(":")
        if kid.startswith(TEST_PREFIX) and pub:
            out[kid] = pub
    return out


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
    return verify(doc, known_keys() if public_keys is None else public_keys,
                  today or dt.datetime.now().astimezone().date(), node)


def allows(feature: str) -> bool:
    return current().allows(feature)
