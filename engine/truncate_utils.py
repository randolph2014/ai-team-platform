"""智能截断工具：保留头尾和错误行。"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# 错误关键词正则（复用 orchestrator 中的词表）
ERROR_PATTERN = re.compile(
    r"(?i)(error|failed|traceback|exception|fatal|panic|timeout|assertion|失败|异常|错误|超时|断言)",
    re.MULTILINE,
)

# 上下文行数
CONTEXT_LINES = 2


def _extract_error_blocks(lines: List[str], max_chars: int) -> str:
    """提取错误行及其上下文，总长度不超过 max_chars。"""
    if not lines or max_chars <= 0:
        return ""

    error_indices = set()
    for i, line in enumerate(lines):
        if ERROR_PATTERN.search(line):
            # 添加上下文
            for j in range(max(0, i - CONTEXT_LINES), min(len(lines), i + CONTEXT_LINES + 1)):
                error_indices.add(j)

    if not error_indices:
        return ""

    # 按行号排序，合并连续块
    sorted_indices = sorted(error_indices)
    blocks: List[List[int]] = []
    current_block = [sorted_indices[0]]

    for idx in sorted_indices[1:]:
        if idx == current_block[-1] + 1:
            current_block.append(idx)
        else:
            blocks.append(current_block)
            current_block = [idx]
    blocks.append(current_block)

    # 拼接错误块
    result_parts = []
    total_chars = 0
    for block in blocks:
        block_text = "\n".join(lines[i] for i in block)
        if total_chars + len(block_text) > max_chars:
            # 剩余空间不足，截断
            remaining = max_chars - total_chars
            if remaining > 0:
                result_parts.append(block_text[:remaining] + "\n[...error block truncated]")
            break
        result_parts.append(block_text)
        total_chars += len(block_text)

    return "\n---\n".join(result_parts)


def smart_truncate(content: str, max_chars: int, content_type: str = "auto") -> str:
    """智能截断：保留头尾，错误行优先。

    策略:
    - 内容长度 ≤ max_chars: 原样返回
    - 提取「错误高亮行」（含 ERROR/FAILED/Traceback/失败 等关键词的行 + 上下 2 行上下文）
    - 头部预算 30% / 错误行预算 50% / 尾部预算 20%
    - 各部分超额时各自再截断，拼接时插入分隔符

    Args:
        content: 待截断的内容
        max_chars: 最大字符数
        content_type: 内容类型（auto/stack/diff/test/log），当前未使用，预留扩展

    Returns:
        截断后的内容
    """
    if len(content) <= max_chars:
        return content

    lines = content.split("\n")

    # 提取错误行（先提取，因为可能没有错误行）
    error_text = _extract_error_blocks(lines, int(max_chars * 0.5))

    # 预算分配
    if error_text:
        # 有错误行时：头部 30% / 错误行 50% / 尾部 20%
        head_budget = int(max_chars * 0.3)
        tail_budget = int(max_chars * 0.2)
    else:
        # 无错误行时：头部 60% / 尾部 40%
        head_budget = int(max_chars * 0.6)
        tail_budget = int(max_chars * 0.4)

    # 头部
    head_lines = []
    head_chars = 0
    for line in lines:
        if head_chars + len(line) + 1 > head_budget:
            break
        head_lines.append(line)
        head_chars += len(line) + 1
    head_text = "\n".join(head_lines)

    # 尾部
    tail_lines = []
    tail_chars = 0
    for line in reversed(lines):
        if tail_chars + len(line) + 1 > tail_budget:
            break
        tail_lines.insert(0, line)
        tail_chars += len(line) + 1
    tail_text = "\n".join(tail_lines)

    # 拼接
    parts = [head_text]

    if error_text:
        parts.append(f"\n[...{len(content) - head_chars - tail_chars - len(error_text)} chars omitted...]\n")
        parts.append("## 关键错误片段\n")
        parts.append(error_text)
        parts.append("\n")
    else:
        parts.append(f"\n[...{len(content) - head_chars - tail_chars} chars omitted...]\n")

    parts.append(tail_text)

    return "".join(parts)


def truncate_with_fallback(content: str, max_chars: int, strategy: str = "smart") -> str:
    """带降级策略的截断。

    Args:
        content: 待截断的内容
        max_chars: 最大字符数
        strategy: 截断策略（smart/head/tail）

    Returns:
        截断后的内容
    """
    if strategy == "smart":
        try:
            return smart_truncate(content, max_chars)
        except Exception:
            # 智能截断失败，降级到 head
            return content[:max_chars] + "\n\n[...truncated]"
    elif strategy == "tail":
        if len(content) <= max_chars:
            return content
        return "\n[...truncated...]\n" + content[-max_chars:]
    else:  # head
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + "\n\n[...truncated]"
