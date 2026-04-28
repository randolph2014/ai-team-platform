from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CICDError(RuntimeError):
    pass


class GitHubIntegration:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self.provider = self.config.get("provider", "github")
        self.create_pr_flag = bool(self.config.get("create_pr", False))
        self.wait_for_checks = bool(self.config.get("wait_for_checks", False))
        self.auto_merge = bool(self.config.get("auto_merge", False))

    def enabled(self) -> bool:
        return self.create_pr_flag

    @staticmethod
    def _run_gh(args: List[str], cwd: Optional[Path] = None, check: bool = False) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["gh"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise CICDError(f"gh {' '.join(args)} failed: {stderr}")
        return result

    def create_pr(self, worktree_path: str, title: str, body: str, base: str = "main") -> Dict[str, Any]:
        wt = Path(worktree_path).resolve()
        if not wt.exists():
            raise CICDError(f"Worktree path does not exist: {worktree_path}")

        branch_result = self._run_gh(["pr", "view", "--json", "number"], cwd=wt, check=False)
        if branch_result.returncode == 0:
            logger.info("PR already exists for this branch")
            return {"status": "existing", "pr_data": branch_result.stdout}

        result = self._run_gh(
            [
                "pr", "create",
                "--title", title,
                "--body", body,
                "--base", base,
                "--head", "",
            ],
            cwd=wt,
            check=False,
        )
        if result.returncode != 0:
            raise CICDError(f"gh pr create failed: {result.stderr.strip() or result.stdout.strip()}")

        pr_url = result.stdout.strip()
        pr_number = None
        try:
            pr_number = self._extract_pr_number(pr_url)
        except Exception:
            pass

        logger.info("PR created: %s", pr_url)
        result_dict: Dict[str, Any] = {"status": "created", "url": pr_url}
        if pr_number is not None:
            result_dict["number"] = pr_number
        return result_dict

    def merge_pr(self, pr_number: int, method: str = "squash") -> Dict[str, Any]:
        result = self._run_gh(
            ["pr", "merge", str(pr_number), f"--{method}", "--delete-branch"],
            check=False,
        )
        if result.returncode != 0:
            raise CICDError(f"gh pr merge #{pr_number} failed: {result.stderr.strip() or result.stdout.strip()}")
        logger.info("PR #%d merged with %s strategy", pr_number, method)
        return {"status": "merged", "pr_number": pr_number, "method": method}

    def list_pr_checks(self, pr_number: int) -> List[Dict[str, Any]]:
        result = self._run_gh(
            ["pr", "view", str(pr_number), "--json", "statusCheckRollup"],
            check=False,
        )
        if result.returncode != 0:
            raise CICDError(f"gh pr view #{pr_number} failed: {result.stderr.strip() or result.stdout.strip()}")
        try:
            data = json.loads(result.stdout)
            return data.get("statusCheckRollup", [])
        except json.JSONDecodeError:
            logger.warning("Failed to parse PR checks JSON for #%d", pr_number)
            return []

    @staticmethod
    def _extract_pr_number(url: str) -> int:
        parts = url.rstrip("/").rsplit("/", 1)
        return int(parts[-1])


def run_ci_cd_hook(
    config: Dict[str, Any],
    worktree_path: str,
    report_summary: Dict[str, Any],
) -> Dict[str, Any]:
    ci_cd_config = config.get("ci_cd", {})
    integration = GitHubIntegration(ci_cd_config)
    if not integration.enabled():
        return {"status": "skipped", "reason": "ci_cd.create_pr is not enabled"}

    run_id = report_summary.get("run_id", "unknown")
    requirement = report_summary.get("requirement", "")
    duration = report_summary.get("duration_seconds", 0)
    stages_count = len(report_summary.get("stages", []))

    title = f"🤖 ai-team: {run_id}"
    body_parts = [
        f"## AI Team 变更提案",
        "",
        f"**Run ID**: `{run_id}`",
        f"**耗时**: {duration:.1f}s",
        f"**执行阶段数**: {stages_count}",
        "",
        "### 需求",
        "",
        requirement,
    ]
    body = "\n".join(body_parts)

    try:
        pr_result = integration.create_pr(worktree_path, title, body)
    except CICDError as e:
        logger.error("CI/CD PR creation failed: %s", e)
        return {"status": "failed", "error": str(e)}

    if pr_result.get("status") == "existing":
        return pr_result

    if integration.wait_for_checks and pr_result.get("number") is not None:
        pr_result["checks"] = integration.list_pr_checks(pr_result["number"])

    if integration.auto_merge and pr_result.get("number") is not None:
        try:
            merge_result = integration.merge_pr(pr_result["number"])
            pr_result["merge"] = merge_result
        except CICDError as e:
            logger.error("CI/CD auto-merge failed: %s", e)
            pr_result["merge"] = {"status": "failed", "error": str(e)}

    return pr_result
