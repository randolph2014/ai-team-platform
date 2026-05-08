from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def run_migrations() -> None:
    from .connection import get_connection, release_connection

    conn = await get_connection()
    if conn is None:
        logger.debug("DATABASE_URL not set, skipping migrations")
        return
    try:
        await _execute_pending(conn)
    finally:
        await release_connection(conn)


async def _execute_pending(conn) -> None:
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
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO migrations (name, executed_at) VALUES ($1, now())",
                name,
            )
        logger.info("Migration applied: %s", name)

    await _update_schema_version(conn)


async def _ensure_tracking_table(conn) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migrations (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            executed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _schema_version (
            key TEXT PRIMARY KEY,
            version INT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


async def _load_executed_names(conn) -> set[str]:
    rows = await conn.fetch("SELECT name FROM migrations ORDER BY id")
    return {row["name"] for row in rows}


async def _update_schema_version(conn) -> None:
    rows = await conn.fetch("SELECT name FROM migrations ORDER BY name")
    max_version = 0
    for row in rows:
        try:
            num = int(row["name"].split("_")[0])
            if num > max_version:
                max_version = num
        except (ValueError, IndexError):
            pass
    await conn.execute(
        """
        INSERT INTO _schema_version (key, version, updated_at)
        VALUES ('current', $1, now())
        ON CONFLICT (key) DO UPDATE SET version = $1, updated_at = now()
        """,
        max_version,
    )


async def get_schema_version(conn) -> int:
    row = await conn.fetchrow(
        "SELECT version FROM _schema_version WHERE key = 'current'"
    )
    if row is None:
        return 0
    return row["version"]
