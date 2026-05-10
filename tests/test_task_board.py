from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.models import HumanDecision, RunReport


class TestTaskBoardStateModel(unittest.TestCase):
    def test_records_accepted_rejected_failed_and_cancelled_histories(self) -> None:
        from engine.task_board import TaskEvent, load_tasks, record_task_event

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            accepted = TaskEvent(
                task_id="T-accepted",
                title="Accepted checkout work",
                state="accepted",
                source_stage="acceptance_confirm",
                decision="approved",
                run_id="run-accepted",
                artifact_dir=str(root / ".ai" / "team-output" / "run-accepted"),
                decision_ids=["human:run-accepted:acceptance_confirm:1"],
                requirement="checkout flow",
                tags=["checkout"],
                related_files=["src/checkout.py"],
                decisions=[{"id": "D-1", "summary": "keep checkout flow"}],
            )
            rejected = TaskEvent(
                task_id="T-rejected",
                title="Rejected checkout work",
                state="rejected",
                source_stage="acceptance_confirm",
                decision="rejected",
                run_id="run-rejected",
                artifact_dir=str(root / ".ai" / "team-output" / "run-rejected"),
                decision_ids=["human:run-rejected:acceptance_confirm:1"],
                requirement="checkout flow",
            )
            failed = TaskEvent(
                task_id="T-failed",
                title="QA failed checkout work",
                state="qa_failed",
                source_stage="qa",
                run_id="run-failed",
                artifact_dir=str(root / ".ai" / "team-output" / "run-failed"),
                decision_ids=["run:run-failed:qa:qa_failed"],
                requirement="checkout flow",
            )
            cancelled = TaskEvent(
                task_id="T-cancelled",
                title="Cancelled checkout work",
                state="cancelled",
                source_stage="cancel",
                run_id="run-cancelled",
                artifact_dir=str(root / ".ai" / "team-output" / "run-cancelled"),
                decision_ids=["run:run-cancelled:cancel:cancelled"],
                requirement="checkout flow",
            )

            for event in (accepted, rejected, failed, cancelled):
                record_task_event(root, event)

            tasks = {task.id: task for task in load_tasks(root)}

        self.assertEqual(tasks["T-accepted"].state, "accepted")
        self.assertEqual(tasks["T-rejected"].state, "rejected")
        self.assertEqual(tasks["T-failed"].state, "qa_failed")
        self.assertEqual(tasks["T-cancelled"].state, "cancelled")
        self.assertEqual(tasks["T-accepted"].run_ids, ["run-accepted"])
        self.assertTrue(tasks["T-accepted"].artifact_dirs[0].endswith("run-accepted"))
        self.assertEqual(tasks["T-accepted"].decision_ids, ["human:run-accepted:acceptance_confirm:1"])
        self.assertEqual(len(tasks["T-accepted"].state_history), 1)

    def test_snapshot_is_optional_and_not_required_for_reads(self) -> None:
        from engine.task_board import TaskEvent, build_snapshot, load_tasks, record_task_event

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_task_event(
                root,
                TaskEvent(
                    task_id="T-1",
                    title="Snapshot optional",
                    state="planned",
                    source_stage="planning",
                    run_id="run-1",
                    artifact_dir=str(root / ".ai" / "team-output" / "run-1"),
                    decision_ids=["artifact:run-1:task-plan:task-1"],
                ),
            )
            snapshot_path = root / ".ai" / "harness" / "task-board.json"
            snapshot = build_snapshot(root, write=True)
            self.assertTrue(snapshot_path.exists())
            snapshot_path.unlink()

            tasks = load_tasks(root)

        self.assertEqual(snapshot["summary"]["total"], 1)
        self.assertEqual([task.id for task in tasks], ["T-1"])


class TestTaskBoardAcceptedGuards(unittest.TestCase):
    def test_accepted_requires_final_human_approval(self) -> None:
        from engine.task_board import TaskEvent, TaskStateError, record_task_event

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(TaskStateError):
                record_task_event(
                    root,
                    TaskEvent(
                        task_id="T-bad",
                        title="Bad accepted event",
                        state="accepted",
                        source_stage="qa",
                        run_id="run-bad",
                        artifact_dir=str(root / ".ai" / "team-output" / "run-bad"),
                        decision_ids=["run:run-bad:qa:accepted"],
                    ),
                )

    def test_negative_events_do_not_overwrite_existing_accepted_state(self) -> None:
        from engine.task_board import TaskEvent, load_tasks, record_task_event

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_task_event(
                root,
                TaskEvent(
                    task_id="T-1",
                    title="Stable accepted work",
                    state="accepted",
                    source_stage="acceptance_confirm",
                    decision="approved",
                    run_id="run-1",
                    artifact_dir=str(root / ".ai" / "team-output" / "run-1"),
                    decision_ids=["human:run-1:acceptance_confirm:1"],
                ),
            )
            record_task_event(
                root,
                TaskEvent(
                    task_id="T-1",
                    title="Stable accepted work",
                    state="qa_failed",
                    source_stage="qa",
                    run_id="run-2",
                    artifact_dir=str(root / ".ai" / "team-output" / "run-2"),
                    decision_ids=["run:run-2:qa:qa_failed"],
                ),
            )

            task = load_tasks(root)[0]

        self.assertEqual(task.state, "accepted")
        self.assertEqual(task.run_ids, ["run-1", "run-2"])
        self.assertEqual(len(task.state_history), 2)


class TestRelatedTaskMatching(unittest.TestCase):
    def test_matches_by_text_tags_files_and_decisions(self) -> None:
        from engine.task_board import TaskEvent, find_related_tasks, record_task_event

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_task_event(
                root,
                TaskEvent(
                    task_id="T-checkout",
                    title="Accepted checkout risk decision",
                    state="accepted",
                    source_stage="acceptance_confirm",
                    decision="approved",
                    run_id="run-checkout",
                    artifact_dir=str(root / ".ai" / "team-output" / "run-checkout"),
                    decision_ids=["D-checkout"],
                    requirement="Implement checkout payment flow",
                    tags=["checkout", "payment"],
                    related_files=["src/checkout.py"],
                    decisions=[{"id": "D-checkout", "summary": "Use idempotent payment submit"}],
                ),
            )
            record_task_event(
                root,
                TaskEvent(
                    task_id="T-profile",
                    title="Profile settings",
                    state="accepted",
                    source_stage="acceptance_confirm",
                    decision="approved",
                    run_id="run-profile",
                    artifact_dir=str(root / ".ai" / "team-output" / "run-profile"),
                    decision_ids=["D-profile"],
                    requirement="Update profile settings",
                    tags=["profile"],
                    related_files=["src/profile.py"],
                ),
            )

            related = find_related_tasks(
                root,
                requirement_text="Change checkout payment submit behavior",
                tags=["payment"],
                related_files=["src/checkout.py"],
                decision_ids=["D-checkout"],
            )

        self.assertEqual(related[0]["task_id"], "T-checkout")
        self.assertGreater(related[0]["match_score"], 0)
        self.assertIn("tag:payment", related[0]["match_reasons"])
        self.assertIn("file:src/checkout.py", related[0]["match_reasons"])
        self.assertIn("decision:D-checkout", related[0]["match_reasons"])


class TestTaskBoardTraceability(unittest.TestCase):
    def test_event_requires_run_artifact_dir_and_decision_ids(self) -> None:
        from pydantic import ValidationError

        from engine.task_board import TaskEvent

        with self.assertRaises(ValidationError):
            TaskEvent(
                task_id="T-1",
                title="Missing traceability",
                state="planned",
                source_stage="planning",
                run_id="",
                artifact_dir="",
                decision_ids=[],
            )

    def test_record_run_task_event_extracts_accepted_traceability(self) -> None:
        from engine.task_board import load_tasks, record_run_task_event

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / ".ai" / "team-output" / "run-accepted"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "requirement-final.json").write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "summary": "Checkout accepted",
                        "goals": [{"id": "G-1", "description": "Checkout"}],
                        "non_goals": [],
                        "scope": {"included": ["checkout"], "excluded": []},
                        "acceptance_criteria": [
                            {"id": "AC-001", "description": "Checkout works", "verification_method": "pytest"}
                        ],
                        "risks": [{"risk": "double submit", "impact": "duplicate payment"}],
                        "decisions": [{"topic": "payment", "decision": "use idempotency key"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report = RunReport(
                run_id="run-accepted",
                status="completed",
                requirement="Implement checkout",
                project_root=str(root),
                output_dir=str(artifact_dir),
                config_source="default",
                human_decisions=[
                    HumanDecision(stage_id="acceptance_confirm", decision="approved", reason="验收通过")
                ],
                changed_files=["src/checkout.py"],
            )

            record_run_task_event(root, report, artifact_dir, state="accepted", source_stage="acceptance_confirm")
            task = load_tasks(root)[0]

        self.assertEqual(task.state, "accepted")
        self.assertEqual(task.run_id, "run-accepted")
        self.assertEqual(task.artifact_dir, str(artifact_dir))
        self.assertIn("human:run-accepted:acceptance_confirm:1", task.decision_ids)
        self.assertEqual(task.related_files, ["src/checkout.py"])


if __name__ == "__main__":
    unittest.main()
