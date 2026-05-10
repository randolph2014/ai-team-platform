from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False
else:
    HAS_FASTAPI = True


class HarnessRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not HAS_FASTAPI:
            raise unittest.SkipTest("FastAPI 未安装，跳过 Harness route tests")

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        (self.project_root / ".git").mkdir()
        (self.project_root / ".ai" / "harness").mkdir(parents=True)
        (self.project_root / ".ai" / "harness.yaml").write_text("schema_version: '1.0'\n", encoding="utf-8")

        from api.app import create_app

        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def fake_db(self, project=None):
        project = project or {
            "id": "proj-1",
            "name": "Harness Project",
            "root_path": str(self.project_root),
            "created_at": "2026-05-09T00:00:00",
        }

        async def fake_get_by_id(conn, id):
            if id == project["id"]:
                return project
            return None

        fake_repo = type("FakeProjectRepo", (), {"get_by_id": staticmethod(fake_get_by_id)})()
        conn = AsyncMock()
        fake_db = (AsyncMock(return_value=conn), AsyncMock(), None, None, None)
        return fake_db, fake_repo


class TestHarnessPublicApiBoundary(HarnessRoutesTest):
    def test_harness_routes_use_project_id_only(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            response = self.client.get("/api/projects/proj-1/harness")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["project_id"], "proj-1")
        self.assertIn("manifest_hash", body)

    def test_harness_rejects_workdir_query_and_body(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            query_response = self.client.get("/api/projects/proj-1/harness", params={"workdir": str(self.project_root)})
            body_response = self.client.post(
                "/api/projects/proj-1/harness/validate",
                json={"workdir": str(self.project_root), "files": []},
            )

        self.assertEqual(query_response.status_code, 400)
        self.assertEqual(body_response.status_code, 400)


class TestHarnessProductionBoundary(HarnessRoutesTest):
    def test_production_rejects_workdir_even_with_project_id(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.is_production_mode", return_value=True), \
             patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            response = self.client.get("/api/projects/proj-1/harness", params={"workdir": str(self.project_root)})

        self.assertEqual(response.status_code, 400)

    def test_production_rejects_workdir_on_validate_and_put(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.is_production_mode", return_value=True), \
             patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            validate_response = self.client.post(
                "/api/projects/proj-1/harness/validate",
                json={"workdir": str(self.project_root), "files": []},
            )
            put_response = self.client.put(
                "/api/projects/proj-1/harness",
                json={"workdir": str(self.project_root), "manifest_hash": "sha256:bad", "files": []},
            )

        self.assertEqual(validate_response.status_code, 400)
        self.assertEqual(put_response.status_code, 400)


class TestHarnessProjectResolver(HarnessRoutesTest):
    def test_valid_project_id_resolves_root(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch.dict(os.environ, {"AI_TEAM_ALLOWED_ROOTS": ""}, clear=False), \
             patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            response = self.client.get("/api/projects/proj-1/harness")

        self.assertEqual(response.status_code, 200)

    def test_missing_project_returns_404(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            response = self.client.get("/api/projects/missing/harness")

        self.assertEqual(response.status_code, 404)

    def test_deleted_project_returns_404(self) -> None:
        fake_db, fake_repo = self.fake_db(project={"id": "deleted", "name": "Deleted", "root_path": str(self.project_root), "created_at": "now"})

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            response = self.client.get("/api/projects/proj-1/harness")

        self.assertEqual(response.status_code, 404)

    def test_project_root_outside_allowed_roots_returns_403(self) -> None:
        outside = self.project_root.parent / f"{self.project_root.name}-outside"
        outside.mkdir()
        (outside / ".git").mkdir()
        fake_db, fake_repo = self.fake_db(project={"id": "proj-1", "name": "Outside", "root_path": str(outside), "created_at": "now"})

        with patch.dict(os.environ, {"AI_TEAM_ALLOWED_ROOTS": str(self.project_root)}, clear=False), \
             patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            response = self.client.get("/api/projects/proj-1/harness")

        self.assertEqual(response.status_code, 403)

    def test_allowed_root_child_is_accepted(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch.dict(os.environ, {"AI_TEAM_ALLOWED_ROOTS": str(self.project_root.parent)}, clear=False), \
             patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            response = self.client.get("/api/projects/proj-1/harness")

        self.assertEqual(response.status_code, 200)


class TestHarnessProjectPermission(HarnessRoutesTest):
    def test_authorized_project_access_succeeds(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo), \
             patch("api.routes.harness.auth_enabled", return_value=True), \
             patch("api.auth.auth_enabled", return_value=True), \
             patch("api.auth.decode_access_token", return_value={"sub": "user-1", "project_ids": ["proj-1"]}):
            response = self.client.get("/api/projects/proj-1/harness", headers={"Authorization": "Bearer token"})

        self.assertEqual(response.status_code, 200)

    def test_unauthorized_project_access_returns_403(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo), \
             patch("api.routes.harness.auth_enabled", return_value=True), \
             patch("api.auth.auth_enabled", return_value=True), \
             patch("api.auth.decode_access_token", return_value={"sub": "user-1", "project_ids": ["other"]}):
            response = self.client.get("/api/projects/proj-1/harness", headers={"Authorization": "Bearer token"})

        self.assertEqual(response.status_code, 403)

    def test_development_anonymous_access_still_requires_valid_project(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo), \
             patch("api.routes.harness.auth_enabled", return_value=False):
            valid = self.client.get("/api/projects/proj-1/harness")
            missing = self.client.get("/api/projects/missing/harness")

        self.assertEqual(valid.status_code, 200)
        self.assertEqual(missing.status_code, 404)


class TestHarnessWriteSafety(HarnessRoutesTest):
    def test_put_rejects_non_harness_file(self) -> None:
        fake_db, fake_repo = self.fake_db()
        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            current = self.client.get("/api/projects/proj-1/harness").json()["manifest_hash"]
            response = self.client.put(
                "/api/projects/proj-1/harness",
                json={"manifest_hash": current, "files": [{"path": ".ai/team.yaml", "content": "bad"}]},
            )

        self.assertEqual(response.status_code, 400)


class TestHarnessValidationApi(HarnessRoutesTest):
    def test_invalid_schema_returns_400_and_writes_nothing(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            response = self.client.post(
                "/api/projects/proj-1/harness/validate",
                json={"files": [{"path": ".ai/harness.yaml", "content": "schema_version: '1.0'\nunknown: true\n"}]},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual((self.project_root / ".ai" / "harness.yaml").read_text(encoding="utf-8"), "schema_version: '1.0'\n")


class TestHarnessManifestApi(HarnessRoutesTest):
    def test_get_returns_manifest_hash(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            response = self.client.get("/api/projects/proj-1/harness")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["manifest_hash"].startswith("sha256:"))

    def test_get_symlink_file_escape_returns_400(self) -> None:
        outside = self.project_root.parent / f"{self.project_root.name}-outside-file.md"
        outside.write_text("outside", encoding="utf-8")
        (self.project_root / ".ai" / "harness" / "escape.md").symlink_to(outside)
        fake_db, fake_repo = self.fake_db()

        try:
            with patch("api.routes.harness.try_persistence", return_value=fake_db), \
                 patch("api.routes.harness._get_project_repo", return_value=fake_repo):
                response = self.client.get("/api/projects/proj-1/harness")
        finally:
            outside.unlink(missing_ok=True)

        self.assertEqual(response.status_code, 400)

    def test_stale_put_returns_409(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            response = self.client.put(
                "/api/projects/proj-1/harness",
                json={"manifest_hash": "sha256:stale", "files": [{"path": ".ai/harness.yaml", "content": "schema_version: '1.0'\n"}]},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "manifest_conflict")

    def test_old_manifest_conflicts_after_different_file_changes(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            current = self.client.get("/api/projects/proj-1/harness").json()["manifest_hash"]
            (self.project_root / ".ai" / "harness" / "rules").mkdir()
            (self.project_root / ".ai" / "harness" / "rules" / "security.md").write_text("changed", encoding="utf-8")
            response = self.client.put(
                "/api/projects/proj-1/harness",
                json={"manifest_hash": current, "files": [{"path": ".ai/harness.yaml", "content": "schema_version: '1.0'\n"}]},
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn(".ai/harness/rules/security.md", response.json()["changed_files"])

    def test_file_hash_alone_is_rejected(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            response = self.client.put(
                "/api/projects/proj-1/harness",
                json={"file_hash": "sha256:abc", "files": [{"path": ".ai/harness.yaml", "content": "schema_version: '1.0'\n"}]},
            )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
