from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
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

    def test_write_audit_db_converts_created_at_for_asyncpg(self):
        import asyncio
        import engine.audit as audit_mod

        conn = AsyncMock()

        async def fake_get_connection():
            return conn

        entry = {
            "id": "00000000-0000-0000-0000-000000000001",
            "action": "create_run",
            "actor": "api-user",
            "resource_type": "run",
            "resource_id": "run-1",
            "detail": {"ok": True},
            "ip_address": None,
            "user_agent": None,
            "created_at": "2026-05-13T14:56:05.930330+00:00",
        }

        with patch("persistence.connection.get_connection", side_effect=fake_get_connection), \
             patch("persistence.connection.release_connection", new_callable=AsyncMock):
            asyncio.run(audit_mod._write_audit_db(entry))

        created_at = conn.execute.await_args.args[-1]
        self.assertIsInstance(created_at, datetime)

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

    def test_record_audit_sync_inside_running_loop_returns_entry(self):
        import asyncio
        import engine.audit as audit_mod

        original = audit_mod._AUDIT_DB_AVAILABLE
        audit_mod._AUDIT_DB_AVAILABLE = False

        async def run_sync_call():
            return audit_mod.record_audit_sync(
                action="sync_in_loop",
                actor="sync_user",
            )

        try:
            entry = asyncio.run(run_sync_call())
            self.assertEqual(entry["action"], "sync_in_loop")
            self.assertEqual(entry["actor"], "sync_user")
        finally:
            audit_mod._AUDIT_DB_AVAILABLE = original
