# Harness Task Board Implementation Plan

> **Execution boundary:** this plan is limited to the Harness Task Board sub-iteration. UI implementation remains out of scope.

**Goal:** Build repository-backed project task memory so accepted work, failed histories, related historical decisions, and explicit adopt/reject reasons can influence later requirements and plans.

**Architecture:** Use `.ai/harness/tasks/*.json` as per-task aggregate records and `.ai/harness/task-events/*.json` as append-only transition evidence. Treat `.ai/harness/task-board.json` only as a derived snapshot. Inject related tasks into `context_scan`, expose project-scoped Task Board APIs under `/api/projects/{project_id}/task-board`, then enforce that `requirement-final.json` and `task-plan.json` explain which related historical decisions were adopted or rejected.

**Tech Stack:** Python 3.12, Pydantic, JSON schema artifacts, existing orchestrator/context scan pipeline, unittest/pytest-compatible tests. No React/Vite/UI files are in scope.

---

## Preflight Evidence

- `git status --short --branch` was executed first on 2026-05-10: `## main...origin/main`; untracked `docs/superpowers/plans/2026-05-09-harness-task-board.md` and `docs/superpowers/plans/2026-05-09-harness-ui.md`.
- Repository-root `AGENTS.md` is not present under `/Users/wurui/IdeaProjects/ai-team-platform`; this plan follows the AGENTS instructions supplied in the session prompt.
- Read `docs/superpowers/specs/2026-05-09-harness-governance-design.md`; Task Board source rows are `H-TASK-001` through `H-TASK-005`.
- Read `docs/superpowers/reports/2026-05-09-harness-core-final-report.md`; Core rows are verified and Core scope explicitly did not implement Task Board or UI.
- Read `docs/superpowers/reports/2026-05-09-harness-checks-final-report.md`; Checks rows are verified, command checks reuse `QualityGateRunner`, and no Task Board/UI workflow was implemented.
- Read `docs/superpowers/reports/2026-05-10-project-governance-configuration-final-report.md`; legacy project `.ai/team.yaml` config source was deprecated and Task Board must not reintroduce project config as truth source.
- Current code evidence:
  - `engine/context_scanner.py` already injects Core Harness summary, but still excludes `.ai` from tree scanning; Task Board related tasks must be explicitly injected.
  - `api/routes/harness.py` already owns project-scoped Harness endpoints and reusable `project_id -> project_root` resolution helpers.
  - `engine/artifact_contracts.py` validates `requirement-final.json` and `task-plan.json` against strict schemas.
  - `engine/schemas/requirement-final.json` and `engine/schemas/task-plan.json` currently use `additionalProperties: false`, so related-task decision fields require schema changes.
  - `templates/team.yaml` already has `context_scan -> requirement_synthesis -> planning -> ... -> acceptance_confirm -> retrospect`.
  - `engine/models.py` has `HumanDecision` but no stable decision ID, so Task Board must derive traceable `decision_ids`.

## Scope

In scope:

- `.ai/harness/tasks/*.json`
- `.ai/harness/task-events/*.json`
- optional `.ai/harness/task-board.json` snapshot generation
- Task state model
- Related task matching
- Context scan injection
- Requirement/planning artifact adoption or rejection reasons for related tasks
- Project-scoped Task Board read/event API under `/api/projects/{project_id}/task-board`
- Orchestrator hooks for QA failed, review changes requested, acceptance rejected, accepted, and cancelled histories

Out of scope:

- UI implementation or UI tests
- DB as the source of truth for Task Board state
- Harness Core or Checks implementation
- Replacing the existing pipeline engine
- Treating `task-board.json` as the only persistent state
- Reintroducing `.ai/team.yaml` as a project config source

## Storage And State Design

Authoritative write model:

- `tasks/*.json`: current aggregate per task, updated under a repository-local lock and written by atomic replace.
- `task-events/*.json`: append-only transition log, written with exclusive create and a timestamp/run/event suffix.
- `task-board.json`: optional derived snapshot rebuilt from task records and events. It is never required to load or update state.

Allowed task states:

```text
proposed
planned
in_progress
blocked
qa_failed
review_changes_requested
accepted
rejected
cancelled
archived
```

State transition rule:

- `accepted` is only reachable from an `acceptance_confirm` human decision with `decision = approved`.
- `qa_failed`, `review_changes_requested`, `rejected`, and `cancelled` remain historical or current non-accepted states and must never update `accepted_at` or accepted summary fields.
- Cancelled runs may append cancellation events and set a task to `cancelled`, but cannot create accepted state.

Traceability rule:

- Every `TaskRecord` and `TaskEvent` must include `run_id`, `artifact_dir`, and `decision_ids`.
- Derived decision IDs should be deterministic strings such as:
  - `human:{run_id}:{stage_id}:{history_index}`
  - `artifact:{run_id}:requirement-final:{sha256(topic + decision)}`
  - `artifact:{run_id}:task-plan:{task_id}`

## Target Files

Create:

- `engine/task_board.py`
- `tests/test_task_board.py`

Modify:

- `engine/context_scanner.py`
- `engine/orchestrator.py`
- `engine/artifact_contracts.py`
- `engine/schemas/requirement-final.json`
- `engine/schemas/task-plan.json`
- `templates/agents/requirements-analyst.md`
- `templates/agents/planner.md`
- `api/routes/harness.py`
- `api/routes/runs.py`
- `tests/test_context_scanner.py`
- `tests/test_artifact_contracts.py`
- `tests/test_engine.py`
- `tests/test_harness_routes.py`
- `tests/test_routes.py`

Do not modify:

- `web/**`
- UI route/page/component files
- persistence migrations for Task Board source of truth

## Traceability Matrix

| Requirement ID | Sub-Iteration | Design Source | Implementation Files | Tests | Verification Command | Status | Evidence |
|---|---|---|---|---|---|---|---|
| H-TASK-001 | Task Board | Sub-Iteration 3 | `engine/task_board.py`; `engine/orchestrator.py`; `.ai/harness/tasks/*.json`; `.ai/harness/task-events/*.json` | `tests/test_task_board.py::TestTaskBoardStateModel`; `tests/test_engine.py::TestHarnessTaskBoardLifecycle` | `.venv/bin/python -m pytest tests/test_task_board.py tests/test_context_scanner.py::TestContextScannerTaskBoard tests/test_context_scanner.py::TestContextScannerHarnessSummary tests/test_artifact_contracts.py::TestRelatedTaskArtifactReasons tests/test_harness_routes.py::TestTaskBoardProjectApi tests/test_engine.py::TestHarnessTaskBoardLifecycle tests/test_routes.py::TestCancelRetryRoutes -q` | verified | Focused Task Board suite passed: 28 passed. Full backend regression passed: 815 tests OK, skipped=2. |
| H-TASK-002 | Task Board | Sub-Iteration 3 | `engine/task_board.py`; `engine/orchestrator.py`; `api/routes/harness.py`; `api/routes/runs.py` | `tests/test_task_board.py::TestTaskBoardAcceptedGuards`; `tests/test_engine.py::TestHarnessTaskBoardLifecycle`; `tests/test_harness_routes.py::TestTaskBoardProjectApi`; `tests/test_routes.py::TestCancelRetryRoutes` | `.venv/bin/python -m pytest tests/test_task_board.py tests/test_context_scanner.py::TestContextScannerTaskBoard tests/test_context_scanner.py::TestContextScannerHarnessSummary tests/test_artifact_contracts.py::TestRelatedTaskArtifactReasons tests/test_harness_routes.py::TestTaskBoardProjectApi tests/test_engine.py::TestHarnessTaskBoardLifecycle tests/test_routes.py::TestCancelRetryRoutes -q` | verified | Focused Task Board suite passed: 28 passed. Tests cover QA/review/rejected/cancelled non-accepted histories and public API rejection of accepted writes. |
| H-TASK-003 | Task Board | Sub-Iteration 3 | `engine/task_board.py`; `engine/context_scanner.py`; `engine/orchestrator.py` | `tests/test_task_board.py::TestRelatedTaskMatching`; `tests/test_context_scanner.py::TestContextScannerTaskBoard`; `tests/test_engine.py::TestHarnessTaskBoardLifecycle` | `.venv/bin/python -m pytest tests/test_task_board.py tests/test_context_scanner.py::TestContextScannerTaskBoard tests/test_context_scanner.py::TestContextScannerHarnessSummary tests/test_artifact_contracts.py::TestRelatedTaskArtifactReasons tests/test_harness_routes.py::TestTaskBoardProjectApi tests/test_engine.py::TestHarnessTaskBoardLifecycle tests/test_routes.py::TestCancelRetryRoutes -q` | verified | Focused Task Board suite passed: 28 passed. Related tasks are matched by text/tags/files/decisions and appear in `codebase-context.md` plus `codebase-context.json`. |
| H-TASK-004 | Task Board | Sub-Iteration 3 | `engine/artifact_contracts.py`; `engine/schemas/requirement-final.json`; `engine/schemas/task-plan.json`; `templates/agents/requirements-analyst.md`; `templates/agents/planner.md` | `tests/test_artifact_contracts.py::TestRelatedTaskArtifactReasons` | `.venv/bin/python -m pytest tests/test_task_board.py tests/test_context_scanner.py::TestContextScannerTaskBoard tests/test_context_scanner.py::TestContextScannerHarnessSummary tests/test_artifact_contracts.py::TestRelatedTaskArtifactReasons tests/test_harness_routes.py::TestTaskBoardProjectApi tests/test_engine.py::TestHarnessTaskBoardLifecycle tests/test_routes.py::TestCancelRetryRoutes -q` | verified | Focused Task Board suite passed: 28 passed. Missing related-task adopt/reject reasons fail validation only when related tasks exist. |
| H-TASK-005 | Task Board | Sub-Iteration 3 | `engine/task_board.py`; `engine/orchestrator.py`; `api/routes/harness.py`; `api/routes/runs.py` | `tests/test_task_board.py::TestTaskBoardTraceability`; `tests/test_engine.py::TestHarnessTaskBoardLifecycle`; `tests/test_harness_routes.py::TestTaskBoardProjectApi`; `tests/test_routes.py::TestCancelRetryRoutes` | `.venv/bin/python -m pytest tests/test_task_board.py tests/test_context_scanner.py::TestContextScannerTaskBoard tests/test_context_scanner.py::TestContextScannerHarnessSummary tests/test_artifact_contracts.py::TestRelatedTaskArtifactReasons tests/test_harness_routes.py::TestTaskBoardProjectApi tests/test_engine.py::TestHarnessTaskBoardLifecycle tests/test_routes.py::TestCancelRetryRoutes -q` | verified | Focused Task Board suite passed: 28 passed. Task/event schema requires `run_id`, `artifact_dir`, `decision_ids`; Task Board APIs resolve by `project_id` and reject `workdir`. |

## Implementation Tasks

### Task 1: Add Task Board Models And File Store

**Files:**

- Create: `engine/task_board.py`
- Test: `tests/test_task_board.py`

Steps:

- [x] Define `TaskState`, `TaskRecord`, and `TaskEvent` Pydantic models plus related-task result payloads.
- [x] Add path helpers that resolve only under `.ai/harness/tasks`, `.ai/harness/task-events`, and `.ai/harness/task-board.json`.
- [x] Add `load_tasks(project_root)`, `append_event(project_root, event)`, `record_task_event(project_root, event)`, and `build_snapshot(project_root)` APIs.
- [x] Use exclusive create for event files and atomic replace for task files.
- [x] Use a repository-local lock file `.ai/harness/.task-board.lock` while updating aggregate task records.
- [x] Ensure loading tasks never requires `task-board.json`.
- [x] Tests prove a missing snapshot does not block reads or writes.

Expected narrow command:

```bash
.venv/bin/python -m pytest tests/test_task_board.py -q
```

### Task 2: Enforce Accepted-State Guards

**Files:**

- Modify: `engine/task_board.py`
- Modify: `engine/orchestrator.py`
- Modify: `api/routes/harness.py`
- Modify: `api/routes/runs.py`
- Test: `tests/test_task_board.py`
- Test: `tests/test_engine.py`
- Test: `tests/test_harness_routes.py`
- Test: `tests/test_routes.py`

Steps:

- [x] Implement a transition helper that rejects `accepted` unless the event source is `acceptance_confirm` and the human decision is approved.
- [x] Add orchestrator hooks for QA failed and review changes requested that append non-accepted events only.
- [x] Add acceptance rejection hook that records `rejected` history but does not accepted-update the task.
- [x] Add acceptance approval hook that writes accepted state after final human approval.
- [x] Add run cancellation hook in `api/routes/runs.py` that records a cancelled event when run context is available.
- [x] Add `GET /api/projects/{project_id}/task-board` and `POST /api/projects/{project_id}/task-board/events`; both reject `workdir`, and the event API rejects direct accepted writes.
- [x] Tests include pollution cases for QA failed, review changes requested, acceptance rejected, cancelled, and public API accepted-write rejection.

Expected narrow command:

```bash
.venv/bin/python -m pytest tests/test_task_board.py tests/test_engine.py tests/test_harness_routes.py tests/test_routes.py -q
```

### Task 3: Implement Related Task Matching

**Files:**

- Modify: `engine/task_board.py`
- Test: `tests/test_task_board.py`

Steps:

- [x] Implement token normalization for requirement text and task titles/summaries.
- [x] Score matches from requirement text overlap, tags, related files, and decision ID/history overlap.
- [x] Return deterministic ordering by score, state priority, updated time, and task ID.
- [x] Include accepted and non-accepted histories; do not hide failures, rejections, or cancellations.
- [x] Cap output size and include match reasons so downstream agents can explain adoption or rejection.

Expected narrow command:

```bash
.venv/bin/python -m pytest tests/test_task_board.py::TestRelatedTaskMatching -q
```

### Task 4: Inject Related Tasks Into Context Scan

**Files:**

- Modify: `engine/context_scanner.py`
- Modify: `engine/orchestrator.py`
- Test: `tests/test_context_scanner.py`
- Test: `tests/test_engine.py`

Steps:

- [x] Extend `scan_codebase` and `scan_to_json` with optional `requirement_text` input.
- [x] In `_run_context_stage`, pass `report.requirement` into context scanning.
- [x] Add a Markdown section `## Harness Related Tasks` when matches exist.
- [x] Add JSON payload under `harness.related_tasks` in `codebase-context.json`.
- [x] Preserve existing behavior when no Task Board files exist.

Expected narrow command:

```bash
.venv/bin/python -m pytest tests/test_context_scanner.py tests/test_engine.py::TestContextScan -q
```

### Task 5: Require Adopt/Reject Reasons In Requirement And Planning Artifacts

**Files:**

- Modify: `engine/schemas/requirement-final.json`
- Modify: `engine/schemas/task-plan.json`
- Modify: `engine/artifact_contracts.py`
- Modify: `templates/agents/requirements-analyst.md`
- Modify: `templates/agents/planner.md`
- Test: `tests/test_artifact_contracts.py`
- Test: `tests/test_engine.py`

Steps:

- [x] Add optional `related_task_decisions` arrays to both schemas.
- [x] Each item must include `task_id`, `action` (`adopted` or `rejected`), `reason`, and optional `decision_ids`.
- [x] Update prompt templates to require explicit adopt/reject reasons when `codebase-context` contains related tasks.
- [x] Extend artifact validation so related tasks in `codebase-context.json` require corresponding decision rows in `requirement-final.json` and `task-plan.json`.
- [x] Keep the field optional when no related tasks exist, so old no-related-task flows remain valid.

Expected narrow command:

```bash
.venv/bin/python -m pytest tests/test_artifact_contracts.py tests/test_engine.py -q
```

### Task 6: Full Regression And Final Report Inputs

**Files:**

- No new implementation files.
- Update the future final report after implementation, not in this planning-only session.

Steps:

- [x] Run focused Task Board tests.
- [x] Run full backend tests required by the governance spec.
- [x] Run frontend tests/build only as regression verification; do not modify UI.
- [x] Run `git diff --check`.
- [x] Final report includes the traceability matrix with rows verified by fresh command output.

Full verification commands:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pytest tests/test_task_board.py tests/test_context_scanner.py tests/test_artifact_contracts.py tests/test_engine.py tests/test_harness_routes.py tests/test_routes.py -q
cd web && npm run test
cd web && npm run build
git diff --check
```

## Stop Conditions

Stop and ask the user before implementation if any of these are true:

- Core/Checks verified public contracts conflict with Task Board implementation requirements.
- Existing Core/Checks code introduces a different Task Board access contract than repository-backed task files plus task events.
- Concurrency cannot be handled safely with task files, event files, exclusive create, and a local lock without introducing DB as source of truth.
- Any implementation path would make `task-board.json` the only durable state source.
- Any accepted-state transition would need to happen before `acceptance_confirm` is approved by a human.
- Artifact validation cannot enforce related-task adopt/reject reasons without breaking existing no-related-task runs.
- Any UI file must be modified to satisfy an in-scope row.

## Plan Self-Check

- [x] Only Task Board sub-iteration is planned.
- [x] UI implementation is explicitly out of scope.
- [x] `task-board.json` is snapshot-only, not the concurrency source of truth.
- [x] QA failed, review changes requested, acceptance rejected, and cancelled cannot write accepted state.
- [x] Accepted state is only reachable after final human approval.
- [x] Task records/events require `run_id`, `artifact_dir`, and `decision_ids`.
- [x] Task Board traceability rows are copied and all in-scope governance placeholders are filled.
- [x] No event-vs-snapshot decision is needed under the current spec because task files plus task events are the selected authority and snapshot is derived.
- [x] Implementation code was written only after the user explicitly requested execution.
