# Project Governance Phase 4 Final Report

## 结论

`complete_with_warnings`

Phase 4 Task Board 与 UI 治理闭环已完成验收收口。当前 Task Board / Harness UI 不是本阶段从零实现；它们在仓库中已有实现、测试和历史 final report。本阶段新增 Phase 4 计划与本报告，并通过 fresh verification 复核现有实现仍满足治理口径。

结论不是 plain `complete`，因为验证仍有非阻塞 warning：后端 Harness GET 当前没有细粒度 `permissions` 字段，UI 只能处理 403 和 optional permissions；前端 build 有既有 chunk-size warning；browser smoke 期间 Vite 打出后端代理不可达日志但脚本退出码为 0；后端全量测试仍有 PyJWT key length 与 RQ deprecation warning。

## 当前状态盘点结论

### 既有实现

- Task Board 状态模型、聚合记录、append-only event、snapshot rebuild、related task matching 已在 `engine/task_board.py` 落地。
- Context scan related tasks 注入已在 `engine/context_scanner.py` 落地。
- Related task adopted/rejected reason 校验已在 `engine/artifact_contracts.py` 和 `engine/schemas/requirement-final.json`、`engine/schemas/task-plan.json` 落地。
- Project-scoped Harness / Task Board API 已在 `api/routes/harness.py` 落地，并拒绝 Harness/Task Board public API 中的 `workdir`。
- UI 五个 tab、validate-before-save、manifest conflict、Task Board read、Run Checks、optional permissions、RunDetail Harness report panel 已在 `web/src/pages/Harness.tsx`、`web/src/components/Harness*.tsx`、`web/src/pages/RunDetail.tsx`、`web/src/lib/api.ts` 落地。
- 历史报告 `docs/superpowers/reports/2026-05-09-harness-task-board-final-report.md` 和 `docs/superpowers/reports/2026-05-10-harness-ui-final-report.md` 存在，但本阶段没有只引用旧报告，而是重新跑了验证。

### 本阶段修正

- 新增 Phase 4 收口计划：`docs/superpowers/plans/2026-05-10-project-governance-phase-4-task-board-ui.md`。
- 新增 Phase 4 final report：本文件。
- 调整计划文件中的废弃入口表述，避免报告/计划自身制造旧路径精确扫描噪音。
- 未修改 Task Board / UI 运行时代码；fresh verification 未发现必须改代码的缺口。

## 修改文件清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `docs/superpowers/plans/2026-05-10-project-governance-phase-4-task-board-ui.md` | 新增 | Phase 4 计划、现状盘点、Task Board/UI 验收矩阵、测试计划、风险与停止条件 |
| `docs/superpowers/reports/2026-05-10-project-governance-phase-4-final-report.md` | 新增 | Phase 4 验收结果、证据、验证命令、残余风险 |

## Task Board 验收表

| 验收项 | 结果 | 证据 |
| --- | --- | --- |
| 只有最终 `acceptance_confirm + approved` 能写入 `accepted` | PASS | `engine/task_board.py::_validate_transition`；`engine/orchestrator.py::_has_approved_acceptance`；focused suite 25 passed |
| QA failed、review changes requested、acceptance rejected、cancelled 不污染 accepted | PASS | `engine/task_board.py::_apply_event` 对已 accepted 记录不被负向事件覆盖；`tests/test_task_board.py` |
| `.ai/harness/tasks/*.json` 为聚合记录 | PASS | `TASKS_DIR` 和 `record_task_event`；`tests/test_task_board.py` |
| `.ai/harness/task-events/*.json` 为 append-only evidence | PASS | `append_event` 使用 `O_EXCL`；`tests/test_task_board.py` |
| `.ai/harness/task-board.json` 仅为 snapshot | PASS | `build_snapshot(write=False/True)` 可从 task records 重建 |
| task/event 包含 `run_id`、`artifact_dir`、`decision_ids` | PASS | `TaskEvent` 字段约束；focused suite 25 passed |
| `context_scan` 注入 related tasks 到 Markdown 和 JSON | PASS | `tests/test_context_scanner.py::TestContextScannerTaskBoard` |
| related tasks 存在时 requirement/planning artifact 必须说明 adopted/rejected 原因 | PASS | `tests/test_artifact_contracts.py::TestRelatedTaskArtifactReasons` |
| Task Board API 使用 `project_id` 并拒绝 `workdir` | PASS | `tests/test_harness_routes.py::TestTaskBoardProjectApi` |
| public event API 拒绝直接写 accepted | PASS | `api/routes/harness.py::post_task_board_event`；route tests |

## UI 验收表

| 验收项 | 结果 | 证据 |
| --- | --- | --- |
| `/harness` 覆盖 Rules / Skills / Checks / Baselines / Task Board | PASS | `web/src/pages/Harness.tsx`；Vitest；Playwright smoke |
| UI 只调用 `project_id` Harness/Task Board API | PASS | `web/src/lib/api.ts`；`tests/test_harness_ui_contract.py`；Playwright route assertions |
| 保存前先 validate | PASS | `Harness.tsx::handleSave`；`web/src/test/HarnessPage.test.tsx` |
| PUT 保存携带 `manifest_hash` | PASS | `saveHarness`；contract tests；Playwright smoke |
| stale manifest 显示冲突且不自动覆盖 | PASS | `HarnessConflictDialog`；Vitest；Playwright smoke |
| UI 只能编辑 Harness assets | PASS | `web/src/lib/harnessSchema.ts`；无任意路径输入；browser smoke 覆盖保存路径 |
| Markdown / report evidence 渲染 sanitize | PASS | `MarkdownViewer` 被 Harness editor/report panel 复用；Vitest |
| permission-aware editing | PASS_WITH_WARNING | UI 覆盖 403 和 optional `permissions`；后端尚无细粒度 permissions 字段 |
| RunDetail 展示 `harness-report.json` 的 blocking、warnings、baseline changes、rule violations、evidence refs | PASS | `HarnessReportPanel`；Vitest；Playwright smoke |
| UI 不改变 pipeline status 语义，不绕过 Phase 3 checks | PASS | RunDetail 只读 report；Run Checks 调 `/harness/checks/run`；backend checks suite 69 passed |

## 红灯和绿灯证据

### 绿灯

- Focused Task Board suite：25 passed。
- Harness UI/core/checks suite：69 passed。
- Full backend regression：949 passed, 2 skipped。
- Frontend unit tests：9 files passed, 29 tests passed。
- Frontend build：exit 0。
- Browser smoke：exit 0，覆盖 `/harness` tabs、保存、manifest conflict、read-only、RunDetail Harness report。
- `git diff --check`：通过。
- 废弃入口扫描：无命中。

### 红灯 / Warning

- 后端 Harness GET 没有细粒度 `permissions` 字段；UI 当前只能通过 403 和 optional `permissions` mock/future contract 隐藏编辑入口。
- `npm run build` 有 Vite chunk-size warning。
- Playwright smoke 期间 Vite 打出一次代理到 `127.0.0.1:8000` 的连接失败日志；脚本验证路径使用 mock route，退出码为 0。
- 后端全量测试有 PyJWT key length 与 RQ `on_failure` deprecation warning。

## 验证命令与结果

| 命令 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest tests/test_task_board.py tests/test_context_scanner.py::TestContextScannerTaskBoard tests/test_artifact_contracts.py::TestRelatedTaskArtifactReasons tests/test_harness_routes.py::TestTaskBoardProjectApi tests/test_engine.py::TestHarnessTaskBoardLifecycle tests/test_routes.py::TestCancelRetryRoutes -q` | 25 passed in 0.86s |
| `.venv/bin/python -m pytest tests/test_harness_ui_contract.py tests/test_harness_routes.py tests/test_harness_checks.py tests/test_harness_core.py -q` | 69 passed in 2.99s |
| `.venv/bin/python -m pytest -q` | 949 passed, 2 skipped, 11 warnings in 17.84s |
| `cd web && npm run test` | 9 files passed, 29 tests passed |
| `cd web && npm run build` | built successfully; chunk-size warning |
| `cd web && node scripts/playwright-harness-ui-smoke.mjs` | exit 0; Vite proxy warning logged |
| `git diff --check` | passed |
| 废弃入口残留扫描（用户指定 find/xargs/rg 组合，旧入口 pattern） | no matches; rg exit 1 |

## 残余 Warning / Risk

- 细粒度 UI permission 当前是前端兼容能力，不是后端强契约；如果后续要区分 view/edit/run checks 权限，需要先设计权限来源和 claims/role 映射，不能在 UI 私自推断。
- `.ai/harness/task-events/` 当前没有实际事件文件；这是无事件状态。已有测试证明 append 时会创建 event evidence。
- Browser smoke 当前使用 route mock 验证 UI 行为，不依赖真实后端服务；真实端到端环境仍应在部署链路单独覆盖。

## 明确说明

- 没有恢复历史项目级 team 配置文件，也没有把 `.ai/` 下名为 `team.yaml` 的废弃入口作为事实源、示例或入口。
- 没有新增 DB 配置事实源；DB 仍只用于项目解析、运行期状态、结果、审计或缓存。
- 没有新增 public `workdir` Harness / Task Board API；现有 project-scoped API 会拒绝 `workdir` 输入。
- 没有新增第二套 command runner；Harness command checks 继续复用 `QualityGateRunner`。
- UI 不是任意仓库文件编辑器，只编辑 `.ai/harness.yaml` 和 `.ai/harness/**` 范围内的 Harness assets。
