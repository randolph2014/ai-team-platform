# Project Governance Configuration Cleanup Final Report

验收日期：2026-05-10

验收对象：Project Governance Configuration cleanup，范围限定为废弃历史项目级 team 配置入口，不包含 Checks 子迭代完成结论。

## 结论

通过，已单独验收。

本次验收发现 2 个 cleanup 缺口，并已做最小修复：

1. `POST /api/runs/{id}/human-decision` 会恢复运行，但继承 `report.config_path` 后未拒绝历史项目级 team 配置入口。已补同构校验，并增加红灯到绿灯测试。
2. `docs/spec_1.0.md`、`docs/spec_1.1.md`、`docs/superpowers/superpower-analysis.md` 仍有旧措辞会让 `team.yaml` 被误解为项目配置事实源。已改为平台模板、DB Settings、物化 pipeline config 或 Harness governance assets。

## Git Status

已按要求第一步执行：

```text
git status --short --branch
## main...origin/main [ahead 1]
```

工作区存在 Checks 相关变更和本 cleanup 相关变更。本报告只对本 cleanup 范围下结论负责，不把 Checks 子迭代并入验收结论。

## Traceability Matrix

| ID | 验收点 | 证据 | 状态 |
|---|---|---|---|
| GOV-001 | 历史项目级 team 配置入口不再被默认加载 | `engine/config.py:388-429` 默认路径只读取 `templates/team.yaml` 或 DB Settings；直接脚本输出 `default_source= platform`、`default_path= .../templates/team.yaml`，即使历史入口文件存在也未作为 `project` source；`tests/test_config.py:292-302` 覆盖默认忽略 | PASS |
| GOV-002 | 显式传入历史项目配置文件被拒绝 | `engine/config.py:344-362` 识别并拒绝 deprecated path；`engine/config.py:391-403` 在读取显式配置前先拒绝；直接脚本输出 `explicit_absolute_rejected= True`、`explicit_relative_rejected= True`；`tests/test_config.py:304-313` 覆盖 | PASS |
| GOV-003 | CLI 不再暴露生成历史项目配置文件的 init 命令 | `cli/main.py:212-264` 仅注册 `run/status/resume/cleanup/serve/install-skill`；直接脚本输出 `subcommands= cleanup,install-skill,resume,run,serve,status` 和 `init_rejected= True`；`tests/test_config.py:283-288` 覆盖 | PASS |
| GOV-004 | API 不接受历史项目配置文件作为 run config | create run: `api/routes/runs.py:239-244`；resume run: `api/routes/runs.py:373-378`；human-decision 恢复路径：`api/routes/runs.py:428-433`；route 测试：`tests/test_routes.py:698-711`、`tests/test_routes.py:765-787`、`tests/test_routes.py:885-930` | PASS |
| GOV-005 | 默认模板不再声明项目文件可覆盖平台配置 | `templates/team.yaml:4-5` 声明自定义入口为 Settings/DB 或 `.ai/pipeline-configs/*.yaml`，历史入口已废弃；`templates/team.yaml:317-318` 声明质量门禁通过 Settings/DB、内置模板或物化配置管理；文档扫描无历史入口字面量命中 | PASS |
| GOV-006 | 治理设计明确 AGENTS、Settings、prompt override、pipeline config、Harness assets 边界 | `docs/superpowers/specs/2026-05-10-project-governance-configuration-design.md:75-82` 明确废弃入口处理；`docs/superpowers/specs/2026-05-10-project-governance-configuration-design.md:121-127` 定义 GOV-001..GOV-007 验收项 | PASS |
| GOV-007 | 每个治理子迭代必须有 traceability rows 和 fresh verification evidence | 本报告提供独立 matrix、修复记录、测试和扫描证据，报告路径即 `docs/superpowers/reports/2026-05-10-project-governance-configuration-final-report.md` | PASS |

## 关键证明

### 历史项目级 team 配置入口不再默认加载

代码证据：

- `load_config()` 无显式配置时初始化为平台模板路径，并只读取 `DEFAULT_TEAM_FILE` 或 `DEFAULT_CONFIG`。
- DB Settings 是唯一默认自定义来源；没有读取项目根历史 team 配置入口的分支。

脚本证据：

```text
default_source= platform
default_path= /Users/wurui/IdeaProjects/ai-team-platform/templates/team.yaml
default_ignored_legacy_exists= True
```

### 显式历史项目级 team 配置入口被拒绝

脚本证据：

```text
explicit_absolute_rejected= True
explicit_relative_rejected= True
```

测试证据：

```text
tests/test_config.py::TestLoadConfig::test_explicit_legacy_project_team_yaml_is_rejected PASSED
```

### CLI 不再暴露 init

脚本证据：

```text
subcommands= cleanup,install-skill,resume,run,serve,status
init_rejected= True
```

测试证据：

```text
tests/test_config.py::TestCliParser::test_deprecated_project_config_init_command_is_not_exposed PASSED
```

### API create/resume 不接受历史项目级 team 配置入口

测试证据：

```text
tests/test_routes.py::TestRunsRoutes::test_create_run_rejects_deprecated_project_team_config_path PASSED
tests/test_routes.py::TestRunsRoutes::test_resume_run_rejects_deprecated_project_team_config_path PASSED
tests/test_routes.py::TestRunsRoutes::test_human_decision_rejects_deprecated_project_team_config_path PASSED
```

红灯证据：

```text
tests/test_routes.py::TestRunsRoutes::test_human_decision_rejects_deprecated_project_team_config_path FAILED
AssertionError: 200 != 400
```

修复后同一用例通过，证明缺口已关闭。

### 文档和模板不再把历史项目级 team 配置入口作为事实源

文档证据：

- `docs/ops/backup-restore-rollback.md:7-9` 配置备份范围为 DB Settings、物化 pipeline config、环境变量、镜像 tag 和 release SHA。
- `docs/spec_1.0.md:373-386` 仅保留 `.ai/agents/*.md` 作为 prompt 覆盖，prompt 路径来自平台模板、DB Settings 或物化 pipeline config。
- `docs/spec_1.0.md:698-702` 配置示例改为物化 pipeline config。
- `docs/spec_1.1.md:461-486` 模板库保存到平台 Settings 或物化 pipeline config。
- `docs/superpowers/superpower-analysis.md:31`、`docs/superpowers/superpower-analysis.md:131`、`docs/superpowers/superpower-analysis.md:329-332` 均限定为平台模板、DB Settings、pipeline config 或 Harness governance assets。

扫描证据：

```text
rg -n "<legacy-project-team-entry-pattern>" <验收对象文件列表>
# 无输出，exit 1
```

```text
find .ai -maxdepth 2 -name team.yaml -print
# 无输出
```

## Verification

```text
.venv/bin/python -m pytest tests/test_config.py tests/test_routes.py tests/test_task_queue.py
154 passed, 2 warnings in 6.13s
```

```text
.venv/bin/python -m compileall engine api cli
PASS
```

```text
git diff --check -- docs/superpowers/specs/2026-05-10-project-governance-configuration-design.md engine/config.py api/routes/runs.py cli/main.py templates/team.yaml .gitignore docs/ops/backup-restore-rollback.md docs/spec_1.0.md docs/spec_1.1.md docs/superpowers/superpower-analysis.md tests/test_config.py tests/test_routes.py tests/test_task_queue.py
PASS
```

```text
rg -n "\.ai/team\.yaml" docs/superpowers/specs/2026-05-10-project-governance-configuration-design.md engine/config.py api/routes/runs.py cli/main.py templates/team.yaml .gitignore docs/ops/backup-restore-rollback.md docs/spec_1.0.md docs/spec_1.1.md docs/superpowers/superpower-analysis.md tests/test_config.py tests/test_routes.py tests/test_task_queue.py
NO MATCH
```

## Scope Boundary

未处理 Checks 子迭代完成度，也未引入新配置体系、DB schema、UI 或 Harness design 变更。

本次新增/修改仅用于关闭 cleanup 验收缺口：

- API 恢复路径拒绝 deprecated config。
- Route 负向测试补齐。
- 文档事实源措辞清理。
- 本独立 final report。
