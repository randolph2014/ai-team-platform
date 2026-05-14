from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.artifact_contracts import validate_artifact
from engine.models import (
    HumanDecision,
    QualityGateRun,
    RunReport,
    StageRun,
)
from engine.release_readiness import generate_release_readiness


def _make_report(
    status="completed",
    stages=None,
    artifacts=None,
    human_decisions=None,
) -> RunReport:
    return RunReport(
        run_id="test-run-001",
        status=status,
        requirement="test requirement",
        project_root="/tmp/test-project",
        output_dir="/tmp/test-output/test-run-001",
        config_source="default",
        stages=stages or [],
        artifacts=artifacts or [],
        human_decisions=human_decisions or [],
    )


def _check(result, name):
    return next(item for item in result["checks"] if item["name"] == name)


class TestReleaseReadiness(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.output_dir = Path(self.tmpdir) / "test-run-001"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def test_ready_when_all_pass(self):
        stages = [
            StageRun(
                stage_id="develop",
                stage_name="Develop",
                status="completed",
                quality_gates=[
                    QualityGateRun(name="lint", type="command", status="passed", required=True),
                ],
            ),
            StageRun(
                stage_id="acceptance_confirm",
                stage_name="Acceptance",
                status="completed",
                human_decision=HumanDecision(stage_id="acceptance_confirm", decision="approved"),
                type="human_review",
            ),
        ]
        report = _make_report(stages=stages)
        result = generate_release_readiness(report, self.output_dir)
        self.assertEqual(result["verdict"], "Ready")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(_check(result, "quality_gates")["status"], "passed")
        self.assertEqual(_check(result, "human_approvals")["status"], "passed")
        self.assertEqual(_check(result, "artifacts")["status"], "passed")
        readiness_file = self.output_dir / "release-readiness.json"
        self.assertTrue(readiness_file.exists())
        parsed = json.loads(readiness_file.read_text(encoding="utf-8"))
        self.assertEqual(parsed["verdict"], "Ready")

    def test_generated_artifact_matches_current_schema(self):
        stage = StageRun(
            stage_id="acceptance_confirm",
            stage_name="Acceptance",
            status="completed",
            type="human_review",
            human_decision=HumanDecision(stage_id="acceptance_confirm", decision="approved"),
        )
        report = _make_report(stages=[stage])
        result = generate_release_readiness(report, self.output_dir)

        errors, status = validate_artifact(result, "release-readiness.json")

        self.assertEqual(status, "passed", f"Errors: {errors}")

    def test_human_approvals_use_decision_history_when_stage_decision_missing(self):
        stages = [
            StageRun(
                stage_id="requirement_confirm",
                stage_name="Requirement Confirm",
                status="completed",
                type="human_review",
            ),
            StageRun(
                stage_id="task_plan_confirm",
                stage_name="Task Plan Confirm",
                status="completed",
                type="human_review",
            ),
            StageRun(
                stage_id="acceptance_confirm",
                stage_name="Acceptance",
                status="waiting",
                type="human_review",
                human_decision=HumanDecision(stage_id="acceptance_confirm", decision="waiting"),
            ),
        ]
        report = _make_report(
            status="paused",
            stages=stages,
            human_decisions=[
                HumanDecision(stage_id="requirement_confirm", decision="approved"),
                HumanDecision(stage_id="task_plan_confirm", decision="approved"),
            ],
        )

        result = generate_release_readiness(report, self.output_dir)

        self.assertEqual(_check(result, "human_approvals")["status"], "failed")
        issues = [item["issue"] for item in result["blocking_issues"]]
        self.assertIn("human review acceptance_confirm is waiting", issues)
        self.assertNotIn("human review requirement_confirm is pending", issues)
        self.assertNotIn("human review task_plan_confirm is pending", issues)

    def test_not_ready_when_run_failed(self):
        report = _make_report(status="failed")
        result = generate_release_readiness(report, self.output_dir)
        self.assertEqual(result["verdict"], "Not Ready")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(_check(result, "run_status")["status"], "failed")

    def test_not_ready_when_gate_failed(self):
        stage = StageRun(
            stage_id="qa",
            stage_name="QA",
            status="completed",
            quality_gates=[
                QualityGateRun(name="test", type="command", status="failed", required=True),
            ],
        )
        report = _make_report(stages=[stage])
        result = generate_release_readiness(report, self.output_dir)
        self.assertEqual(result["verdict"], "Not Ready")
        self.assertEqual(_check(result, "quality_gates")["status"], "failed")
        self.assertIn("quality gate test failed in stage qa", [item["issue"] for item in result["blocking_issues"]])

    def test_not_ready_when_completed_develop_has_no_quality_gate_evidence(self):
        stage = StageRun(
            stage_id="develop",
            stage_name="Develop",
            status="completed",
            quality_gates=[],
        )
        report = _make_report(stages=[stage])

        result = generate_release_readiness(report, self.output_dir)

        self.assertEqual(result["verdict"], "Not Ready")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(_check(result, "quality_gates")["status"], "failed")
        self.assertIn(
            "quality gate evidence is missing for completed stage develop",
            [item["issue"] for item in result["blocking_issues"]],
        )

    def test_not_ready_when_human_approval_missing(self):
        stage = StageRun(
            stage_id="acceptance_confirm",
            stage_name="Acceptance",
            status="completed",
            type="human_review",
            human_decision=None,
        )
        report = _make_report(stages=[stage])
        result = generate_release_readiness(report, self.output_dir)
        self.assertEqual(result["verdict"], "Not Ready")
        self.assertEqual(_check(result, "human_approvals")["status"], "failed")
        self.assertIn("human review acceptance_confirm is pending", [item["issue"] for item in result["blocking_issues"]])

    def test_not_ready_when_human_rejected(self):
        stage = StageRun(
            stage_id="acceptance_confirm",
            stage_name="Acceptance",
            status="completed",
            type="human_review",
            human_decision=HumanDecision(stage_id="acceptance_confirm", decision="rejected", reason="bad"),
        )
        report = _make_report(stages=[stage])
        result = generate_release_readiness(report, self.output_dir)
        self.assertEqual(result["verdict"], "Not Ready")
        self.assertIn("human review acceptance_confirm is rejected", [item["issue"] for item in result["blocking_issues"]])

    def test_not_ready_when_artifact_missing(self):
        report = _make_report(artifacts=["missing-file.txt"])
        result = generate_release_readiness(report, self.output_dir)
        self.assertEqual(result["verdict"], "Not Ready")
        self.assertEqual(_check(result, "artifacts")["status"], "failed")
        self.assertIn("artifact missing-file.txt is missing", [item["issue"] for item in result["blocking_issues"]])

    def test_optional_gate_failure_does_not_block(self):
        stage = StageRun(
            stage_id="develop",
            stage_name="Develop",
            status="completed",
            quality_gates=[
                QualityGateRun(name="lint", type="command", status="failed", required=False),
            ],
        )
        report = _make_report(stages=[stage])
        result = generate_release_readiness(report, self.output_dir)
        self.assertEqual(_check(result, "quality_gates")["status"], "passed")

    def test_stages_count(self):
        stages = [
            StageRun(stage_id="scan", stage_name="Scan", status="completed"),
            StageRun(stage_id="develop", stage_name="Develop", status="completed"),
            StageRun(stage_id="qa", stage_name="QA", status="failed"),
        ]
        report = _make_report(stages=stages)
        result = generate_release_readiness(report, self.output_dir)
        self.assertIn("2/3 stages completed", result["summary"])
