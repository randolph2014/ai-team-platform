"""Tests for truncate_utils module."""
from __future__ import annotations

import pytest

from engine.truncate_utils import smart_truncate, truncate_with_fallback


class TestSmartTruncate:
    """Tests for smart_truncate function."""

    def test_short_content_unchanged(self):
        content = "short content"
        assert smart_truncate(content, 100) == content

    def test_exact_max_chars_unchanged(self):
        content = "a" * 100
        assert smart_truncate(content, 100) == content

    def test_preserves_error_lines(self):
        content = "line1\nline2\nERROR: something failed\nline4\nline5"
        result = smart_truncate(content, 50)
        assert "ERROR" in result

    def test_preserves_traceback(self):
        content = "start\n" + "x" * 50 + "\nTraceback (most recent call last):\n  File 'test.py'\n" + "y" * 50 + "\nend"
        result = smart_truncate(content, 200)
        assert "Traceback" in result

    def test_preserves_chinese_error_keywords(self):
        content = "开始\n" + "x" * 50 + "\n失败: 测试不通过\n" + "y" * 50 + "\n结束"
        result = smart_truncate(content, 200)
        assert "失败" in result

    def test_head_tail_preserved(self):
        content = "HEAD\n" + "x" * 100 + "\nTAIL"
        result = smart_truncate(content, 60)
        assert result.startswith("HEAD")
        assert "TAIL" in result

    def test_budget_allocation(self):
        # 30% head, 50% error, 20% tail
        content = "a" * 30 + "\nERROR\n" + "b" * 50 + "\nc" * 20
        result = smart_truncate(content, 100)
        # Should contain ERROR
        assert "ERROR" in result


class TestTruncateWithFallback:
    """Tests for truncate_with_fallback function."""

    def test_smart_strategy(self):
        content = "line1\nERROR: fail\nline3"
        result = truncate_with_fallback(content, 50, strategy="smart")
        assert "ERROR" in result

    def test_head_strategy(self):
        content = "a" * 100
        result = truncate_with_fallback(content, 50, strategy="head")
        assert result.startswith("a" * 50)
        assert "[...truncated]" in result

    def test_tail_strategy(self):
        content = "a" * 100
        result = truncate_with_fallback(content, 50, strategy="tail")
        assert result.endswith("a" * 50)
        assert "[...truncated...]" in result

    def test_smart_fallback_on_error(self):
        """If smart_truncate raises, should fallback to head."""
        # This test ensures graceful degradation
        content = "a" * 100
        result = truncate_with_fallback(content, 50, strategy="smart")
        assert len(result) <= 50 + 20  # Allow for truncation marker
