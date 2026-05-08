from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.worktree import WorktreeError, WorktreeManager


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, capture_output=True, check=True)
    (path / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "branch", "-m", "main"], cwd=path, capture_output=True, check=False)


def _make_commit_in(path: Path, filename: str, content: str, message: str) -> None:
    (path / filename).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=path, capture_output=True, check=True)


class TestWorktreeCreate(unittest.TestCase):
    def test_create_worktree_with_correct_branch(self) -> None:
        """create 应创建 worktree 目录且分支名以 ai-team/ 开头"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root)
            wt_path = mgr.create("run-001")
            self.assertTrue(wt_path.exists())
            self.assertTrue(wt_path.is_dir())
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=wt_path, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.stdout.strip(), "ai-team/run-001")
            mgr.cleanup(wt_path)

    def test_create_duplicate_raises_error(self) -> None:
        """重复 create 同一 run_id 应抛出 WorktreeError"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root)
            wt_path = mgr.create("run-dup")
            try:
                with self.assertRaises(WorktreeError):
                    mgr.create("run-dup")
            finally:
                mgr.cleanup(wt_path)


class TestWorktreeCleanup(unittest.TestCase):
    def test_cleanup_removes_worktree_and_branch(self) -> None:
        """cleanup 应删除 worktree 目录并清理分支"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root)
            wt_path = mgr.create("run-002")
            self.assertTrue(wt_path.exists())
            mgr.cleanup(wt_path)
            self.assertFalse(wt_path.exists())
            result = subprocess.run(
                ["git", "branch", "--list", "ai-team/run-002"],
                cwd=root, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.stdout.strip(), "")

    def test_cleanup_nonexistent_path_returns_true(self) -> None:
        """cleanup 不存在的路径应返回 True"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root)
            self.assertTrue(mgr.cleanup(root / "nonexistent"))


class TestWorktreeNonGitRepo(unittest.TestCase):
    def test_non_git_repo_raises_error(self) -> None:
        """非 git 仓库调用 create 应抛出 WorktreeError"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mgr = WorktreeManager(root)
            with self.assertRaises(WorktreeError) as ctx:
                mgr.create("run-003")
            self.assertIn("Not a git repository", str(ctx.exception))


class TestWorktreeGetPath(unittest.TestCase):
    def test_get_worktree_path_exists(self) -> None:
        """get_worktree_path 返回已存在的路径"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root)
            wt_path = mgr.create("run-004")
            try:
                found = mgr.get_worktree_path("run-004")
                self.assertEqual(found, wt_path)
            finally:
                mgr.cleanup(wt_path)

    def test_get_worktree_path_not_exists(self) -> None:
        """get_worktree_path 返回 None 当路径不存在"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root)
            self.assertIsNone(mgr.get_worktree_path("nonexistent"))


class TestWorktreeChanges(unittest.TestCase):
    def test_has_changes_true(self) -> None:
        """有未提交文件时 has_changes 返回 True"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root)
            wt_path = mgr.create("run-005")
            try:
                (wt_path / "new_file.txt").write_text("change", encoding="utf-8")
                self.assertTrue(mgr.has_changes(wt_path))
            finally:
                mgr.cleanup(wt_path)

    def test_has_changes_false(self) -> None:
        """clean worktree 时 has_changes 返回 False"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root)
            wt_path = mgr.create("run-006")
            try:
                self.assertFalse(mgr.has_changes(wt_path))
            finally:
                mgr.cleanup(wt_path)

    def test_get_changed_files(self) -> None:
        """get_changed_files 返回变更文件列表"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root)
            wt_path = mgr.create("run-007")
            try:
                # Modify an existing tracked file
                (wt_path / "README.md").write_text("changed content\n", encoding="utf-8")
                files = mgr.get_changed_files(wt_path)
                self.assertIn("README.md", files)
            finally:
                mgr.cleanup(wt_path)

    def test_get_diff(self) -> None:
        """get_diff 返回 diff 输出"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root)
            wt_path = mgr.create("run-008")
            try:
                (wt_path / "README.md").write_text("changed content\n", encoding="utf-8")
                diff = mgr.get_diff(wt_path)
                self.assertIn("README.md", diff)
            finally:
                mgr.cleanup(wt_path)

    def test_get_diff_stat(self) -> None:
        """get_diff_stat 返回 diff --stat 输出"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root)
            wt_path = mgr.create("run-009")
            try:
                (wt_path / "app.py").write_text("new code", encoding="utf-8")
                subprocess.run(["git", "add", "-A"], cwd=wt_path, capture_output=True, check=False)
                subprocess.run(["git", "commit", "-m", "change"], cwd=wt_path, capture_output=True, check=False)
                stat = mgr.get_diff_stat(wt_path)
                self.assertIsInstance(stat, str)
            finally:
                mgr.cleanup(wt_path)


class TestWorktreeCommit(unittest.TestCase):
    def test_commit_all_succeeds(self) -> None:
        """commit_all 提交所有变更"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root)
            wt_path = mgr.create("run-010")
            try:
                (wt_path / "file.txt").write_text("content", encoding="utf-8")
                result = mgr.commit_all(wt_path, "test commit")
                self.assertTrue(result)
            finally:
                mgr.cleanup(wt_path)


class TestWorktreePush(unittest.TestCase):
    def test_push_branch_sets_upstream(self) -> None:
        mgr = WorktreeManager(Path("/tmp/project"))
        with patch.object(mgr, "_run_git") as mock_run_git:
            mock_run_git.side_effect = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout="ai-team/run-010\n", stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            ]

            result = mgr.push_branch(Path("/tmp/project/.ai/worktrees/run-010"))

        self.assertEqual(result["status"], "pushed")
        self.assertEqual(mock_run_git.call_args_list[1].args[0], ["push", "--set-upstream", "origin", "ai-team/run-010"])


class TestWorktreeOrphans(unittest.TestCase):
    def test_list_orphans_empty(self) -> None:
        """无孤立 worktree 时返回空列表"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root)
            self.assertEqual(mgr.list_orphans(), [])

    def test_cleanup_orphans(self) -> None:
        """cleanup_orphans 清除孤立目录"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root)
            # 创建一个假的孤立目录
            wt_dir = root / ".ai" / "worktrees"
            wt_dir.mkdir(parents=True, exist_ok=True)
            orphan = wt_dir / "orphan-run"
            orphan.mkdir()
            (orphan / "file.txt").write_text("orphan", encoding="utf-8")
            cleaned = mgr.cleanup_orphans()
            self.assertIn("orphan-run", cleaned)
            self.assertFalse(orphan.exists())


class TestWorktreeMerge(unittest.TestCase):
    def test_merge_squash_succeeds(self) -> None:
        """merge squash 成功合并 worktree 的提交到主分支"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root, config={"merge_strategy": "squash"})
            wt_path = mgr.create("run-020")
            try:
                # 在 worktree 中创建提交
                (wt_path / "feature.py").write_text("new feature\n", encoding="utf-8")
                subprocess.run(["git", "add", "-A"], cwd=wt_path, capture_output=True, check=True)
                subprocess.run(["git", "commit", "-m", "feat: add feature"], cwd=wt_path, capture_output=True, check=True)

                result = mgr.merge(wt_path)
                self.assertEqual(result["status"], "merged")
                self.assertEqual(result["target_branch"], "main")
            finally:
                # cleanup merged branch
                subprocess.run(["git", "worktree", "remove", "--force", str(wt_path)], cwd=root, capture_output=True, check=False)
                subprocess.run(["git", "branch", "-D", "ai-team/run-020"], cwd=root, capture_output=True, check=False)

    def test_merge_no_changes(self) -> None:
        """merge 无变更时返回 no_changes"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            mgr = WorktreeManager(root, config={"merge_strategy": "squash"})
            wt_path = mgr.create("run-021")
            try:
                result = mgr.merge(wt_path)
                self.assertEqual(result["status"], "no_changes")
            finally:
                subprocess.run(["git", "worktree", "remove", "--force", str(wt_path)], cwd=root, capture_output=True, check=False)
                subprocess.run(["git", "branch", "-D", "ai-team/run-021"], cwd=root, capture_output=True, check=False)


if __name__ == "__main__":
    unittest.main()
