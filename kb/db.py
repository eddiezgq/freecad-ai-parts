"""数据库连接与迁移（ADR-0018）。"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def connect(url: str | None = None) -> psycopg.Connection:
    """连接数据库；未给出 url 时读环境变量 DATABASE_URL。"""
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("未配置 DATABASE_URL")
    return psycopg.connect(url)


def migrate(conn: psycopg.Connection) -> list[str]:
    """按编号顺序执行尚未执行的迁移脚本，返回本次执行的文件名。可重复运行。"""
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        cur.execute("SELECT name FROM schema_migrations")
        done = {row[0] for row in cur.fetchall()}
    applied = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(path.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied
