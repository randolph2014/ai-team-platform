from __future__ import annotations

import unittest

from engine.agent_eval import (
    BUILTIN_SUITES,
    CODE_GENERATION_SUITE,
    CODE_REVIEW_SUITE,
    EvalResult,
    EvalSuite,
    EvalTask,
    TEST_WRITING_SUITE,
    _estimate_tokens,
    _rule_score_output,
    run_eval_suite,
)


class TestRuleScoreOutput(unittest.TestCase):
    def test_perfect_score(self) -> None:
        """满足所有条件时得满分或接近满分"""
        task = EvalTask(
            task_id="t1",
            description="test",
            expected_keywords=["def", "sort", "return"],
            min_output_length=80,
            expected_sections=["实现代码"],
            require_code_block=True,
        )
        output = "## 实现代码\n\ndef sort_array(arr):\n    return sorted(arr)\n\n```python\npass\n```\n\n" * 4
        score = _rule_score_output(task, output)
        self.assertGreaterEqual(score, 75.0)

    def test_no_keywords_match(self) -> None:
        """关键词不匹配时得分较低"""
        task = EvalTask(
            task_id="t2",
            description="test",
            expected_keywords=["def", "sort", "return"],
            min_output_length=0,
        )
        score = _rule_score_output(task, "hello world")
        self.assertLess(score, 80.0)

    def test_missing_code_block(self) -> None:
        """缺少代码块时扣分"""
        task = EvalTask(
            task_id="t3",
            description="test",
            require_code_block=True,
            min_output_length=0,
        )
        score_no_block = _rule_score_output(task, "just text")
        score_with_block = _rule_score_output(task, "```python\ncode\n```")
        self.assertLess(score_no_block, score_with_block)

    def test_output_too_short(self) -> None:
        """输出长度不满足 min_output_length 时扣分"""
        task = EvalTask(
            task_id="t4",
            description="test",
            min_output_length=200,
        )
        score = _rule_score_output(task, "short")
        self.assertLessEqual(score, 75.0)

    def test_partial_sections(self) -> None:
        """部分章节匹配则得部分分数"""
        task = EvalTask(
            task_id="t5",
            description="test",
            expected_sections=["设计思路", "实现代码", "测试方案"],
        )
        output = "## 设计思路\nsome thought\n## 实现代码\nsome code"
        score = _rule_score_output(task, output)
        self.assertGreater(score, 0)
        self.assertLess(score, 100.0)

    def test_empty_output_scores_zero(self) -> None:
        """空输出得低分但不为0（有保底分）"""
        task = EvalTask(
            task_id="t6",
            description="test",
            expected_keywords=["def"],
            require_code_block=True,
            expected_sections=["测试方案"],
            min_output_length=100,
        )
        score = _rule_score_output(task, "")
        self.assertLessEqual(score, 25.0)

    def test_section_with_markdown_heading(self) -> None:
        """Markdown 标题格式匹配"""
        task = EvalTask(
            task_id="t7",
            description="test",
            expected_sections=["问题分析", "优化方案"],
        )
        output = "### 问题分析\n发现问题\n# 优化方案\n方案内容"
        score = _rule_score_output(task, output)
        self.assertGreaterEqual(score, 50.0)


class TestEstimateTokens(unittest.TestCase):
    def test_simple_estimate(self) -> None:
        self.assertEqual(_estimate_tokens("hello world"), 2)

    def test_empty_estimate(self) -> None:
        self.assertEqual(_estimate_tokens(""), 0)

    def test_long_text_estimate(self) -> None:
        text = "one two three four five six seven eight nine ten"
        self.assertEqual(_estimate_tokens(text), 10)


class TestRunEvalSuite(unittest.TestCase):
    def test_code_generation_suite_perfect(self) -> None:
        """代码生成套件：提供符合所有要求的输出应得高分"""
        outputs = {
            "func_impl": (
                "实现一个排序函数：\n\n"
                "```python\n"
                "def bubble_sort(arr):\n"
                "    n = len(arr)\n"
                "    for i in range(n):\n"
                "        for j in range(n - i - 1):\n"
                "            if arr[j] > arr[j + 1]:\n"
                "                arr[j], arr[j + 1] = arr[j + 1], arr[j]\n"
                "    return arr\n"
                "```\n"
            ),
            "error_handling": (
                "## 实现代码\n\n"
                "```python\n"
                "def safe_divide(a, b):\n"
                "    try:\n"
                "        return a / b\n"
                "    except ZeroDivisionError:\n"
                "        raise ValueError('Cannot divide by zero')\n"
                "```\n"
            ),
            "class_design": (
                "## 设计思路\n\n使用dataclass设计用户模型\n\n"
                "## 实现代码\n\n"
                "```python\n"
                "class User:\n"
                "    def __init__(self, name, email):\n"
                "        self.name = name\n"
                "        self.email = email\n"
                "```\n"
            ),
        }
        result = run_eval_suite(outputs, suite=CODE_GENERATION_SUITE, agent_name="test-agent", model="test-model")
        self.assertIsInstance(result, EvalResult)
        self.assertEqual(result.agent_name, "test-agent")
        self.assertEqual(result.model, "test-model")
        self.assertEqual(result.tasks_total, 3)
        self.assertEqual(result.tasks_completed, 3)
        self.assertGreater(result.completion_rate, 0.0)
        self.assertGreater(result.overall_score, 50.0)

    def test_code_review_suite(self) -> None:
        """代码审查套件：提供审查内容应得分"""
        outputs = {
            "bug_detection": (
                "## 问题描述\n\n变量可能为 None 导致空指针异常\n\n"
                "## 修复建议\n\n添加 None 检查判断后再使用\n"
            ),
            "performance_review": (
                "## 问题分析\n\n嵌套循环导致 O(n^2) 时间复杂度\n\n"
                "## 优化方案\n\n使用哈希表将复杂度降至 O(n)\n\n"
                "## 代码对比\n\n优化前和优化后的对比\n"
            ),
            "security_review": (
                "## 风险描述\n\n存在 SQL 注入风险，需要参数化查询\n\n"
                "## 修复方案\n\n使用预编译语句 sanitize 输入\n"
            ),
        }
        result = run_eval_suite(outputs, suite=CODE_REVIEW_SUITE, agent_name="reviewer")
        self.assertEqual(result.suite_name, "code_review")
        self.assertEqual(result.tasks_total, 3)
        self.assertGreater(result.overall_score, 40.0)

    def test_test_writing_suite(self) -> None:
        """测试编写套件：提供测试代码应得分"""
        outputs = {
            "unit_test": (
                "```python\n"
                "import unittest\n"
                "def test_add():\n"
                "    assert add(1, 2) == 3\n"
                "    assert add(-1, 1) == 0\n"
                "    assert add(0, 0) == 0\n"
                "```\n"
            ),
            "edge_cases": (
                "## 测试场景\n\n空列表和单元素列表的边界测试\n\n"
                "## 测试代码\n\n"
                "```python\n"
                "def test_empty_list():\n"
                "    self.assertEqual(process([]), [])\n"
                "def test_single_element():\n"
                "    self.assertEqual(process([1]), [1])\n"
                "```\n"
            ),
            "mock_test": (
                "```python\n"
                "from unittest.mock import MagicMock, patch\n"
                "with patch('db.connect') as mock_conn:\n"
                "    mock_conn.return_value = MagicMock()\n"
                "    result = fetch_data()\n"
                "    assert result is not None\n"
                "```\n"
            ),
        }
        result = run_eval_suite(outputs, suite=TEST_WRITING_SUITE, agent_name="tester")
        self.assertEqual(result.suite_name, "test_writing")
        self.assertGreater(result.overall_score, 40.0)

    def test_partial_outputs(self) -> None:
        """部分任务无输出时 completion_rate 应小于 1"""
        outputs = {
            "func_impl": "def foo(): pass",
        }
        result = run_eval_suite(outputs, suite=CODE_GENERATION_SUITE, agent_name="partial")
        self.assertEqual(result.tasks_total, 3)
        self.assertLess(result.tasks_completed, 3)
        self.assertLess(result.completion_rate, 1.0)

    def test_empty_outputs(self) -> None:
        """所有任务都无输出"""
        result = run_eval_suite({}, suite=CODE_GENERATION_SUITE, agent_name="empty")
        self.assertEqual(result.tasks_total, 3)
        self.assertEqual(result.tasks_completed, 0)
        self.assertEqual(result.completion_rate, 0.0)
        self.assertEqual(result.overall_score, 0.0)

    def test_response_time_recorded(self) -> None:
        """响应时间应被记录"""
        import time
        start = time.monotonic()
        result = run_eval_suite({"func_impl": "def foo(): pass"}, suite=CODE_GENERATION_SUITE, agent_name="timing", start_time=start)
        self.assertGreaterEqual(result.response_time_ms, 0)
        self.assertIsInstance(result.response_time_ms, float)

    def test_token_usage_stats(self) -> None:
        """token 用量统计"""
        outputs = {"func_impl": "one two three four five", "error_handling": "a b c", "class_design": "x y z w"}
        result = run_eval_suite(outputs, suite=CODE_GENERATION_SUITE, agent_name="tokens")
        self.assertIn("total_estimated", result.token_usage)
        self.assertIn("avg_per_task", result.token_usage)
        self.assertGreater(result.token_usage["total_estimated"], 0)

    def test_task_details_contain_all_fields(self) -> None:
        """task_details 包含所有必要字段"""
        outputs = {"func_impl": "def foo(): pass"}
        result = run_eval_suite(outputs, suite=CODE_GENERATION_SUITE, agent_name="details")
        self.assertEqual(len(result.task_details), 3)
        for detail in result.task_details:
            self.assertIn("task_id", detail)
            self.assertIn("description", detail)
            self.assertIn("completed", detail)
            self.assertIn("quality_score", detail)
            self.assertIn("output_length", detail)
            self.assertIn("tokens_estimated", detail)

    def test_overall_score_range(self) -> None:
        """overall_score 应在 0-100 之间"""
        outputs = {"func_impl": "def foo(): pass"}
        result = run_eval_suite(outputs, suite=CODE_GENERATION_SUITE, agent_name="range")
        self.assertGreaterEqual(result.overall_score, 0.0)
        self.assertLessEqual(result.overall_score, 100.0)


class TestBuiltinSuites(unittest.TestCase):
    def test_three_suites_available(self) -> None:
        """应存在 3 个内置套件"""
        self.assertEqual(len(BUILTIN_SUITES), 3)
        self.assertIn("code_generation", BUILTIN_SUITES)
        self.assertIn("code_review", BUILTIN_SUITES)
        self.assertIn("test_writing", BUILTIN_SUITES)

    def test_each_suite_has_three_tasks(self) -> None:
        """每个套件应有 3 个任务"""
        for name, suite in BUILTIN_SUITES.items():
            with self.subTest(suite=name):
                self.assertEqual(len(suite.tasks), 3)

    def test_suite_descriptions(self) -> None:
        """每个套件应有非空描述"""
        for name, suite in BUILTIN_SUITES.items():
            with self.subTest(suite=name):
                self.assertIsInstance(suite.description, str)
                self.assertGreater(len(suite.description), 0)
                self.assertIsInstance(suite.name, str)
                self.assertGreater(len(suite.name), 0)


class TestEvalDataclasses(unittest.TestCase):
    def test_eval_task_creation(self) -> None:
        task = EvalTask(task_id="t1", description="test task")
        self.assertEqual(task.task_id, "t1")
        self.assertEqual(task.expected_keywords, [])
        self.assertEqual(task.min_output_length, 0)
        self.assertFalse(task.require_code_block)

    def test_eval_suite_creation(self) -> None:
        suite = EvalSuite(name="test", description="test suite", tasks=[EvalTask(task_id="t1", description="d1")])
        self.assertEqual(suite.name, "test")
        self.assertEqual(len(suite.tasks), 1)

    def test_eval_suite_with_id(self) -> None:
        suite = EvalSuite(name="test", description="test", tasks=[], suite_id="abc")
        self.assertEqual(suite.suite_id, "abc")
