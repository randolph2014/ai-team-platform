# Project Governance Phase 3 Plan: Executable Checks

计划日期：2026-05-10

## 目标与非目标

目标：

- 将 Phase 1 的 Harness checks skeleton 推进为仓库内可执行的 Phase 3 command check。
- 继续以 `.ai/harness.yaml` 和 `.ai/harness/**` 作为 Harness 配置事实源。
- command check 必须复用现有 `QualityGateRunner` / `run_quality_gates()` 执行路径，并继承 cwd、timeout、输出截断和环境变量 allowlist 约束。
- Harness report / check result 必须保持结构化字段：`id`、`status`、`blocking`、`duration_ms`、`exit_code`、`evidence_refs`。
- blocking check 失败必须阻断 `harness_verify` stage，或在 report 的 `blocking` / `next_stage_contract.blocked` 中明确表达。
- baseline 继续保持 raise-only，降低 baseline 不允许静默通过。
- 清理 Phase 1 skeleton-only 文案，避免后续把已废弃阶段边界当作当前事实。

非目标：

- 不实现 Phase 4 Task Board 与 UI。
- 不新增数据库表，不把 DB 变成 Harness 配置事实源。
- 不新增第二套 command runner。
- 不调整默认 agent/pipeline 模板之外的无关结构。
- 不恢复、引用或示例化废弃的历史项目级 team 配置入口。

## 影响范围

计划内文件：

- `.ai/harness.yaml`
- `.ai/harness/checks/README.md`
- `.ai/harness/checks/checks-contract.md`
- 可新增 `.ai/harness/checks/executable-command-checks.md`
- `tests/test_harness_core.py`
- `tests/test_harness_checks.py`

只在发现测试缺口必须修复时才触碰：

- `engine/harness.py`
- `engine/harness_checks.py`
- `engine/quality_gates.py`
- `engine/orchestrator.py`

当前盘点证据：

- `engine/harness.py` 的 `HarnessCheckRef` 已支持 `type: command`、`command`、`timeout_seconds`、`cwd`、`blocking` 等字段，并校验 command check 必须有命令和正 timeout。
- `engine/harness_checks.py` 的 `_run_command_checks()` 已把 Harness command check 转成 quality gate，并调用 `run_quality_gates()`。
- `engine/quality_gates.py` 已提供 `QualityGateExecutionPolicy`，用于限制 cwd、强制 timeout、截断输出和环境变量 allowlist。
- `engine/orchestrator.py` 的 `_run_harness_verify_stage()` 已在 `harness_report.blocking` 为真时写出 `harness-feedback.md` 并使 stage 失败。
- `tests/test_harness_checks.py` 已覆盖 command check 复用 quality gate runner、timeout 失败阻断、env allowlist、cwd 安全、report schema、baseline raise-only。
- `tests/test_harness_core.py` 仍保留 Phase 1 skeleton-only 断言，是本阶段需要先改成红灯的仓库资产验收测试。

## 设计原则

1. Repo-file-first：Harness 配置事实源只来自 `.ai/harness.yaml` 和 `.ai/harness/**`。
2. Runner reuse：command check 只声明命令，由 `run_quality_gates()` 执行，不在 Harness Checks 内部调用 subprocess 或 shell API。
3. Blocking explicit：blocking 结果必须同时体现在单项 check、report 汇总和下一阶段契约里。
4. Evidence first：每个 check result 必须有可追溯 evidence refs；最终报告记录红灯、绿灯、命令和扫描结果。
5. Raise-only baseline：baseline 降低是阻断风险；本阶段不做自动修复或静默降级。
6. Phase isolation：只推进可执行 checks，不进入 Task Board/UI/DB 配置事实源。
7. Legacy cleanup：发现精确残留引用到废弃历史项目级 team 配置入口时清理；不把泛化测试样例误判为配置事实源。

## 具体文件边界

| 文件 | 动作 | 边界 |
|---|---|---|
| `.ai/harness.yaml` | 将 skeleton-only check 改为 Phase 3 command check | 命令使用现有测试命令，声明 `timeout_seconds`、`severity`、`blocking`、`file` |
| `.ai/harness/checks/README.md` | 更新为 Phase 3 可执行 checks 当前契约 | 删除 Phase 1 skeleton-only 当前边界文案 |
| `.ai/harness/checks/checks-contract.md` | 从 future contract 更新为 active contract | 明确 QualityGateRunner reuse 和 report 字段 |
| `.ai/harness/checks/executable-command-checks.md` | 记录首个可执行 command check 的目的和边界 | 只描述当前 check，不扩展到 UI/DB |
| `tests/test_harness_core.py` | 先把仓库资产测试改成要求可执行 command check | 保留 AGENTS / source-of-truth / forbidden capabilities 验收 |
| `tests/test_harness_checks.py` | 补仓库 command check 可执行 report 验收 | 不引入第二套 runner |

## 验收矩阵

| ID | 验收点 | 验证方式 |
|---|---|---|
| P3-001 | `.ai/harness.yaml` 声明至少一个可执行 command check | `tests/test_harness_core.py` 仓库资产测试 |
| P3-002 | command check 复用 QualityGateRunner | `tests/test_harness_checks.py::TestHarnessCommandChecks::test_command_checks_reuse_quality_gate_runner` |
| P3-003 | check result 包含结构化字段 | 新增或现有 `tests/test_harness_checks.py` report contract 测试 |
| P3-004 | blocking command check 失败会阻断 | `tests/test_harness_checks.py` 和 `tests/test_harness_orchestrator.py` |
| P3-005 | checks 不能绕过 AGENTS / human gate / quality gate / platform safety | `.ai/harness/skills/**` forbidden capabilities + README/contract + core 测试 |
| P3-006 | baseline raise-only 不退化 | `tests/test_harness_checks.py::TestHarnessBaselineChecks::test_baseline_lowering_blocks_without_approval` |
| P3-007 | 废弃历史项目级 team 配置不作为入口或事实源出现 | 用户指定残留扫描 |
| P3-008 | 不推进 Phase 4 / UI / DB | diff 文件清单和最终报告 |

## 测试计划

红灯：

- 先修改仓库资产测试，要求 `.ai/harness.yaml` 有 `type: command` 的 blocking check，并确认当前 skeleton-only 配置失败。

绿灯：

- 更新 `.ai/harness.yaml` 和 `.ai/harness/checks/**` 后，运行新增/修改的单测。

最终验证：

- `.venv/bin/python -m pytest tests/test_harness_core.py tests/test_harness_checks.py tests/test_quality_gates.py -q`
- 如改到 `engine/orchestrator.py`，运行 `.venv/bin/python -m pytest tests/test_engine.py -q`
- `git diff --check`
- 用户指定的废弃入口残留扫描。

## 风险与停止条件

风险：

- 当前工作区已有多处未提交改动，必须避免把 Phase 1/2 或其他任务的改动误归因到本阶段。
- 仓库级 command check 如果过重，会让默认 `harness_verify` 阶段耗时上升；本阶段选用最小相关测试命令。
- 若现有 `run_quality_gates()` 无法满足 command check 的安全边界，必须修复共享质量门禁路径，而不是新增 runner。

停止条件：

- 需要 DB 结构变更、Task Board UI 或公共 API 设计决策时停止。
- 发现 command check 无法复用 `QualityGateRunner` 时停止，先让用户决策是否调整共享 runner。
- 发现废弃历史项目级 team 配置仍作为默认加载入口存在且清理会跨越本阶段边界时停止。
- 残留扫描出现精确入口引用且不确定是否测试 fixture 时停止确认。
