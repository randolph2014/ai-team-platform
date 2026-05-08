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


class TestMaskSecret(unittest.TestCase):

    def test_mask_long_secret(self):
        from engine.webhook import mask_secret
        self.assertEqual(mask_secret("abcdefghijklmnop"), "abcd****mnop")

    def test_mask_short_secret(self):
        from engine.webhook import mask_secret
        self.assertEqual(mask_secret("short"), "********")

    def test_mask_empty_secret(self):
        from engine.webhook import mask_secret
        self.assertEqual(mask_secret(""), "********")

    def test_mask_exactly_8_chars(self):
        from engine.webhook import mask_secret
        self.assertEqual(mask_secret("12345678"), "********")

    def test_mask_9_chars(self):
        from engine.webhook import mask_secret
        self.assertEqual(mask_secret("123456789"), "1234****6789")


class TestGitHubEventParsing(unittest.TestCase):

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

    def test_rotate_secret_endpoint_requires_auth(self):
        from api.app import create_app

        with patch.dict("os.environ", {"AI_TEAM_API_KEYS": "test-key"}, clear=False):
            app = create_app()
            client = TestClient(app)
            response = client.post(
                "/api/webhooks/some-id/rotate-secret",
                json={"new_secret": "new-secret-value"},
            )
            self.assertEqual(response.status_code, 401)

    def test_deliveries_endpoint_requires_auth(self):
        from api.app import create_app

        with patch.dict("os.environ", {"AI_TEAM_API_KEYS": "test-key"}, clear=False):
            app = create_app()
            client = TestClient(app)
            response = client.get("/api/webhooks/some-id/deliveries")
            self.assertEqual(response.status_code, 401)


class TestWebhookRepo(unittest.TestCase):

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

    def test_secret_masked_in_get_by_id(self):
        self._run_async_test(self._test_secret_masked_in_get_by_id)

    def test_secret_masked_in_list_all(self):
        self._run_async_test(self._test_secret_masked_in_list_all)

    def test_get_by_id_without_mask(self):
        self._run_async_test(self._test_get_by_id_without_mask)

    def test_rotate_secret(self):
        self._run_async_test(self._test_rotate_secret)

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
                "secret": "test-secret-value-here",
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
            secret="test-secret-value-here",
            events=["push"],
            pipeline_id=None,
            enabled=True,
        )

        record = await repo.get_by_id(mock_conn, "wh-001")
        self.assertIsNotNone(record)
        self.assertEqual(record["url"], "https://example.com/webhook")
        self.assertNotEqual(record["secret"], "test-secret-value-here")
        self.assertIn("****", record["secret"])
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
                    "secret": "test-secret-value-here",
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
        self.assertIn("****", records[0]["secret"])

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

    async def _test_secret_masked_in_get_by_id(self):
        from persistence.repository import WebhookRepo
        from unittest.mock import AsyncMock

        repo = WebhookRepo()
        mock_conn = MagicMock()
        raw_secret = "a-very-long-secret-value"
        mock_conn.fetchrow = AsyncMock(
            return_value={
                "id": "wh-002",
                "url": "https://example.com",
                "secret": raw_secret,
                "events": '[]',
                "pipeline_id": None,
                "enabled": True,
                "created_at": "2025-01-01T00:00:00+00:00",
            }
        )

        record = await repo.get_by_id(mock_conn, "wh-002", mask_secret=True)
        self.assertNotEqual(record["secret"], raw_secret)
        self.assertIn("****", record["secret"])

    async def _test_secret_masked_in_list_all(self):
        from persistence.repository import WebhookRepo
        from unittest.mock import AsyncMock

        repo = WebhookRepo()
        raw_secret = "a-very-long-secret-value"
        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": "wh-003",
                    "url": "https://example.com",
                    "secret": raw_secret,
                    "events": '[]',
                    "pipeline_id": None,
                    "enabled": True,
                    "created_at": "2025-01-01T00:00:00+00:00",
                }
            ]
        )

        records = await repo.list_all(mock_conn, mask_secret=True)
        self.assertNotEqual(records[0]["secret"], raw_secret)
        self.assertIn("****", records[0]["secret"])

    async def _test_get_by_id_without_mask(self):
        from persistence.repository import WebhookRepo
        from unittest.mock import AsyncMock

        repo = WebhookRepo()
        raw_secret = "a-very-long-secret-value"
        mock_conn = MagicMock()
        mock_conn.fetchrow = AsyncMock(
            return_value={
                "id": "wh-004",
                "url": "https://example.com",
                "secret": raw_secret,
                "events": '[]',
                "pipeline_id": None,
                "enabled": True,
                "created_at": "2025-01-01T00:00:00+00:00",
            }
        )

        record = await repo.get_by_id(mock_conn, "wh-004", mask_secret=False)
        self.assertEqual(record["secret"], raw_secret)

    async def _test_rotate_secret(self):
        from persistence.repository import WebhookRepo
        from unittest.mock import AsyncMock

        repo = WebhookRepo()
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        result = await repo.rotate_secret(mock_conn, "wh-001", "new-secret-value")
        self.assertTrue(result)

        mock_conn.execute.return_value = "UPDATE 0"
        result = await repo.rotate_secret(mock_conn, "wh-nonexistent", "new-secret")
        self.assertFalse(result)


class TestWebhookDeliveryRepo(unittest.TestCase):

    def test_create_delivery(self):
        self._run_async_test(self._test_create_delivery)

    def test_get_by_webhook(self):
        self._run_async_test(self._test_get_by_webhook)

    def test_mark_status(self):
        self._run_async_test(self._test_mark_status)

    def _run_async_test(self, coro_func):
        import asyncio
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro_func())
        else:
            import threading
            event = threading.Event()
            def runner():
                asyncio.run(coro_func())
                event.set()
            threading.Thread(target=runner, daemon=True).start()
            event.wait(timeout=10)

    async def _test_create_delivery(self):
        from persistence.repository import WebhookDeliveryRepo
        from unittest.mock import AsyncMock

        repo = WebhookDeliveryRepo()
        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(
            return_value=[{"id": "del-001"}]
        )

        delivery_id = await repo.create(
            mock_conn,
            webhook_id="wh-001",
            event_type="push",
            status="delivered",
            request_url="https://example.com/hook",
            request_body={"ref": "refs/heads/main"},
            response_status=200,
        )
        self.assertEqual(delivery_id, "del-001")

    async def _test_get_by_webhook(self):
        from persistence.repository import WebhookDeliveryRepo
        from unittest.mock import AsyncMock
        from datetime import datetime, timezone

        repo = WebhookDeliveryRepo()
        mock_conn = MagicMock()
        now = datetime.now(timezone.utc)
        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": "del-001",
                    "webhook_id": "wh-001",
                    "event_type": "push",
                    "status": "delivered",
                    "request_url": "https://example.com/hook",
                    "request_headers": "{}",
                    "request_body": "{}",
                    "response_status": 200,
                    "response_body": None,
                    "attempts": 1,
                    "last_attempt_at": now,
                    "next_retry_at": None,
                    "error_message": None,
                    "created_at": now,
                }
            ]
        )

        deliveries = await repo.get_by_webhook(mock_conn, "wh-001")
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["status"], "delivered")

    async def _test_mark_status(self):
        from persistence.repository import WebhookDeliveryRepo
        from unittest.mock import AsyncMock

        repo = WebhookDeliveryRepo()
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")

        result = await repo.mark_status(mock_conn, "del-001", "failed", response_status=500, error_message="timeout")
        self.assertTrue(result)


def reset_auth():
    try:
        from api.auth import reset_auth_config
        reset_auth_config()
    except Exception:
        pass
