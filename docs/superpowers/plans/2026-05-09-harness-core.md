# Harness Core Implementation Plan

> **For implementation agents:** This plan covers only Harness Core. Do not implement Checks, Task Board, or UI. If implementation requires those areas, stop and report before editing more files.

**Goal:** Build the safe repo-file-backed Harness Core asset layer: project_id resolution, loader/schema validation, path safety, manifest hashing, context_scan summary injection, and public project_id API boundaries.

**Architecture:** Keep repository files as the Harness source of truth. Add an engine-level Harness loader for file safety, schema validation, and manifest hashing; add a project_id-only API route that resolves projects through the existing project registry and allowlist; inject a compact Harness summary into context_scan because the scanner excludes `.ai` by default.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, PyYAML, unittest/pytest-compatible tests.

---

## Preflight Evidence

- `git status --short --branch` before planning:
  - `## main...origin/main`
  - `?? docs/superpowers/plans/2026-05-09-harness-core.md`
  - `?? docs/superpowers/plans/2026-05-09-harness-task-board.md`
  - `?? docs/superpowers/plans/2026-05-09-harness-ui.md`
  - `?? docs/superpowers/specs/2026-05-09-harness-governance-design.md`
- Repository-root `AGENTS.md` file is absent. `find . -maxdepth 2 -name 'AGENTS.md' -print` returned no files, so apply the session-provided AGENTS instructions for this repo.
- Governance spec Core scope is limited to Project Resolver, Harness Loader, Harness schema validation, Path safety, Manifest hash, Context scan Harness summary injection, and public `project_id` API boundary.
- Collaboration workflow spec requires `context_scan` before requirement synthesis/planning, hard human gates, standardized artifacts, and reject loopback. Core must therefore inject Harness summary into `context_scan` as project governance context without changing Checks, Task Board, UI, or human gate behavior.
- Existing code evidence:
  - `persistence/repository.py` has `ProjectRepo.get_by_id`, `get_by_root_path`, `list_all`, and `delete`.
  - `api/routes/projects.py` already has `AI_TEAM_ALLOWED_ROOTS` validation via `_validate_root_path`.
  - `api/routes/runs.py` already rejects `workdir` in production when `project_id` is absent.
  - `engine/context_scanner.py` excludes `.ai` via `DEFAULT_EXCLUDE_DIRS`, so Harness summary must be explicitly injected.
  - `api/app.py` includes routers manually; a new Harness router must be registered there.

## Hard Scope Boundaries

- In scope:
  - `GET /api/projects/{project_id}/harness`
  - `PUT /api/projects/{project_id}/harness`
  - `POST /api/projects/{project_id}/harness/validate`
  - Engine helpers for safe Harness file access, loading, validation, manifest hash, and summary generation.
  - Context scan markdown/json Harness summary injection.
- Out of scope:
  - `POST /api/projects/{project_id}/harness/checks/run`
  - `GET /api/projects/{project_id}/task-board`
  - `POST /api/projects/{project_id}/task-board/events`
  - Pattern check execution, command check execution, baseline comparison, `harness-report.json`, pipeline blocking semantics, React pages/components, navigation, and RunDetail display.
- Stop rule: if any in-scope row cannot be implemented without Checks, Task Board, or UI, stop and report. Do not hide the expansion inside "small supporting changes."

## Planned File Changes

- Create: `engine/harness.py`
  - Owns Harness Pydantic models, YAML parsing, asset metadata validation, path safety, symlink escape prevention, manifest hashing, stale manifest conflict detection, and summary generation.
- Modify: `engine/context_scanner.py`
  - Adds Harness summary to markdown and JSON outputs without enabling general `.ai` scanning.
- Create: `api/routes/harness.py`
  - Owns public project_id-only Harness Core endpoints, ProjectRepo lookup, allowlist validation, permission check, request/response models, and HTTP error mapping.
- Modify: `api/app.py`
  - Registers `api.routes.harness.router` under `/api`.
- Create: `tests/test_harness_core.py`
  - Unit tests for loader, schema validation, path safety, manifest stability/conflict detection, and context summary helpers.
- Create: `tests/test_harness_routes.py`
  - Route tests for public project_id API boundary, production workdir rejection, missing/deleted project handling, allowlist rejection, permission rejection, schema errors, and stale manifest 409.
- Modify: `tests/test_context_scanner.py`
  - Focused tests proving Harness summary is injected into markdown and JSON while `.ai` remains excluded from generic tree scanning.

No implementation should modify `engine/quality_gates.py`, `web/**`, task-board storage files, or pipeline stage execution in this Core sub-iteration.

## Public API Contract

### GET `/api/projects/{project_id}/harness`

Response:

```json
{
  "project_id": "project_xxx",
  "manifest_hash": "sha256:...",
  "files": [
    {
      "path": ".ai/harness.yaml",
      "hash": "sha256:...",
      "content": "schema_version: '1.0'\n..."
    }
  ],
  "summary": {
    "schema_version": "1.0",
    "rules_count": 0,
    "skills_count": 0,
    "checks_count": 0,
    "baselines_count": 0,
    "warnings": []
  },
  "validation": {
    "valid": true,
    "errors": []
  }
}
```

### POST `/api/projects/{project_id}/harness/validate`

Request:

```json
{
  "files": [
    {"path": ".ai/harness.yaml", "content": "schema_version: '1.0'\n"}
  ]
}
```

Response:

```json
{"valid": true, "errors": [], "manifest_hash": "sha256:..."}
```

### PUT `/api/projects/{project_id}/harness`

Request:

```json
{
  "manifest_hash": "sha256:last-seen",
  "files": [
    {"path": ".ai/harness.yaml", "content": "schema_version: '1.0'\n"}
  ]
}
```

Rules:

- Body must use `manifest_hash`; `file_hash` is not accepted as a substitute.
- Any `workdir` query or body field is rejected. Production and development Harness public APIs both keep the stricter `project_id` contract.
- All file paths must be relative POSIX paths under `.ai/harness.yaml` or `.ai/harness/**`.
- Absolute paths, `../`, empty paths, directory paths, and symlink escapes are rejected.
- If current manifest differs from request `manifest_hash`, return `409 Conflict` with `error: manifest_conflict`, `current_manifest_hash`, and `changed_files`.
- Validate the complete candidate Harness asset set before writing. Invalid schema returns `400` and writes nothing.

## Permission Decision Before Implementation

Current auth only returns `{"sub": "anonymous"}` in development mode and API-key/JWT payloads do not define a persisted project ACL. Because H-PERM-001 changes permission behavior, implementation must not start until the user confirms the Harness-only policy below or provides a different one:

- Auth disabled / anonymous development mode: allow project access after project_id resolution and root allowlist validation.
- Auth enabled: allow when JWT payload has `is_admin: true`, `role: "admin"`, `project_ids: ["*"]`, or the requested `project_id` in `project_ids` / `projects` / `allowed_projects`.
- Auth enabled without one of those claims: return `403`.

This keeps Harness public file access fail-closed under auth while preserving local development compatibility.

## Traceability Matrix

These rows are copied from the Core scope of `docs/superpowers/specs/2026-05-09-harness-governance-design.md` plus the all-iteration DoD rows. No in-scope row contains the governance placeholder token.

| Requirement ID | Sub-Iteration | Design Source | Implementation Files | Tests | Verification Command | Status | Evidence |
|---|---|---|---|---|---|---|---|
| H-API-001 | Core | Public API Boundary | `api/routes/harness.py`, `api/app.py` | `tests/test_harness_routes.py::TestHarnessPublicApiBoundary::test_harness_routes_use_project_id_only`; `tests/test_harness_routes.py::TestHarnessPublicApiBoundary::test_harness_rejects_workdir_query_and_body` | `.venv/bin/python -m pytest tests/test_harness_routes.py::TestHarnessPublicApiBoundary -q` | verified | Verified via `.venv/bin/python -m pytest tests/test_harness_routes.py -q`: 19 passed; project-scoped Harness routes use `project_id` and reject `workdir`. |
| H-API-002 | Core | Public API Boundary | `api/routes/harness.py` | `tests/test_harness_routes.py::TestHarnessProductionBoundary::test_production_rejects_workdir_even_with_project_id`; `tests/test_harness_routes.py::TestHarnessProductionBoundary::test_production_rejects_workdir_on_validate_and_put` | `.venv/bin/python -m pytest tests/test_harness_routes.py::TestHarnessProductionBoundary -q` | verified | Verified via `.venv/bin/python -m pytest tests/test_harness_routes.py -q`: 19 passed; production mode rejects `workdir` on read/validate/write. |
| H-PROJ-001 | Core | Public API Boundary | `api/routes/harness.py`, `persistence/repository.py` | `tests/test_harness_routes.py::TestHarnessProjectResolver::test_valid_project_id_resolves_root`; `tests/test_harness_routes.py::TestHarnessProjectResolver::test_missing_project_returns_404`; `tests/test_harness_routes.py::TestHarnessProjectResolver::test_deleted_project_returns_404` | `.venv/bin/python -m pytest tests/test_harness_routes.py::TestHarnessProjectResolver -q` | verified | Verified via `.venv/bin/python -m pytest tests/test_harness_routes.py -q`: 19 passed; route lookup uses `ProjectRepo.get_by_id` and missing/deleted projects return `404`. |
| H-PROJ-002 | Core | Public API Boundary | `api/routes/harness.py`, `api/routes/projects.py` | `tests/test_harness_routes.py::TestHarnessProjectResolver::test_project_root_outside_allowed_roots_returns_403`; `tests/test_harness_routes.py::TestHarnessProjectResolver::test_allowed_root_child_is_accepted` | `.venv/bin/python -m pytest tests/test_harness_routes.py::TestHarnessProjectResolver -q` | verified | Verified via `.venv/bin/python -m pytest tests/test_harness_routes.py -q`: 19 passed; project root passes through existing `AI_TEAM_ALLOWED_ROOTS` validation. |
| H-PERM-001 | Core | Public API Boundary | `api/routes/harness.py` | `tests/test_harness_routes.py::TestHarnessProjectPermission::test_authorized_project_access_succeeds`; `tests/test_harness_routes.py::TestHarnessProjectPermission::test_unauthorized_project_access_returns_403`; `tests/test_harness_routes.py::TestHarnessProjectPermission::test_development_anonymous_access_still_requires_valid_project` | `.venv/bin/python -m pytest tests/test_harness_routes.py::TestHarnessProjectPermission -q` | verified | Verified via `.venv/bin/python -m pytest tests/test_harness_routes.py -q`: 19 passed; auth-enabled requests require admin or project allow claims, anonymous dev still requires valid project. |
| H-PATH-001 | Core | Source Of Truth Model | `engine/harness.py`, `api/routes/harness.py` | `tests/test_harness_core.py::TestHarnessPathSafety::test_allows_only_harness_yaml_and_harness_directory`; `tests/test_harness_routes.py::TestHarnessWriteSafety::test_put_rejects_non_harness_file` | `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessPathSafety tests/test_harness_routes.py::TestHarnessWriteSafety -q` | verified | Verified via `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessPathSafety -q`: 6 passed, plus route suite 19 passed; only `.ai/harness.yaml` and `.ai/harness/**` are accepted. |
| H-PATH-002 | Core | Source Of Truth Model | `engine/harness.py`, `api/routes/harness.py` | `tests/test_harness_core.py::TestHarnessPathSafety::test_rejects_absolute_path`; `tests/test_harness_core.py::TestHarnessPathSafety::test_rejects_parent_traversal`; `tests/test_harness_core.py::TestHarnessPathSafety::test_rejects_symlink_escape`; `tests/test_harness_core.py::TestHarnessPathSafety::test_manifest_scan_rejects_symlink_file_escape_as_harness_path_error`; `tests/test_harness_routes.py::TestHarnessManifestApi::test_get_symlink_file_escape_returns_400` | `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessPathSafety -q`; `.venv/bin/python -m pytest tests/test_harness_routes.py::TestHarnessManifestApi::test_get_symlink_file_escape_returns_400 -q` | verified | Verified via `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessPathSafety -q`: 6 passed; direct path checks and manifest scan reject symlink escapes with `HarnessPathError`; route regression returns 400. |
| H-SCHEMA-001 | Core | Manifest And Conflict Model | `engine/harness.py`, `api/routes/harness.py` | `tests/test_harness_core.py::TestHarnessSchemaValidation::test_invalid_harness_yaml_fails`; `tests/test_harness_core.py::TestHarnessSchemaValidation::test_skill_metadata_requires_allowed_agents_and_forbidden_capabilities`; `tests/test_harness_routes.py::TestHarnessValidationApi::test_invalid_schema_returns_400_and_writes_nothing` | `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessSchemaValidation tests/test_harness_routes.py::TestHarnessValidationApi -q` | verified | Verified via `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessSchemaValidation -q`: 8 passed, plus route suite 19 passed; invalid schema returns error and does not write. |
| H-MANIFEST-001 | Core | Manifest And Conflict Model | `engine/harness.py`, `api/routes/harness.py` | `tests/test_harness_core.py::TestHarnessManifest::test_manifest_hash_is_stable_and_reproducible`; `tests/test_harness_routes.py::TestHarnessManifestApi::test_get_returns_manifest_hash`; `tests/test_harness_routes.py::TestHarnessManifestApi::test_stale_put_returns_409` | `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessManifest tests/test_harness_routes.py::TestHarnessManifestApi -q` | verified | Verified via `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessManifest -q`: 4 passed, plus manifest route focused command 8 passed; GET returns manifest hash and stale PUT returns `409`. |
| H-MANIFEST-002 | Core | Manifest And Conflict Model | `engine/harness.py`, `api/routes/harness.py` | `tests/test_harness_core.py::TestHarnessManifest::test_manifest_changes_when_another_harness_file_changes`; `tests/test_harness_routes.py::TestHarnessManifestApi::test_old_manifest_conflicts_after_different_file_changes`; `tests/test_harness_routes.py::TestHarnessManifestApi::test_file_hash_alone_is_rejected` | `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessManifest tests/test_harness_routes.py::TestHarnessManifestApi -q` | verified | Verified via `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessManifest -q`: 4 passed, plus manifest route focused command 8 passed; another file changes manifest and `file_hash` alone is rejected. |
| H-SKILL-001 | Core | Security Priority | `engine/harness.py`, `engine/context_scanner.py` | `tests/test_harness_core.py::TestHarnessSkillPolicy::test_harness_skill_summary_is_project_context_not_platform_policy`; `tests/test_context_scanner.py::TestContextScannerHarnessSummary::test_harness_summary_labels_skills_as_project_context` | `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessSkillPolicy tests/test_context_scanner.py::TestContextScannerHarnessSummary -q` | verified | Verified via `.venv/bin/python -m pytest tests/test_context_scanner.py::TestContextScannerHarnessSummary -q`: 3 passed; Harness skills are injected as project context and cannot override safety policy/human gates/quality gates. |
| H-SKILL-002 | Core | Security Priority | `engine/harness.py` | `tests/test_harness_core.py::TestHarnessSchemaValidation::test_skill_metadata_requires_allowed_agents_and_forbidden_capabilities`; `tests/test_harness_core.py::TestHarnessSchemaValidation::test_valid_skill_metadata_loads` | `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessSchemaValidation -q` | verified | Verified via `.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessSchemaValidation -q`: 8 passed; skill metadata requires `allowed_agents` and `forbidden_capabilities`. |
| H-DOD-001 | All | Definition Of Done | `docs/superpowers/plans/2026-05-09-harness-core.md`; `docs/superpowers/reports/2026-05-09-harness-core-final-report.md` | Manual review plus placeholder-token grep; final report traceability matrix must keep every in-scope row `verified` before completion claim | `TOKEN="$(printf 'plan%s' '-time')"; ! rg -n "$TOKEN" docs/superpowers/plans/2026-05-09-harness-core.md`; final report creation review | verified | Verified: placeholder-token grep exited 0 with no matches; final report is created with all Core rows marked `verified`. |
| H-DOD-002 | All | Definition Of Done | `docs/superpowers/plans/2026-05-09-harness-core.md`, implementation files, final report | Fresh command output from focused tests, full backend tests, required frontend smoke commands, and `git diff --check` | `.venv/bin/python -m unittest discover -s tests -v`; `.venv/bin/python -m pytest tests/test_harness*.py tests/test_routes.py tests/test_context_scanner.py -q`; `cd web && npm run test`; `cd web && npm run build`; `git diff --check` | verified | Verified: unittest `766 tests OK (skipped=2)`; focused pytest `136 passed, 2 warnings`; web test `7 files/21 tests passed`; web build succeeded; `git diff --check` exited 0. |

## Implementation Tasks

### Task 1: Add Harness Core Engine Models And Loader

**Objective:** Create the engine-owned Harness asset model without route or UI concerns.

**Files:**

- Create: `engine/harness.py`
- Test: `tests/test_harness_core.py`

Steps:

1. Add failing tests for valid minimal `.ai/harness.yaml`, invalid YAML, invalid top-level type, unknown/unsafe file references, and valid empty Harness state.
2. Implement Pydantic models with `extra="forbid"` for Harness config and asset refs.
3. Parse `.ai/harness.yaml` with PyYAML and return a typed `HarnessBundle`.
4. Treat missing `.ai/harness.yaml` as an empty valid Harness bundle with warning `harness_config_missing`, not as an execution failure.
5. Keep check declarations as metadata only. Do not execute or convert checks in this task.

Expected focused command:

```bash
.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessSchemaValidation -q
```

### Task 2: Implement Harness Path Safety

**Objective:** Guarantee Core file access cannot escape `.ai/harness.yaml` and `.ai/harness/**`.

**Files:**

- Modify: `engine/harness.py`
- Test: `tests/test_harness_core.py`

Steps:

1. Add failing tests for allowed `.ai/harness.yaml`, allowed nested Harness files, absolute paths, `../`, path normalization, directory targets, and symlink escape.
2. Implement `resolve_harness_path(project_root: Path, rel_path: str) -> Path`.
3. Resolve paths with `strict=False` for missing write targets, then validate each existing parent symlink with `resolve()`.
4. Use POSIX relative paths in API/manifest output.
5. Reuse this helper for all loader and writer file access.

Expected focused command:

```bash
.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessPathSafety -q
```

### Task 3: Implement Manifest Hash And Conflict Helpers

**Objective:** Provide deterministic manifest-level conflict detection across the whole Harness asset package.

**Files:**

- Modify: `engine/harness.py`
- Test: `tests/test_harness_core.py`

Steps:

1. Add failing tests for stable ordering, deterministic hash, hash changes when another Harness file changes, empty manifest hash, and changed file reporting.
2. Implement `compute_harness_manifest(project_root: Path)`.
3. Include all regular files under `.ai/harness.yaml` and `.ai/harness/**`; skip directories and reject symlink escapes.
4. Hash each file as `sha256:<hex>`.
5. Hash the canonical JSON list of `{path, hash}` entries to produce `manifest_hash`.

Expected focused command:

```bash
.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessManifest -q
```

### Task 4: Add Public Harness Project API

**Objective:** Expose Core read/validate/write operations through project_id-only routes.

**Files:**

- Create: `api/routes/harness.py`
- Modify: `api/app.py`
- Test: `tests/test_harness_routes.py`

Steps:

1. Add failing route tests for GET/PUT/validate happy paths through `project_id`.
2. Add failing route tests proving `workdir` query/body fields are rejected.
3. Add failing tests for missing project, deleted project, database unavailable, and allowlist rejection.
4. Add failing tests for authorized/unauthorized project access after the user confirms the permission policy in this plan.
5. Implement route-local ProjectRepo lookup using existing `try_persistence()` and `ProjectRepo.get_by_id`.
6. Pass resolved root through existing project allowlist validation.
7. Map Harness errors to HTTP statuses: schema/path errors `400`, missing project `404`, unauthorized `403`, conflict `409`, DB unavailable `503`.
8. Register router in `api/app.py`.

Expected focused command:

```bash
.venv/bin/python -m pytest tests/test_harness_routes.py -q
```

### Task 5: Wire Validate And Write Safety

**Objective:** Ensure PUT validates the full candidate asset set before writing and never writes partial invalid state.

**Files:**

- Modify: `engine/harness.py`
- Modify: `api/routes/harness.py`
- Test: `tests/test_harness_core.py`
- Test: `tests/test_harness_routes.py`

Steps:

1. Add failing tests where a PUT changes `.ai/harness.yaml` plus one asset file.
2. Add failing tests where invalid schema returns `400` and existing files remain unchanged.
3. Add failing tests where stale manifest returns `409` with `current_manifest_hash` and `changed_files`.
4. Implement candidate validation in a temporary in-memory file map before disk writes.
5. Write files only after manifest check and schema validation pass.

Expected focused command:

```bash
.venv/bin/python -m pytest tests/test_harness_core.py::TestHarnessWriteValidation tests/test_harness_routes.py::TestHarnessManifestApi -q
```

### Task 6: Inject Harness Summary Into Context Scan

**Objective:** Make context_scan aware of Harness assets without scanning arbitrary `.ai` content.

**Files:**

- Modify: `engine/context_scanner.py`
- Test: `tests/test_context_scanner.py`

Steps:

1. Add failing tests proving generic tree scanning still excludes `.ai`.
2. Add failing tests proving markdown scan includes `## Harness Summary` when Harness assets exist.
3. Add failing tests proving `scan_to_json()` includes a `harness` object with manifest hash, counts, and warnings.
4. Call Harness summary helper directly from `ContextScanner.scan()` and `scan_to_json()`.
5. Ensure summary contains only metadata/counts and safe relative paths, not full skill/rule contents.

Expected focused command:

```bash
.venv/bin/python -m pytest tests/test_context_scanner.py::TestContextScannerHarnessSummary -q
```

### Task 7: Core Verification And Review Preparation

**Objective:** Produce fresh evidence before any completion claim.

**Files:**

- No source files beyond the planned Core files.
- Final report file to be created only after implementation is done and verified.

Steps:

1. Run focused Harness commands from each task.
2. Run the spec-required backend command:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

3. Run the spec-required focused pytest command:

```bash
.venv/bin/python -m pytest tests/test_harness*.py tests/test_routes.py tests/test_context_scanner.py -q
```

4. Run the spec-required frontend smoke commands even though Core does not modify UI:

```bash
cd web && npm run test
cd web && npm run build
```

5. Run diff hygiene:

```bash
git diff --check
```

6. Update the Core final report traceability rows with fresh command output and status.
7. If any command fails after planned fixes, mark final status `partial` or `blocked`; do not claim complete.

## Self-Check

- [x] `git status --short --branch` was run before planning.
- [x] Repository-root `AGENTS.md` absence was verified; session-provided AGENTS instructions are applied.
- [x] Governance spec and collaboration workflow spec were read.
- [x] Plan file is limited to Harness Core.
- [x] Checks / Task Board / UI implementation is explicitly out of scope.
- [x] Core traceability rows were copied and filled with Implementation Files, Tests, Verification Command, Status, and Evidence.
- [x] In-scope rows contain no governance placeholder token.
- [x] The plan includes a stop rule for scope expansion.
- [x] The plan stops before implementation code.
