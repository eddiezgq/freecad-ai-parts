"""数据库连接与迁移（ADR-0018）。

本模块的写操作都自己管理事务，要求连接为 autocommit 模式；connect() 返回的连接即是。
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_MIGRATE_LOCK = 0x46415001  # 迁移用的 advisory lock 键


def connect(url: str | None = None) -> psycopg.Connection:
    """连接数据库（autocommit 模式）；未给出 url 时读环境变量 DATABASE_URL。"""
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("未配置 DATABASE_URL")
    return psycopg.connect(url, autocommit=True)


def require_autocommit(conn: psycopg.Connection) -> None:
    """非 autocommit 连接上，transaction() 只会建 savepoint、不会提交，因此直接拒绝。"""
    if not conn.autocommit:
        raise ValueError("知识库写操作要求 autocommit 连接，请使用 kb.db.connect()")


def migrate(conn: psycopg.Connection) -> list[str]:
    """按编号顺序执行尚未执行的迁移脚本，返回本次执行的文件名。可重复运行，多进程并发时串行。"""
    require_autocommit(conn)
    applied = []
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATE_LOCK,))
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        cur.execute("SELECT name FROM schema_migrations")
        done = {row[0] for row in cur.fetchall()}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                continue
            cur.execute(path.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
    return applied
