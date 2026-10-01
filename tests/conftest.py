"""共用的测试夹具。

数据库测试读环境变量 FAP_TEST_DATABASE_URL；每个测试在独立的 schema 中运行，结束后删除。
本地未配置时跳过数据库测试；CI 中（环境变量 CI 存在）缺少配置则直接失败，避免测试被静默跳过。

标记 freecad 的测试需要能导入 FreeCAD：未安装时跳过；设置 FAP_REQUIRE_FREECAD=1 时（CI 的 freecad 作业）
导入失败即判失败（ADR-0032）。
"""

import importlib.util
import os
import uuid

import pytest


@pytest.fixture(scope="session")
def db_url() -> str:
    url = os.environ.get("FAP_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("CI"):
            pytest.fail("CI 中必须配置 FAP_TEST_DATABASE_URL，数据库测试不得跳过")
        pytest.skip("未配置 FAP_TEST_DATABASE_URL，跳过数据库测试")
    return url


@pytest.fixture()
def db(db_url: str):
    """每个测试一个全新的 schema，已执行迁移。"""
    import psycopg

    from kb.db import migrate

    schema = f"fap_test_{uuid.uuid4().hex[:12]}"
    conn = psycopg.connect(db_url, autocommit=True)
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}, public")
    try:
        migrate(conn)
        yield conn
    finally:
        conn.execute(f"DROP SCHEMA {schema} CASCADE")
        conn.close()


def _freecad_available() -> bool:
    return importlib.util.find_spec("FreeCAD") is not None


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("freecad") is None or _freecad_available():
        return
    if os.environ.get("FAP_REQUIRE_FREECAD") == "1":
        pytest.fail("FAP_REQUIRE_FREECAD=1 但无法导入 FreeCAD，FreeCAD 测试不得跳过")
    pytest.skip("未安装 FreeCAD，跳过（CI 的 freecad 作业中运行）")
