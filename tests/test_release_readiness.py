from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.models import (
    AgentRun,
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
    )


class TestReleaseReadiness(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.output_dir = Path(self.tmpdir) / "test-run-001"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def test_ready_when_all_pass(self):
        stage = StageRun(
            stage_id="develop",
            stage_name="Develop",
            status="completed",
            quality_gates=[
                QualityGateRun(name="lint", type="command", status="passed", required=True),
            ],
            human_decision=HumanDecision(stage_id="acceptance_confirm", decision="approved"),
            type="human_review",
        )
        report = _make_report(stages=[stage])
        result = generate_release_readiness(report, self.output_dir)
        self.assertTrue(result["ready"])
        self.assertTrue(result["checks"]["quality_gates"]["passed"])
        self.assertTrue(result["checks"]["human_approvals"]["passed"])
        self.assertTrue(result["checks"]["artifacts"]["passed"])
        readiness_file = self.output_dir / "release-readiness.json"
        self.assertTrue(readiness_file.exists())
        parsed = json.loads(readiness_file.read_text(encoding="utf-8"))
        self.assertTrue(parsed["ready"])

    def test_not_ready_when_run_failed(self):
        report = _make_report(status="failed")
        result = generate_release_readiness(report, self.output_dir)
        self.assertFalse(result["ready"])
        self.assertEqual(result["run_status"], "failed")

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
        self.assertFalse(result["ready"])
        self.assertFalse(result["checks"]["quality_gates"]["passed"])
        self.assertEqual(len(result["checks"]["quality_gates"]["failures"]), 1)

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
        self.assertFalse(result["ready"])
        self.assertFalse(result["checks"]["human_approvals"]["passed"])
        self.assertEqual(len(result["checks"]["human_approvals"]["missing"]), 1)

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
        self.assertFalse(result["ready"])

    def test_not_ready_when_artifact_missing(self):
        report = _make_report(artifacts=["missing-file.txt"])
        result = generate_release_readiness(report, self.output_dir)
        self.assertFalse(result["ready"])
        self.assertFalse(result["checks"]["artifacts"]["passed"])
        self.assertEqual(len(result["checks"]["artifacts"]["missing"]), 1)

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
        self.assertTrue(result["checks"]["quality_gates"]["passed"])

    def test_stages_count(self):
        stages = [
            StageRun(stage_id="scan", stage_name="Scan", status="completed"),
            StageRun(stage_id="develop", stage_name="Develop", status="completed"),
            StageRun(stage_id="qa", stage_name="QA", status="failed"),
        ]
        report = _make_report(stages=stages)
        result = generate_release_readiness(report, self.output_dir)
        self.assertEqual(result["stages_completed"], 2)
        self.assertEqual(result["stages_total"], 3)
