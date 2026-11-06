# -*- coding: utf-8 -*-
"""判定代码（格式校验、板子模型、检查）只做计算：不 import 网络库、AI 库，也不碰数据库。"""
import ast
import os

from conftest import EDA

PURE = ["wqeda/checks", "wqeda/schema", "wqeda/model.py"]
FORBIDDEN = {"socket", "http", "urllib", "requests", "httpx", "aiohttp", "websocket", "websockets",
             "anthropic", "openai",
             "sqlite3", "psycopg", "psycopg2", "sqlalchemy", "subprocess"}


def _files():
    for p in PURE:
        full = os.path.join(EDA, p)
        if os.path.isfile(full):
            yield full
        else:
            for root, _, names in os.walk(full):
                yield from (os.path.join(root, n) for n in names if n.endswith(".py"))


def test_judgement_code_imports_nothing_forbidden():
    bad = []
    for path in _files():
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                mods = [node.module or ""]
            bad += ["{}: {}".format(os.path.relpath(path, EDA), m) for m in mods if m.split(".")[0] in FORBIDDEN]
    assert not bad, bad
