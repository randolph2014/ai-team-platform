from __future__ import annotations

import logging
import os
from typing import Dict, Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None
_pools: Dict[int, asyncpg.Pool] = {}


def _get_database_url() -> Optional[str]:
    """从环境变量读取数据库连接地址，优先 DATABASE_URL，其次 AI_TEAM_DB_URL"""
    return os.environ.get("DATABASE_URL") or os.environ.get("AI_TEAM_DB_URL")


async def get_connection() -> Optional[asyncpg.Connection]:
    """获取数据库连接，若未配置 DATABASE_URL 则返回 None（优雅降级）"""
    import asyncio

    global _pool
    url = _get_database_url()
    if not url:
        logger.debug("DATABASE_URL not set, persistence disabled")
        return None

    loop_id = id(asyncio.get_running_loop())
    pool = _pools.get(loop_id)
    if pool is None or getattr(pool, "_closed", False):
        pool = await asyncpg.create_pool(dsn=url, min_size=1, max_size=10)
        _pools[loop_id] = pool
        _pool = pool
        logger.info("Database connection pool created")
    return await pool.acquire()


async def release_connection(conn: asyncpg.Connection) -> None:
    """释放连接回连接池"""
    import asyncio

    if conn is None:
        return
    pool = _pools.get(id(asyncio.get_running_loop())) or _pool
    if pool:
        await pool.release(conn)


async def close_pool() -> None:
    """关闭连接池"""
    import asyncio

    global _pool
    loop_id = id(asyncio.get_running_loop())
    pool = _pools.pop(loop_id, None)
    if pool is None and _pool is not None:
        pool = _pool
        for key, value in list(_pools.items()):
            if value is pool:
                _pools.pop(key, None)
    if pool:
        await pool.close()
        _pool = next(iter(_pools.values()), None)
        logger.info("Database connection pool closed")


def is_available() -> bool:
    """同步检查：数据库连接是否已配置"""
    return _get_database_url() is not None


def run_sync(coro):
    import asyncio
    import concurrent.futures

    async def _run_and_close():
        try:
            return await coro
        finally:
            await close_pool()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run_and_close())
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(_run_and_close())).result(timeout=30)
