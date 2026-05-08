from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from engine.pr_manager import (
    PRDescriptionBuilder,
    PRManager,
    PRManagerError,
    GitHubPRProvider,
    GitLabPRProvider,
)


class TestPRDescriptionBuilder(unittest.TestCase):
    def test_build_minimal(self) -> None:
        summary = {"run_id": "r1", "requirement": "fix bug", "changed_files": [], "diff_stat": "", "stages": []}
        body = PRDescriptionBuilder.build(summary)
        self.assertIn("fix bug", body)
        self.assertIn("r1", body)
        self.assertIn("需求", body)
        self.assertIn("回滚步骤", body)
        self.assertIn("风险评估", body)

    def test_build_with_files_and_stages(self) -> None:
        summary = {
            "run_id": "r2",
            "requirement": "add feature",
            "changed_files": ["src/main.py", "tests/test_main.py"],
            "diff_stat": "2 files changed",
            "duration_seconds": 42.5,
            "stages": [
                {"stage_id": "develop", "stage_name": "develop", "status": "completed"},
                {"stage_id": "review", "stage_name": "review", "status": "completed", "agents": [{"agent_name": "reviewer", "status": "completed"}]},
            ],
        }
        body = PRDescriptionBuilder.build(summary)
        self.assertIn("src/main.py", body)
        self.assertIn("tests/test_main.py", body)
        self.assertIn("develop", body)
        self.assertIn("COMPLETED", body)
        self.assertIn("42.5s", body)
        self.assertIn("review", body)
        self.assertIn("reviewer", body)

    def test_build_with_quality_gates(self) -> None:
        summary = {
            "run_id": "r3",
            "requirement": "req",
            "changed_files": [],
            "diff_stat": "",
            "stages": [
                {"stage_id": "develop", "stage_name": "develop", "status": "completed",
                 "quality_gates": [{"name": "lint", "status": "passed"}, {"name": "test", "status": "failed"}]},
            ],
        }
        body = PRDescriptionBuilder.build(summary)
        self.assertIn("lint", body)
        self.assertIn("test", body)

    def test_extract_test_results_empty(self) -> None:
        result = PRDescriptionBuilder._extract_test_results([])
        self.assertEqual(result, [])

    def test_extract_risks_no_review(self) -> None:
        result = PRDescriptionBuilder._extract_risks([{"stage_id": "develop"}])
        self.assertEqual(result, [])


class TestGitHubPRProviderCreatePR(unittest.TestCase):
    def test_create_pr_success(self) -> None:
        provider = GitHubPRProvider()
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            view_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
            create_result = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="https://github.com/o/r/pull/42\n", stderr=""
            )
            with patch.object(provider, "_run_gh", side_effect=[view_result, create_result]):
                result = provider.create_pr(str(wt), "title", "body")
                self.assertEqual(result["status"], "created")
                self.assertEqual(result["number"], 42)

    def test_create_pr_existing(self) -> None:
        provider = GitHubPRProvider()
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            view_result = subprocess.CompletedProcess(args=[], returncode=0, stdout='{"number":42}', stderr="")
            with patch.object(provider, "_run_gh", return_value=view_result):
                result = provider.create_pr(str(wt), "title", "body")
                self.assertEqual(result["status"], "existing")

    def test_create_pr_nonexistent_path(self) -> None:
        provider = GitHubPRProvider()
        with self.assertRaises(PRManagerError):
            provider.create_pr("/nonexistent", "title", "body")

    def test_create_pr_failure(self) -> None:
        provider = GitHubPRProvider()
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            view_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
            create_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
            with patch.object(provider, "_run_gh", side_effect=[view_result, create_result]):
                with self.assertRaises(PRManagerError):
                    provider.create_pr(str(wt), "title", "body")


class TestGitHubPRProviderCheckCI(unittest.TestCase):
    def test_all_passed(self) -> None:
        provider = GitHubPRProvider()
        checks_json = '[{"name":"ci","status":"completed","conclusion":"success"}]'
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f'{{"statusCheckRollup":{checks_json}}}', stderr=""
        )
        with patch.object(provider, "_run_gh", return_value=mock_result):
            result = provider.check_ci(1)
            self.assertEqual(result["status"], "passed")

    def test_failed_check(self) -> None:
        provider = GitHubPRProvider()
        checks_json = '[{"name":"ci","status":"completed","conclusion":"failure"}]'
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f'{{"statusCheckRollup":{checks_json}}}', stderr=""
        )
        with patch.object(provider, "_run_gh", return_value=mock_result):
            result = provider.check_ci(1)
            self.assertEqual(result["status"], "failed")
            self.assertIn("ci", result["failed"])

    def test_pending_check(self) -> None:
        provider = GitHubPRProvider()
        checks_json = '[{"name":"ci","status":"in_progress","conclusion":null}]'
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f'{{"statusCheckRollup":{checks_json}}}', stderr=""
        )
        with patch.object(provider, "_run_gh", return_value=mock_result):
            result = provider.check_ci(1)
            self.assertEqual(result["status"], "pending")

    def test_no_checks(self) -> None:
        provider = GitHubPRProvider()
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"statusCheckRollup":[]}', stderr=""
        )
        with patch.object(provider, "_run_gh", return_value=mock_result):
            result = provider.check_ci(1)
            self.assertEqual(result["status"], "no_checks")

    def test_gh_failure(self) -> None:
        provider = GitHubPRProvider()
        mock_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
        with patch.object(provider, "_run_gh", return_value=mock_result):
            result = provider.check_ci(1)
            self.assertEqual(result["status"], "unknown")

    def test_bad_json(self) -> None:
        provider = GitHubPRProvider()
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="not json", stderr="")
        with patch.object(provider, "_run_gh", return_value=mock_result):
            result = provider.check_ci(1)
            self.assertEqual(result["status"], "unknown")


class TestGitHubPRProviderWaitCI(unittest.TestCase):
    def test_wait_ci_immediate_pass(self) -> None:
        provider = GitHubPRProvider()
        with patch.object(provider, "check_ci", return_value={"status": "passed", "checks": []}):
            result = provider.wait_ci(1, timeout=1, poll_interval=1)
            self.assertEqual(result["status"], "passed")

    def test_wait_ci_immediate_fail(self) -> None:
        provider = GitHubPRProvider()
        with patch.object(provider, "check_ci", return_value={"status": "failed", "checks": []}):
            result = provider.wait_ci(1, timeout=1, poll_interval=1)
            self.assertEqual(result["status"], "failed")

    def test_wait_ci_timeout(self) -> None:
        provider = GitHubPRProvider()
        with patch.object(provider, "check_ci", return_value={"status": "pending", "checks": []}):
            result = provider.wait_ci(1, timeout=1, poll_interval=1)
            self.assertEqual(result["status"], "timeout")

    def test_wait_ci_transition_to_pass(self) -> None:
        provider = GitHubPRProvider()
        call_count = 0
        original_check = provider.check_ci

        def mock_check(pr_number):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                return {"status": "passed", "checks": []}
            return {"status": "pending", "checks": []}

        with patch.object(provider, "check_ci", side_effect=mock_check):
            result = provider.wait_ci(1, timeout=30, poll_interval=0)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(call_count, 2)


class TestGitHubPRProviderGetStatus(unittest.TestCase):
    def test_get_status_open(self) -> None:
        provider = GitHubPRProvider()
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"state":"OPEN","mergedAt":null}', stderr=""
        )
        with patch.object(provider, "_run_gh", return_value=mock_result):
            result = provider.get_pr_status(1)
            self.assertEqual(result["state"], "OPEN")
            self.assertFalse(result["merged"])

    def test_get_status_merged(self) -> None:
        provider = GitHubPRProvider()
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"state":"MERGED","mergedAt":"2024-01-01"}', stderr=""
        )
        with patch.object(provider, "_run_gh", return_value=mock_result):
            result = provider.get_pr_status(1)
            self.assertTrue(result["merged"])


class TestGitLabPRProvider(unittest.TestCase):
    def test_check_ci_success(self) -> None:
        provider = GitLabPRProvider({"gitlab_url": "https://gitlab.com", "gitlab_token": "tok", "project_id": 1})
        mock_response = [{"status": "success", "id": 1}]
        with patch.object(provider, "_request", return_value=mock_response):
            result = provider.check_ci(1)
            self.assertEqual(result["status"], "passed")

    def test_check_ci_failed(self) -> None:
        provider = GitLabPRProvider({"gitlab_url": "https://gitlab.com", "gitlab_token": "tok", "project_id": 1})
        mock_response = [{"status": "failed", "id": 1}]
        with patch.object(provider, "_request", return_value=mock_response):
            result = provider.check_ci(1)
            self.assertEqual(result["status"], "failed")

    def test_check_ci_no_pipelines(self) -> None:
        provider = GitLabPRProvider({"gitlab_url": "https://gitlab.com", "gitlab_token": "tok", "project_id": 1})
        with patch.object(provider, "_request", return_value=[]):
            result = provider.check_ci(1)
            self.assertEqual(result["status"], "no_checks")

    def test_check_ci_api_error(self) -> None:
        provider = GitLabPRProvider({"gitlab_url": "https://gitlab.com", "gitlab_token": "tok", "project_id": 1})
        with patch.object(provider, "_request", side_effect=PRManagerError("api error")):
            result = provider.check_ci(1)
            self.assertEqual(result["status"], "no_checks")

    def test_get_pr_status_merged(self) -> None:
        provider = GitLabPRProvider({"gitlab_url": "https://gitlab.com", "gitlab_token": "tok", "project_id": 1})
        with patch.object(provider, "_request", return_value={"state": "merged", "iid": 1}):
            result = provider.get_pr_status(1)
            self.assertTrue(result["merged"])

    def test_get_pr_status_open(self) -> None:
        provider = GitLabPRProvider({"gitlab_url": "https://gitlab.com", "gitlab_token": "tok", "project_id": 1})
        with patch.object(provider, "_request", return_value={"state": "opened", "iid": 1}):
            result = provider.get_pr_status(1)
            self.assertFalse(result["merged"])


class TestPRManager(unittest.TestCase):
    def test_create_pr_github(self) -> None:
        mgr = PRManager({"provider": "github"})
        self.assertIsInstance(mgr._provider, GitHubPRProvider)

    def test_create_pr_gitlab(self) -> None:
        mgr = PRManager({"provider": "gitlab", "gitlab_token": "tok", "project_id": 1})
        self.assertIsInstance(mgr._provider, GitLabPRProvider)

    def test_create_pr_default_github(self) -> None:
        mgr = PRManager({})
        self.assertIsInstance(mgr._provider, GitHubPRProvider)

    def test_create_pr_handles_error(self) -> None:
        mgr = PRManager({"provider": "github"})
        with patch.object(mgr._provider, "create_pr", side_effect=PRManagerError("fail")):
            result = mgr.create_pr("/tmp", {"run_id": "r1", "requirement": "req"})
            self.assertEqual(result["status"], "failed")
            self.assertIn("fail", result["error"])

    def test_create_pr_builds_description(self) -> None:
        mgr = PRManager({"provider": "github"})
        summary = {"run_id": "r1", "requirement": "test req", "changed_files": ["a.py"], "diff_stat": "", "stages": []}
        with patch.object(mgr._provider, "create_pr", return_value={"status": "created", "number": 1}) as mock:
            mgr.create_pr("/tmp", summary)
            call_args = mock.call_args
            body = call_args[1].get("body") if "body" in (call_args[1] or {}) else call_args[0][2]
            self.assertIn("test req", body)

    def test_check_ci_delegates(self) -> None:
        mgr = PRManager({"provider": "github"})
        with patch.object(mgr._provider, "check_ci", return_value={"status": "passed", "checks": []}):
            result = mgr.check_ci(1)
            self.assertEqual(result["status"], "passed")

    def test_wait_ci_delegates(self) -> None:
        mgr = PRManager({"provider": "github"})
        with patch.object(mgr._provider, "wait_ci", return_value={"status": "passed", "checks": []}):
            result = mgr.wait_ci(1, timeout=1, poll_interval=1)
            self.assertEqual(result["status"], "passed")

    def test_get_pr_status_delegates(self) -> None:
        mgr = PRManager({"provider": "github"})
        with patch.object(mgr._provider, "get_pr_status", return_value={"state": "OPEN", "merged": False}):
            result = mgr.get_pr_status(1)
            self.assertEqual(result["state"], "OPEN")


class TestOrchestratorDeliverPR(unittest.TestCase):
    def test_deliver_pr_commits_and_pushes(self) -> None:
        from engine.orchestrator import Orchestrator

        mock_wt_mgr = MagicMock()
        mock_wt_mgr.has_changes.return_value = True
        mock_wt_mgr.push_branch.return_value = {"status": "pushed", "branch": "ai-team/r-push"}

        mock_report = MagicMock()
        mock_report.run_id = "r-push"
        mock_report.requirement = "req"
        mock_report.changed_files = ["a.py"]
        mock_report.diff_stat = "1 file"
        mock_report.duration_seconds = 1.0
        mock_report.stages = []

        mock_pr_result = {"status": "created", "url": "https://github.com/o/r/pull/1", "number": 1}
        with patch("engine.pr_manager.PRManager") as MockPRManager:
            mock_pm_instance = MockPRManager.return_value
            mock_pm_instance.create_pr.return_value = mock_pr_result

            orch = MagicMock(spec=Orchestrator)
            orch.config = {"ci_cd": {"create_pr": True}}
            orch.bus = MagicMock()
            orch._deliver_pr = Orchestrator._deliver_pr.__get__(orch, Orchestrator)

            result = orch._deliver_pr(mock_wt_mgr, Path("/tmp/wt"), mock_report, Path("/tmp/out"))
            self.assertEqual(result["status"], "created")
            mock_wt_mgr.commit_all.assert_called_once()
            mock_wt_mgr.push_branch.assert_called_once()
            mock_pm_instance.create_pr.assert_called_once()

    def test_deliver_pr_blocked_on_ci_failure(self) -> None:
        from engine.orchestrator import Orchestrator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            config = {"ci_cd": {"create_pr": True, "wait_for_checks": True}}

            mock_wt_mgr = MagicMock()
            mock_wt_mgr.has_changes.return_value = False

            mock_report = MagicMock()
            mock_report.run_id = "r-blocked"
            mock_report.requirement = "req"
            mock_report.changed_files = []
            mock_report.diff_stat = ""
            mock_report.duration_seconds = 1.0
            mock_report.stages = []

            mock_ci_result = {"status": "failed", "checks": [], "failed": ["lint"]}

            with patch("engine.pr_manager.PRManager") as MockPRManager:
                mock_pm = MockPRManager.return_value
                mock_pm.create_pr.return_value = {"status": "created", "number": 5}
                mock_pm.wait_ci.return_value = mock_ci_result

                orch = MagicMock(spec=Orchestrator)
                orch.config = config
                orch.bus = MagicMock()
                orch._deliver_pr = Orchestrator._deliver_pr.__get__(orch, Orchestrator)

                result = orch._deliver_pr(mock_wt_mgr, Path("/tmp/wt"), mock_report, Path("/tmp/out"))
                self.assertEqual(result["status"], "blocked")
                mock_pm.wait_ci.assert_called_once()

    def test_deliver_pr_push_failure(self) -> None:
        from engine.orchestrator import Orchestrator
        from engine.worktree import WorktreeError

        config = {"ci_cd": {"create_pr": True}}
        mock_wt_mgr = MagicMock()
        mock_wt_mgr.has_changes.return_value = False
        mock_wt_mgr.push_branch.side_effect = WorktreeError("push failed")

        mock_report = MagicMock()
        mock_report.run_id = "r-fail"
        mock_report.requirement = "req"
        mock_report.changed_files = []
        mock_report.diff_stat = ""
        mock_report.duration_seconds = 1.0
        mock_report.stages = []

        orch = MagicMock(spec=Orchestrator)
        orch.config = config
        orch.bus = MagicMock()
        orch._deliver_pr = Orchestrator._deliver_pr.__get__(orch, Orchestrator)

        result = orch._deliver_pr(mock_wt_mgr, Path("/tmp/wt"), mock_report, Path("/tmp/out"))
        self.assertEqual(result["status"], "failed")
        self.assertIn("push failed", result["error"])


if __name__ == "__main__":
    unittest.main()
