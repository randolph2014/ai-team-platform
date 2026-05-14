from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.artifact_contracts import (
    SchemaValidationError,
    artifact_schema_hint_for,
    current_contract_validations,
    has_artifact_validation_failure,
    load_schema_for_artifact,
    validate_artifact,
    validate_artifact_schema,
    validate_requirement_for_planning,
    validate_required_artifacts,
    validate_review_for_loopback,
    validate_review_verdict_consistency,
    validate_task_plan_acceptance_refs,
)
from engine.models import ArtifactValidationRun


def _valid_requirement():
    return {
        "status": "completed",
        "summary": "用户登录功能",
        "goals": [{"id": "G-1", "description": "实现用户登录"}],
        "non_goals": [{"description": "不包含注册功能"}],
        "scope": {"included": ["登录页面", "认证接口"], "excluded": ["注册"]},
        "acceptance_criteria": [
            {"id": "AC-001", "description": "用户可以通过用户名密码登录", "verification_method": "自动化测试"}
        ],
        "risks": [{"risk": "认证服务不可用", "impact": "无法登录", "mitigation": "重试机制"}],
    }


def _valid_task_plan():
    return {
        "status": "completed",
        "summary": "任务计划",
        "tasks": [
            {
                "id": "task-001",
                "title": "实现登录接口",
                "description": "创建 POST /api/login 接口",
                "priority": "P0",
                "depends_on": [],
                "estimated_effort": "M",
                "acceptance_criteria_refs": ["AC-001"],
            }
        ],
        "execution_order": [["task-001"]],
    }


def _valid_solution_plan():
    return {
        "status": "completed",
        "summary": "使用现有编排器扩展交接契约",
        "decisions": [{"topic": "交接事实源", "decision": "pipeline 配置定义输入输出"}],
        "alternatives_considered": [{"option": "只改 prompt", "reason_rejected": "无法机械校验"}],
        "impact_scope": ["engine/config.py", "templates/team.yaml"],
        "configuration_strategy": {"source_of_truth": "pipeline", "notes": "schema 定义内容结构"},
        "risks": [{"risk": "stage 名称变化影响旧配置", "impact": "旧 run 兼容性", "mitigation": "保留兼容说明"}],
        "rollback_strategy": {"scope": "pipeline", "strategy": "恢复旧 planning stage"},
        "verification_strategy": [{"command": "pytest tests/test_config.py -q", "expected": "pass"}],
        "evidence": [{"source": "templates/team.yaml", "finding": "定义 stage input/output"}],
        "next_stage_contract": {"required_inputs_for_coder": ["task-plan.json"]},
    }


def _valid_plan_draft():
    return {
        "status": "completed",
        "summary": "方案草案",
        "decisions": [{"topic": "pipeline", "decision": "拆出 challenge 阶段"}],
        "tasks_preview": [
            {"id": "task-001", "title": "补齐 handoff schema", "acceptance_criteria_refs": ["AC-001"]}
        ],
        "file_boundaries": [{"task_id": "task-001", "allowed_files": ["engine/artifact_contracts.py"]}],
        "test_plan": [{"task_id": "task-001", "command": "pytest tests/test_artifact_contracts.py -q"}],
        "risks": [{"risk": "schema 过松", "impact": "错误输出通过", "mitigation": "增加 required 字段"}],
        "evidence": [{"source": "engine/config.py", "finding": "pipeline 已声明 required_artifacts"}],
        "next_stage_contract": {"required_inputs_for_challenger": ["plan-draft.json"]},
    }


def _valid_plan_review():
    return {
        "status": "completed",
        "verdict": "Approve",
        "summary": "方案可进入定稿",
        "blocking_findings": [],
        "findings": [
            {
                "severity": "Suggestion",
                "description": "补充 schema 测试",
                "recommendation": "增加缺失字段失败用例",
            }
        ],
        "open_questions": [],
        "required_changes": [],
        "evidence": [{"source": "plan-draft.json", "finding": "草案包含文件边界和测试计划"}],
        "next_stage_contract": {"required_inputs_for_planner": ["plan-review.json"]},
    }


def _valid_traceability():
    return [
        {
            "requirement_id": "REQ-001",
            "acceptance_id": "AC-001",
            "status": "verified",
            "evidence_refs": ["tests/test_auth.py::test_login"],
            "files": ["src/auth.py"],
            "tests": ["pytest tests/test_auth.py -q"],
            "harness_checks": ["checks.contract.skeleton-only"],
        }
    ]


def _valid_implementation_report():
    return {
        "status": "completed",
        "summary": "实现完成",
        "changed_files": ["src/auth.py", "tests/test_auth.py"],
        "tests_run": [
            {
                "command": "pytest tests/test_auth.py -q",
                "exit_code": 0,
                "duration": 1.2,
                "result": "passed",
            }
        ],
        "acceptance_coverage": [
            {
                "acceptance_id": "AC-001",
                "status": "passed",
                "evidence": "tests/test_auth.py::test_login",
            }
        ],
        "evidence": [
            {
                "source": "pytest tests/test_auth.py -q",
                "finding": "1 passed",
            }
        ],
        "risks": [],
        "traceability": _valid_traceability(),
    }


def _valid_test_report():
    return {
        "status": "completed",
        "summary": "测试通过",
        "commands": [
            {"command": "pytest tests/", "exit_code": 0, "duration": 12.5}
        ],
        "results": [
            {"test_name": "test_login", "status": "passed", "duration": 0.5}
        ],
        "acceptance_coverage": [
            {
                "acceptance_id": "AC-001",
                "covered_by": "test_login",
                "status": "passed",
            }
        ],
        "evidence": [
            {
                "source": "pytest tests/",
                "finding": "test_login passed",
            }
        ],
        "traceability": _valid_traceability(),
    }


def _valid_review_report():
    return {
        "status": "completed",
        "summary": "审查通过",
        "verdict": "Approve",
        "review_dimensions": _valid_review_dimensions(),
        "blocking_findings": [],
        "findings": [],
        "evidence": [
            {
                "source": "git diff",
                "finding": "No blocking findings",
            }
        ],
        "risks": [],
        "traceability": _valid_traceability(),
    }


def _valid_review_report_with_changes():
    return {
        "status": "completed",
        "summary": "需要修改",
        "verdict": "Request Changes",
        "review_dimensions": [
            {"dimension": "spec", "status": "failed", "evidence": "AC-001 缺少验收证据"},
            {"dimension": "regression", "status": "passed", "evidence": "回归测试已执行"},
            {"dimension": "architecture", "status": "passed", "evidence": "未发现架构边界破坏"},
            {"dimension": "debt", "status": "warning", "evidence": "存在后续清理项"},
            {"dimension": "test", "status": "failed", "evidence": "测试覆盖不足"},
        ],
        "blocking_findings": [
            {
                "severity": "Critical",
                "file_path": "src/auth.py",
                "line": 42,
                "description": "SQL injection risk",
                "fix_suggestion": "Use parameterized queries",
            }
        ],
        "findings": [
            {
                "severity": "Critical",
                "file_path": "src/auth.py",
                "line": 42,
                "description": "SQL injection risk",
                "fix_suggestion": "Use parameterized queries",
            }
        ],
        "evidence": [
            {
                "source": "git diff",
                "finding": "src/auth.py builds SQL with string interpolation",
            }
        ],
        "risks": [
            {
                "risk": "SQL injection",
                "impact": "Credential compromise",
                "mitigation": "Use parameterized queries",
            }
        ],
        "traceability": _valid_traceability(),
    }


def _valid_review_dimensions():
    return [
        {"dimension": "spec", "status": "passed", "evidence": "验收点均已对照"},
        {"dimension": "regression", "status": "passed", "evidence": "回归风险已检查"},
        {"dimension": "architecture", "status": "passed", "evidence": "架构边界未变化"},
        {"dimension": "debt", "status": "passed", "evidence": "未引入明显技术债"},
        {"dimension": "test", "status": "passed", "evidence": "测试证据充分"},
    ]


class TestSchemaLoading(unittest.TestCase):
    def test_load_all_schemas(self):
        for name in [
            "requirement-final.json",
            "solution-plan.json",
            "plan-draft.json",
            "plan-review.json",
            "task-plan.json",
            "test-report.json",
            "review-report.json",
            "implementation-report.json",
            "release-readiness.json",
            "harness-report.json",
        ]:
            schema = load_schema_for_artifact(name)
            self.assertIsNotNone(schema, f"Failed to load schema: {name}")
            self.assertIn("required", schema)

    def test_unknown_schema_returns_none(self):
        result = load_schema_for_artifact("unknown.json")
        self.assertIsNone(result)

    def test_requirement_final_schema_is_platform_task_contract(self):
        schema = load_schema_for_artifact("requirement-final.json")
        hint = artifact_schema_hint_for("requirement-final.json")

        self.assertEqual(schema["title"], "Task Contract")
        self.assertEqual(hint["display_name"], "Task Contract")
        self.assertIn("Task Contract", schema["description"])

    def test_implementation_schema_hint_includes_array_property_shapes(self):
        hint = artifact_schema_hint_for("implementation-report.json")

        self.assertEqual(hint["properties"]["traceability"]["type"], "array")
        self.assertIn("requirement_id", hint["properties"]["traceability"]["items_required"])
        self.assertIn("acceptance_id", hint["properties"]["traceability"]["items_required"])
        self.assertEqual(hint["properties"]["acceptance_coverage"]["type"], "array")
        self.assertIn("acceptance_id", hint["properties"]["acceptance_coverage"]["items_required"])

    def test_schema_hint_includes_nested_array_item_shapes(self):
        hint = artifact_schema_hint_for("requirement-final.json")

        rejected_inputs = hint["properties"]["decisions"]["items_properties"]["rejected_inputs"]

        self.assertEqual(rejected_inputs["type"], "array")
        self.assertEqual(rejected_inputs["items_type"], "object")
        self.assertIn("input", rejected_inputs["items_required"])
        self.assertIn("reason", rejected_inputs["items_required"])
        self.assertEqual(rejected_inputs["items_properties"]["input"]["type"], "string")
        self.assertEqual(rejected_inputs["items_properties"]["reason"]["type"], "string")


class TestRequirementValidation(unittest.TestCase):
    def test_valid_requirement_passes(self):
        errors, status = validate_artifact(_valid_requirement(), "requirement-final.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_missing_goals_fails(self):
        data = _valid_requirement()
        del data["goals"]
        errors, status = validate_artifact(data, "requirement-final.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("goals" in e for e in errors))

    def test_missing_acceptance_criteria_fails(self):
        data = _valid_requirement()
        del data["acceptance_criteria"]
        errors, status = validate_artifact(data, "requirement-final.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("acceptance_criteria" in e for e in errors))

    def test_empty_goals_fails(self):
        data = _valid_requirement()
        data["goals"] = []
        errors, status = validate_artifact(data, "requirement-final.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("goals" in e and "minItems" in e.lower() or "too short" in e.lower() for e in errors))

    def test_empty_acceptance_criteria_fails(self):
        data = _valid_requirement()
        data["acceptance_criteria"] = []
        errors, status = validate_artifact(data, "requirement-final.json")
        self.assertEqual(status, "failed")

    def test_missing_non_goals_fails(self):
        data = _valid_requirement()
        del data["non_goals"]
        errors, status = validate_artifact(data, "requirement-final.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("non_goals" in e for e in errors))

    def test_missing_scope_fails(self):
        data = _valid_requirement()
        del data["scope"]
        errors, status = validate_artifact(data, "requirement-final.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("scope" in e for e in errors))

    def test_missing_risks_fails(self):
        data = _valid_requirement()
        del data["risks"]
        errors, status = validate_artifact(data, "requirement-final.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("risks" in e for e in errors))

    def test_invalid_status_fails(self):
        data = _valid_requirement()
        data["status"] = "invalid"
        errors, status = validate_artifact(data, "requirement-final.json")
        self.assertEqual(status, "failed")

    def test_acceptance_criteria_id_pattern(self):
        data = _valid_requirement()
        data["acceptance_criteria"][0]["id"] = "INVALID-001"
        errors, status = validate_artifact(data, "requirement-final.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("pattern" in e for e in errors))

    def test_additional_property_rejected(self):
        data = _valid_requirement()
        data["unknown_field"] = "value"
        errors, status = validate_artifact(data, "requirement-final.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("additional" in e for e in errors))

    def test_blocks_planning_without_acceptance_criteria(self):
        data = _valid_requirement()
        data["acceptance_criteria"] = []
        errors = validate_requirement_for_planning(data)
        self.assertTrue(len(errors) > 0)
        self.assertTrue(any("acceptance" in e.lower() for e in errors))

    def test_allows_planning_with_acceptance_criteria(self):
        errors = validate_requirement_for_planning(_valid_requirement())
        self.assertEqual(errors, [])


class TestTaskPlanValidation(unittest.TestCase):
    def test_valid_task_plan_passes(self):
        errors, status = validate_artifact(_valid_task_plan(), "task-plan.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_markdown_deliverable_type_passes(self):
        data = _valid_task_plan()
        data["tasks"][0]["deliverable"] = {
            "type": "markdown",
            "path": "implementation-report.md",
            "description": "文档总结",
        }
        errors, status = validate_artifact(data, "task-plan.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_missing_tasks_fails(self):
        data = _valid_task_plan()
        del data["tasks"]
        errors, status = validate_artifact(data, "task-plan.json")
        self.assertEqual(status, "failed")

    def test_empty_tasks_fails(self):
        data = _valid_task_plan()
        data["tasks"] = []
        errors, status = validate_artifact(data, "task-plan.json")
        self.assertEqual(status, "failed")

    def test_task_without_acceptance_criteria_refs_fails(self):
        data = _valid_task_plan()
        data["tasks"][0]["acceptance_criteria_refs"] = []
        errors, status = validate_artifact(data, "task-plan.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("acceptance_criteria_refs" in e and "empty" in e for e in errors))

    def test_task_missing_acceptance_criteria_refs_field_fails(self):
        data = _valid_task_plan()
        del data["tasks"][0]["acceptance_criteria_refs"]
        errors, status = validate_artifact(data, "task-plan.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("acceptance_criteria_refs" in e for e in errors))

    def test_task_acceptance_ref_wrong_pattern_fails(self):
        data = _valid_task_plan()
        data["tasks"][0]["acceptance_criteria_refs"] = ["INVALID"]
        errors, status = validate_artifact(data, "task-plan.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("AC-" in e for e in errors))

    def test_missing_execution_order_fails(self):
        data = _valid_task_plan()
        del data["execution_order"]
        errors, status = validate_artifact(data, "task-plan.json")
        self.assertEqual(status, "failed")

    def test_invalid_priority_fails(self):
        data = _valid_task_plan()
        data["tasks"][0]["priority"] = "P5"
        errors, status = validate_artifact(data, "task-plan.json")
        self.assertEqual(status, "failed")


class TestPlanningHandoffValidation(unittest.TestCase):
    def test_valid_solution_plan_passes(self):
        errors, status = validate_artifact(_valid_solution_plan(), "solution-plan.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_solution_plan_missing_verification_strategy_fails(self):
        data = _valid_solution_plan()
        del data["verification_strategy"]
        errors, status = validate_artifact(data, "solution-plan.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("verification_strategy" in e for e in errors))

    def test_valid_plan_draft_passes(self):
        errors, status = validate_artifact(_valid_plan_draft(), "plan-draft.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_plan_draft_requires_next_stage_contract(self):
        data = _valid_plan_draft()
        del data["next_stage_contract"]
        errors, status = validate_artifact(data, "plan-draft.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("next_stage_contract" in e for e in errors))

    def test_valid_plan_review_passes(self):
        errors, status = validate_artifact(_valid_plan_review(), "plan-review.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_plan_review_request_changes_requires_required_changes(self):
        data = _valid_plan_review()
        data["verdict"] = "Request Changes"
        data["required_changes"] = []
        errors, status = validate_artifact(data, "plan-review.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("required_changes" in e for e in errors))


class TestRelatedTaskArtifactReasons(unittest.TestCase):
    def test_requirement_requires_related_task_adopt_or_reject_reason_when_context_has_related_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "codebase-context.json").write_text(
                json.dumps({"harness": {"related_tasks": [{"task_id": "T-checkout"}]}}),
                encoding="utf-8",
            )
            (output_dir / "requirement-final.json").write_text(
                json.dumps(_valid_requirement(), ensure_ascii=False),
                encoding="utf-8",
            )

            results = validate_required_artifacts({"required_artifacts": ["requirement-final.json"]}, output_dir)

        self.assertEqual(results[0].status, "failed")
        self.assertIn("related_task_decisions", results[0].message)

    def test_task_plan_accepts_related_task_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            task_plan = _valid_task_plan()
            task_plan["related_task_decisions"] = [
                {
                    "task_id": "T-checkout",
                    "action": "adopted",
                    "reason": "沿用已验收支付幂等设计",
                    "decision_ids": ["D-checkout"],
                }
            ]
            (output_dir / "codebase-context.json").write_text(
                json.dumps({"harness": {"related_tasks": [{"task_id": "T-checkout"}]}}),
                encoding="utf-8",
            )
            (output_dir / "task-plan.json").write_text(json.dumps(task_plan, ensure_ascii=False), encoding="utf-8")

            results = validate_required_artifacts({"required_artifacts": ["task-plan.json"]}, output_dir)

        self.assertEqual(results[0].status, "passed", results[0].message)

    def test_no_related_tasks_keeps_related_decisions_optional(self) -> None:
        errors, status = validate_artifact(_valid_requirement(), "requirement-final.json")
        self.assertEqual(status, "passed", errors)


class TestImplementationReportValidation(unittest.TestCase):
    def test_valid_implementation_report_passes(self):
        errors, status = validate_artifact(_valid_implementation_report(), "implementation-report.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_read_only_implementation_report_allows_empty_changed_files(self):
        data = _valid_implementation_report()
        data["changed_files"] = []
        errors, status = validate_artifact(data, "implementation-report.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_read_only_implementation_report_allows_empty_tests_run(self):
        data = _valid_implementation_report()
        data["tests_run"] = []
        errors, status = validate_artifact(data, "implementation-report.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_implementation_evidence_supports_acceptance_reference(self):
        data = _valid_implementation_report()
        data["evidence"][0]["supports"] = "AC-001"
        errors, status = validate_artifact(data, "implementation-report.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_implementation_test_result_allows_output_excerpt(self):
        data = _valid_implementation_report()
        data["tests_run"][0]["output_excerpt"] = "1 passed"
        errors, status = validate_artifact(data, "implementation-report.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_missing_traceability_fails(self):
        data = _valid_implementation_report()
        del data["traceability"]
        errors, status = validate_artifact(data, "implementation-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("traceability" in e for e in errors))

    def test_empty_traceability_fails(self):
        data = _valid_implementation_report()
        data["traceability"] = []
        errors, status = validate_artifact(data, "implementation-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("traceability" in e and "too short" in e for e in errors))

    def test_missing_acceptance_coverage_fails(self):
        data = _valid_implementation_report()
        del data["acceptance_coverage"]
        errors, status = validate_artifact(data, "implementation-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("acceptance_coverage" in e for e in errors))

    def test_missing_evidence_fails(self):
        data = _valid_implementation_report()
        del data["evidence"]
        errors, status = validate_artifact(data, "implementation-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("evidence" in e for e in errors))


class TestTestReportValidation(unittest.TestCase):
    def test_valid_test_report_passes(self):
        errors, status = validate_artifact(_valid_test_report(), "test-report.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_blocked_command_allows_null_metrics_and_metadata(self):
        data = _valid_test_report()
        data["status"] = "partial"
        data["commands"][0] = {
            "id": "CMD-001",
            "command": "./.venv/bin/python -m pytest",
            "exit_code": None,
            "duration": None,
            "result": "blocked",
            "note": "sandbox blocked access to the linked virtualenv",
        }
        data["results"][0]["status"] = "blocked"

        errors, status = validate_artifact(data, "test-report.json")

        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_evidence_supports_acceptance_reference(self):
        data = _valid_test_report()
        data["evidence"][0]["supports"] = "AC-001"

        errors, status = validate_artifact(data, "test-report.json")

        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_traceability_passed_status_is_accepted_as_verified_alias(self):
        data = _valid_test_report()
        data["traceability"][0]["status"] = "passed"

        errors, status = validate_artifact(data, "test-report.json")

        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_missing_commands_fails(self):
        data = _valid_test_report()
        del data["commands"]
        errors, status = validate_artifact(data, "test-report.json")
        self.assertEqual(status, "failed")

    def test_command_missing_exit_code_fails(self):
        data = _valid_test_report()
        del data["commands"][0]["exit_code"]
        errors, status = validate_artifact(data, "test-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("exit_code" in e for e in errors))

    def test_command_missing_duration_passes_for_manual_review(self):
        data = _valid_test_report()
        del data["commands"][0]["duration"]
        errors, status = validate_artifact(data, "test-report.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_command_result_success_is_accepted_as_passed_alias(self):
        data = _valid_test_report()
        data["commands"][0]["result"] = "success"
        errors, status = validate_artifact(data, "test-report.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_result_missing_duration_passes_for_manual_review(self):
        data = _valid_test_report()
        del data["results"][0]["duration"]
        errors, status = validate_artifact(data, "test-report.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_result_null_duration_passes_for_manual_review(self):
        data = _valid_test_report()
        data["results"][0]["duration"] = None
        errors, status = validate_artifact(data, "test-report.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_result_invalid_status_fails(self):
        data = _valid_test_report()
        data["results"][0]["status"] = "unknown"
        errors, status = validate_artifact(data, "test-report.json")
        self.assertEqual(status, "failed")

    def test_missing_results_fails(self):
        data = _valid_test_report()
        del data["results"]
        errors, status = validate_artifact(data, "test-report.json")
        self.assertEqual(status, "failed")

    def test_missing_acceptance_coverage_fails(self):
        data = _valid_test_report()
        del data["acceptance_coverage"]
        errors, status = validate_artifact(data, "test-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("acceptance_coverage" in e for e in errors))

    def test_missing_evidence_fails(self):
        data = _valid_test_report()
        del data["evidence"]
        errors, status = validate_artifact(data, "test-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("evidence" in e for e in errors))

    def test_missing_traceability_fails(self):
        data = _valid_test_report()
        del data["traceability"]
        errors, status = validate_artifact(data, "test-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("traceability" in e for e in errors))


class TestReviewReportValidation(unittest.TestCase):
    def test_valid_approve_passes(self):
        errors, status = validate_artifact(_valid_review_report(), "review-report.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")
        self.assertEqual(errors, [])

    def test_valid_request_changes_passes(self):
        errors, status = validate_artifact(_valid_review_report_with_changes(), "review-report.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")

    def test_missing_verdict_fails(self):
        data = _valid_review_report()
        del data["verdict"]
        errors, status = validate_artifact(data, "review-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("verdict" in e for e in errors))

    def test_missing_blocking_findings_fails(self):
        data = _valid_review_report()
        del data["blocking_findings"]
        errors, status = validate_artifact(data, "review-report.json")
        self.assertEqual(status, "failed")

    def test_missing_review_dimensions_fails(self):
        data = _valid_review_report()
        del data["review_dimensions"]
        errors, status = validate_artifact(data, "review-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("review_dimensions" in e for e in errors))

    def test_review_dimensions_must_cover_all_required_dimensions(self):
        data = _valid_review_report()
        data["review_dimensions"] = [
            {"dimension": "spec", "status": "passed", "evidence": "checked"},
            {"dimension": "test", "status": "passed", "evidence": "checked"},
        ]
        errors, status = validate_artifact(data, "review-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("review_dimensions missing dimensions" in e for e in errors))

    def test_approve_with_blocking_findings_fails(self):
        data = _valid_review_report()
        data["blocking_findings"] = [{"severity": "Critical", "file_path": "x.py", "description": "bad"}]
        errors, status = validate_artifact(data, "review-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("Approve" in e and "blocking_findings" in e for e in errors))

    def test_request_changes_without_findings_or_critical_fails(self):
        data = {
            "status": "completed",
            "summary": "changes needed",
            "verdict": "Request Changes",
            "review_dimensions": _valid_review_dimensions(),
            "blocking_findings": [],
            "findings": [],
            "evidence": [{"source": "git diff", "finding": "No critical finding"}],
            "risks": [],
            "traceability": _valid_traceability(),
        }
        errors, status = validate_artifact(data, "review-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("Request Changes" in e for e in errors))

    def test_request_changes_with_critical_in_findings_passes(self):
        data = {
            "status": "completed",
            "summary": "changes needed",
            "verdict": "Request Changes",
            "review_dimensions": _valid_review_dimensions(),
            "blocking_findings": [],
            "findings": [{"severity": "Critical", "file_path": "x.py", "description": "sql injection"}],
            "evidence": [{"source": "git diff", "finding": "sql injection"}],
            "risks": [{"risk": "sql injection", "impact": "data exposure"}],
            "traceability": _valid_traceability(),
        }
        errors, status = validate_artifact(data, "review-report.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")

    def test_invalid_verdict_value_fails(self):
        data = _valid_review_report()
        data["verdict"] = "Maybe"
        errors, status = validate_artifact(data, "review-report.json")
        self.assertEqual(status, "failed")

    def test_missing_findings_fails(self):
        data = _valid_review_report()
        del data["findings"]
        errors, status = validate_artifact(data, "review-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("findings" in e for e in errors))

    def test_missing_evidence_fails(self):
        data = _valid_review_report()
        del data["evidence"]
        errors, status = validate_artifact(data, "review-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("evidence" in e for e in errors))

    def test_missing_risks_fails(self):
        data = _valid_review_report()
        del data["risks"]
        errors, status = validate_artifact(data, "review-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("risks" in e for e in errors))

    def test_missing_traceability_fails(self):
        data = _valid_review_report()
        del data["traceability"]
        errors, status = validate_artifact(data, "review-report.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("traceability" in e for e in errors))


class TestReviewLoopbackDetection(unittest.TestCase):
    def test_approve_no_loopback(self):
        self.assertFalse(validate_review_for_loopback(_valid_review_report()))

    def test_request_changes_triggers_loopback(self):
        self.assertTrue(validate_review_for_loopback(_valid_review_report_with_changes()))

    def test_critical_blocking_triggers_loopback(self):
        data = _valid_review_report()
        data["verdict"] = "Approve"
        data["blocking_findings"] = [{"severity": "Critical", "file_path": "x.py", "description": "bad"}]
        self.assertTrue(validate_review_for_loopback(data))

    def test_warning_blocking_no_loopback(self):
        data = _valid_review_report()
        data["blocking_findings"] = [{"severity": "Warning", "file_path": "x.py", "description": "warn"}]
        self.assertFalse(validate_review_for_loopback(data))


class TestRequiredArtifactsValidation(unittest.TestCase):
    def test_missing_required_artifact_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            stage = {"required_artifacts": ["requirement-final.json"]}
            results = validate_required_artifacts(stage, output_dir)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].status, "failed")
            self.assertIn("missing", results[0].message)

    def test_valid_required_artifact_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "requirement-final.json").write_text(
                json.dumps(_valid_requirement(), ensure_ascii=False),
                encoding="utf-8",
            )
            stage = {"required_artifacts": ["requirement-final.json"]}
            results = validate_required_artifacts(stage, output_dir)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].status, "passed")

    def test_invalid_json_artifact_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "requirement-final.json").write_text("not json", encoding="utf-8")
            stage = {"required_artifacts": ["requirement-final.json"]}
            results = validate_required_artifacts(stage, output_dir)
            self.assertEqual(results[0].status, "failed")
            self.assertIn("invalid json", results[0].message)

    def test_schema_invalid_artifact_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "requirement-final.json").write_text(
                json.dumps({"status": "completed", "summary": "test"}),
                encoding="utf-8",
            )
            stage = {"required_artifacts": ["requirement-final.json"]}
            results = validate_required_artifacts(stage, output_dir)
            self.assertEqual(results[0].status, "failed")
            self.assertIn("goals", results[0].message)

    def test_non_json_artifact_just_checks_existence(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "report.md").write_text("# Report", encoding="utf-8")
            stage = {"required_artifacts": ["report.md"]}
            results = validate_required_artifacts(stage, output_dir)
            self.assertEqual(results[0].status, "passed")


class TestHasArtifactValidationFailure(unittest.TestCase):
    def test_no_failure(self):
        results = [ArtifactValidationRun(artifact="a.json", status="passed", message="ok")]
        self.assertFalse(has_artifact_validation_failure(results))

    def test_has_failure(self):
        results = [
            ArtifactValidationRun(artifact="a.json", status="passed", message="ok"),
            ArtifactValidationRun(artifact="b.json", status="failed", message="bad"),
        ]
        self.assertTrue(has_artifact_validation_failure(results))

    def test_empty_results(self):
        self.assertFalse(has_artifact_validation_failure([]))


class TestCurrentContractValidation(unittest.TestCase):
    def test_current_contract_revalidates_historical_schema_valid_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "implementation-report.json").write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "summary": "old runtime-valid report",
                        "changed_files": ["src/app.py"],
                        "tests_run": [],
                        "acceptance_coverage": [],
                        "evidence": [],
                        "risks": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            results = current_contract_validations(output_dir, ["implementation-report.json"])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].artifact, "implementation-report.json")
        self.assertEqual(results[0].validator, "current-schema")
        self.assertEqual(results[0].status, "failed")
        self.assertIn("traceability", results[0].message)
        self.assertIn("acceptance_coverage", results[0].message)


class TestSchemaValidationErrors(unittest.TestCase):
    def test_schema_validation_error_message(self):
        err = SchemaValidationError("test.json", ["field missing", "bad type"])
        self.assertIn("test.json", str(err))
        self.assertIn("field missing", str(err))
        self.assertEqual(err.artifact, "test.json")
        self.assertEqual(len(err.errors), 2)

    def test_validate_artifact_schema_valid(self):
        errors = validate_artifact_schema(_valid_requirement(), "requirement-final.json")
        self.assertEqual(errors, [])

    def test_validate_artifact_schema_invalid(self):
        errors = validate_artifact_schema({"status": "completed"}, "requirement-final.json")
        self.assertTrue(len(errors) > 0)


class TestReleaseReadinessValidation(unittest.TestCase):
    def test_valid_release_readiness(self):
        data = {
            "status": "completed",
            "verdict": "Ready",
            "summary": "所有检查通过",
            "checks": [
                {"name": "requirement", "status": "passed", "source_artifact": "requirement-final.json"},
                {"name": "tests", "status": "passed", "source_artifact": "test-report.json"},
            ],
        }
        errors, status = validate_artifact(data, "release-readiness.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")

    def test_not_ready_with_blocking_issues(self):
        data = {
            "status": "completed",
            "verdict": "Not Ready",
            "summary": "有阻断项",
            "checks": [
                {"name": "requirement", "status": "passed", "source_artifact": "requirement-final.json"},
                {"name": "tests", "status": "failed", "source_artifact": "test-report.json"},
            ],
            "blocking_issues": [
                {"source": "test-report.json", "issue": "测试失败", "severity": "Critical"},
            ],
        }
        errors, status = validate_artifact(data, "release-readiness.json")
        self.assertEqual(status, "passed", f"Errors: {errors}")

    def test_missing_checks_fails(self):
        data = {"status": "completed", "verdict": "Ready", "summary": "test"}
        errors, status = validate_artifact(data, "release-readiness.json")
        self.assertEqual(status, "failed")
        self.assertTrue(any("checks" in e for e in errors))

    def test_empty_checks_fails(self):
        data = {"status": "completed", "verdict": "Ready", "summary": "test", "checks": []}
        errors, status = validate_artifact(data, "release-readiness.json")
        self.assertEqual(status, "failed")


if __name__ == "__main__":
    unittest.main()
