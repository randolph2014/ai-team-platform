from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def run_migrations() -> None:
    """入口函数：扫描并按序执行所有未运行的 .up.sql 迁移脚本。

    如果 DATABASE_URL 未配置则静默跳过。
    """
    from .connection import get_connection, release_connection

    conn = await get_connection()
    if conn is None:
        logger.debug("DATABASE_URL not set, skipping migrations")
        return
    try:
        await _execute_pending(conn)
    except Exception:
        logger.exception("Migration execution failed")
    finally:
        await release_connection(conn)


async def _execute_pending(conn) -> None:
    """执行所有尚未记录的迁移文件"""
    await _ensure_tracking_table(conn)
    executed = await _load_executed_names(conn)

    migration_files = sorted(
        [f for f in MIGRATIONS_DIR.glob("*.up.sql") if f.name not in executed],
        key=lambda f: f.name,
    )

    for sql_file in migration_files:
        name = sql_file.name
        logger.info("Applying migration: %s", name)
        sql = sql_file.read_text(encoding="utf-8")
        await conn.execute(sql)
        await conn.execute(
            "INSERT INTO migrations (name, executed_at) VALUES ($1, now())",
            name,
        )
        logger.info("Migration applied: %s", name)


async def _ensure_tracking_table(conn) -> None:
    """创建迁移追踪表（如不存在）"""
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migrations (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            executed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


async def _load_executed_names(conn) -> set[str]:
    rows = await conn.fetch("SELECT name FROM migrations ORDER BY id")
    return {row["name"] for row in rows}
