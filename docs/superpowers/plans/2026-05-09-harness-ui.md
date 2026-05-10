# Harness UI Implementation Plan

> **For agentic workers:** 本计划只执行 Harness UI 子迭代。实现前必须重新读取本计划、`docs/superpowers/specs/2026-05-09-harness-governance-design.md`、Core final report、Checks final report、Task Board final report、Project Governance cleanup final report；若已提交的 API 契约与本计划冲突，停止并让用户决策。

**Goal:** 为 Harness Governance Layer 增加可用的管理界面和 RunDetail 报告展示，覆盖 Rules、Skills、Checks、Baselines、Task Board 五个 tab，并把 manifest 冲突、权限、schema validation、Markdown sanitize 变成 UI 可见且可测试的行为。

**Architecture:** 前端只通过 `project_id` 调用 Harness 和 Task Board API，不暴露 `workdir`。UI 读取 Core/Checks/Task Board 已稳定的 repo-file-first API，保存前先调用 validate API，保存时携带 `manifest_hash`，遇到 `409 manifest_conflict` 只显示冲突与刷新入口，不覆盖文件。Markdown 渲染统一复用已有 `MarkdownViewer` 的 DOMPurify + ReactMarkdown 渲染链路，RunDetail 通过 Harness report 专用面板展示 blocking、warnings、baseline changes 和 evidence。

**Tech Stack:** React 18, TypeScript, Vite, Vitest, Testing Library, Playwright, FastAPI route contract tests, Python unittest/pytest.

---

## Input Evidence

- 2026-05-10 implementation preflight 已刷新：`git status --short --branch` 输出 `## main...origin/main`；工作区变更限定在 Harness UI 页面、RunDetail report 展示、前端 API/types/styles、UI/contract/browser tests，以及本计划文件。
- 前置提交已在当前 `main` 历史上：Core `c969b40`、Checks `e42c2a3`、Project Governance cleanup `943c19b`、Task Board `9899277`。
- 已重新读取 final reports：`docs/superpowers/reports/2026-05-09-harness-core-final-report.md`、`docs/superpowers/reports/2026-05-09-harness-checks-final-report.md`、`docs/superpowers/reports/2026-05-09-harness-task-board-final-report.md`、`docs/superpowers/reports/2026-05-10-project-governance-configuration-final-report.md`。
- 当前路径 `/Users/wurui/IdeaProjects/ai-team-platform` 下未找到仓库根 `AGENTS.md` 文件；本计划按用户消息中提供的 AGENTS 约束执行。
- 当前真实 Core API response 不包含 `permissions` 字段；UI 必须兼容可选 `permissions` 字段，并在 Harness GET 返回 403 或 `permissions.can_edit=false` 的 mock/未来响应中隐藏编辑入口。不得为满足 UI 自行修改 Core 后端权限语义。
- 当前仓库证据显示：已有 `web/src/components/MarkdownViewer.tsx` 使用 `DOMPurify.sanitize(content)`；已有 `web/src/test/MarkdownViewer.test.tsx` 覆盖 `<script>` 和 `onerror` 被移除。
- 当前仓库证据显示：已有 `web/src/components/ProjectSelector.tsx` 读取 `/api/projects`，但没有全局 project context；Harness UI 需要自己维护选中 `project_id`。
- 当前仓库证据显示：`web/src/lib/api.ts` 的 run/artifact 读取仍以 `workdir` 为主；RunDetail Harness report 展示必须补 project-aware 查询路径，避免 UI 新增 `workdir` 依赖。
- 当前仓库证据显示：`api/routes/runs.py`、`api/routes/artifacts.py` 已支持部分 `project_id` 查询参数；Harness UI 不应新增任何公共 `workdir` Harness API。

## Scope

In scope:

- 新增 Harness 页面，包含五个 tab：Rules、Skills、Checks、Baselines、Task Board。
- 新增 Harness API client/types，所有 Harness/Task Board UI 请求使用 `project_id`。
- 保存前调用 schema validation API；validation 失败不发保存请求。
- 保存请求携带读取时的 `manifest_hash`。
- stale save 显示 manifest conflict，不覆盖文件。
- 无权限用户看不到编辑、保存、新增、删除入口。
- Markdown 预览和 Harness report markdown/evidence 渲染必须 sanitize。
- RunDetail 展示 `harness-report.json` 的 blocking reason、warnings、baseline changes 和 check evidence。
- 添加 Vitest 覆盖、FastAPI UI 契约测试、Playwright 浏览器 smoke 验证。

Out of scope:

- 不实现 Core asset model、path safety、manifest hash 后端算法。
- 不实现 Checks execution engine、Quality Gate runner 复用、baseline raise-only 语义。
- 不实现 Task Board event model 和 matching 算法。
- 不编辑 `.ai/harness.yaml` 和 `.ai/harness/**` 之外的项目文件；UI 也不提供任意路径输入框。
- 不把 Settings 页面改造成 Harness 页面，不复用 `workdir` settings API。

## Required Upstream API Contract

实现前从 Core/Checks/Task Board final report 逐项核对以下接口。任一接口不存在、仍要求 `workdir`、或返回结构缺少 `manifest_hash` 信息，停止并让用户决策。当前 Core final report 和代码证据显示 GET response 不包含 `permissions`；UI 只兼容可选 `permissions` 字段，不把它作为后端契约前提。

```text
GET  /api/projects/{project_id}/harness
PUT  /api/projects/{project_id}/harness
POST /api/projects/{project_id}/harness/validate
POST /api/projects/{project_id}/harness/checks/run
GET  /api/projects/{project_id}/task-board
POST /api/projects/{project_id}/task-board/events
GET  /api/runs/{run_id}?project_id={project_id}
GET  /api/runs/{run_id}/artifacts/harness-report.json?project_id={project_id}
```

Expected response shape for UI planning:

```ts
type HarnessBundle = {
  project_id: string;
  manifest_hash: string;
  permissions?: {
    can_view: boolean;
    can_edit: boolean;
    can_run_checks: boolean;
  };
  files: Array<{ path: string; hash: string; content: string; kind: 'config' | 'rule' | 'skill' | 'check' | 'baseline' }>;
  validation?: HarnessValidationResult;
};
```

Expected stale save error:

```json
{
  "error": "manifest_conflict",
  "current_manifest_hash": "sha256:...",
  "changed_files": [".ai/harness.yaml"]
}
```

## Target Files

- Create: `web/src/pages/Harness.tsx`
- Create: `web/src/components/HarnessAssetEditor.tsx`
- Create: `web/src/components/HarnessConflictDialog.tsx`
- Create: `web/src/components/HarnessReportPanel.tsx`
- Create: `web/src/components/HarnessTaskBoard.tsx`
- Create: `web/src/lib/harnessSchema.ts`
- Create: `web/src/test/HarnessPage.test.tsx`
- Create: `web/src/test/HarnessReportPanel.test.tsx`
- Create: `web/scripts/playwright-harness-ui-smoke.mjs`
- Create: `tests/test_harness_ui_contract.py`
- Modify: `web/src/App.tsx`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/pages/RunDetail.tsx`
- Modify: `web/src/components/ArtifactViewer.tsx`
- Modify: `web/src/components/ArtifactContent.tsx`
- Modify: `web/src/styles.css`

## Traceability Matrix

| Requirement ID | Sub-Iteration | Design Source | Implementation Files | Tests | Verification Command | Status | Evidence |
|---|---|---|---|---|---|---|---|
| H-UI-001 | UI | Sub-Iteration 4 | `web/src/pages/Harness.tsx`; `web/src/components/HarnessAssetEditor.tsx`; `web/src/lib/api.ts`; `web/src/lib/types.ts`; `web/src/lib/harnessSchema.ts` | `web/src/test/HarnessPage.test.tsx`; `tests/test_harness_ui_contract.py`; `web/scripts/playwright-harness-ui-smoke.mjs` | `cd web && npm run test`; `.venv/bin/python -m pytest tests/test_harness*.py tests/test_routes.py -q`; `cd web && node scripts/playwright-harness-ui-smoke.mjs` | verified | UI 只使用 `/api/projects/{project_id}/harness`、`/harness/validate`、`/harness/checks/run`、`/task-board`、`/task-board/events`；contract test 证明 `workdir` Harness/Task Board 调用返回 400；browser smoke 在 mock route 中断言 save/validate body 不含 `workdir`。 |
| H-UI-002 | UI | Sub-Iteration 4 | `web/src/pages/Harness.tsx`; `web/src/components/HarnessConflictDialog.tsx`; `web/src/lib/api.ts`; `web/src/lib/types.ts` | `web/src/test/HarnessPage.test.tsx`; `tests/test_harness_ui_contract.py`; `web/scripts/playwright-harness-ui-smoke.mjs` | `cd web && npm run test`; `.venv/bin/python -m pytest tests/test_harness*.py tests/test_routes.py -q`; `cd web && node scripts/playwright-harness-ui-smoke.mjs` | verified | 保存先调用 validate；PUT body 携带 `manifest_hash`；缺失 `manifest_hash` 的后端 contract test 返回 400；stale hash 返回 409 并展示 `Manifest 冲突`，不自动重试、不覆盖文件。 |
| H-UI-003 | UI | Sub-Iteration 4 | `web/src/components/HarnessAssetEditor.tsx`; `web/src/components/HarnessReportPanel.tsx`; `web/src/components/MarkdownViewer.tsx`; `web/src/pages/Harness.tsx` | `web/src/test/HarnessPage.test.tsx`; `web/src/test/HarnessReportPanel.test.tsx`; `web/src/test/MarkdownViewer.test.tsx` | `cd web && npm run test`; `cd web && node scripts/playwright-harness-ui-smoke.mjs` | verified | Rules preview 和 Harness report evidence 均通过 `MarkdownViewer` 渲染；测试覆盖 `<script>` 与 `onerror` 被移除；browser smoke 展示 sanitized report evidence。 |
| H-UI-004 | UI | Sub-Iteration 4 | `web/src/pages/Harness.tsx`; `web/src/components/HarnessAssetEditor.tsx`; `web/src/components/HarnessTaskBoard.tsx`; `web/src/lib/types.ts` | `web/src/test/HarnessPage.test.tsx`; `web/scripts/playwright-harness-ui-smoke.mjs` | `cd web && npm run test`; `cd web && node scripts/playwright-harness-ui-smoke.mjs` | verified | `permissions.can_edit=false` 时 Save / Add / textarea 编辑入口不渲染；`permissions.can_run_checks=false` 时 Run Checks 不渲染但编辑仍可用；`permissions.can_view=false` 时不渲染 Harness 内容并显示无权限状态。 |
| H-REPORT-002 | UI | Harness Report Contract | `web/src/pages/RunDetail.tsx`; `web/src/components/HarnessReportPanel.tsx`; `web/src/lib/api.ts`; `web/src/lib/types.ts`; `web/src/lib/harnessSchema.ts`; `web/src/components/ArtifactViewer.tsx`; `web/src/components/ArtifactContent.tsx`; `web/src/components/PipelineTimeline.tsx` | `web/src/test/HarnessReportPanel.test.tsx`; `web/scripts/playwright-harness-ui-smoke.mjs` | `cd web && npm run test`; `cd web && node scripts/playwright-harness-ui-smoke.mjs`; `cd web && npm run build` | verified | RunDetail 使用 `project_id` 查询 run 和 `harness-report.json` artifact；展示 blocking failure、warnings、baseline changes、rule violations 和 evidence refs；不改变 pipeline status 语义。 |
| H-DOD-001 | All | Definition Of Done | `docs/superpowers/plans/2026-05-09-harness-ui.md`; `docs/superpowers/reports/2026-05-10-harness-ui-final-report.md` | `tests/test_harness_ui_contract.py`; `web/src/test/HarnessPage.test.tsx`; `web/src/test/HarnessReportPanel.test.tsx`; Playwright smoke script | `rg -n "H-[A-Z]+-[0-9]{3}" docs/superpowers/plans/2026-05-09-harness-ui.md` | verified | UI implementation plan 已回填 in-scope traceability rows；UI final report 已复制并填实对应 rows。 |
| H-DOD-002 | All | Definition Of Done | UI final report; command logs from implementation session | Same as all rows above | `.venv/bin/python -m unittest discover -s tests -v`; `.venv/bin/python -m pytest tests/test_harness*.py tests/test_routes.py -q`; `cd web && npm run test`; `cd web && npm run build`; `cd web && node scripts/playwright-harness-ui-smoke.mjs`; `git diff --check` | verified | Fresh verification 全部通过；剩余警告为既有/环境警告，不阻断 UI 子迭代。 |

## Upstream Dependency Rows

These rows are not implemented in this UI iteration, but UI work depends on their final reports:

- `H-SCHEMA-001`: UI calls `/harness/validate` before save; backend remains the source of truth for schema validation and must refuse invalid writes.
- `H-MANIFEST-001` and `H-MANIFEST-002`: UI carries and displays manifest conflicts; backend must compute manifest hashes and reject stale writes.
- `H-PERM-001`: backend enforces project permission. Current GET has no separate edit permission field, so UI hides all content/actions on 403 and additionally honors optional future/mock `permissions.can_edit=false` by removing edit entry points.
- `H-PATH-001` and `H-PATH-002`: UI does not expose arbitrary path editing; backend must still enforce path safety.
- `H-REPORT-001` and `H-REPORT-003`: UI displays report data; Checks iteration must own report schema generation and pipeline blocking semantics.

## Implementation Tasks

### Task 1: Preflight Contract Verification

**Objective:** Prove the UI iteration is starting from accepted Core/Checks/Task Board outputs.

**Files:**
- Read: Core final report
- Read: Checks final report
- Read: Task Board final report
- Create: `tests/test_harness_ui_contract.py`

Steps:

- Re-run `git status --short --branch`.
- Read the three final reports and extract the exact API route names, response fields, permission semantics, conflict payload, and report artifact location.
- Add contract tests that call the existing Harness and Task Board APIs with `project_id`, not `workdir`.
- Contract tests must cover: no public Harness API accepts `workdir`; harness read includes `manifest_hash`; save body requires `manifest_hash`; stale save returns `409`; validation failure does not write. 权限入口隐藏通过前端 mock/future optional `permissions.can_edit=false` 覆盖，后端权限语义仍由 Core 403 enforcement 负责。
- Run `.venv/bin/python -m pytest tests/test_harness_ui_contract.py -q`.
- Stop if these tests cannot be written against already-landed upstream APIs without implementing Core/Checks/Task Board logic.

### Task 2: Harness API Client And Types

**Objective:** Add typed frontend accessors for Harness and project-aware run/report reads.

**Files:**
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/lib/api.ts`
- Create: `web/src/lib/harnessSchema.ts`

Steps:

- Add `HarnessBundle`, `HarnessFile`, `HarnessPermission`, `HarnessValidationResult`, `HarnessSaveRequest`, `HarnessConflictError`, `TaskBoardResponse`, and `HarnessReport` types.
- Add `fetchHarness(projectId)`, `validateHarness(projectId, draft)`, `saveHarness(projectId, draft, manifestHash)`, `runHarnessChecks(projectId)`, `fetchTaskBoard(projectId)`, and `appendTaskBoardEvent(projectId, event)` helpers.
- Add `projectQuery({ projectId, workdir })` helper so RunDetail can prefer `project_id` while legacy pages remain compatible.
- Add `fetchRunArtifactText(runId, artifactName, { projectId, workdir })` helper and use it for Harness report display.
- Ensure every new Harness helper path starts with `/projects/${projectId}/...`.
- Unit-test by mocking `apiFetch` through page/component tests; do not rely on live backend in Vitest.

### Task 3: Harness Page Shell And Navigation

**Objective:** Add a first-class Harness page without changing Settings semantics.

**Files:**
- Create: `web/src/pages/Harness.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/styles.css`
- Test: `web/src/test/HarnessPage.test.tsx`

Steps:

- Add sidebar route `/harness` with a governance-oriented icon from `lucide-react`.
- Render a project selector at the top of Harness page and persist the selected project id in local storage under a new key such as `ai-team.lastProjectId`.
- Load Harness bundle only after a project is selected.
- Render five stable tab buttons: Rules, Skills, Checks, Baselines, Task Board.
- Show loading, empty, error, and unauthorized states.
- Test that selecting a project calls `GET /api/projects/{project_id}/harness` and renders all five tabs.

### Task 4: Asset Editors And Sanitized Preview

**Objective:** Provide editable Harness asset views while constraining edits to API-provided Harness files.

**Files:**
- Create: `web/src/components/HarnessAssetEditor.tsx`
- Create: `web/src/components/HarnessTaskBoard.tsx`
- Modify: `web/src/pages/Harness.tsx`
- Modify: `web/src/styles.css`
- Test: `web/src/test/HarnessPage.test.tsx`

Steps:

- Group API-provided files by kind into Rules, Skills, Checks, and Baselines tabs.
- For Markdown rule/skill content, render editor plus sanitized preview using `MarkdownViewer`.
- For Checks/Baselines YAML or JSON content, render a focused editor with validation messages from `/harness/validate`.
- For Task Board, read from `/task-board` and render task state, run ids, decision ids, artifact dirs, and event history; show event append controls only when `can_edit=true`.
- Do not render an arbitrary file path input. Adding a new rule/skill/check/baseline must choose a controlled type and generate a path under the allowed Harness directories.
- Test malicious Markdown and assert no script/event handler survives.

### Task 5: Validate And Save Flow

**Objective:** Make save behavior conflict-safe and schema-aware.

**Files:**
- Modify: `web/src/pages/Harness.tsx`
- Create: `web/src/components/HarnessConflictDialog.tsx`
- Modify: `web/src/lib/api.ts`
- Test: `web/src/test/HarnessPage.test.tsx`

Steps:

- Track `manifest_hash` from the last successful read.
- Track dirty drafts separately from the loaded bundle.
- On Save, call `POST /api/projects/{project_id}/harness/validate` first.
- If validation returns errors, display errors and do not call PUT.
- If validation passes, call `PUT /api/projects/{project_id}/harness` with `manifest_hash` and draft files.
- If PUT returns `409 manifest_conflict`, show a conflict dialog containing `current_manifest_hash` and `changed_files`; do not retry automatically.
- Provide a Refresh action that reloads the bundle and resets dirty drafts after user confirmation.
- Test that stale save displays conflict and does not overwrite local state or issue a second save request.

### Task 6: Permission-Aware Editing

**Objective:** Ensure unauthorized users have no edit entry points.

**Files:**
- Modify: `web/src/pages/Harness.tsx`
- Modify: `web/src/components/HarnessAssetEditor.tsx`
- Modify: `web/src/components/HarnessTaskBoard.tsx`
- Test: `web/src/test/HarnessPage.test.tsx`

Steps:

- Treat `permissions.can_edit=false` as read-only mode.
- In read-only mode, do not render Save, Reset, Add, Delete, Rename, or editable textareas.
- Keep sanitized preview and metadata visible when `permissions.can_view=true`.
- If `permissions.can_view=false`, show a no-access state and do not render asset content.
- Test hidden controls with `queryByRole` and DOM assertions, not only disabled state checks.

### Task 7: RunDetail Harness Report Panel

**Objective:** Make Harness verification results visible where users inspect a run.

**Files:**
- Create: `web/src/components/HarnessReportPanel.tsx`
- Modify: `web/src/pages/RunDetail.tsx`
- Modify: `web/src/components/ArtifactViewer.tsx`
- Modify: `web/src/components/ArtifactContent.tsx`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/lib/types.ts`
- Test: `web/src/test/HarnessReportPanel.test.tsx`

Steps:

- Read `project_id` from RunDetail URL query when present and prefer it for `fetchRun`, `fetchRunDiff`, artifact list, and artifact content.
- Detect `harness-report.json` in `run.artifacts`; fetch and parse it through `fetchRunArtifactText`.
- Render summary status, blocking flag, blocking failures, warnings, baseline results, rule violations, and evidence refs.
- Warning checks must be visually distinct from blocking failures and must not make the RunDetail status look failed by themselves.
- Render any Markdown evidence through `MarkdownViewer`.
- Keep the generic artifact viewer available for raw report JSON.
- Test pass/warning/fail report examples and malicious evidence markdown.

### Task 8: Browser Verification

**Objective:** Prove the major UI pages work in a real browser, not only unit tests.

**Files:**
- Create: `web/scripts/playwright-harness-ui-smoke.mjs`
- Optional modify: `web/package.json` to add `smoke:harness-ui`

Steps:

- Start Vite on a strict local port.
- Use Playwright route mocks for `/api/auth/status`, `/api/projects`, Harness APIs, Task Board APIs, RunDetail APIs, and artifact APIs.
- Navigate to `/harness`, select a project, verify all five tabs render.
- Edit a rule, click Save, verify validate then save include `manifest_hash`.
- Re-run save with mocked `409 manifest_conflict`, verify conflict dialog renders and no overwrite request follows.
- Reload with `can_edit=false`, verify edit controls are absent.
- Navigate to `/runs/run-harness-ui?project_id=proj-1`, verify Harness report panel shows warnings, blocking failure, baseline change, and evidence.
- Save screenshots under `docs/validation/` only if implementation changes visual layout materially; otherwise smoke output is enough.

## Verification Commands

Focused commands:

```bash
.venv/bin/python -m pytest tests/test_harness_ui_contract.py -q
cd web && npm run test -- HarnessPage.test.tsx HarnessReportPanel.test.tsx MarkdownViewer.test.tsx
cd web && node scripts/playwright-harness-ui-smoke.mjs
```

Full required commands before final report:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pytest tests/test_harness*.py tests/test_routes.py -q
cd web && npm run test
cd web && npm run build
cd web && node scripts/playwright-harness-ui-smoke.mjs
git diff --check
```

## Stop Conditions

Stop and ask the user before implementation if:

- Any upstream Harness API requires `workdir`.
- Harness read response does not include `manifest_hash`.
- Save API accepts missing `manifest_hash`.
- Stale save does not return `409 manifest_conflict`.
- Harness GET 403 cannot be surfaced as a no-access/read-only state without showing edit controls.
- UI would need to edit files outside `.ai/harness.yaml` or `.ai/harness/**`.
- RunDetail cannot retrieve `harness-report.json` through `project_id`.
- Browser smoke cannot be made meaningful without adding backend behavior outside UI scope.

## Plan Self-Check

- Scope is limited to UI iteration; Core, Checks, and Task Board logic remain upstream dependencies.
- In-scope traceability rows have concrete Implementation Files, Tests, Verification Command, Status, and Evidence expectations.
- The plan includes a browser verification command for major Harness UI pages and RunDetail report display.
- The plan preserves the hard constraints: `project_id` APIs only, save carries `manifest_hash`, stale save is conflict-visible, no arbitrary repo file editing, permission-aware editing, sanitized Markdown, and RunDetail report display.
