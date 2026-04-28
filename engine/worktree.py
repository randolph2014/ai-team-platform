from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional


WORKTREE_BASE = ".ai/worktrees"


class WorktreeError(RuntimeError):
    pass


class WorktreeManager:
    def __init__(self, project_root: Path, config: Optional[Dict] = None) -> None:
        self.project_root = project_root.resolve()
        self.config = config or {}
        self.base_branch = self.config.get("base_branch", "main")
        self.merge_strategy = self.config.get("merge_strategy", "squash")
        self.auto_cleanup = bool(self.config.get("auto_cleanup", True))
        self.merge_on_conflict = self.config.get("merge_on_conflict", "pause")

    def _run_git(self, args: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd or self.project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise WorktreeError(f"git {' '.join(args)} failed: {stderr}")
        return result

    def ensure_git_repo(self) -> None:
        result = self._run_git(["rev-parse", "--show-toplevel"], check=False)
        if result.returncode != 0:
            raise WorktreeError(f"Not a git repository: {self.project_root}")

    def _worktree_dir(self) -> Path:
        return self.project_root / WORKTREE_BASE

    def create(self, run_id: str) -> Path:
        self.ensure_git_repo()
        wt_dir = self._worktree_dir()
        wt_dir.mkdir(parents=True, exist_ok=True)
        branch_name = f"ai-team/{run_id}"
        wt_path = wt_dir / run_id
        if wt_path.exists():
            raise WorktreeError(f"Worktree already exists: {wt_path}")

        result = self._run_git(
            ["worktree", "add", "-b", branch_name, str(wt_path), self.base_branch],
            check=False,
        )
        if result.returncode != 0:
            self._run_git(["branch", "-D", branch_name], check=False)
            result = self._run_git(
                ["worktree", "add", "-b", branch_name, str(wt_path), self.base_branch],
                check=False,
            )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise WorktreeError(f"Failed to create worktree from {self.base_branch}: {stderr}")
        return wt_path

    def get_worktree_path(self, run_id: str) -> Optional[Path]:
        path = self._worktree_dir() / run_id
        return path if path.exists() else None

    def get_diff(self, worktree_path: Path, base_branch: Optional[str] = None) -> str:
        base = base_branch or self.base_branch
        result = self._run_git(["diff", f"{base}...HEAD"], cwd=worktree_path, check=False)
        staged = self._run_git(["diff", "--cached"], cwd=worktree_path, check=False)
        plain = self._run_git(["diff"], cwd=worktree_path, check=False)
        parts = [result.stdout, staged.stdout, plain.stdout]
        return "\n".join(part for part in parts if part.strip())

    def get_diff_stat(self, worktree_path: Path, base_branch: Optional[str] = None) -> str:
        base = base_branch or self.base_branch
        result = self._run_git(["diff", "--stat", f"{base}...HEAD"], cwd=worktree_path, check=False)
        return result.stdout

    def get_changed_files(self, worktree_path: Path, base_branch: Optional[str] = None) -> List[str]:
        base = base_branch or self.base_branch
        committed = self._run_git(["diff", "--name-only", f"{base}...HEAD"], cwd=worktree_path, check=False)
        unstaged = self._run_git(["diff", "--name-only"], cwd=worktree_path, check=False)
        staged = self._run_git(["diff", "--cached", "--name-only"], cwd=worktree_path, check=False)
        files = []
        for output in (committed.stdout, staged.stdout, unstaged.stdout):
            for line in output.splitlines():
                if line and line not in files:
                    files.append(line)
        return files

    def has_changes(self, worktree_path: Path) -> bool:
        result = self._run_git(["status", "--porcelain"], cwd=worktree_path, check=False)
        return bool(result.stdout.strip())

    def commit_all(self, worktree_path: Path, message: str) -> bool:
        self._run_git(["add", "-A"], cwd=worktree_path)
        result = self._run_git(["commit", "-m", message], cwd=worktree_path, check=False)
        return result.returncode == 0

    def merge(self, worktree_path: Path, target_branch: Optional[str] = None) -> Dict:
        target = target_branch or self.base_branch
        if self.has_changes(worktree_path):
            self.commit_all(worktree_path, f"ai-team: run {worktree_path.name}")
        branch_result = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree_path, check=False)
        source_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else f"ai-team/{worktree_path.name}"

        self._run_git(["checkout", target])
        if self.merge_strategy == "squash":
            result = self._run_git(["merge", "--squash", source_branch], check=False)
        else:
            result = self._run_git(["merge", source_branch], check=False)

        if result.returncode != 0:
            self._run_git(["merge", "--abort"], check=False)
            return {
                "status": "conflict",
                "action": "keep" if self.merge_on_conflict == "pause" else "aborted",
                "details": result.stderr or result.stdout,
                "source_branch": source_branch,
                "worktree_path": str(worktree_path),
            }

        commit = self._run_git(["commit", "-m", f"ai-team: merge {source_branch}"], check=False)
        if commit.returncode != 0:
            return {"status": "no_changes", "source_branch": source_branch, "target_branch": target}
        return {"status": "merged", "source_branch": source_branch, "target_branch": target}

    def cleanup(self, worktree_path: Path) -> bool:
        if not worktree_path.exists():
            return True
        branch_result = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree_path, check=False)
        branch_name = branch_result.stdout.strip() if branch_result.returncode == 0 else None
        self._run_git(["worktree", "remove", "--force", str(worktree_path)], check=False)
        if branch_name and branch_name.startswith("ai-team/"):
            self._run_git(["branch", "-D", branch_name], check=False)
        return True

    def list_orphans(self) -> List[Dict[str, str]]:
        wt_dir = self._worktree_dir()
        if not wt_dir.exists():
            return []
        result = self._run_git(["worktree", "list", "--porcelain"], check=False)
        known_paths = set()
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                known_paths.add(str(Path(line[9:].strip()).resolve()))
        orphans = []
        for entry in wt_dir.iterdir():
            if entry.is_dir() and str(entry.resolve()) not in known_paths:
                orphans.append({"name": entry.name, "path": str(entry)})
        return orphans

    def cleanup_orphans(self) -> List[str]:
        cleaned: List[str] = []
        for orphan in self.list_orphans():
            path = Path(orphan["path"])
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
                cleaned.append(orphan["name"])
        return cleaned

    def push_branch(self, worktree_path: Path, remote: str = "origin", force: bool = False) -> Dict[str, Any]:
        branch_result = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree_path, check=False)
        branch_name = branch_result.stdout.strip() if branch_result.returncode == 0 else None
        if not branch_name:
            raise WorktreeError("Cannot determine current branch in worktree")

        args = ["push", remote, branch_name]
        if force:
            args.append("--force")
        result = self._run_git(args, cwd=worktree_path, check=False)
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise WorktreeError(f"git push {branch_name} failed: {stderr}")
        return {"status": "pushed", "branch": branch_name, "remote": remote}
