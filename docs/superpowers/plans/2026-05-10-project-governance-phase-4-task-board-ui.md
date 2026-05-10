# Project Governance Phase 4 Task Board UI Implementation Plan

> **For implementation:** this phase is not a greenfield rewrite. Treat existing Task Board and Harness UI implementation/report traces as upstream evidence, then close gaps with the smallest tested change set.

**Goal:** 验收并收口 Project Governance Phase 4：Task Board accepted memory、related tasks context scan、Harness/Task Board UI 管理面进入项目治理闭环。

**Architecture:** 继续以仓库内 `.ai/harness.yaml` 和 `.ai/harness/**` 作为 Harness 配置事实源；Task Board 以 `.ai/harness/tasks/*.json` 聚合记录和 `.ai/harness/task-events/*.json` append-only evidence 为权威，`.ai/harness/task-board.json` 只做可重建 snapshot。UI 只通过 `project_id` 访问 Harness/Task Board API，保存前调用后端 validate，保存时携带 `manifest_hash`，RunDetail 只读展示 `harness-report.json`。

---

## 当前状态盘点

### 已实现

- Phase 1-3 报告存在：`docs/superpowers/reports/2026-05-10-project-governance-phase-1-final-report.md`、`phase-2-final-report.md`、`phase-3-final-report.md`。
- `.ai/harness.yaml` 已声明 rules、skills、command checks、baselines；`.ai/harness/**` 已有 rules/skills/checks/baselines/tasks 文档资产。
- `engine/task_board.py` 已实现 `TaskEvent` / `TaskRecord`、accepted guard、append-only event 写入、task 聚合记录、snapshot rebuild、related tasks match、run report 到 task event 的映射。
- `engine/context_scanner.py` 已把 related tasks 注入 `codebase-context.md` 的 `## Harness Related Tasks`，并写入 `codebase-context.json.harness.related_tasks`。
- `engine/artifact_contracts.py` 已在 context 存在 related tasks 时要求 `requirement-final.json` 和 `task-plan.json` 写 `related_task_decisions`。
- `api/routes/harness.py` 已提供 `GET /api/projects/{project_id}/task-board` 和 `POST /api/projects/{project_id}/task-board/events`，并拒绝 Harness/Task Board API 中的 `workdir`。
- `web/src/pages/Harness.tsx` 和 `web/src/components/Harness*.tsx` 已覆盖 Rules / Skills / Checks / Baselines / Task Board、manifest hash 保存、conflict dialog、optional permissions、Markdown preview 和 Task Board 读取。
- `web/src/pages/RunDetail.tsx` 已支持通过 `project_id` 读取 `harness-report.json` 并使用 `HarnessReportPanel` 展示 blocking、warnings、baseline changes、rule violations、evidence refs。
- 后端和前端测试文件已经存在：`tests/test_task_board.py`、`tests/test_context_scanner.py`、`tests/test_artifact_contracts.py`、`tests/test_harness_routes.py`、`tests/test_harness_ui_contract.py`、`web/src/test/HarnessPage.test.tsx`、`web/src/test/HarnessReportPanel.test.tsx`、`web/scripts/playwright-harness-ui-smoke.mjs`。

### 过期

- 旧的项目级 team 配置文件不能恢复、不能引用为 Harness 事实源、不能作为示例入口；本阶段只允许精确残留扫描并清理命中项。该废弃文件位于 `.ai/` 目录下，文件名为 `team.yaml`。
- 旧计划里“UI/Core/Task Board final report 不存在”的阻断条件已过期；当前仓库已经存在 Task Board/UI final report，本阶段需要用当前代码和 fresh verification 重验，而不是复述旧阻断。

### 缺口

- `.ai/harness/task-events/` 当前不存在实际事件文件；这是未发生事件时的正常状态，验收要证明 append 时会创建 append-only event。
- Harness GET 当前没有后端细粒度 `permissions` 字段；现有 UI 兼容可选 `permissions` 并处理 403。若 fresh verification 表明必须由后端返回编辑/运行权限，本阶段需停止让用户确认权限模型，不私自扩展安全语义。
- 工作区已有多批未提交改动，Phase 4 报告必须区分既有实现、既有未提交改动和本阶段新增文件/修正。

### 冲突

- 目前未发现必须从零重写 Task Board 或 UI 的冲突。
- 若验证发现任一公共 Harness/Task Board API 仍接受 `workdir`，或 UI 新增任意路径编辑入口，必须按缺陷修正。
- 若验证发现 command checks 不是复用 `QualityGateRunner`，必须停止并回到 Phase 3 边界确认，不新增第二套 runner。

## 目标与非目标

### 目标

- 用当前代码证据和 fresh verification 证明 Task Board 与 UI 满足 Phase 4 最低验收要求。
- 对缺失契约先补失败测试，再做最小实现修正。
- 产出 Phase 4 final report，明确验收矩阵、红绿灯证据、验证命令和残余风险。

### 非目标

- 不恢复旧的项目级 team 配置文件，不把它作为示例、入口或事实源。
- 不引入 DB-backed Harness 配置事实源；DB 只能用于项目解析、运行期状态、结果、审计或缓存。
- 不新增 public `workdir` Harness / Task Board API。
- 不新增第二套 command runner；Phase 3 command checks 继续复用 `QualityGateRunner`。
- 不把 UI 做成任意仓库文件编辑器。
- 不修改 DB migration / schema、不做无关业务模块改动、不做大规模格式化。

## 文件边界

### 优先允许

- `docs/superpowers/plans/2026-05-10-project-governance-phase-4-task-board-ui.md`
- `docs/superpowers/reports/2026-05-10-project-governance-phase-4-final-report.md`
- `engine/task_board.py`
- `engine/context_scanner.py`
- `engine/orchestrator.py`
- `engine/artifact_contracts.py`
- `engine/schemas/requirement-final.json`
- `engine/schemas/task-plan.json`
- `api/routes/harness.py`
- `api/routes/runs.py`
- `web/src/pages/Harness.tsx`
- `web/src/components/Harness*.tsx`
- `web/src/lib/api.ts`
- `web/src/lib/types.ts`
- `web/src/lib/harnessSchema.ts`
- `web/src/pages/RunDetail.tsx`
- `tests/test_task_board.py`
- `tests/test_context_scanner.py`
- `tests/test_artifact_contracts.py`
- `tests/test_harness_routes.py`
- `tests/test_harness_ui_contract.py`
- `web/src/test/HarnessPage.test.tsx`
- `web/src/test/HarnessReportPanel.test.tsx`
- `web/scripts/playwright-harness-ui-smoke.mjs`

### 禁止

- DB migration / schema
- 第二套 command runner
- 恢复旧的项目级 team 配置文件
- 无关业务模块
- 无关大规模格式化

## Task Board 验收矩阵

| 要求 | 当前证据 | 验收方式 |
| --- | --- | --- |
| 只有最终 `acceptance_confirm + approved` 能写入 `accepted` | `engine/task_board.py::_validate_transition`；`engine/orchestrator.py::_has_approved_acceptance` | `tests/test_task_board.py`、`tests/test_engine.py::TestHarnessTaskBoardLifecycle` |
| QA failed / review changes requested / acceptance rejected / cancelled 不污染 accepted | `_apply_event` 对非 accepted 不覆盖已 accepted；cancel route 写 cancelled event | `tests/test_task_board.py`、`tests/test_routes.py::TestCancelRetryRoutes` |
| `.ai/harness/tasks/*.json` 是聚合记录 | `TASKS_DIR = ".ai/harness/tasks"`；`record_task_event` 写 task json | `tests/test_task_board.py` |
| `.ai/harness/task-events/*.json` 是 append-only evidence | `append_event` 使用 `O_EXCL` 创建事件文件 | `tests/test_task_board.py` |
| `.ai/harness/task-board.json` 只做 snapshot | `build_snapshot(write=False/True)` 可从 tasks 重建 | `tests/test_task_board.py` |
| task/event 包含 `run_id`、`artifact_dir`、`decision_ids` | `TaskEvent` Pydantic 字段 min length；`TaskRecord` 保存 traceability | `tests/test_task_board.py` |
| context scan 注入 related tasks | `ContextScanner.scan` 和 `scan_to_json` 调 `related_tasks_for_context` | `tests/test_context_scanner.py::TestContextScannerTaskBoard` |
| related task decisions 强制 adopted/rejected reason | `validate_related_task_decisions` | `tests/test_artifact_contracts.py::TestRelatedTaskArtifactReasons` |
| Task Board API 使用 `project_id` 并拒绝 `workdir` | `api/routes/harness.py::_reject_workdir` | `tests/test_harness_routes.py::TestTaskBoardProjectApi` |
| public API 拒绝直接写 accepted | `post_task_board_event` 对 `event.state == "accepted"` 返回 400 | `tests/test_harness_routes.py::TestTaskBoardProjectApi` |

## UI 验收矩阵

| 要求 | 当前证据 | 验收方式 |
| --- | --- | --- |
| `/harness` 覆盖 Rules / Skills / Checks / Baselines / Task Board | `web/src/pages/Harness.tsx` 的 `TABS` | `web/src/test/HarnessPage.test.tsx`、Playwright smoke |
| UI 只调用 `project_id` Harness/Task Board API | `web/src/lib/api.ts` Harness helpers 使用 `/projects/{projectId}` | `tests/test_harness_ui_contract.py`、Playwright route assertions |
| 保存前先 validate | `Harness.tsx::handleSave` 先 `validateHarness` 后 `saveHarness` | `web/src/test/HarnessPage.test.tsx` |
| PUT 携带 `manifest_hash` | `saveHarness(projectId, files, manifestHash)` | `tests/test_harness_ui_contract.py`、frontend tests |
| stale manifest 显示冲突不覆盖 | `HarnessConflictDialog`；409 处理为 `manifest_conflict` | frontend tests、Playwright smoke |
| UI 只能编辑 Harness assets | `isEditableHarnessPath`、`normalizeHarnessFiles`、无任意路径输入 | frontend tests、code scan |
| Markdown/report evidence sanitize | `HarnessAssetEditor` 和 `HarnessReportPanel` 复用 `MarkdownViewer` | `web/src/test/HarnessPage.test.tsx`、`HarnessReportPanel.test.tsx` |
| permission-aware editing | UI 处理 403 与 optional `permissions` 字段 | frontend tests；若需后端细粒度权限则停止确认 |
| RunDetail 展示 Harness report 关键字段 | `RunDetail.tsx` + `HarnessReportPanel.tsx` | `HarnessReportPanel.test.tsx`、Playwright smoke |
| UI 不改变 pipeline status，不绕过 Phase 3 checks | UI 只读 report；Run Checks 调后端 `/harness/checks/run` | frontend tests、后端 checks tests |

## 测试计划

1. 先运行用户指定 focused Task Board suite。
2. 运行 Harness UI/core/checks focused suite。
3. 运行完整后端 pytest。
4. 运行前端 unit tests 和 production build。
5. 运行真实浏览器 Playwright smoke，确认页面非空、tab 可切换、validate/save 顺序、manifest conflict 可见、Task Board 可读、RunDetail report 可见。
6. 运行 `git diff --check`。
7. 运行废弃入口残留扫描，确保没有恢复或引用项目级旧 team 配置入口。

## 风险与停止条件

- 如果现有 Task Board event/snapshot 模型需要从“tasks + events + derived snapshot”改成其他并发模型，停止让用户决策。
- 如果需要新增 DB schema 或把 DB 作为 Harness 配置事实源，停止让用户决策。
- 如果需要新增 public `workdir` API 才能满足 UI，停止让用户决策。
- 如果 Phase 3 checks 未复用 `QualityGateRunner`，停止让用户决策。
- 如果权限验收要求后端必须返回细粒度 `can_edit` / `can_run_checks`，而当前授权模型没有对应来源，停止让用户决策。
- 如果验证发现缺口能在允许文件边界内最小修正，则先补失败测试，再实现。

## 明确不做

- 不恢复旧的项目级 team 配置文件。
- 不引入 DB 配置事实源。
- 不新增 public `workdir` API。
- 不新增第二套 command runner。
- UI 不是任意仓库文件编辑器。
