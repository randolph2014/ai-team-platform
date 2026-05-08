from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

from engine.production_guard import ProductionGuard, is_production_mode


class TestIsProductionMode(unittest.TestCase):
    @patch.dict("os.environ", {"AI_TEAM_PRODUCTION": "true"}, clear=False)
    def test_true_value(self):
        self.assertTrue(is_production_mode())

    @patch.dict("os.environ", {"AI_TEAM_PRODUCTION": "1"}, clear=False)
    def test_one_value(self):
        self.assertTrue(is_production_mode())

    @patch.dict("os.environ", {"AI_TEAM_PRODUCTION": "yes"}, clear=False)
    def test_yes_value(self):
        self.assertTrue(is_production_mode())

    @patch.dict("os.environ", {"AI_TEAM_PRODUCTION": "false"}, clear=False)
    def test_false_value(self):
        self.assertFalse(is_production_mode())

    @patch.dict("os.environ", {}, clear=False)
    def test_missing_value(self):
        import os
        os.environ.pop("AI_TEAM_PRODUCTION", None)
        self.assertFalse(is_production_mode())


class TestProductionGuardApiKeyCheck(unittest.TestCase):
    @patch.dict("os.environ", {"AI_TEAM_PRODUCTION": "true", "AI_TEAM_API_KEYS": ""}, clear=False)
    def test_missing_api_keys_in_production(self):
        guard = ProductionGuard(production=True)
        passed, errors, _ = guard.check_all()
        self.assertFalse(passed)
        self.assertTrue(any("AI_TEAM_API_KEYS" in e for e in errors))

    @patch.dict("os.environ", {"AI_TEAM_PRODUCTION": "true", "AI_TEAM_API_KEYS": "key1,key2"}, clear=False)
    def test_api_keys_present_in_production(self):
        guard = ProductionGuard(production=True)
        _, errors, _ = guard.check_all()
        self.assertFalse(any("AI_TEAM_API_KEYS" in e for e in errors))

    def test_missing_api_keys_in_dev_mode(self):
        guard = ProductionGuard(production=False)
        _, errors, _ = guard.check_all()
        self.assertFalse(any("AI_TEAM_API_KEYS" in e for e in errors))


class TestProductionGuardJwtSecretCheck(unittest.TestCase):
    @patch.dict("os.environ", {"AI_TEAM_JWT_SECRET": ""}, clear=False)
    def test_missing_jwt_secret_production(self):
        guard = ProductionGuard(production=True)
        passed, errors, _ = guard.check_all()
        self.assertFalse(passed)
        self.assertTrue(any("AI_TEAM_JWT_SECRET is not set" in e for e in errors))

    @patch.dict("os.environ", {"AI_TEAM_JWT_SECRET": "dev-secret-change-me"}, clear=False)
    def test_default_jwt_secret_production(self):
        guard = ProductionGuard(production=True)
        passed, errors, _ = guard.check_all()
        self.assertFalse(passed)
        self.assertTrue(any("default value" in e for e in errors))

    @patch.dict("os.environ", {"AI_TEAM_JWT_SECRET": "real-secret-123"}, clear=False)
    def test_real_jwt_secret_production(self):
        guard = ProductionGuard(production=True)
        _, errors, _ = guard.check_all()
        self.assertFalse(any("AI_TEAM_JWT_SECRET" in e for e in errors))

    @patch.dict("os.environ", {"AI_TEAM_JWT_SECRET": ""}, clear=False)
    def test_missing_jwt_secret_dev_mode_is_warning(self):
        guard = ProductionGuard(production=False)
        passed, errors, warnings = guard.check_all()
        self.assertTrue(passed)
        self.assertTrue(any("AI_TEAM_JWT_SECRET" in w for w in warnings))

    @patch.dict("os.environ", {"AI_TEAM_JWT_SECRET": "dev-secret-change-me"}, clear=False)
    def test_default_jwt_secret_dev_mode_is_warning(self):
        guard = ProductionGuard(production=False)
        passed, errors, warnings = guard.check_all()
        self.assertTrue(passed)
        self.assertTrue(any("default value" in w for w in warnings))


class TestProductionGuardCorsCheck(unittest.TestCase):
    @patch.dict("os.environ", {"AI_TEAM_CORS_ORIGINS": ""}, clear=False)
    def test_missing_cors_in_production(self):
        guard = ProductionGuard(production=True)
        passed, errors, _ = guard.check_all()
        self.assertFalse(passed)
        self.assertTrue(any("CORS_ORIGINS" in e for e in errors))

    @patch.dict("os.environ", {"AI_TEAM_CORS_ORIGINS": "*"}, clear=False)
    def test_wildcard_cors_in_production(self):
        guard = ProductionGuard(production=True)
        passed, errors, _ = guard.check_all()
        self.assertFalse(passed)
        self.assertTrue(any("must not be '*'" in e for e in errors))

    @patch.dict("os.environ", {"AI_TEAM_CORS_ORIGINS": "https://app.example.com"}, clear=False)
    def test_specific_cors_in_production(self):
        guard = ProductionGuard(production=True)
        _, errors, _ = guard.check_all()
        self.assertFalse(any("CORS_ORIGINS" in e for e in errors))

    @patch.dict("os.environ", {"AI_TEAM_CORS_ORIGINS": "*"}, clear=False)
    def test_wildcard_cors_in_dev_mode_is_ok(self):
        guard = ProductionGuard(production=False)
        _, errors, _ = guard.check_all()
        self.assertFalse(any("CORS_ORIGINS" in e for e in errors))


class TestProductionGuardWebhookSecretCheck(unittest.TestCase):
    @patch.dict("os.environ", {"AI_TEAM_WEBHOOK_SECRET_KEY": ""}, clear=False)
    def test_missing_webhook_secret_key_in_production(self):
        guard = ProductionGuard(production=True)
        passed, errors, _ = guard.check_all()
        self.assertFalse(passed)
        self.assertTrue(any("AI_TEAM_WEBHOOK_SECRET_KEY is not set" in e for e in errors))

    @patch.dict("os.environ", {"AI_TEAM_WEBHOOK_SECRET_KEY": "webhook-secret-key"}, clear=False)
    def test_webhook_secret_key_present_in_production(self):
        guard = ProductionGuard(production=True)
        _, errors, _ = guard.check_all()
        self.assertFalse(any("AI_TEAM_WEBHOOK_SECRET_KEY" in e for e in errors))


class TestProductionGuardDatabaseCheck(unittest.TestCase):
    @patch.dict("os.environ", {"DATABASE_URL": "", "AI_TEAM_DB_URL": ""}, clear=False)
    def test_missing_database_url_in_production(self):
        guard = ProductionGuard(production=True)
        passed, errors, _ = guard.check_all()
        self.assertFalse(passed)
        self.assertTrue(any("DATABASE_URL" in e for e in errors))

    @patch.dict("os.environ", {"DATABASE_URL": "postgresql://localhost/db"}, clear=False)
    def test_database_available_in_production(self):
        mock_mod = MagicMock()
        mock_mod.is_available.return_value = True
        sys.modules["persistence.connection"] = mock_mod
        try:
            guard = ProductionGuard(production=True)
            _, errors, _ = guard.check_all()
            self.assertFalse(any("DATABASE_URL" in e for e in errors))
        finally:
            sys.modules.pop("persistence.connection", None)

    @patch.dict("os.environ", {"DATABASE_URL": "postgresql://localhost/db"}, clear=False)
    def test_database_not_reachable_in_production(self):
        mock_mod = MagicMock()
        mock_mod.is_available.return_value = False
        sys.modules["persistence.connection"] = mock_mod
        try:
            guard = ProductionGuard(production=True)
            passed, errors, _ = guard.check_all()
            self.assertFalse(passed)
            self.assertTrue(any("not reachable" in e for e in errors))
        finally:
            sys.modules.pop("persistence.connection", None)


class TestProductionGuardRedisCheck(unittest.TestCase):
    @patch.dict("os.environ", {"AI_TEAM_REDIS_URL": ""}, clear=False)
    def test_missing_redis_url_in_production(self):
        guard = ProductionGuard(production=True)
        passed, errors, _ = guard.check_all()
        self.assertFalse(passed)
        self.assertTrue(any("AI_TEAM_REDIS_URL" in e for e in errors))

    @patch.dict("os.environ", {"AI_TEAM_REDIS_URL": "redis://localhost:6379/0"}, clear=False)
    def test_redis_available_in_production(self):
        mock_redis_mod = MagicMock()
        mock_conn = MagicMock()
        mock_redis_mod.Redis.from_url.return_value = mock_conn
        sys.modules["redis"] = mock_redis_mod
        try:
            guard = ProductionGuard(production=True)
            _, errors, _ = guard.check_all()
            self.assertFalse(any("REDIS_URL" in e for e in errors))
            mock_conn.ping.assert_called_once()
        finally:
            sys.modules.pop("redis", None)

    @patch.dict("os.environ", {"AI_TEAM_REDIS_URL": "redis://localhost:6379/0"}, clear=False)
    def test_redis_not_reachable_in_production(self):
        mock_redis_mod = MagicMock()
        mock_redis_mod.Redis.from_url.side_effect = Exception("Connection refused")
        sys.modules["redis"] = mock_redis_mod
        try:
            guard = ProductionGuard(production=True)
            passed, errors, _ = guard.check_all()
            self.assertFalse(passed)
            self.assertTrue(any("not reachable" in e for e in errors))
        finally:
            sys.modules.pop("redis", None)


class TestProductionGuardMockRuntimeCheck(unittest.TestCase):
    def test_mock_runtime_in_production(self):
        config = {"runtimes": {"test": {"cli": "mock"}}}
        guard = ProductionGuard(production=True, config=config)
        passed, errors, _ = guard.check_all()
        self.assertFalse(passed)
        self.assertTrue(any("mock" in e for e in errors))

    def test_mock_runtime_in_dev_mode_is_ok(self):
        config = {"runtimes": {"test": {"cli": "mock"}}}
        guard = ProductionGuard(production=False, config=config)
        _, errors, _ = guard.check_all()
        self.assertFalse(any("mock" in e for e in errors))

    def test_no_mock_runtime_in_production(self):
        config = {"runtimes": {"main": {"cli": "claude"}}}
        guard = ProductionGuard(production=True, config=config)
        _, errors, _ = guard.check_all()
        self.assertFalse(any("mock" in e for e in errors))


class TestProductionGuardQualityGatesCheck(unittest.TestCase):
    def test_empty_quality_gates_in_production(self):
        config = {"quality_gates": []}
        guard = ProductionGuard(production=True, config=config)
        passed, errors, _ = guard.check_all()
        self.assertFalse(passed)
        self.assertTrue(any("quality_gates" in e for e in errors))

    def test_missing_quality_gates_in_production(self):
        config: dict = {}
        guard = ProductionGuard(production=True, config=config)
        passed, errors, _ = guard.check_all()
        self.assertFalse(passed)
        self.assertTrue(any("quality_gates" in e for e in errors))

    def test_quality_gates_present_in_production(self):
        config = {"quality_gates": [{"name": "lint", "type": "command", "command": "echo ok"}]}
        guard = ProductionGuard(production=True, config=config)
        _, errors, _ = guard.check_all()
        self.assertFalse(any("quality_gates" in e for e in errors))

    def test_empty_quality_gates_in_dev_mode_is_ok(self):
        config: dict = {}
        guard = ProductionGuard(production=False, config=config)
        _, errors, _ = guard.check_all()
        self.assertFalse(any("quality_gates" in e for e in errors))


class TestProductionGuardWorktreeCheck(unittest.TestCase):
    def test_worktree_disabled_in_production(self):
        config = {"worktree": {"enabled": False}}
        guard = ProductionGuard(production=True, config=config)
        passed, errors, _ = guard.check_all()
        self.assertFalse(passed)
        self.assertTrue(any("worktree" in e for e in errors))

    def test_worktree_enabled_in_production(self):
        config = {"worktree": {"enabled": True}}
        guard = ProductionGuard(production=True, config=config)
        _, errors, _ = guard.check_all()
        self.assertFalse(any("worktree" in e for e in errors))

    def test_worktree_disabled_in_dev_mode_is_ok(self):
        config = {"worktree": {"enabled": False}}
        guard = ProductionGuard(production=False, config=config)
        _, errors, _ = guard.check_all()
        self.assertFalse(any("worktree" in e for e in errors))


class TestProductionGuardAllPass(unittest.TestCase):
    @patch.dict("os.environ", {
        "AI_TEAM_PRODUCTION": "true",
        "AI_TEAM_API_KEYS": "key1",
        "AI_TEAM_JWT_SECRET": "real-secret-abc",
        "AI_TEAM_WEBHOOK_SECRET_KEY": "webhook-secret-key",
        "AI_TEAM_CORS_ORIGINS": "https://app.example.com",
        "DATABASE_URL": "postgresql://localhost/db",
        "AI_TEAM_REDIS_URL": "redis://localhost:6379/0",
    }, clear=False)
    def test_all_checks_pass(self):
        mock_db = MagicMock()
        mock_db.is_available.return_value = True
        sys.modules["persistence.connection"] = mock_db

        mock_redis_mod = MagicMock()
        mock_conn = MagicMock()
        mock_redis_mod.Redis.from_url.return_value = mock_conn
        sys.modules["redis"] = mock_redis_mod

        try:
            config = {
                "runtimes": {"main": {"cli": "claude"}},
                "quality_gates": [{"name": "lint", "type": "command", "command": "echo ok"}],
                "worktree": {"enabled": True},
            }
            guard = ProductionGuard(production=True, config=config)
            passed, errors, warnings = guard.check_all()
            self.assertTrue(passed)
            self.assertEqual(errors, [])
        finally:
            sys.modules.pop("persistence.connection", None)
            sys.modules.pop("redis", None)


class TestProductionGuardDevModeWarnings(unittest.TestCase):
    @patch.dict("os.environ", {
        "AI_TEAM_JWT_SECRET": "dev-secret-change-me",
    }, clear=False)
    def test_dev_mode_produces_warnings_not_errors(self):
        guard = ProductionGuard(production=False)
        passed, errors, warnings = guard.check_all()
        self.assertTrue(passed)
        self.assertEqual(errors, [])
        self.assertTrue(len(warnings) > 0)
