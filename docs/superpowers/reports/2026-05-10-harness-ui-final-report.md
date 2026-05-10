# Harness UI Final Report

**Date:** 2026-05-10
**Status:** complete_with_warnings
**Scope:** Harness UI sub-iteration only

## Summary

Harness UI 子迭代已完成：新增 `/harness` 页面，覆盖 Rules / Skills / Checks / Baselines / Task Board 五个 tab；新增 manifest_hash 保存、stale conflict 展示、保存前 schema validation、permission-aware editing、Markdown sanitization，以及 RunDetail 的 `harness-report.json` 展示。

本迭代没有修改 Core / Checks / Task Board 后端语义。UI 新增 Harness / Task Board 请求均走 `project_id` API，未引入公共 `workdir` Harness API。

## Preflight Evidence

- 先执行的 `git status --short --branch`：`## main...origin/main`，后续工作区变更限定在 UI、测试、计划和报告文件。
- 已读取 final reports：
  - `docs/superpowers/reports/2026-05-09-harness-core-final-report.md`
  - `docs/superpowers/reports/2026-05-09-harness-checks-final-report.md`
  - `docs/superpowers/reports/2026-05-09-harness-task-board-final-report.md`
  - `docs/superpowers/reports/2026-05-10-project-governance-configuration-final-report.md`
- 已修正 `docs/superpowers/plans/2026-05-09-harness-ui.md` 的过期 preflight：当前 Core GET response 不含 `permissions`，UI 兼容可选字段并通过 403 / mock `can_edit=false` 覆盖权限入口隐藏。

## Changed Files

- Harness page and components:
  - `web/src/pages/Harness.tsx`
  - `web/src/components/HarnessAssetEditor.tsx`
  - `web/src/components/HarnessConflictDialog.tsx`
  - `web/src/components/HarnessTaskBoard.tsx`
  - `web/src/components/HarnessReportPanel.tsx`
- Frontend contracts and routing:
  - `web/src/lib/api.ts`
  - `web/src/lib/types.ts`
  - `web/src/lib/harnessSchema.ts`
  - `web/src/App.tsx`
  - `web/src/pages/RunDetail.tsx`
  - `web/src/components/ArtifactViewer.tsx`
  - `web/src/components/ArtifactContent.tsx`
  - `web/src/components/PipelineTimeline.tsx`
  - `web/src/styles.css`
- Tests and browser smoke:
  - `tests/test_harness_ui_contract.py`
  - `web/src/test/HarnessPage.test.tsx`
  - `web/src/test/HarnessReportPanel.test.tsx`
  - `web/scripts/playwright-harness-ui-smoke.mjs`
- Planning/reporting:
  - `docs/superpowers/plans/2026-05-09-harness-ui.md`
  - `docs/superpowers/reports/2026-05-10-harness-ui-final-report.md`

## Traceability Matrix

| Requirement ID | Status | Implementation Files | Tests | Verification Command | Evidence |
|---|---|---|---|---|---|
| H-UI-001 | verified | `web/src/pages/Harness.tsx`; `web/src/components/HarnessAssetEditor.tsx`; `web/src/lib/api.ts`; `web/src/lib/types.ts`; `web/src/lib/harnessSchema.ts` | `web/src/test/HarnessPage.test.tsx`; `tests/test_harness_ui_contract.py`; `web/scripts/playwright-harness-ui-smoke.mjs` | `cd web && npm run test`; `.venv/bin/python -m pytest tests/test_harness*.py tests/test_routes.py -q`; `cd web && node scripts/playwright-harness-ui-smoke.mjs` | UI 只使用 `/api/projects/{project_id}/harness`、`/harness/validate`、`/harness/checks/run`、`/task-board`、`/task-board/events`；contract test 证明 `workdir` Harness/Task Board 调用返回 400；browser smoke 在 mock route 中断言 save/validate body 不含 `workdir`。 |
| H-UI-002 | verified | `web/src/pages/Harness.tsx`; `web/src/components/HarnessConflictDialog.tsx`; `web/src/lib/api.ts`; `web/src/lib/types.ts` | `web/src/test/HarnessPage.test.tsx`; `tests/test_harness_ui_contract.py`; `web/scripts/playwright-harness-ui-smoke.mjs` | `cd web && npm run test`; `.venv/bin/python -m pytest tests/test_harness*.py tests/test_routes.py -q`; `cd web && node scripts/playwright-harness-ui-smoke.mjs` | 保存先调用 validate；PUT body 携带 `manifest_hash`；缺失 manifest_hash 的后端 contract test 返回 400；stale hash 返回 409 并展示 `Manifest 冲突`，不自动重试、不覆盖文件。 |
| H-UI-003 | verified | `web/src/components/HarnessAssetEditor.tsx`; `web/src/components/HarnessReportPanel.tsx`; `web/src/components/MarkdownViewer.tsx`; `web/src/pages/Harness.tsx` | `web/src/test/HarnessPage.test.tsx`; `web/src/test/HarnessReportPanel.test.tsx`; `web/src/test/MarkdownViewer.test.tsx` | `cd web && npm run test`; `cd web && node scripts/playwright-harness-ui-smoke.mjs` | Rules preview 和 Harness report evidence 均通过 `MarkdownViewer` 渲染；测试覆盖 `<script>` 与 `onerror` 被移除；browser smoke 展示 sanitized report evidence。 |
| H-UI-004 | verified | `web/src/pages/Harness.tsx`; `web/src/components/HarnessAssetEditor.tsx`; `web/src/components/HarnessTaskBoard.tsx`; `web/src/lib/types.ts` | `web/src/test/HarnessPage.test.tsx`; `web/scripts/playwright-harness-ui-smoke.mjs` | `cd web && npm run test`; `cd web && node scripts/playwright-harness-ui-smoke.mjs` | `permissions.can_edit=false` 时 Save / Add / textarea 编辑入口不渲染；`permissions.can_run_checks=false` 时 Run Checks 不渲染但编辑仍可用；`permissions.can_view=false` 时不渲染 Harness 内容并显示无权限状态。真实后端 403 权限由 Core enforcement 负责。 |
| H-REPORT-002 | verified | `web/src/pages/RunDetail.tsx`; `web/src/components/HarnessReportPanel.tsx`; `web/src/lib/api.ts`; `web/src/lib/types.ts`; `web/src/lib/harnessSchema.ts`; `web/src/components/ArtifactViewer.tsx`; `web/src/components/ArtifactContent.tsx`; `web/src/components/PipelineTimeline.tsx` | `web/src/test/HarnessReportPanel.test.tsx`; `web/scripts/playwright-harness-ui-smoke.mjs` | `cd web && npm run test`; `cd web && node scripts/playwright-harness-ui-smoke.mjs`; `cd web && npm run build` | RunDetail 使用 `project_id` 查询 run 和 `harness-report.json` artifact；展示 blocking failure、warnings、baseline changes、rule violations 和 evidence refs；不改变 pipeline status 语义。 |
| H-DOD-001 | verified | `docs/superpowers/plans/2026-05-09-harness-ui.md`; `docs/superpowers/reports/2026-05-10-harness-ui-final-report.md` | All listed tests | Commands below | Plan preflight 已刷新；本 final report 已复制并填实 UI in-scope traceability rows。 |
| H-DOD-002 | verified | All changed implementation/test/report files | All listed tests | Commands below | Fresh verification 全部通过；剩余警告为既有/环境警告，不阻断 UI 子迭代。 |

## Fresh Verification

| Command | Result | Notes |
|---|---|---|
| `.venv/bin/python -m pytest tests/test_harness*.py tests/test_routes.py -q` | passed | 158 passed, 2 warnings. |
| `.venv/bin/python -m unittest discover -s tests -v` | passed | 819 tests passed, skipped=2. |
| `cd web && npm run test` | passed | 9 test files passed, 29 tests passed. Vite reported existing deprecated `esbuild` / `optimizeDeps.esbuildOptions` warnings. |
| `cd web && npm run build` | passed | TypeScript build and Vite build passed. Vite reported existing chunk size warning for a 1.28 MB JS asset. |
| `cd web && node scripts/playwright-harness-ui-smoke.mjs` | passed | Chromium opened Harness and RunDetail pages; verified five tabs, save manifest hash, conflict display, read-only UI, and Harness report display. Vite logged a WS proxy `ECONNREFUSED 127.0.0.1:8000` warning because the smoke test mocks HTTP APIs and does not run the backend websocket server. |
| `git diff --check` | passed | No whitespace errors. |

## Boundary Confirmation

- UI Harness / Task Board helpers only use project-scoped endpoints.
- Save payload includes `manifest_hash`.
- Stale save displays conflict and does not overwrite.
- UI cannot create arbitrary paths; generated paths are restricted to `.ai/harness.yaml` or `.ai/harness/**`.
- Permission-aware UI hides edit entry points when `can_edit=false`, hides Run Checks when `can_run_checks=false`, and hides Harness content when `can_view=false`; 403 shows no-access state.
- Markdown rendering uses sanitized Markdown viewer.
- RunDetail report display is read-only and does not change Checks or pipeline blocking semantics.

## Residual Warnings

- Current Core GET Harness response has no `permissions` field. UI supports optional `permissions`, but real edit permission granularity remains a future backend contract if needed.
- Playwright smoke logs websocket proxy `ECONNREFUSED` in mocked dev-server mode; HTTP UI assertions passed and process exited 0.
- Vite build still reports a large chunk warning unrelated to this Harness UI scope.
