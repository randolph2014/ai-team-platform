from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.ci_cd import CICDError, GitHubIntegration, run_ci_cd_hook


class TestGitHubIntegrationCreatePR(unittest.TestCase):
    def test_create_pr_success(self) -> None:
        """gh pr create 成功时返回 created status 和 url"""
        gi = GitHubIntegration({"provider": "github", "create_pr": True})
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            pr_view_result = subprocess.CompletedProcess(
                args=["gh", "pr", "view"],
                returncode=1,  # PR does not exist yet
                stdout="",
                stderr="no pull request for current branch",
            )
            create_result = subprocess.CompletedProcess(
                args=["gh", "pr", "create"],
                returncode=0,
                stdout="https://github.com/owner/repo/pull/42\n",
                stderr="",
            )
            with patch("engine.ci_cd.GitHubIntegration._run_gh", side_effect=[pr_view_result, create_result]):
                result = gi.create_pr(str(wt), "test title", "test body")
                self.assertEqual(result["status"], "created")
                self.assertEqual(result["url"], "https://github.com/owner/repo/pull/42")
                self.assertEqual(result["number"], 42)

    def test_create_pr_non_existent_path(self) -> None:
        """不存在的 worktree 路径应抛出 CICDError"""
        gi = GitHubIntegration({"create_pr": True})
        with self.assertRaises(CICDError):
            gi.create_pr("/nonexistent/path", "title", "body")

    def test_create_pr_gh_failure(self) -> None:
        """gh pr create 失败应抛出 CICDError"""
        gi = GitHubIntegration({"create_pr": True})
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            mock_result = subprocess.CompletedProcess(
                args=["gh", "pr", "create"],
                returncode=1,
                stdout="",
                stderr="GitHub CLI error",
            )
            with patch("engine.ci_cd.GitHubIntegration._run_gh", return_value=mock_result):
                with self.assertRaises(CICDError) as ctx:
                    gi.create_pr(str(wt), "title", "body")
                self.assertIn("GitHub CLI error", str(ctx.exception))

    def test_create_pr_already_exists(self) -> None:
        """PR 已存在时返回 existing status"""
        gi = GitHubIntegration({"create_pr": True})
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            view_result = subprocess.CompletedProcess(
                args=["gh", "pr", "view"],
                returncode=0,
                stdout='{"number":42}',
                stderr="",
            )
            with patch("engine.ci_cd.GitHubIntegration._run_gh", return_value=view_result):
                result = gi.create_pr(str(wt), "title", "body")
                self.assertEqual(result["status"], "existing")

    def test_create_pr_custom_base(self) -> None:
        """自定义 base branch 参数"""
        gi = GitHubIntegration({"create_pr": True})
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            pr_view_result = subprocess.CompletedProcess(
                args=["gh", "pr", "view"],
                returncode=1,
                stdout="",
                stderr="",
            )
            create_result = subprocess.CompletedProcess(
                args=["gh", "pr", "create"],
                returncode=0,
                stdout="https://github.com/owner/repo/pull/10\n",
                stderr="",
            )
            with patch("engine.ci_cd.GitHubIntegration._run_gh", side_effect=[pr_view_result, create_result]) as mock_run:
                result = gi.create_pr(str(wt), "title", "body", base="develop")
                self.assertEqual(result["status"], "created")
                call_args_list = mock_run.call_args_list
                found_base = any("--base" in call[0][0] and "develop" in call[0][0] for call in call_args_list)
                self.assertTrue(found_base)


class TestGitHubIntegrationMergePR(unittest.TestCase):
    def test_merge_pr_success(self) -> None:
        """gh pr merge 成功"""
        gi = GitHubIntegration()
        mock_result = subprocess.CompletedProcess(
            args=["gh", "pr", "merge"],
            returncode=0,
            stdout="Merged\n",
            stderr="",
        )
        with patch("engine.ci_cd.GitHubIntegration._run_gh", return_value=mock_result):
            result = gi.merge_pr(42)
            self.assertEqual(result["status"], "merged")
            self.assertEqual(result["pr_number"], 42)

    def test_merge_pr_failure(self) -> None:
        """gh pr merge 失败应抛出 CICDError"""
        gi = GitHubIntegration()
        mock_result = subprocess.CompletedProcess(
            args=["gh", "pr", "merge"],
            returncode=1,
            stdout="",
            stderr="Merge conflict",
        )
        with patch("engine.ci_cd.GitHubIntegration._run_gh", return_value=mock_result):
            with self.assertRaises(CICDError) as ctx:
                gi.merge_pr(99)
            self.assertIn("Merge conflict", str(ctx.exception))

    def test_merge_pr_custom_method(self) -> None:
        """自定义 merge 策略"""
        gi = GitHubIntegration()
        mock_result = subprocess.CompletedProcess(
            args=["gh", "pr", "merge"],
            returncode=0,
            stdout="",
            stderr="",
        )
        with patch("engine.ci_cd.GitHubIntegration._run_gh", return_value=mock_result) as mock_run:
            result = gi.merge_pr(1, method="rebase")
            self.assertEqual(result["status"], "merged")
            self.assertEqual(result["method"], "rebase")


class TestGitHubIntegrationChecks(unittest.TestCase):
    def test_list_pr_checks_success(self) -> None:
        """列出 PR checks"""
        gi = GitHubIntegration()
        checks_json = '[{"name":"lint","status":"completed","conclusion":"success"}]'
        mock_result = subprocess.CompletedProcess(
            args=["gh", "pr", "view"],
            returncode=0,
            stdout=f'{{"statusCheckRollup":{checks_json}}}',
            stderr="",
        )
        with patch("engine.ci_cd.GitHubIntegration._run_gh", return_value=mock_result):
            checks = gi.list_pr_checks(42)
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0]["name"], "lint")

    def test_list_pr_checks_failure(self) -> None:
        """gh pr view 失败应抛出 CICDError"""
        gi = GitHubIntegration()
        mock_result = subprocess.CompletedProcess(
            args=["gh", "pr", "view"],
            returncode=1,
            stdout="",
            stderr="Not found",
        )
        with patch("engine.ci_cd.GitHubIntegration._run_gh", return_value=mock_result):
            with self.assertRaises(CICDError):
                gi.list_pr_checks(999)

    def test_list_pr_checks_bad_json(self) -> None:
        """JSON 解析失败返回空列表"""
        gi = GitHubIntegration()
        mock_result = subprocess.CompletedProcess(
            args=["gh", "pr", "view"],
            returncode=0,
            stdout="not json",
            stderr="",
        )
        with patch("engine.ci_cd.GitHubIntegration._run_gh", return_value=mock_result):
            checks = gi.list_pr_checks(42)
            self.assertEqual(checks, [])


class TestGitHubIntegrationEnabled(unittest.TestCase):
    def test_enabled_with_create_pr(self) -> None:
        """create_pr: true 时 enabled() 返回 True"""
        gi = GitHubIntegration({"create_pr": True})
        self.assertTrue(gi.enabled())

    def test_disabled_by_default(self) -> None:
        """默认配置 enabled() 返回 False"""
        gi = GitHubIntegration()
        self.assertFalse(gi.enabled())

    def test_disabled_with_false(self) -> None:
        """create_pr: false 时 enabled() 返回 False"""
        gi = GitHubIntegration({"create_pr": False})
        self.assertFalse(gi.enabled())


class TestRunCICDHook(unittest.TestCase):
    def test_skipped_when_disabled(self) -> None:
        """ci_cd.create_pr 未启用时跳过"""
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            result = run_ci_cd_hook({}, str(wt), {"run_id": "test", "requirement": "req"})
            self.assertEqual(result["status"], "skipped")

    def test_failed_when_gh_unavailable(self) -> None:
        """gh CLI 不可用时返回 failed"""
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            fail_result = subprocess.CompletedProcess(
                args=["gh", "pr", "create"],
                returncode=1,
                stdout="",
                stderr="gh: command not found",
            )
            pr_view_result = subprocess.CompletedProcess(
                args=["gh", "pr", "view"],
                returncode=1,
                stdout="",
                stderr="",
            )
            with patch("engine.ci_cd.GitHubIntegration._run_gh", side_effect=[pr_view_result, fail_result]):
                result = run_ci_cd_hook(
                    {"ci_cd": {"create_pr": True}},
                    str(wt),
                    {"run_id": "test", "requirement": "req", "duration_seconds": 1.0, "stages": []},
                )
                self.assertEqual(result["status"], "failed")
                self.assertIn("error", result)

    def test_auto_merge_on_success(self) -> None:
        """auto_merge: true 且 PR 创建成功后自动合并"""
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            pr_view_result = subprocess.CompletedProcess(
                args=["gh", "pr", "view"],
                returncode=1,
                stdout="",
                stderr="",
            )
            create_result = subprocess.CompletedProcess(
                args=["gh", "pr", "create"],
                returncode=0,
                stdout="https://github.com/owner/repo/pull/7\n",
                stderr="",
            )
            merge_result = subprocess.CompletedProcess(
                args=["gh", "pr", "merge"],
                returncode=0,
                stdout="",
                stderr="",
            )
            with patch("engine.ci_cd.GitHubIntegration._run_gh", side_effect=[pr_view_result, create_result, merge_result]):
                result = run_ci_cd_hook(
                    {"ci_cd": {"create_pr": True, "auto_merge": True}},
                    str(wt),
                    {"run_id": "test", "requirement": "req", "duration_seconds": 1.0, "stages": []},
                )
                self.assertEqual(result["status"], "created")
                self.assertIn("merge", result)
                self.assertEqual(result["merge"]["status"], "merged")

    def test_wait_for_checks_flag(self) -> None:
        """wait_for_checks: true 时拉取 CI checks 到结果中"""
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            pr_view_result = subprocess.CompletedProcess(
                args=["gh", "pr", "view"],
                returncode=1,
                stdout="",
                stderr="",
            )
            create_result = subprocess.CompletedProcess(
                args=["gh", "pr", "create"],
                returncode=0,
                stdout="https://github.com/owner/repo/pull/3\n",
                stderr="",
            )
            checks_result = subprocess.CompletedProcess(
                args=["gh", "pr", "view"],
                returncode=0,
                stdout='{"statusCheckRollup":[{"name":"ci","conclusion":"success"}]}',
                stderr="",
            )
            with patch("engine.ci_cd.GitHubIntegration._run_gh", side_effect=[pr_view_result, create_result, checks_result]):
                result = run_ci_cd_hook(
                    {"ci_cd": {"create_pr": True, "wait_for_checks": True}},
                    str(wt),
                    {"run_id": "test", "requirement": "req", "duration_seconds": 1.0, "stages": []},
                )
                self.assertEqual(result["status"], "created")
                self.assertIn("checks", result)
                self.assertEqual(len(result["checks"]), 1)


class TestCICDExtractPRNumber(unittest.TestCase):
    def test_extract_valid_url(self) -> None:
        url = "https://github.com/owner/repo/pull/42"
        self.assertEqual(GitHubIntegration._extract_pr_number(url), 42)

    def test_extract_trailing_slash(self) -> None:
        url = "https://github.com/owner/repo/pull/42/"
        self.assertEqual(GitHubIntegration._extract_pr_number(url), 42)

    def test_extract_large_number(self) -> None:
        url = "https://github.com/owner/repo/pull/12345"
        self.assertEqual(GitHubIntegration._extract_pr_number(url), 12345)
