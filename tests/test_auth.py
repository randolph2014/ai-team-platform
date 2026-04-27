"""Authentication tests for the AI Team Platform API.

Covers:
- No token returns 401 when auth is enabled
- Valid JWT returns 200
- Login endpoint issues JWT for valid API key
- Auth disabled (no AI_TEAM_API_KEYS) allows all requests
- Health endpoint is always accessible
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:
    HAS_FASTAPI = False
else:
    HAS_FASTAPI = True


class _AuthTestBase(unittest.TestCase):
    """Base class providing a working project structure for route tests."""

    @classmethod
    def setUpClass(cls) -> None:
        if not HAS_FASTAPI:
            raise unittest.SkipTest("FastAPI not installed")

    def setUp(self) -> None:
        from api.auth import reset_auth_config
        reset_auth_config()

        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        (root / ".git").mkdir(parents=True)
        (root / ".ai").mkdir(parents=True)
        (root / ".ai" / "agents").mkdir(parents=True)
        (root / ".ai" / "agents" / "dev.md").write_text("You are a dev agent.", encoding="utf-8")
        (root / ".ai" / "team.yaml").write_text(
            """
providers:
  Mock:
    cli: mock
agents:
  - name: dev
    provider: Mock
    role: developer
    prompt: agents/dev.md
pipeline:
  - id: develop
    name: Develop
    agents: [dev]
    input: requirement
    output:
      dev: dev-output.md
""",
            encoding="utf-8",
        )
        self.project_root = root

        from api.app import create_app
        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        from api.auth import reset_auth_config

        reset_auth_config()
        self.temp_dir.cleanup()


class TestHealthNoAuth(_AuthTestBase):
    """Health endpoint should always work without any auth."""

    def test_health_no_token_no_env(self) -> None:
        """GET /health returns 200 even when auth is not configured."""
        with patch.dict(os.environ, {}, clear=False):
            response = self.client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ok"})


class TestAuthDisabled(_AuthTestBase):
    """When AI_TEAM_API_KEYS is not set, all routes are accessible."""

    def test_runs_list_without_auth(self) -> None:
        """GET /api/runs returns 200 when auth is disabled."""
        with patch.dict(os.environ, {}, clear=False):
            from api.auth import reset_auth_config
            reset_auth_config()

            from api.app import create_app
            app = create_app()
            client = TestClient(app)

            response = client.get("/api/runs", params={"workdir": str(self.project_root)})
            self.assertEqual(response.status_code, 200)


class TestAuthEnabled(_AuthTestBase):
    """Tests when AI_TEAM_API_KEYS is configured."""

    def _setup_auth_env(self) -> None:
        """Configure auth environment variables."""
        from api.auth import reset_auth_config
        reset_auth_config()

        os.environ["AI_TEAM_API_KEYS"] = "test-key-1,test-key-2"
        os.environ["AI_TEAM_JWT_SECRET"] = "test-jwt-secret-for-tests"

        from api.app import create_app
        self.app = create_app()
        self.client = TestClient(self.app)

    def _teardown_auth_env(self) -> None:
        """Remove auth environment variables."""
        os.environ.pop("AI_TEAM_API_KEYS", None)
        os.environ.pop("AI_TEAM_JWT_SECRET", None)
        from api.auth import reset_auth_config
        reset_auth_config()

    def test_no_token_returns_401(self) -> None:
        """GET /api/runs without token returns 401 when auth is enabled."""
        try:
            self._setup_auth_env()
            response = self.client.get("/api/runs", params={"workdir": str(self.project_root)})
            self.assertEqual(response.status_code, 401)
        finally:
            self._teardown_auth_env()

    def test_invalid_token_returns_401(self) -> None:
        """GET /api/runs with invalid token returns 401."""
        try:
            self._setup_auth_env()
            response = self.client.get(
                "/api/runs",
                params={"workdir": str(self.project_root)},
                headers={"Authorization": "Bearer invalid-token"},
            )
            self.assertEqual(response.status_code, 401)
        finally:
            self._teardown_auth_env()

    def test_login_with_valid_key_returns_jwt(self) -> None:
        """POST /api/auth/login with valid API key returns a JWT token."""
        try:
            self._setup_auth_env()
            response = self.client.post("/api/auth/login", params={"api_key": "test-key-1"})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn("access_token", data)
            self.assertEqual(data["token_type"], "bearer")
        finally:
            self._teardown_auth_env()

    def test_login_with_invalid_key_returns_401(self) -> None:
        """POST /api/auth/login with invalid API key returns 401."""
        try:
            self._setup_auth_env()
            response = self.client.post("/api/auth/login", params={"api_key": "wrong-key"})
            self.assertEqual(response.status_code, 401)
        finally:
            self._teardown_auth_env()

    def test_valid_jwt_returns_200(self) -> None:
        """GET /api/runs with valid JWT returns 200."""
        try:
            self._setup_auth_env()

            # Login to get JWT
            login_resp = self.client.post("/api/auth/login", params={"api_key": "test-key-1"})
            self.assertEqual(login_resp.status_code, 200)
            token = login_resp.json()["access_token"]

            # Access protected route
            response = self.client.get(
                "/api/runs",
                params={"workdir": str(self.project_root)},
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(response.status_code, 200)
        finally:
            self._teardown_auth_env()

    def test_health_still_works_with_auth(self) -> None:
        """GET /health still returns 200 even when auth is enabled."""
        try:
            self._setup_auth_env()
            response = self.client.get("/health")
            self.assertEqual(response.status_code, 200)
        finally:
            self._teardown_auth_env()


class TestAuthHelpers(unittest.TestCase):
    """Unit tests for auth helper functions."""

    def setUp(self) -> None:
        from api.auth import reset_auth_config
        reset_auth_config()

    def tearDown(self) -> None:
        os.environ.pop("AI_TEAM_API_KEYS", None)
        os.environ.pop("AI_TEAM_JWT_SECRET", None)
        from api.auth import reset_auth_config
        reset_auth_config()

    def test_auth_enabled_false_when_no_keys(self) -> None:
        """auth_enabled returns False when no API keys are set."""
        from api.auth import auth_enabled
        with patch.dict(os.environ, {}, clear=False):
            from api.auth import reset_auth_config
            reset_auth_config()
            self.assertFalse(auth_enabled())

    def test_auth_enabled_true_when_keys_set(self) -> None:
        """auth_enabled returns True when API keys are configured."""
        os.environ["AI_TEAM_API_KEYS"] = "my-key"
        from api.auth import reset_auth_config
        reset_auth_config()
        from api.auth import auth_enabled
        self.assertTrue(auth_enabled())

    def test_create_and_decode_token(self) -> None:
        """create_access_token and decode_access_token round-trip correctly."""
        os.environ["AI_TEAM_JWT_SECRET"] = "test-secret"
        from api.auth import reset_auth_config, create_access_token, decode_access_token
        reset_auth_config()

        token = create_access_token({"sub": "user-1"})
        payload = decode_access_token(token)
        self.assertEqual(payload["sub"], "user-1")

    def test_decode_expired_token_raises(self) -> None:
        """Decoding an expired token raises HTTPException."""
        os.environ["AI_TEAM_JWT_SECRET"] = "test-secret"
        from datetime import timedelta
        from api.auth import reset_auth_config, create_access_token, decode_access_token
        from fastapi import HTTPException
        reset_auth_config()

        token = create_access_token({"sub": "user-1"}, expires_delta=timedelta(seconds=-1))
        with self.assertRaises(HTTPException) as ctx:
            decode_access_token(token)
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
