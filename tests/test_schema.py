"""schema 校验：schema/ 下每个 *.schema.json 必须是合法的 JSON Schema（Draft 2020-12）。

M0 阶段 schema/ 还是空的，此测试会跳过；M1 定稿 schema 后自动生效。
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
SCHEMA_FILES = sorted(SCHEMA_DIR.rglob("*.schema.json"))


@pytest.mark.skipif(not SCHEMA_FILES, reason="M1 之前尚无 schema 文件")
@pytest.mark.parametrize("path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_is_valid(path: Path):
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
