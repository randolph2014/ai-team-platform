# Superpower Skill 分析报告

> 基于 ai-team-platform 项目代码的深度分析

---

## 1. Superpower 的定义与入口

### 1.1 定义文件位置

| 文件 | 作用 |
|------|------|
| `adapters/ai-team-skill/SKILL.md` | Skill 元数据（名称、描述、用法） |
| `adapters/ai-team-skill/scripts/run.py` | 入口脚本，转发到平台 CLI |
| `adapters/ai-team-skill/adapter-version.json` | 版本追踪 |
| `templates/team.yaml` | 默认流水线配置（核心） |
| `templates/agents/*.md` | 6 个 Agent 的 prompt 定义 |

### 1.2 Skill 安装方式

```bash
ai-team install-skill --target ~/.agents/skills/ai-team --symlink
```

安装的是一个轻量 adapter，核心逻辑在平台仓库的 `engine/` 中。

---

## 2. 核心流程：单需求的完整生命周期

### 2.1 Pipeline 阶段（平台 `templates/team.yaml` 定义）

```
plan (并行)  →  architect  →  context_scan  →  develop  →  code_apply  →  qa  →  review  →  accept
   ↓                ↓              ↓              ↓                        ↓       ↓
brainstormer    solution-      codebase-      tech-lead              qa-auto  code-reviewer
devils-advocate  architect     context        (代码实现)              (测试)    (审查)
```

**7 个阶段，6 个 Agent，1 个代码扫描器，1 个人工验收点。**

### 2.2 每个阶段的输入/输出

| 阶段 | Agent | 输入 | 输出文件 |
|------|-------|------|----------|
| plan | brainstormer, devils-advocate | requirement | brainstorm.md, gap-analysis.md |
| architect | solution-architect | requirement + brainstorm + gap-analysis | solution-draft.md |
| context | (scanner) | solution-draft.md | codebase-context.md |
| develop | tech-lead | requirement + solution + context | tech-lead-output.md |
| code_apply | (自动) | tech-lead-output.md | 写入代码文件 |
| qa | qa-automation | 全部 + git-diff | test-report.md |
| review | code-reviewer | 全部 + git-diff | review-report.md |
| accept | human_review | 全部 | 人工决策 |

### 2.3 数据流：产物级联

每个 Agent 的输出自动成为下游 Agent 的输入。Orchestrator 的 `_collect_inputs()` 方法负责：
- 读取 `requirement.md`
- 读取前序阶段的产物文件
- 获取 `git-diff`
- 将所有内容注入到下一个 Agent 的 prompt 中

---

## 3. 任务清单机制

### 3.1 任务清单的定义方式

**任务清单不是独立的数据结构，而是嵌入在方案文档中的结构化内容。**

Solution Architect Agent 的 prompt 要求其输出必须包含 `## 实施清单` 章节：

```markdown
## 实施清单

### 新增文件
- `path/to/new/file.ext` — 文件用途说明

### 修改文件
- `path/to/existing/file.ext` — 修改内容概述

### 测试文件
- `path/to/test/file.ext` — 测试覆盖范围

### 验证命令
- 编译: `swift build -c debug`
- 测试: `swift test --parallel`
```

### 3.2 任务完成状态跟踪

**由多个 Agent 协同验证，而非单一 checklist：**

1. **Tech Lead**：严格按实施清单执行，只修改清单中列出的文件
2. **QA Automation**：检查测试文件是否与清单一致
3. **Code Reviewer**：对照清单检查完整性
   - 是否遗漏了清单中的文件
   - 是否修改了清单外的文件
   - 依赖变更是否与清单一致

### 3.3 实际运行报告结构（RunReport）

```python
class RunReport(BaseModel):
    run_id: str
    status: RunStatus  # pending | running | completed | failed | cancelled | waiting
    requirement: str
    stages: List[StageRun]  # 每个阶段的运行状态
    artifacts: List[str]    # 生成的文件列表
    worktree_path: Optional[str]
    merge_result: Optional[Dict]
    duration_seconds: Optional[float]
```

每个 Stage 包含：
```python
class StageRun(BaseModel):
    stage_id: str
    status: StageStatus  # pending | running | completed | failed | skipped | waiting
    agents: List[AgentRun]        # Agent 执行详情
    quality_gates: List[QualityGateRun]  # 质量门禁结果
    iteration: int  # 第几次重试
```

---

## 4. 质量检查机制

### 4.1 Quality Gates（质量门禁）

默认定义在平台 `templates/team.yaml` 的 `quality_gates` 配置中：

```yaml
quality_gates:
  - name: python-syntax
    type: command
    command: "python3 -m py_compile ..."
    required: true
  - name: test-coverage
    type: threshold
    command: "pytest --cov ..."
    parse: "regex:Coverage:\\s*([\\d.]+)%"
    operator: ">="
    threshold: 80
    required: false
    max_retries: 1
```

**两种门禁类型：**
- `command`：执行命令，退出码 = 0 为通过
- `threshold`：执行命令，用正则解析输出，与阈值比较

**required 字段：**
- `true`：失败 → 阻塞（failed）
- `false`：失败 → 警告（warning），不阻塞

### 4.2 Quality Loop（质量循环）

`_run_develop_quality_loop()` 实现了 develop 阶段后的自动质量检查循环：

```
develop 完成 → 运行 quality_gates
  ↓ 全部通过
  继续下一阶段
  ↓ 有 required 失败
  渲染失败反馈 → 重新运行 develop Agent（带错误反馈）
  ↓ 重试后再次检查
  ↓ 超过 max_retries
  标记 failed，停止
```

### 4.3 Loopback 机制（阶段间回退）

多个阶段配置了 `loopback_to` 和 `loopback_trigger`：

```yaml
# QA 阶段如果发现测试失败，回退到 develop
- id: qa
  loopback_to: develop
  loopback_trigger: ["FAILED", "ERROR", "失败", "exit code: 1"]
  max_retries: 2

# Review 阶段如果要求修改，回退到 develop
- id: review
  loopback_to: develop
  loopback_trigger: "Request Changes"
  max_retries: 2
```

**智能止损机制：**
- 总耗时上限（默认 2 小时）
- 连续 2 次相同错误自动停止
- 错误签名提取（忽略行号、时间戳等易变信息）
- 语义关键词匹配（中英文同义词扩展）

### 4.4 Agent 级别的自验证

每个 Agent 的 prompt 都包含自验证要求：

- **Tech Lead**：必须执行验证命令，失败则自行修复
- **QA Automation**：必须真实执行测试，报告退出码
- **Code Reviewer**：必须基于 git-diff 的实际代码下结论

---

## 5. 与现有 Agent 的集成方式

### 5.1 Runtime 抽象

```yaml
runtimes:
  auto:
    name: Auto
    cli: auto  # 自动检测 claude/codex/copilot 等

agents:
  - name: tech-lead
    runtime_id: auto  # 引用 runtime，而非直接配置 provider
```

`build_runtime_command()` 负责将 runtime 配置转换为实际的 CLI 命令。

### 5.2 Agent 执行链

```
Orchestrator.run()
  → _run_agent_stage()
    → AgentRunner.run()
      → build_runtime_command()  # 构建 CLI 命令
      → subprocess.Popen()       # 启动子进程
      → 流式读取 stdout          # 实时输出
      → 写入 output_file         # 保存产物
      → 模型 fallback            # 失败时切换模型
```

### 5.3 结构化输出协议

Tech Lead 的输出支持两种格式：

**JSON 格式（推荐）：**
```json
{
  "files": [
    {"path": "src/auth/login.py", "action": "create", "content": "..."},
    {"path": "tests/test_login.py", "action": "modify", "content": "..."}
  ]
}
```

**Markdown 格式（兼容）：**
```markdown
### 修改文件: `path/to/file.ext`
```language
（完整代码内容）
```
```

`CodeApplier` 自动解析并将代码写入文件系统。

---

## 6. 核心设计理念

### 6.1 流水线即配置

整个开发流程用 YAML 定义，可以：
- 自定义 Agent 组合
- 调整阶段顺序
- 配置质量门禁
- 设置重试策略

### 6.2 产物级联

每个 Agent 的输出成为下游的输入，形成信息传递链：
```
requirement → brainstorm → solution → context → code → test → review
```

### 6.3 多层质量保障

| 层级 | 机制 | 触发者 |
|------|------|--------|
| L1 | Agent 自验证 | Agent prompt 要求 |
| L2 | Quality Gates | Orchestrator 自动运行 |
| L3 | Loopback 重试 | 阶段间自动回退 |
| L4 | 人工验收 | Human Review 阶段 |

### 6.4 智能止损

- 总耗时上限
- 重复错误检测
- 最大重试次数
- 关键阶段不可跳过（production 模式）

### 6.5 Worktree 隔离

每个 run 在独立的 git worktree 中工作，互不干扰：
```
.ai/worktrees/{run_id}/  # 独立工作目录
  → 完成后 squash merge 回主分支
```

---

## 7. 可复用的部分

### 7.1 可直接复用

| 组件 | 文件 | 用途 |
|------|------|------|
| Quality Gates 引擎 | `engine/quality_gates.py` | 任何项目的质量门禁 |
| Worktree 管理器 | `engine/worktree.py` | Git worktree 自动化 |
| Code Applier | `engine/code_applier.py` | 解析 AI 输出并写入文件 |
| 事件总线 | `engine/events.py` | 运行时事件通知 |
| 成本追踪 | `engine/cost_tracker.py` | Token 用量统计 |

### 7.2 可参考的模式

1. **Agent Prompt 模板化**：每个 Agent 的 role、输入、输出、原则都结构化定义
2. **实施清单模式**：方案文档中嵌入可验证的任务清单
3. **Loopback 反馈循环**：失败时自动将错误信息注入重试 prompt
4. **结构化输出协议**：JSON + Markdown 双格式兼容
5. **Checkpoint 恢复**：长任务中断后可从断点继续

### 7.3 可扩展的接口

| 扩展点 | 方式 |
|--------|------|
| 新增 Agent | 添加 prompt 文件 + 更新平台模板、DB Settings 或 pipeline 模板 |
| 新增质量门禁 | 在平台模板、DB Settings 或物化 pipeline config 的 quality_gates 配置中添加条目 |
| 自定义 Runtime | 在 DB Settings 或 pipeline config 的 runtimes 中配置 CLI 命令 |
| 项目级覆盖 | `.ai/agents/*.md` + Harness governance assets |

---

## 8. 总结

**ai-team-platform 的 superpower 本质是一个多 Agent 协作的软件开发流水线引擎。**

它的核心创新不是单个 Agent 的能力，而是：
1. **流程编排**：用配置定义复杂的多阶段开发流程
2. **信息传递**：通过产物文件在 Agent 间传递上下文
3. **质量闭环**：多层验证 + 自动重试 + 智能止损
4. **任务追踪**：实施清单嵌入方案文档，由多个 Agent 交叉验证

这不是一个"通用任务管理器"，而是一个**针对软件开发场景深度优化的 Agent 编排框架**。
