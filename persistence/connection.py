from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Dict, Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None
_pool_loop: Optional[asyncio.AbstractEventLoop] = None
_pool_dsn: Optional[str] = None
_conn_pool_by_id: Dict[int, asyncpg.Pool] = {}
_sync_loop: Optional[asyncio.AbstractEventLoop] = None
_sync_loop_lock = threading.Lock()


def _get_database_url() -> Optional[str]:
    """从环境变量读取数据库连接地址，优先 DATABASE_URL，其次 AI_TEAM_DB_URL"""
    return os.environ.get("DATABASE_URL") or os.environ.get("AI_TEAM_DB_URL")


async def get_connection() -> Optional[asyncpg.Connection]:
    """获取数据库连接，若未配置 DATABASE_URL 则返回 None（优雅降级）"""
    global _pool, _pool_loop, _pool_dsn
    url = _get_database_url()
    if not url:
        logger.debug("DATABASE_URL not set, persistence disabled")
        return None

    loop = asyncio.get_running_loop()
    if _pool is not None and (_pool_loop is not loop or _pool_dsn != url or (_pool_loop and _pool_loop.is_closed())):
        logger.info("Discarding database pool bound to a different event loop or DSN")
        _pool = None
        _pool_loop = None
        _pool_dsn = None
        _conn_pool_by_id.clear()
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=url, min_size=1, max_size=10)
        _pool_loop = loop
        _pool_dsn = url
        logger.info("Database connection pool created")
    conn = await _pool.acquire()
    _conn_pool_by_id[id(conn)] = _pool
    return conn


async def release_connection(conn: asyncpg.Connection) -> None:
    """释放连接回连接池"""
    if conn is None:
        return
    pool = _conn_pool_by_id.pop(id(conn), None) or _pool
    if pool:
        await pool.release(conn)


async def close_pool() -> None:
    """关闭连接池"""
    global _pool, _pool_loop, _pool_dsn
    if _pool:
        await _pool.close()
        _pool = None
        _pool_loop = None
        _pool_dsn = None
        _conn_pool_by_id.clear()
        logger.info("Database connection pool closed")


def is_available() -> bool:
    """同步检查：数据库连接是否已配置"""
    return _get_database_url() is not None


def run_sync(coro):
    loop = _get_sync_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=30)


def _get_sync_loop() -> asyncio.AbstractEventLoop:
    global _sync_loop
    with _sync_loop_lock:
        if _sync_loop is not None and _sync_loop.is_running() and not _sync_loop.is_closed():
            return _sync_loop

        ready = threading.Event()
        loop = asyncio.new_event_loop()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()

        thread = threading.Thread(target=_run, name="ai-team-db-sync-loop", daemon=True)
        thread.start()
        ready.wait(timeout=5)
        _sync_loop = loop
        return loop
