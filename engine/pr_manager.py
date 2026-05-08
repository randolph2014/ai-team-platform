from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PRManagerError(RuntimeError):
    pass


class PRDescriptionBuilder:
    @staticmethod
    def build(report_summary: Dict[str, Any]) -> str:
        run_id = report_summary.get("run_id", "unknown")
        requirement = report_summary.get("requirement", "")
        changed_files = report_summary.get("changed_files", [])
        diff_stat = report_summary.get("diff_stat", "")
        duration = report_summary.get("duration_seconds", 0)
        stages = report_summary.get("stages", [])

        lines = [
            "## AI Team 变更提案",
            "",
            f"**Run ID**: `{run_id}`",
            f"**耗时**: {duration:.1f}s",
            "",
            "### 需求",
            "",
            requirement[:2000],
            "",
            "### 任务列表",
            "",
        ]

        task_items = []
        for stage in stages:
            stage_id = stage.get("stage_id", "")
            stage_name = stage.get("stage_name", stage_id)
            status = stage.get("status", "")
            task_items.append(f"- [{status.upper()}] {stage_name}")
        if task_items:
            lines.extend(task_items)
        else:
            lines.append("- (无任务记录)")

        lines.extend(["", "### 变更文件", ""])
        if changed_files:
            for f in changed_files:
                lines.append(f"- `{f}`")
        else:
            lines.append("- (无文件变更)")

        if diff_stat:
            lines.extend(["", "### 变更统计", "", "```", diff_stat.strip(), "```"])

        test_results = PRDescriptionBuilder._extract_test_results(stages)
        lines.extend(["", "### 测试结果", ""])
        if test_results:
            lines.extend(test_results)
        else:
            lines.append("- 未记录质量门禁结果")

        risks = PRDescriptionBuilder._extract_risks(stages)
        lines.extend(["", "### 风险评估", ""])
        if risks:
            lines.extend(risks)
        else:
            lines.append("- 未发现显著风险")

        lines.extend([
            "",
            "### 回滚步骤",
            "",
            "1. 关闭本 PR 即可回滚，代码不会合入主分支",
            "2. 如已合并: `git revert <merge-commit>`",
            "3. 确认主分支恢复到变更前状态",
            "",
            "---",
            "",
            "> 本 PR 由 AI Team 自动生成，需人工验收后合并。",
        ])

        return "\n".join(lines)

    @staticmethod
    def _extract_test_results(stages: List[Dict[str, Any]]) -> List[str]:
        results: List[str] = []
        for stage in stages:
            for gate in stage.get("quality_gates", []):
                name = gate.get("name", "unknown")
                status = gate.get("status", "unknown")
                results.append(f"- {name}: {status}")
        return results

    @staticmethod
    def _extract_risks(stages: List[Dict[str, Any]]) -> List[str]:
        risks: List[str] = []
        for stage in stages:
            if stage.get("stage_id") == "review":
                for agent in stage.get("agents", []):
                    risks.append(f"- review: {agent.get('agent_name', 'unknown')} ({agent.get('status', 'unknown')})")
        return risks


class GitHubPRProvider:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}

    def _run_gh(self, args: List[str], cwd: Optional[Path] = None, check: bool = False) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["gh"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise PRManagerError(f"gh {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
        return result

    def create_pr(self, worktree_path: str, title: str, body: str, base: str = "main") -> Dict[str, Any]:
        wt = Path(worktree_path).resolve()
        if not wt.exists():
            raise PRManagerError(f"Worktree path does not exist: {worktree_path}")

        view_result = self._run_gh(["pr", "view", "--json", "number"], cwd=wt, check=False)
        if view_result.returncode == 0:
            try:
                data = json.loads(view_result.stdout)
                return {"status": "existing", "number": data.get("number")}
            except json.JSONDecodeError:
                pass

        result = self._run_gh(
            ["pr", "create", "--title", title, "--body", body, "--base", base],
            cwd=wt,
            check=False,
        )
        if result.returncode != 0:
            raise PRManagerError(f"gh pr create failed: {result.stderr.strip() or result.stdout.strip()}")

        url = result.stdout.strip()
        number = None
        try:
            number = int(url.rstrip("/").rsplit("/", 1)[-1])
        except (ValueError, IndexError):
            pass

        return {"status": "created", "url": url, "number": number}

    def get_pr_status(self, pr_number: int) -> Dict[str, Any]:
        result = self._run_gh(
            ["pr", "view", str(pr_number), "--json", "state,mergedAt,closedAt"],
            check=False,
        )
        if result.returncode != 0:
            raise PRManagerError(f"gh pr view failed: {result.stderr.strip()}")
        try:
            data = json.loads(result.stdout)
            return {"state": data.get("state"), "merged": bool(data.get("mergedAt"))}
        except json.JSONDecodeError:
            return {"state": "unknown"}

    def check_ci(self, pr_number: int) -> Dict[str, Any]:
        result = self._run_gh(
            ["pr", "view", str(pr_number), "--json", "statusCheckRollup"],
            check=False,
        )
        if result.returncode != 0:
            return {"status": "unknown", "checks": []}
        try:
            data = json.loads(result.stdout)
            checks = data.get("statusCheckRollup", [])
        except json.JSONDecodeError:
            return {"status": "unknown", "checks": []}

        if not checks:
            return {"status": "no_checks", "checks": []}

        all_completed = all(str(c.get("status", "")).lower() == "completed" for c in checks)
        if not all_completed:
            return {"status": "pending", "checks": checks}

        failed_checks = [
            c for c in checks
            if str(c.get("conclusion", "")).lower()
            in ("failure", "timed_out", "cancelled", "action_required", "startup_failure")
        ]
        if failed_checks:
            return {"status": "failed", "checks": checks, "failed": [c.get("name") for c in failed_checks]}

        return {"status": "passed", "checks": checks}

    def wait_ci(self, pr_number: int, timeout: int = 600, poll_interval: int = 30) -> Dict[str, Any]:
        start = time.monotonic()
        while True:
            result = self.check_ci(pr_number)
            if result["status"] in ("passed", "failed", "no_checks", "unknown"):
                return result
            if time.monotonic() - start >= timeout:
                return {"status": "timeout", "checks": result.get("checks", [])}
            time.sleep(poll_interval)


class GitLabPRProvider:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self.base_url = self.config.get("gitlab_url", "https://gitlab.com").rstrip("/")
        self.token = self.config.get("gitlab_token", "")
        self.project_id = self.config.get("project_id")

    def _headers(self) -> Dict[str, str]:
        return {"PRIVATE-TOKEN": self.token, "Content-Type": "application/json"}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            import requests
        except ImportError:
            raise PRManagerError("requests library is required for GitLab integration")
        url = f"{self.base_url}/api/v4/projects/{self.project_id}/{path}"
        resp = getattr(requests, method)(url, headers=self._headers(), **kwargs)
        if resp.status_code >= 400:
            raise PRManagerError(f"GitLab API {method} {path} failed: {resp.status_code} {resp.text}")
        return resp.json()

    def create_pr(self, worktree_path: str, title: str, body: str, base: str = "main") -> Dict[str, Any]:
        wt = Path(worktree_path).resolve()
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=wt, capture_output=True, text=True, check=False,
        )
        source_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
        try:
            existing = self._request("get", f"merge_requests?source_branch={source_branch}&state=opened")
            if existing:
                mr = existing[0]
                return {"status": "existing", "number": mr.get("iid"), "url": mr.get("web_url")}
        except PRManagerError:
            pass

        data = {
            "source_branch": source_branch,
            "target_branch": base,
            "title": title,
            "description": body,
        }
        mr = self._request("post", "merge_requests", json=data)
        return {"status": "created", "number": mr.get("iid"), "url": mr.get("web_url")}

    def get_pr_status(self, pr_number: int) -> Dict[str, Any]:
        mr = self._request("get", f"merge_requests/{pr_number}")
        state = mr.get("state", "unknown")
        return {"state": state, "merged": state == "merged"}

    def check_ci(self, pr_number: int) -> Dict[str, Any]:
        try:
            pipelines = self._request("get", f"merge_requests/{pr_number}/pipelines")
        except PRManagerError:
            return {"status": "no_checks", "checks": []}
        if not pipelines:
            return {"status": "no_checks", "checks": []}
        latest = pipelines[0] if isinstance(pipelines, list) else pipelines
        status = latest.get("status", "unknown")
        mapping = {
            "success": "passed",
            "failed": "failed",
            "canceled": "failed",
            "running": "pending",
            "pending": "pending",
        }
        return {"status": mapping.get(status, "unknown"), "checks": pipelines}

    def wait_ci(self, pr_number: int, timeout: int = 600, poll_interval: int = 30) -> Dict[str, Any]:
        start = time.monotonic()
        while True:
            result = self.check_ci(pr_number)
            if result["status"] in ("passed", "failed", "no_checks", "unknown"):
                return result
            if time.monotonic() - start >= timeout:
                return {"status": "timeout", "checks": result.get("checks", [])}
            time.sleep(poll_interval)


class PRManager:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        provider = self.config.get("provider", "github")
        self._provider: GitHubPRProvider | GitLabPRProvider
        if provider == "gitlab":
            self._provider = GitLabPRProvider(self.config)
        else:
            self._provider = GitHubPRProvider(self.config)

    def create_pr(self, worktree_path: str, report_summary: Dict[str, Any]) -> Dict[str, Any]:
        run_id = report_summary.get("run_id", "unknown")
        title = f"ai-team: {run_id}"
        body = PRDescriptionBuilder.build(report_summary)
        base = self.config.get("base_branch", "main")
        try:
            return self._provider.create_pr(worktree_path, title, body, base)
        except PRManagerError as e:
            logger.error("PR creation failed: %s", e)
            return {"status": "failed", "error": str(e)}

    def check_ci(self, pr_number: int) -> Dict[str, Any]:
        return self._provider.check_ci(pr_number)

    def wait_ci(self, pr_number: int, timeout: int = 600, poll_interval: int = 30) -> Dict[str, Any]:
        return self._provider.wait_ci(pr_number, timeout, poll_interval)

    def get_pr_status(self, pr_number: int) -> Dict[str, Any]:
        return self._provider.get_pr_status(pr_number)
