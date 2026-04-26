from __future__ import annotations

import logging
import os
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


def _get_database_url() -> Optional[str]:
    """从环境变量读取数据库连接地址，优先 DATABASE_URL，其次 AI_TEAM_DB_URL"""
    return os.environ.get("DATABASE_URL") or os.environ.get("AI_TEAM_DB_URL")


async def get_connection() -> Optional[asyncpg.Connection]:
    """获取数据库连接，若未配置 DATABASE_URL 则返回 None（优雅降级）"""
    global _pool
    url = _get_database_url()
    if not url:
        logger.debug("DATABASE_URL not set, persistence disabled")
        return None
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=url, min_size=1, max_size=10)
        logger.info("Database connection pool created")
    return await _pool.acquire()


async def release_connection(conn: asyncpg.Connection) -> None:
    """释放连接回连接池"""
    if _pool and conn is not None:
        await _pool.release(conn)


async def close_pool() -> None:
    """关闭连接池"""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


def is_available() -> bool:
    """同步检查：数据库连接是否已配置"""
    return _get_database_url() is not None
