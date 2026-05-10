# Harness Epic Final Report

Date: 2026-05-10
Status: complete_with_warnings

## Scope

This report closes the Harness epic across the already accepted sub-iterations:

- Harness Core
- Harness Checks
- Project Governance Configuration cleanup
- Harness Task Board
- Harness UI

The goal of this report is not to repeat every sub-iteration detail. It records the cross-iteration acceptance evidence that the platform now has a project-level Harness capability: repository-backed rules, skills, checks, baselines, task memory, and UI management, all scoped by `project_id`.

## Commit Evidence

| Commit | Scope |
|---|---|
| `c969b40` | Implement Harness Core governance |
| `e42c2a3` | Implement Harness Checks verification |
| `943c19b` | Deprecate project team config source |
| `9899277` | Implement Harness Task Board memory |
| `4f7e5c8` | Implement Harness UI governance surface |

Push evidence:

```text
git push origin main
To github.com:randolph2014/ai-team-platform.git
   9899277..4f7e5c8  main -> main
```

Current branch evidence after push:

```text
git status --short --branch --untracked-files=all
## main...origin/main
```

## Capability Acceptance Matrix

| Capability | Status | Evidence |
|---|---|---|
| Repository files are the Harness source of truth | PASS | Core stores and validates `.ai/harness.yaml` and `.ai/harness/**`; Task Board stores `.ai/harness/tasks/*.json` and `.ai/harness/task-events/*.json`; no DB-first Harness source was introduced. |
| Public Harness APIs use `project_id` instead of `workdir` | PASS | Harness and Task Board routes live under `/api/projects/{project_id}/...`; route and UI contract tests reject `workdir` inputs. |
| Command checks reuse `QualityGateRunner` | PASS | Checks report documents the call path through `engine.quality_gates.run_quality_gates`; tests spy on `run_quality_gates`; `engine/harness_checks.py` has no second shell runner. |
| Rules, skills, checks, and baselines are enforceable | PASS | Core schema validation covers rule/skill metadata and safe file references; Checks verification covers command, pattern, baseline, report, blocking, and warning behavior. |
| Harness checks generate report artifacts | PASS | `harness-report.json` validates against artifact schema; `harness-feedback.md` is written for blocking checks; RunDetail displays Harness report artifacts. |
| Task Board makes history available to future requirements | PASS | Related tasks are matched by text, tags, files, and decisions; context scan injects related tasks into Markdown and JSON outputs; requirement/planning artifacts must adopt or reject related tasks with reasons when related tasks exist. |
| UI manages Harness assets without exposing arbitrary file paths | PASS | `/harness` page manages Rules / Skills / Checks / Baselines / Task Board; generated editable paths are restricted to `.ai/harness.yaml` or `.ai/harness/**`; save uses `manifest_hash` and stale conflicts return 409. |
| Permission-aware UI does not expose forbidden actions | PASS | UI hides edit entry points when `can_edit=false`, hides Run Checks when `can_run_checks=false`, hides Harness content when `can_view=false`, and shows no-access state for 403. |
| Deprecated project governance config does not remain a competing source | PASS | Historical project team config is ignored by default, explicit use is rejected, `init` is not exposed, and run/resume/human-decision paths reject the deprecated config. |

## Fresh Verification

| Command | Result | Notes |
|---|---|---|
| `.venv/bin/python -m pytest tests/test_harness*.py tests/test_task_board.py tests/test_context_scanner.py tests/test_quality_gates.py tests/test_routes.py -q` | PASS | 205 passed, 2 warnings. Covers Core, Checks, Task Board, context injection, QualityGateRunner behavior, project APIs, and route boundaries. |
| `cd web && npm run test` | PASS | 9 test files passed, 29 tests passed. Covers Harness page, report panel, Markdown sanitization, and existing UI behavior. |
| `.venv/bin/python -m unittest discover -s tests -v` | PASS | 819 tests OK, skipped=2. Covers the broader backend regression surface. |
| `cd web && npm run build` | PASS | TypeScript and Vite build succeeded. Vite reported the existing large chunk warning. |
| `cd web && node scripts/playwright-harness-ui-smoke.mjs` | PASS | Browser smoke exited 0. It verified `/harness` tabs, save manifest hash, conflict display, read-only UI, and RunDetail Harness report display. |

## Residual Warnings

- Backend tests still emit existing RQ `on_failure` deprecation warnings and PyJWT test-secret length warnings in some unittest output. These are not introduced by the Harness epic.
- Frontend tests still emit existing Vite esbuild/oxc deprecation warnings.
- Frontend build still emits the existing chunk-size warning for the main JS bundle.
- Playwright smoke logs a Vite websocket proxy `ECONNREFUSED 127.0.0.1:8000` warning because the smoke test mocks HTTP APIs and does not run the backend websocket server. The browser assertions passed and the process exited 0.

## Conclusion

Harness is now closed as a platform epic, with the main product distinction implemented:

```text
Demand delivery platform
  -> not only runs agents
  -> constrains agents with project-level Harness
  -> turns rules / skills / checks / baselines into repository-backed engineering memory
  -> uses Task Board history as context for the next requirement
```

The next iteration should not reopen the completed Core / Checks / Task Board / UI scope unless new evidence shows a defect. Future work should be framed as a new productization or production-hardening iteration with its own plan, acceptance rows, and final report.
