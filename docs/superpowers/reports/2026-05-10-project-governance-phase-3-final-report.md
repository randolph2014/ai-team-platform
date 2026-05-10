# Project Governance Phase 3 Final Report

验收日期：2026-05-10

验收对象：Project Governance Phase 3：可执行质量门禁。范围限定为 Harness executable checks、QualityGateRunner 复用、结构化 Harness report 和阻断语义验证。

## 结论

complete。

本阶段已把 Phase 1 的 checks skeleton 推进为仓库内可执行 command check：`.ai/harness.yaml` 现在声明 blocking command check，执行路径复用 `engine.harness_checks.run_harness_verification()` 到 `engine.quality_gates.run_quality_gates()`。未推进 Phase 4 Task Board/UI，未改数据库结构，未新增第二套 command runner，也未恢复废弃的历史项目级 team 配置入口。

## 修改文件清单

| 文件 | 为什么改 |
|---|---|
| `docs/superpowers/plans/2026-05-10-project-governance-phase-3-executable-checks.md` | Phase 3 实施计划、文件边界、验收矩阵和停止条件 |
| `.ai/harness.yaml` | 将 checks 从 skeleton-only 推进为可执行 blocking command check |
| `.ai/harness/checks/README.md` | 更新 Checks 当前边界：Phase 3 可执行 checks，不含 UI/DB/第二套 runner |
| `.ai/harness/checks/checks-contract.md` | 将 future contract 更新为 active executable check contract |
| `.ai/harness/checks/executable-command-checks.md` | 记录首个可执行 command check 的目的、命令和安全边界 |
| `tests/test_harness_core.py` | 仓库资产测试从 Phase 1 skeleton 断言更新为 Phase 3 command check 断言 |
| `tests/test_harness_checks.py` | 新增仓库 command check 真实执行和结构化 report 验收 |
| `docs/superpowers/reports/2026-05-10-project-governance-phase-3-final-report.md` | 本阶段验收报告 |

本阶段没有编辑 `engine/harness.py`、`engine/harness_checks.py`、`engine/quality_gates.py` 或 `engine/orchestrator.py`；这些文件的既有实现已满足 Phase 3 最小执行链路。

## Phase 3 验收表

| 验收项 | 状态 | 证据 |
|---|---|---|
| `.ai/harness.yaml` 可以声明可执行 command check | PASS | `tests/test_harness_core.py::TestRepositoryHarnessGovernanceAssets::test_phase3_governance_assets_declare_executable_command_check` |
| command check 复用 QualityGateRunner | PASS | `tests/test_harness_checks.py::TestHarnessCommandChecks::test_command_checks_reuse_quality_gate_runner` patch `run_quality_gates` 并确认被调用 |
| check result 结构化字段完整 | PASS | `tests/test_harness_checks.py::TestRepositoryHarnessExecutableChecks::test_repository_command_check_writes_structured_result` 校验 `id/status/blocking/duration_ms/exit_code/evidence_refs` |
| blocking check 失败能阻断 | PASS | `tests/test_harness_checks.py::TestHarnessCommandChecks::test_command_timeout_failure_blocks_pipeline` 和 `tests/test_harness_orchestrator.py` |
| checks 不绕过 AGENTS、human gate、quality gate、platform safety | PASS | `.ai/harness/skills/**` forbidden capabilities、`.ai/harness/checks/**` 契约、core 测试均保留 |
| baseline 保持 raise-only | PASS | `tests/test_harness_checks.py::TestHarnessBaselineChecks::test_baseline_lowering_blocks_without_approval` |
| 废弃历史项目级 team 配置入口没有重新成为默认入口、文档事实源或示例入口 | PASS | 用户指定残留扫描无输出 |
| 没有推进 Phase 4 Task Board/UI，未改 DB | PASS | diff 文件清单无 UI/API/DB migration 变更 |

## 红灯和绿灯证据

红灯 1：

```text
.venv/bin/python -m pytest tests/test_harness_core.py::TestRepositoryHarnessGovernanceAssets::test_phase3_governance_assets_declare_executable_command_check -q
FAILED
AssertionError: 0 not greater than or equal to 1
```

原因：当前仓库 Harness 配置仍是 Phase 1 skeleton-only，没有 command check。

红灯 2：

```text
.venv/bin/python -m pytest tests/test_harness_checks.py::TestRepositoryHarnessExecutableChecks::test_repository_command_check_writes_structured_result -q
FAILED
AssertionError: 0 not greater than or equal to 1
```

原因：`run_harness_verification()` 没有从仓库配置中执行到任何 command check。

绿灯：

```text
.venv/bin/python -m pytest tests/test_harness_core.py::TestRepositoryHarnessGovernanceAssets::test_phase3_governance_assets_declare_executable_command_check -q
1 passed in 0.13s
```

```text
.venv/bin/python -m pytest tests/test_harness_checks.py::TestRepositoryHarnessExecutableChecks::test_repository_command_check_writes_structured_result -q
1 passed in 0.44s
```

## 全部验证命令与结果

```text
.venv/bin/python -m pytest tests/test_harness_core.py tests/test_harness_checks.py tests/test_quality_gates.py -q
68 passed in 2.15s
```

```text
.venv/bin/python -m pytest tests/test_harness_orchestrator.py -q
2 passed in 0.24s
```

```text
.venv/bin/python -m pytest tests/test_engine.py -q
67 passed in 2.60s
```

```text
git diff --check
PASS
```

```text
find . -path './.git' -prune -o -path './web/node_modules' -prune -o -path './.ai/worktrees' -prune -o -path './.ai/team-output' -prune -o -type f -print | xargs rg -n "<legacy-entry-pattern>"
NO MATCH
```

说明：最后一条扫描实际执行的是用户指定的精确正则；stdout 为空，`rg` 按 no-match 语义返回非 0。

## 残余风险

1. 当前仓库 command check 依赖本地 `.venv/bin/python`；这与本阶段验证命令一致，但如果未来在无 `.venv` 的执行环境运行，需要通过平台运行环境规范处理，而不是改成第二套 runner。
2. 本阶段只把 command check 最小闭环落地；跨 artifact 的 traceability 语义一致性仍应由后续更具体的 checks 或 Task Board 需求独立推进。
3. 工作区进入前已有多处未提交改动；本报告只对 Phase 3 修改文件和本阶段验证命令负责。

## Scope Boundary

本阶段没有推进 Phase 4 Task Board 或 UI，没有新增数据库事实源，没有修改 DB schema，没有新增第二套 command runner，也没有恢复废弃的历史项目级 team 配置入口。
