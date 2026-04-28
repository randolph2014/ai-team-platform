"""
Webhook 模块测试。

测试范围：
- HMAC-SHA256 签名验证
- GitHub/GitLab 事件解析
- event_info 标准化
- Webhook CRUD API（create, list, get, delete）
- Webhook trigger 端点

使用 FastAPI TestClient 进行集成测试。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from unittest.mock import MagicMock, patch

try:
    from fastapi.testclient import TestClient
except ImportError:
    HAS_FASTAPI = False
else:
    HAS_FASTAPI = True


class TestSignatureVerification(unittest.TestCase):
    """测试 webhook 签名验证"""

    def test_valid_signature(self):
        from engine.webhook import verify_signature

        secret = "test-secret"
        payload = b'{"event":"push"}'
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature(payload, expected, secret))

    def test_invalid_signature(self):
        from engine.webhook import verify_signature

        secret = "test-secret"
        payload = b'{"event":"push"}'
        wrong_sig = "sha256=abc123"
        self.assertFalse(verify_signature(payload, wrong_sig, secret))

    def test_wrong_secret(self):
        from engine.webhook import verify_signature

        secret = "test-secret"
        payload = b'{"event":"push"}'
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        self.assertFalse(verify_signature(payload, expected, "wrong-secret"))

    def test_empty_payload(self):
        from engine.webhook import verify_signature

        secret = "test-secret"
        payload = b""
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature(payload, expected, secret))


class TestGitHubEventParsing(unittest.TestCase):
    """测试 GitHub webhook 事件解析"""

    def test_parse_github_push(self):
        from engine.webhook import parse_event, normalize_trigger_info

        headers = {"x-github-event": "push"}
        body = {
            "ref": "refs/heads/main",
            "commits": [
                {"message": "fix: update", "author": {"name": "Alice"}}
            ],
            "repository": {"full_name": "my-org/my-repo"},
        }
        event_info = parse_event(headers, body)
        self.assertIsNotNone(event_info)
        self.assertEqual(event_info["event"], "push")
        self.assertEqual(event_info["provider"], "github")
        self.assertEqual(event_info["ref"], "refs/heads/main")

        trigger = normalize_trigger_info(event_info)
        self.assertEqual(trigger["event"], "push")
        self.assertEqual(trigger["provider"], "github")
        self.assertEqual(trigger["branch"], "main")
        self.assertEqual(trigger["repository"], "my-org/my-repo")
        self.assertEqual(trigger["commit_count"], 1)

    def test_parse_github_pull_request(self):
        from engine.webhook import parse_event, normalize_trigger_info

        headers = {"x-github-event": "pull_request"}
        body = {
            "action": "opened",
            "pull_request": {
                "title": "Add webhook support",
                "html_url": "https://github.com/my-org/my-repo/pull/1",
                "head": {"ref": "feature/webhook"},
                "base": {"ref": "main"},
            },
            "repository": {"full_name": "my-org/my-repo"},
        }
        event_info = parse_event(headers, body)
        self.assertIsNotNone(event_info)
        self.assertEqual(event_info["event"], "pull_request")
        self.assertEqual(event_info["provider"], "github")
        self.assertEqual(event_info["action"], "opened")

        trigger = normalize_trigger_info(event_info)
        self.assertEqual(trigger["event"], "pull_request")
        self.assertEqual(trigger["pr_title"], "Add webhook support")
        self.assertEqual(trigger["source_branch"], "feature/webhook")
        self.assertEqual(trigger["target_branch"], "main")

    def test_parse_github_unknown_event(self):
        from engine.webhook import parse_event

        headers = {"x-github-event": "unknown"}
        body = {}
        event_info = parse_event(headers, body)
        self.assertIsNone(event_info)


class TestGitLabEventParsing(unittest.TestCase):
    """测试 GitLab webhook 事件解析"""

    def test_parse_gitlab_push(self):
        from engine.webhook import parse_event, normalize_trigger_info

        headers = {"x-gitlab-event": "Push Hook"}
        body = {
            "ref": "refs/heads/main",
            "commits": [{"message": "fix", "author": {"name": "Bob"}}],
            "project": {"name": "my-repo"},
        }
        event_info = parse_event(headers, body)
        self.assertIsNotNone(event_info)
        self.assertEqual(event_info["event"], "push")
        self.assertEqual(event_info["provider"], "gitlab")

        trigger = normalize_trigger_info(event_info)
        self.assertEqual(trigger["event"], "push")
        self.assertEqual(trigger["provider"], "gitlab")
        self.assertEqual(trigger["branch"], "main")

    def test_parse_gitlab_merge_request(self):
        from engine.webhook import parse_event

        headers = {"x-gitlab-event": "Merge Request Hook"}
        body = {
            "object_attributes": {
                "action": "open",
                "title": "Merge feature",
                "url": "https://gitlab.com/my-org/my-repo/-/merge_requests/1",
            },
            "project": {"name": "my-repo"},
        }
        event_info = parse_event(headers, body)
        self.assertIsNotNone(event_info)
        self.assertEqual(event_info["event"], "merge_request")
        self.assertEqual(event_info["provider"], "gitlab")

    def test_parse_gitlab_unknown_event(self):
        from engine.webhook import parse_event

        headers = {"x-gitlab-event": "Unknown Hook"}
        body = {}
        event_info = parse_event(headers, body)
        self.assertIsNone(event_info)

    def test_parse_no_event_header(self):
        from engine.webhook import parse_event

        headers = {"content-type": "application/json"}
        body = {}
        event_info = parse_event(headers, body)
        self.assertIsNone(event_info)


class TestNormalizeTriggerInfo(unittest.TestCase):
    """测试事件信息标准化"""

    def test_normalize_push_ref_with_prefix(self):
        from engine.webhook import normalize_trigger_info

        event_info = {
            "event": "push",
            "provider": "github",
            "ref": "refs/heads/feature/test",
            "commits": [{"message": "test", "author": {"name": "Tester"}}],
            "repository": {"full_name": "org/repo"},
        }
        trigger = normalize_trigger_info(event_info)
        self.assertEqual(trigger["branch"], "feature/test")

    def test_normalize_push_no_ref_prefix(self):
        from engine.webhook import normalize_trigger_info

        event_info = {
            "event": "push",
            "provider": "github",
            "ref": "main",
            "commits": [],
            "repository": {"full_name": "org/repo"},
        }
        trigger = normalize_trigger_info(event_info)
        self.assertEqual(trigger["branch"], "main")
        self.assertEqual(trigger["commit_count"], 0)

    def test_normalize_empty_commits(self):
        from engine.webhook import normalize_trigger_info

        event_info = {
            "event": "push",
            "provider": "github",
            "ref": "refs/heads/main",
            "commits": "not-a-list",
            "repository": {"full_name": "org/repo"},
        }
        trigger = normalize_trigger_info(event_info)
        self.assertEqual(trigger["commit_count"], 0)


class TestWebhookApiRoutes(unittest.TestCase):
    """测试 Webhook CRUD API 端点"""

    @classmethod
    def setUpClass(cls) -> None:
        if not HAS_FASTAPI:
            raise unittest.SkipTest("FastAPI 未安装，跳过路由测试")

    def setUp(self) -> None:
        reset_auth()

    def test_create_webhook_requires_auth(self):
        from api.app import create_app

        with patch.dict("os.environ", {"AI_TEAM_API_KEYS": "test-key"}, clear=False):
            app = create_app()
            client = TestClient(app)
            response = client.post(
                "/api/webhooks",
                json={
                    "url": "https://example.com/webhook",
                    "secret": "my-secret",
                    "events": ["push"],
                },
            )
            self.assertEqual(response.status_code, 401)

    def test_list_webhooks_empty(self):
        from api.app import create_app

        app = create_app()
        client = TestClient(app)
        response = client.get("/api/webhooks")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_create_webhook_invalid_event(self):
        from api.app import create_app

        app = create_app()
        client = TestClient(app)
        response = client.post(
            "/api/webhooks",
            json={
                "url": "https://example.com/webhook",
                "secret": "my-secret",
                "events": ["invalid_event"],
            },
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("Unsupported", data.get("detail", ""))

    def test_trigger_webhook_no_event_header(self):
        from api.app import create_app

        app = create_app()
        client = TestClient(app)
        response = client.post(
            "/api/webhooks/trigger",
            json={"test": "data"},
            headers={"content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("No webhook event header", data.get("detail", ""))

    def test_trigger_webhook_github_push(self):
        from api.app import create_app

        app = create_app()
        client = TestClient(app)
        response = client.post(
            "/api/webhooks/trigger",
            json={
                "ref": "refs/heads/main",
                "commits": [{"message": "test", "author": {"name": "Tester"}}],
                "repository": {"full_name": "org/repo"},
            },
            headers={
                "x-github-event": "push",
                "x-hub-signature-256": "sha256=test",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "processed")
        self.assertEqual(data["event"], "push")


class TestWebhookRepo(unittest.TestCase):
    """测试 WebhookRepo CRUD 操作（mock 数据库）"""

    def setUp(self) -> None:
        reset_auth()

    def test_create_and_get_webhook(self):
        self._run_async_test(self._test_create_and_get_webhook)

    def test_list_all_webhooks(self):
        self._run_async_test(self._test_list_all_webhooks)

    def test_delete_webhook(self):
        self._run_async_test(self._test_delete_webhook)

    def test_update_enabled(self):
        self._run_async_test(self._test_update_enabled)

    def _run_async_test(self, coro_func):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro_func())
        else:
            import threading
            import concurrent.futures
            event = threading.Event()

            def runner():
                asyncio.run(coro_func())
                event.set()

            threading.Thread(target=runner, daemon=True).start()
            event.wait(timeout=10)

    async def _test_create_and_get_webhook(self):
        from persistence.repository import WebhookRepo
        from unittest.mock import AsyncMock

        repo = WebhookRepo()

        mock_conn = MagicMock()
        mock_conn.fetchrow = AsyncMock(
            return_value={
                "id": "wh-001",
                "url": "https://example.com/webhook",
                "secret": "test-secret",
                "events": '["push"]',
                "pipeline_id": None,
                "enabled": True,
                "created_at": "2025-01-01T00:00:00+00:00",
            }
        )
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        await repo.create(
            mock_conn,
            id="wh-001",
            url="https://example.com/webhook",
            secret="test-secret",
            events=["push"],
            pipeline_id=None,
            enabled=True,
        )

        record = await repo.get_by_id(mock_conn, "wh-001")
        self.assertIsNotNone(record)
        self.assertEqual(record["url"], "https://example.com/webhook")
        self.assertEqual(record["secret"], "test-secret")
        self.assertEqual(record["events"], ["push"])

    async def _test_list_all_webhooks(self):
        from persistence.repository import WebhookRepo
        from unittest.mock import AsyncMock

        repo = WebhookRepo()

        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": "wh-001",
                    "url": "https://example.com/webhook",
                    "secret": "test-secret",
                    "events": '["push"]',
                    "pipeline_id": None,
                    "enabled": True,
                    "created_at": "2025-01-01T00:00:00+00:00",
                }
            ]
        )

        records = await repo.list_all(mock_conn)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], "wh-001")

    async def _test_delete_webhook(self):
        from persistence.repository import WebhookRepo
        from unittest.mock import AsyncMock

        repo = WebhookRepo()

        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 1")

        result = await repo.delete(mock_conn, "wh-001")
        self.assertTrue(result)

        mock_conn.execute.return_value = "DELETE 0"
        result = await repo.delete(mock_conn, "wh-nonexistent")
        self.assertFalse(result)

    async def _test_update_enabled(self):
        from persistence.repository import WebhookRepo
        from unittest.mock import AsyncMock

        repo = WebhookRepo()

        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        result = await repo.update_enabled(mock_conn, "wh-001", False)
        self.assertTrue(result)

        mock_conn.execute.return_value = "UPDATE 0"
        result = await repo.update_enabled(mock_conn, "wh-nonexistent", False)
        self.assertFalse(result)


def reset_auth():
    """Reset auth configuration for tests that need to modify env vars."""
    try:
        from api.auth import reset_auth_config
        reset_auth_config()
    except Exception:
        pass
