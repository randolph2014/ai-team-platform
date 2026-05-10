from __future__ import annotations

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


class HarnessUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not HAS_FASTAPI:
            raise unittest.SkipTest("FastAPI is not installed")

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        (self.project_root / ".git").mkdir()
        (self.project_root / ".ai" / "harness" / "rules").mkdir(parents=True)
        (self.project_root / ".ai" / "harness.yaml").write_text(
            "schema_version: '1.0'\n"
            "rules:\n"
            "  - id: rule.sec\n"
            "    file: .ai/harness/rules/security.md\n",
            encoding="utf-8",
        )
        (self.project_root / ".ai" / "harness" / "rules" / "security.md").write_text("# Security\n", encoding="utf-8")
        from api.app import create_app

        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def fake_db(self):
        async def fake_get_by_id(conn, project_id):
            if project_id == "proj-1":
                return {
                    "id": "proj-1",
                    "name": "Harness UI",
                    "root_path": str(self.project_root),
                    "created_at": "2026-05-10T00:00:00",
                }
            return None

        fake_repo = type("FakeProjectRepo", (), {"get_by_id": staticmethod(fake_get_by_id)})()
        conn = AsyncMock()
        fake_db = (AsyncMock(return_value=conn), AsyncMock(), None, None, None)
        return fake_db, fake_repo

    def test_ui_contract_uses_project_id_and_returns_manifest(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            response = self.client.get("/api/projects/proj-1/harness")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["project_id"], "proj-1")
        self.assertTrue(body["manifest_hash"].startswith("sha256:"))
        self.assertTrue(all(item["path"] == ".ai/harness.yaml" or item["path"].startswith(".ai/harness/") for item in body["files"]))

    def test_ui_contract_rejects_workdir_harness_and_task_board_calls(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            harness = self.client.get("/api/projects/proj-1/harness", params={"workdir": str(self.project_root)})
            validate = self.client.post("/api/projects/proj-1/harness/validate", json={"workdir": str(self.project_root), "files": []})
            task_board = self.client.get("/api/projects/proj-1/task-board", params={"workdir": str(self.project_root)})

        self.assertEqual(harness.status_code, 400)
        self.assertEqual(validate.status_code, 400)
        self.assertEqual(task_board.status_code, 400)

    def test_ui_contract_save_requires_manifest_and_stale_save_conflicts(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            missing = self.client.put(
                "/api/projects/proj-1/harness",
                json={"files": [{"path": ".ai/harness/rules/security.md", "content": "# Updated\n"}]},
            )
            stale = self.client.put(
                "/api/projects/proj-1/harness",
                json={"manifest_hash": "sha256:stale", "files": [{"path": ".ai/harness/rules/security.md", "content": "# Updated\n"}]},
            )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"], "manifest_conflict")

    def test_ui_contract_validate_failure_does_not_write(self) -> None:
        fake_db, fake_repo = self.fake_db()

        with patch("api.routes.harness.try_persistence", return_value=fake_db), \
             patch("api.routes.harness._get_project_repo", return_value=fake_repo):
            response = self.client.post(
                "/api/projects/proj-1/harness/validate",
                json={"files": [{"path": ".ai/harness.yaml", "content": "schema_version: '1.0'\nunknown: true\n"}]},
            )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("unknown", (self.project_root / ".ai" / "harness.yaml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
