from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SUPPORTED_EVENTS = ["push", "pull_request", "merge_request"]


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _matches_events(event_type: str, registered_events: List[str]) -> bool:
    return not registered_events or event_type in registered_events


def _parse_github_event(headers: Dict[str, str], body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    event_type = headers.get("x-github-event", "")
    if event_type == "push":
        return {
            "event": "push",
            "provider": "github",
            "ref": body.get("ref", ""),
            "commits": body.get("commits", []),
            "repository": body.get("repository", {}),
        }
    elif event_type == "pull_request":
        return {
            "event": "pull_request",
            "provider": "github",
            "action": body.get("action", ""),
            "pull_request": body.get("pull_request", {}),
            "repository": body.get("repository", {}),
        }
    return None


def _parse_gitlab_event(headers: Dict[str, str], body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    event_type = headers.get("x-gitlab-event", "")
    if event_type == "Push Hook":
        return {
            "event": "push",
            "provider": "gitlab",
            "ref": body.get("ref", ""),
            "commits": body.get("commits", []),
            "repository": body.get("project", {}),
        }
    elif event_type == "Merge Request Hook":
        attrs = body.get("object_attributes", {})
        return {
            "event": "merge_request",
            "provider": "gitlab",
            "action": attrs.get("action", ""),
            "merge_request": attrs,
            "repository": body.get("project", {}),
        }
    return None


def parse_event(headers: Dict[str, str], body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse incoming webhook event based on provider headers."""
    if "x-github-event" in headers:
        return _parse_github_event(headers, body)
    elif "x-gitlab-event" in headers:
        return _parse_gitlab_event(headers, body)
    return None


def normalize_trigger_info(event_info: Dict[str, Any]) -> Dict[str, Any]:
    """Convert provider-specific event info into a uniform trigger format."""
    repo_info = event_info.get("repository", {})
    ref = event_info.get("ref", "")
    branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref

    result = {
        "event": event_info.get("event"),
        "provider": event_info.get("provider"),
        "branch": branch,
        "repository": repo_info.get("full_name") or repo_info.get("name", ""),
    }

    if event_info.get("event") == "push":
        commits = event_info.get("commits", [])
        result["commit_count"] = len(commits) if isinstance(commits, list) else 0
        if isinstance(commits, list) and len(commits) > 0:
            latest = commits[0]
            result["commit_message"] = latest.get("message", "") if isinstance(latest, dict) else ""
            result["commit_author"] = (
                latest.get("author", {}).get("name", "")
                if isinstance(latest, dict) and isinstance(latest.get("author"), dict)
                else ""
            )
    elif event_info.get("event") in ("pull_request", "merge_request"):
        pr = event_info.get("pull_request") or event_info.get("merge_request", {})
        if isinstance(pr, dict):
            result["pr_title"] = pr.get("title", "")
            result["pr_url"] = pr.get("html_url") or pr.get("url", "")
            result["source_branch"] = pr.get("head", {}).get("ref", "") if isinstance(pr.get("head"), dict) else ""
            result["target_branch"] = pr.get("base", {}).get("ref", "") if isinstance(pr.get("base"), dict) else ""

    return result
