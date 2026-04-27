"""API 层共享的数据库工具函数。

将 run_id 转换、persistence 导入检测等逻辑集中管理，避免重复定义。
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple


def run_db_id(run_id: str) -> str:
    """将应用的 run_id 转为数据库 pipeline_run.id（UUID v5）。"""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"ai-team:pipeline_run:{run_id}"))


def try_persistence():
    """尝试导入 persistence 模块。asyncpg 不可用时返回 None。

    Returns: (get_connection, release_connection, PipelineRunRepo, run_row_to_summary, run_detail_to_response) or None
    """
    try:
        from persistence.connection import get_connection, release_connection
        from persistence.repository import PipelineRunRepo, run_row_to_summary, run_detail_to_response
        return get_connection, release_connection, PipelineRunRepo, run_row_to_summary, run_detail_to_response
    except ImportError:
        return None
