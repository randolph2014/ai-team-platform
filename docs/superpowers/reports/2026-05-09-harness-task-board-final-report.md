# Harness Task Board Final Report

验收日期：2026-05-10

## Final Status

`complete_with_warnings`

Task Board 子迭代范围内的 H-TASK-001 到 H-TASK-005 均已实现并通过 fresh verification。状态不是 plain `complete`，因为验证输出包含既有的非阻塞警告：PyJWT 测试密钥长度警告、RQ `on_failure` deprecation warning、Vite esbuild/oxc deprecation warning，以及前端 build 的 chunk-size warning。

未实现 UI，未修改 `web/**`，未引入 DB schema，未重写 Core / Checks 已验收逻辑。Harness 公共 API 继续使用 `project_id`，Task Board public API 拒绝 `workdir`。

## Scope Summary

实现内容：

- 仓库文件优先的 Task Board 存储：`.ai/harness/tasks/*.json` 为任务聚合记录，`.ai/harness/task-events/*.json` 为 append-only 事件证据，`.ai/harness/task-board.json` 仅作为可重建 snapshot。
- Task state model：覆盖 `planned`、`qa_failed`、`review_changes_requested`、`accepted`、`rejected`、`cancelled` 等状态。
- accepted state guard：底层 storage 只允许 `acceptance_confirm + approved` 写 accepted；public event API 进一步拒绝直接写 accepted，accepted 只由最终 pipeline acceptance 内部写入。
- Orchestrator / run lifecycle hooks：记录 QA failed、review changes requested、acceptance rejected、cancelled，以及最终 acceptance approved。
- Related task matching：按 requirement text、tags、related files、decision IDs/history 匹配并返回 match reasons。
- Context scan injection：将 related tasks 注入 `codebase-context.md` 的 `## Harness Related Tasks`，并写入 `codebase-context.json.harness.related_tasks`。
- Requirement / planning artifact contract：当 context 中存在 related tasks 时，`requirement-final.json` 和 `task-plan.json` 必须逐条写 `related_task_decisions` 的采纳或拒绝理由。
- Project-scoped Task Board API：`GET /api/projects/{project_id}/task-board` 和 `POST /api/projects/{project_id}/task-board/events`。

## Traceability Matrix

| Requirement ID | Status | Modified Files | Test Files | Verification Command | Evidence |
|---|---|---|---|---|---|
| H-TASK-001 | verified | `engine/task_board.py`; `engine/orchestrator.py` | `tests/test_task_board.py`; `tests/test_engine.py` | `.venv/bin/python -m pytest tests/test_task_board.py tests/test_context_scanner.py::TestContextScannerTaskBoard tests/test_context_scanner.py::TestContextScannerHarnessSummary tests/test_artifact_contracts.py::TestRelatedTaskArtifactReasons tests/test_harness_routes.py::TestTaskBoardProjectApi tests/test_engine.py::TestHarnessTaskBoardLifecycle tests/test_routes.py::TestCancelRetryRoutes -q` | Focused suite passed: 28 passed. Full backend regression passed: 815 tests OK, skipped=2. |
| H-TASK-002 | verified | `engine/task_board.py`; `engine/orchestrator.py`; `api/routes/harness.py`; `api/routes/runs.py` | `tests/test_task_board.py`; `tests/test_engine.py`; `tests/test_harness_routes.py`; `tests/test_routes.py` | Same focused command above | Focused suite passed: 28 passed. QA failed, review changes requested, acceptance rejected, and cancelled append non-accepted history. Public API rejects direct accepted writes. |
| H-TASK-003 | verified | `engine/task_board.py`; `engine/context_scanner.py`; `engine/orchestrator.py` | `tests/test_task_board.py`; `tests/test_context_scanner.py`; `tests/test_engine.py` | Same focused command above | Focused suite passed: 28 passed. Related tasks are matched by text, tags, files, and decisions, then injected into Markdown and JSON context scan outputs. |
| H-TASK-004 | verified | `engine/artifact_contracts.py`; `engine/schemas/requirement-final.json`; `engine/schemas/task-plan.json`; `templates/agents/requirements-analyst.md`; `templates/agents/planner.md` | `tests/test_artifact_contracts.py` | Same focused command above | Focused suite passed: 28 passed. Missing related-task adopt/reject reason fails validation only when related tasks exist. |
| H-TASK-005 | verified | `engine/task_board.py`; `engine/orchestrator.py`; `api/routes/harness.py`; `api/routes/runs.py` | `tests/test_task_board.py`; `tests/test_engine.py`; `tests/test_harness_routes.py`; `tests/test_routes.py` | Same focused command above | Focused suite passed: 28 passed. Task events require non-empty `run_id`, `artifact_dir`, and `decision_ids`; Task Board APIs resolve by `project_id` and reject `workdir`. |

## Key Evidence

Storage authority:

- `engine/task_board.py` writes aggregate records under `.ai/harness/tasks/*.json`.
- `engine/task_board.py` appends immutable event files under `.ai/harness/task-events/*.json` with exclusive create.
- `engine/task_board.py` rebuilds `.ai/harness/task-board.json` from records; reads do not require the snapshot.

Accepted-state boundary:

- `engine/task_board.py` rejects accepted state unless `source_stage == acceptance_confirm` and `decision == approved`.
- `api/routes/harness.py` rejects public `POST /task-board/events` requests that try to write `state = accepted`, so external callers cannot fake final acceptance.
- `engine/orchestrator.py` writes accepted state only after final `acceptance_confirm` has an approved human decision.
- `api/routes/runs.py` records cancellation as `cancelled`, and tests prove cancellation does not overwrite an existing accepted task state.

Context and artifact adoption boundary:

- `engine/context_scanner.py` passes requirement text into related-task lookup and writes related tasks into both Markdown and JSON context.
- `engine/artifact_contracts.py` reads `codebase-context.json.harness.related_tasks` and requires `related_task_decisions` in `requirement-final.json` and `task-plan.json`.
- `templates/agents/requirements-analyst.md` and `templates/agents/planner.md` now explicitly tell agents to adopt or reject each related task with a reason.

Project API boundary:

- `api/routes/harness.py` Task Board endpoints sit under `/api/projects/{project_id}/...`.
- `api/routes/harness.py` reuses the existing project resolver and rejects `workdir` in query/body.
- No `workdir` Task Board API was introduced.

## Actual Commands And Results

Preflight:

```text
git status --short --branch
## main...origin/main
?? docs/superpowers/plans/2026-05-09-harness-task-board.md
?? docs/superpowers/plans/2026-05-09-harness-ui.md
```

Focused Task Board verification:

```text
.venv/bin/python -m pytest tests/test_task_board.py tests/test_context_scanner.py::TestContextScannerTaskBoard tests/test_context_scanner.py::TestContextScannerHarnessSummary tests/test_artifact_contracts.py::TestRelatedTaskArtifactReasons tests/test_harness_routes.py::TestTaskBoardProjectApi tests/test_engine.py::TestHarnessTaskBoardLifecycle tests/test_routes.py::TestCancelRetryRoutes -q
28 passed in 0.88s
```

Full backend regression:

```text
.venv/bin/python -m unittest discover -s tests -v
Ran 815 tests in 16.933s
OK (skipped=2)
```

Frontend regression verification only, with no UI changes:

```text
cd web && npm run test
Test Files  7 passed (7)
Tests       21 passed (21)
```

```text
cd web && npm run build
tsc -b && vite build
2908 modules transformed
built in 2.90s
```

Diff hygiene and UI boundary:

```text
git diff --check
PASS
```

```text
git diff --name-only -- web
NO OUTPUT
```

```text
git status --short web
NO OUTPUT
```

Final working tree:

```text
git status --short --branch
## main...origin/main
 M api/routes/harness.py
 M api/routes/runs.py
 M engine/artifact_contracts.py
 M engine/context_scanner.py
 M engine/orchestrator.py
 M engine/schemas/requirement-final.json
 M engine/schemas/task-plan.json
 M templates/agents/planner.md
 M templates/agents/requirements-analyst.md
 M tests/test_artifact_contracts.py
 M tests/test_context_scanner.py
 M tests/test_engine.py
 M tests/test_harness_routes.py
 M tests/test_routes.py
?? docs/superpowers/plans/2026-05-09-harness-task-board.md
?? docs/superpowers/plans/2026-05-09-harness-ui.md
?? docs/superpowers/reports/2026-05-09-harness-task-board-final-report.md
?? engine/task_board.py
?? tests/test_task_board.py
```

## Warnings And Risks

- Existing warnings only: PyJWT short test secret warnings, RQ `on_failure` deprecation warnings, Vite esbuild/oxc deprecation warnings, and Vite chunk-size warning.
- No verification was skipped.
- No event-vs-snapshot redesign was needed: the selected authority is task files plus task events; snapshot remains derived.
- No UI, DB schema, or cross-iteration design change was needed.

## Scope Boundary Confirmation

- UI implementation: not done.
- `web/**`: not modified.
- Core logic rewrite: not done.
- Checks command execution rewrite: not done; Checks still routes through `run_harness_verification` and existing Quality Gate runner.
- Public Harness API `workdir`: not introduced; Task Board APIs reject `workdir`.
- `task-board.json`: not authoritative; only a rebuildable snapshot.
