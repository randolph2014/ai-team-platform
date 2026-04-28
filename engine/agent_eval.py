from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EvalTask:
    task_id: str
    description: str
    expected_keywords: List[str] = field(default_factory=list)
    min_output_length: int = 0
    expected_sections: List[str] = field(default_factory=list)
    require_code_block: bool = False


@dataclass
class EvalSuite:
    name: str
    description: str
    tasks: List[EvalTask]
    suite_id: Optional[str] = None


@dataclass
class EvalResult:
    suite_id: str
    suite_name: str
    agent_name: str
    model: Optional[str]
    tasks_total: int
    tasks_completed: int
    completion_rate: float
    quality_score: float
    response_time_ms: float
    token_usage: Dict[str, int]
    task_details: List[Dict[str, Any]]
    overall_score: float


def _rule_score_output(task: EvalTask, output: str) -> float:
    score = 0.0
    max_score = 100.0

    if task.min_output_length > 0:
        if len(output) >= task.min_output_length:
            score += 25
    else:
        score += 25

    if task.expected_keywords:
        hit_count = 0
        output_lower = output.lower()
        for kw in task.expected_keywords:
            if kw.lower() in output_lower:
                hit_count += 1
        kw_ratio = hit_count / len(task.expected_keywords)
        score += 30 * kw_ratio
    else:
        score += 30

    if task.expected_sections:
        hit_count = 0
        for section in task.expected_sections:
            pattern = rf"#{{{1,3}}}\s+{re.escape(section)}"
            if re.search(pattern, output, re.IGNORECASE):
                hit_count += 1
        section_ratio = hit_count / len(task.expected_sections)
        score += 25 * section_ratio
    else:
        score += 25

    if task.require_code_block:
        if re.search(r"```[\s\S]*?```", output):
            score += 20
    else:
        score += 20

    return min(score, max_score)


def _estimate_tokens(output: str) -> int:
    return len(output.split())


def _build_task_output(output: Optional[str]) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    return str(output)


CODE_GENERATION_SUITE = EvalSuite(
    name="code_generation",
    description="评估代码生成能力：函数实现、错误处理、代码结构",
    tasks=[
        EvalTask(
            task_id="func_impl",
            description="实现一个排序函数",
            expected_keywords=["def", "sort", "return", "len"],
            min_output_length=80,
            require_code_block=True,
        ),
        EvalTask(
            task_id="error_handling",
            description="实现带错误处理的除法函数",
            expected_keywords=["try", "except", "ZeroDivisionError", "raise"],
            min_output_length=60,
            require_code_block=True,
        ),
        EvalTask(
            task_id="class_design",
            description="设计一个用户类",
            expected_keywords=["class", "__init__", "self"],
            expected_sections=["设计思路", "实现代码"],
            min_output_length=100,
            require_code_block=True,
        ),
    ],
)

CODE_REVIEW_SUITE = EvalSuite(
    name="code_review",
    description="评估代码审查能力：问题发现、修复建议、代码质量",
    tasks=[
        EvalTask(
            task_id="bug_detection",
            description="检测代码中的空指针问题",
            expected_keywords=["None", "null", "检查", "判断", "修复"],
            expected_sections=["问题描述", "修复建议"],
            min_output_length=100,
        ),
        EvalTask(
            task_id="performance_review",
            description="评估嵌套循环的性能问题",
            expected_keywords=["时间复杂度", "优化", "嵌套", "O(n"],
            expected_sections=["问题分析", "优化方案", "代码对比"],
            min_output_length=120,
        ),
        EvalTask(
            task_id="security_review",
            description="审查SQL注入风险",
            expected_keywords=["SQL注入", "参数化", "预编译", "sanitize"],
            expected_sections=["风险描述", "修复方案"],
            min_output_length=80,
        ),
    ],
)

TEST_WRITING_SUITE = EvalSuite(
    name="test_writing",
    description="评估测试编写能力：单元测试、边界条件、Mock使用",
    tasks=[
        EvalTask(
            task_id="unit_test",
            description="为add函数编写单元测试",
            expected_keywords=["def test_", "assert", "unittest", "pytest"],
            min_output_length=100,
            require_code_block=True,
        ),
        EvalTask(
            task_id="edge_cases",
            description="测试空列表和单元素列表",
            expected_keywords=["assertEqual", "[]", "边界", "edge"],
            expected_sections=["测试场景", "测试代码"],
            min_output_length=80,
            require_code_block=True,
        ),
        EvalTask(
            task_id="mock_test",
            description="使用mock测试数据库调用",
            expected_keywords=["mock", "patch", "MagicMock", "return_value"],
            min_output_length=100,
            require_code_block=True,
        ),
    ],
)

BUILTIN_SUITES: Dict[str, EvalSuite] = {
    "code_generation": CODE_GENERATION_SUITE,
    "code_review": CODE_REVIEW_SUITE,
    "test_writing": TEST_WRITING_SUITE,
}


def run_eval_suite(
    outputs_by_task: Dict[str, str],
    *,
    suite: EvalSuite,
    agent_name: str = "unknown",
    model: Optional[str] = None,
    start_time: Optional[float] = None,
) -> EvalResult:
    if start_time is None:
        start_time = time.monotonic()
    response_time_ms = round((time.monotonic() - start_time) * 1000, 1)

    task_details: List[Dict[str, Any]] = []
    total_quality = 0.0
    tasks_completed = 0
    total_tokens = 0

    for task in suite.tasks:
        output = _build_task_output(outputs_by_task.get(task.task_id, ""))
        quality = _rule_score_output(task, output)
        tokens = _estimate_tokens(output)
        total_tokens += tokens

        completed = quality > 0 and len(output) > 0
        if completed:
            tasks_completed += 1
            total_quality += quality

        task_details.append({
            "task_id": task.task_id,
            "description": task.description,
            "completed": completed,
            "quality_score": quality,
            "output_length": len(output),
            "tokens_estimated": tokens,
        })

    tasks_total = len(suite.tasks)
    completion_rate = tasks_completed / tasks_total if tasks_total > 0 else 0.0
    avg_quality = total_quality / tasks_total if tasks_total > 0 else 0.0

    overall_score = (completion_rate * 0.4 + avg_quality / 100 * 0.6) * 100

    return EvalResult(
        suite_id=suite.suite_id or "",
        suite_name=suite.name,
        agent_name=agent_name,
        model=model,
        tasks_total=tasks_total,
        tasks_completed=tasks_completed,
        completion_rate=completion_rate,
        quality_score=avg_quality,
        response_time_ms=response_time_ms,
        token_usage={"total_estimated": total_tokens, "avg_per_task": total_tokens // max(tasks_total, 1)},
        task_details=task_details,
        overall_score=overall_score,
    )
