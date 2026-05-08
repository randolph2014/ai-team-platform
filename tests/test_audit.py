from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from engine.audit import record_audit


class TestAuditLogging(unittest.TestCase):
    def setUp(self):
        self.output_dir = tempfile.mkdtemp()
        os.environ["AI_TEAM_OUTPUT_DIR"] = self.output_dir

    def tearDown(self):
        os.environ.pop("AI_TEAM_OUTPUT_DIR", None)

    def test_record_audit_file_fallback(self):
        import engine.audit as audit_mod
        original = audit_mod._AUDIT_DB_AVAILABLE
        audit_mod._AUDIT_DB_AVAILABLE = False
        try:
            import asyncio
            entry = asyncio.run(record_audit(
                action="test_action",
                actor="test_user",
                resource_type="run",
                resource_id="run-123",
                detail={"key": "value"},
            ))
            self.assertEqual(entry["action"], "test_action")
            self.assertEqual(entry["actor"], "test_user")
            self.assertEqual(entry["resource_type"], "run")
            self.assertEqual(entry["resource_id"], "run-123")
            self.assertEqual(entry["detail"]["key"], "value")
            self.assertIn("id", entry)
            self.assertIn("created_at", entry)
            audit_dir = Path(self.output_dir) / "_audit"
            self.assertTrue(audit_dir.exists())
            files = list(audit_dir.glob("audit-*.jsonl"))
            self.assertEqual(len(files), 1)
            line = files[0].read_text(encoding="utf-8").strip()
            parsed = json.loads(line)
            self.assertEqual(parsed["action"], "test_action")
        finally:
            audit_mod._AUDIT_DB_AVAILABLE = original

    def test_record_audit_db_path(self):
        import engine.audit as audit_mod
        original = audit_mod._AUDIT_DB_AVAILABLE
        audit_mod._AUDIT_DB_AVAILABLE = True
        try:
            import asyncio
            with patch("engine.audit._write_audit_db", new_callable=AsyncMock) as mock_db:
                asyncio.run(record_audit(
                    action="login",
                    actor="api-user",
                    resource_type="session",
                ))
                mock_db.assert_called_once()
                entry = mock_db.call_args[0][0]
                self.assertEqual(entry["action"], "login")
                self.assertEqual(entry["actor"], "api-user")
        finally:
            audit_mod._AUDIT_DB_AVAILABLE = original

    def test_record_audit_sync(self):
        import engine.audit as audit_mod
        original = audit_mod._AUDIT_DB_AVAILABLE
        audit_mod._AUDIT_DB_AVAILABLE = False
        try:
            entry = audit_mod.record_audit_sync(
                action="sync_action",
                actor="sync_user",
            )
            self.assertEqual(entry["action"], "sync_action")
        finally:
            audit_mod._AUDIT_DB_AVAILABLE = original
