# Harness Core Final Report

Date: 2026-05-09
Updated: 2026-05-10

## Final Status

complete

All Core in-scope requirement rows are verified. No Checks execution, Task Board workflow, or UI implementation was added.

2026-05-10 correction: H-PATH-002 now explicitly covers manifest scanning of `.ai/harness/escape.md` symlinked to a file outside the project root. The Core layer raises `HarnessPathError`, and `GET /api/projects/{project_id}/harness` returns 400 for that scenario.

## Core In-Scope Requirement IDs

H-API-001, H-API-002, H-PROJ-001, H-PROJ-002, H-PERM-001, H-PATH-001, H-PATH-002, H-SCHEMA-001, H-MANIFEST-001, H-MANIFEST-002, H-SKILL-001, H-SKILL-002, H-DOD-001, H-DOD-002.

## Requirement Verification Matrix

| Requirement ID | Status | Modified Files | Test Files | Verification Command | Evidence |
|---|---|---|---|---|---|
| H-API-001 | verified | `api/routes/harness.py`, `api/app.py` | `tests/test_harness_routes.py` | `.venv/bin/python -m pytest tests/test_harness_routes.py -q` | 19 passed; Harness public routes are project-scoped and reject `workdir`. |
| H-API-002 | verified | `api/routes/harness.py` | `tests/test_harness_routes.py` | `.venv/bin/python -m pytest tests/test_harness_routes.py -q` | 19 passed; production-mode tests reject `workdir` on GET, validate, and PUT. |
| H-PROJ-001 | verified | `api/routes/harness.py` | `tests/test_harness_routes.py` | `.venv/bin/python -m pytest tests/test_harness_routes.py -q` | 19 passed; route lookup uses `ProjectRepo.get_by_id`; missing/deleted projects return 404. |
| H-PROJ-002 | verified | `api/routes/harness.py` | `tests/test_harness_routes.py` | `.venv/bin/python -m pytest tests/test_harness_routes.py -q` | 19 passed; resolved project roots pass existing `AI_TEAM_ALLOWED_ROOTS` validation. |
| H-PERM-001 | verified | `api/routes/harness.py` | `tests/test_harness_routes.py` | `.venv/bin/python -m pytest tests/test_harness_routes.py -q` | 19 passed; auth-enabled access requires admin or allowed project claims; anonymous dev still requires a valid project. |
| H-PATH-001 | verified | `engine/harness.py`, `api/routes/harness.py` | `tests/test_harness_core.py`, `tests/test_harness_routes.py` | `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessPathSafety -q`; `.venv/bin/python -m pytest tests/test_harness_routes.py -q` | 6 path tests passed and 19 route tests passed; writable/readable Harness files are limited to `.ai/harness.yaml` and `.ai/harness/**`. |
| H-PATH-002 | verified | `engine/harness.py`, `api/routes/harness.py` | `tests/test_harness_core.py`, `tests/test_harness_routes.py` | `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessPathSafety -q`; `.venv/bin/python -m pytest tests/test_harness_routes.py::TestHarnessManifestApi::test_get_symlink_file_escape_returns_400 -q` | 6 path tests passed; manifest scan of a symlink file escape raises `HarnessPathError`; route regression returns 400 instead of surfacing `ValueError`/500. |
| H-SCHEMA-001 | verified | `engine/harness.py`, `api/routes/harness.py` | `tests/test_harness_core.py`, `tests/test_harness_routes.py` | `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessSchemaValidation -q`; `.venv/bin/python -m pytest tests/test_harness_routes.py -q` | 8 schema tests passed and 19 route tests passed; invalid schema returns errors and write validation avoids partial writes. |
| H-MANIFEST-001 | verified | `engine/harness.py`, `api/routes/harness.py` | `tests/test_harness_core.py`, `tests/test_harness_routes.py` | `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessManifest -q`; `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessWriteValidation tests/test_harness_routes.py::TestHarnessManifestApi -q` | 4 manifest tests passed and 8 write/manifest API tests passed; GET returns manifest hash and stale PUT returns 409. |
| H-MANIFEST-002 | verified | `engine/harness.py`, `api/routes/harness.py` | `tests/test_harness_core.py`, `tests/test_harness_routes.py` | `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessManifest -q`; `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessWriteValidation tests/test_harness_routes.py::TestHarnessManifestApi -q` | 4 manifest tests passed and 8 write/manifest API tests passed; manifest changes when another Harness file changes, and `file_hash` alone is rejected. |
| H-SKILL-001 | verified | `engine/harness.py`, `engine/context_scanner.py` | `tests/test_harness_core.py`, `tests/test_context_scanner.py` | `.venv/bin/python -m pytest tests/test_context_scanner.py::TestContextScannerHarnessSummary -q` | 3 passed; Harness skills are injected as project context and are labeled as unable to override safety policy, human gates, or quality gates. |
| H-SKILL-002 | verified | `engine/harness.py` | `tests/test_harness_core.py` | `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessSchemaValidation -q` | 8 passed; Harness skill metadata requires `allowed_agents` and `forbidden_capabilities`. |
| H-DOD-001 | verified | `docs/superpowers/plans/2026-05-09-harness-core.md`, `docs/superpowers/reports/2026-05-09-harness-core-final-report.md` | Manual report review | `TOKEN="$(printf 'plan%s' '-time')"; ! rg -n "$TOKEN" docs/superpowers/plans/2026-05-09-harness-core.md` | Exit 0 with no output; the governance placeholder token is not present in the Core plan. |
| H-DOD-002 | verified | All implementation and test files in this report | Backend, focused pytest, frontend smoke, diff hygiene | Full command list below | All required commands passed; warnings are listed below and no verification was skipped. |

## Actual Commands And Results

| Command | Result |
|---|---|
| `git status --short --branch` | Current evidence: branch `main...origin/main`; Core files modified/untracked as listed in this report; Task Board/UI plan files remain untracked and were not touched for implementation. |
| `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessSchemaValidation -q` | Re-run passed: 8 passed in 0.17s. |
| `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessPathSafety::test_manifest_scan_rejects_symlink_file_escape_as_harness_path_error -q` | RED before fix: failed with raw `ValueError` from `Path.relative_to`; after fix: 1 passed in 0.10s. |
| `.venv/bin/python -m pytest tests/test_harness_routes.py::TestHarnessManifestApi::test_get_symlink_file_escape_returns_400 -q` | RED before fix: TestClient surfaced raw `ValueError`; after fix: 1 passed in 0.32s and route returns 400. |
| `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessPathSafety -q` | 6 passed in 0.12s. |
| `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessManifest -q` | 4 passed in 0.13s. |
| `.venv/bin/python -m pytest tests/test_harness_routes.py -q` | 19 passed in 0.90s. |
| `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessWriteValidation tests/test_harness_routes.py::TestHarnessManifestApi -q` | 8 passed in 0.47s. |
| `.venv/bin/python -m pytest tests/test_context_scanner.py::TestContextScannerHarnessSummary -q` | 3 passed in 0.20s. |
| `.venv/bin/python -m unittest discover -s tests -v` | Ran 766 tests in 15.628s; OK (skipped=2). |
| `.venv/bin/python -m pytest tests/test_harness*.py tests/test_routes.py tests/test_context_scanner.py -q` | 136 passed, 2 warnings in 6.84s. Warnings were existing RQ `on_failure` deprecation warnings in run route tests. |
| `cd web && npm run test` | Vitest passed: 7 test files, 21 tests in 1.81s. Vite emitted existing esbuild/oxc deprecation warnings. |
| `cd web && npm run build` | `tsc -b && vite build` succeeded; 2908 modules transformed; built in 3.18s. Vite emitted a chunk-size warning for the main JS bundle. |
| `git diff --check` | Exit 0 with no output. |
| `TOKEN="$(printf 'plan%s' '-time')"; ! rg -n "$TOKEN" docs/superpowers/plans/2026-05-09-harness-core.md` | Exit 0 with no output. |

## Implemented Files

- `AGENTS.md`
- `engine/harness.py`
- `api/routes/harness.py`
- `api/app.py`
- `engine/context_scanner.py`
- `tests/test_harness_core.py`
- `tests/test_harness_routes.py`
- `tests/test_context_scanner.py`
- `docs/superpowers/plans/2026-05-09-harness-core.md`
- `docs/superpowers/reports/2026-05-09-harness-core-final-report.md`

## Warnings, Risks, And Skipped Verification

- Unfinished items: none for Harness Core.
- Warnings: full backend unittest output included existing PyJWT `InsecureKeyLengthWarning` messages and no-DB cost-tracking skip logs in mocked tests; focused pytest reported existing RQ deprecation warnings; frontend test reported existing Vite esbuild/oxc deprecation warnings; frontend build reported an existing large chunk warning.
- Risks: permission behavior follows the confirmed Core plan policy. Auth-disabled development allows access only after valid project resolution and allowed-root validation; auth-enabled access requires admin or project allow claims.
- Skipped verification: none.
- Scope control: Checks execution, command check running, Task Board workflow, and UI were not implemented.
- Governance placeholder token (`plan` + `-time`) remaining in the Core plan: no.
