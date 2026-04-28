# AI Team Platform 全量实施方案

## Context

基于对仓库的完整代码审计，将修复缺口 + 新功能拆成 **10 个独立迭代**。
每个迭代是一个**自包含的工作包**：包含完整背景、要改的文件、具体改动、测试方案、验收标准。
单个迭代的全部信息（含读取的源码）应控制在 200k token 以内，确保一个 agent 上下文能消化全生命周期（需求→设计→编码→测试→审查）。

> **状态说明**：迭代 1-5 已基本实现，实际代码与 spec 修订版一致。迭代 6-10 为未来计划。

## 全局依赖图

```
迭代 1 (loopback 反馈注入) ──┐
迭代 2 (worktree 默认启用)  ──┤
迭代 3 (Runtime 多模型)     ──┤         ┌─ M1 集成验证 ─┐
迭代 4 (持久化 ORM + 鉴权) ──┼── 迭代 5 (RQ + Redis) ── 迭代 7 (前端接真实 API)
                              │         │                     │
                              │         └─ M2 持久化验证 ──┐  │
                              │               │            │  │
                              │               v            │  │
                              │       迭代 6 (API 切持久化)  │  │
                              │               │            │  │
                              │               v            │  │
                              │       迭代 8 (日志 + metrics)  │
                              │               │            │  │
                              │               v            │  │
                              │       迭代 9 (编辑器 + 模板)   │
                              │               │            │  │
                              │               v            │  │
                              └─────── 迭代 10 (CI/CD + 评估)  │
                                                      │       │
                                                      └─ M3 端到端验证
```

**可并行的迭代**：1/2/3/4 互相独立，可同时启动。5 依赖 1-4 全部完成后才能开始。

**集成验证里程碑**：
- **M1**（迭代 3 完成后）：在本仓库自身上跑一次完整 plan→architect→develop→qa→review，产出验收材料
- **M2**（迭代 6 完成后）：API 重启后历史 run 完整可查，DB 数据不丢失
- **M3**（迭代 10 完成后）：浏览器登录→创建 run→看到实时输出→看到产物，全链路端到端验证

## 迭代索引

| # | 名称 | 目标 | 状态 | 改动量 | 预估 |
|---|------|------|------|--------|------|
| 1 | Loopback 反馈注入 | 修复 orchestrator loopback 只写 marker 不注入实际输出的问题 | ✅ 已完成 | ~50 行 | 0.5 天 |
| 2 | Worktree 默认启用 + 测试补全 | 默认 worktree.enabled=true + 自动检测回退 + engine 测试补全 | ✅ 已完成 | ~200 行 | 1 天 |
| 3 | Runtime 多模型 + Fallback | AgentDefinition 加 model 字段、build_runtime_command 支持 --model、fallback 链 | ✅ 已完成 | ~150 行 | 1 天 |
| 4 | 持久化 ORM + API 鉴权 | asyncpg CRUD 6 表 + JWT/API Key auth + model_used 迁移 | 🟡 部分完成 | ~450 行 | 2.5 天 |
| 5 | RQ 任务队列 + Docker | 替换 threading 为 RQ、docker-compose 加 Redis+Worker、Worker 镜像 CLI 依赖 | 🟡 部分完成 | ~250 行 | 1.5 天 |
| 6 | API 层切换持久化 | runtime.py 从内存切 DB、routes 从文件切 DB | ⬜ 未开始 | ~300 行 | 2 天 |
| 7 | 前端接真实 API | 5 页面 mock→real API、新增 Login 页、原型对齐验收 | ⬜ 未开始 | ~600 行 | 2.5 天 |
| 8 | 结构化日志 + Metrics + 测试覆盖 | structlog + prometheus + api/persistence 覆盖率 ≥ 80% | ⬜ 未开始 | ~300 行 | 1.5 天 |
| 9 | Pipeline 编辑器 + 模板库 + Webhook | React Flow 编辑器 + 模板管理 API + Webhook 触发 | ⬜ 未开始 | ~900 行 | 3.5 天 |
| 10 | CI/CD 集成 + Agent 评估 | GitHub PR 创建 + Agent 质量评分 | ⬜ 未开始 | ~400 行 | 2 天 |

总预估：~16 天（串行），考虑并行可压缩到 ~10 天。

---

下面是每个迭代的**完整自包含规格**。实施时，把单个迭代的内容（本文件对应 section + 涉及的源码文件）交给一个 agent 即可，不需要跨迭代引用。

---

## 迭代 1：Loopback 反馈注入 — ✅ 已完成

### 背景
`engine/orchestrator.py:168-186` 中，当 qa/review stage 的 loopback 触发（如 qa 输出包含 "FAILED"）时，只写了一个 marker 字符串 `## Loopback feedback\n\nStage ... triggered loopback to ...`，**没有把上一轮失败输出/审查意见注入到下一轮 develop prompt**。这导致 tech-lead agent 在 loopback 回来时不知道具体哪里失败，只能盲改。

`engine/quality_gates.py:134-151` 的 `render_gate_feedback` 函数已正确实现了反馈注入（包含失败命令、退出码、输出内容），格式为 `## 质量门禁失败反馈（第 N 次重试）`，作为参考模式。

### 实际实现（`engine/orchestrator.py:356-389`）

核心改动：
1. 新增 `_render_loopback_feedback` 方法，与 `render_gate_feedback` 保持格式一致（均用 `## xxx 反馈（第 N 次重试）` 标题）
2. **截断长度配置化**：从 `runner.max_loopback_feedback_chars` 读取上限（默认 20000），而非硬编码 5000
3. 反馈包含 agent 的 runtime、状态、错误信息、输出内容；超过上限时自动截断并注明
4. 无 agent 时回退到 `_stage_output_text` 取整体 stage 输出

```python
# engine/orchestrator.py:356-389 实际实现
def _render_loopback_feedback(self, stage_id, stage_run, retry_count, target):
    max_chars = int(self.config.get("runner", {}).get("max_loopback_feedback_chars") or 20000)
    lines = [f"## Loopback 反馈（第 {retry_count} 次重试）", ""]
    # ... 按 agent 逐个输出，用 used_chars 控制总量
    # 与 quality_gates.render_gate_feedback 格式对齐
```

5. 修改原第 184 行：调用 `_render_loopback_feedback` + 写入 `loopback-feedback-{stage_id}-{count}.md`

### 配置

```yaml
runner:
  max_loopback_feedback_chars: 20000  # 反馈内容上限，防止 prompt 过长
```

### 验收标准
- `pytest tests/test_loopback.py -v` 全部通过
- loopback 反馈文件包含实际 agent 输出（不是空 marker）
- 反馈格式与 `render_gate_feedback` 一致（均用中文标题 `反馈（第 N 次重试）` 格式）

---

## 迭代 2：Worktree 默认启用 + Auto 模式回退 — ✅ 已完成

### 背景
`templates/team.yaml:39` 默认 `worktree.enabled: true`，`engine/config.py:140` 的 `normalize_config` 默认值同步。engine 测试已从 7 个增长到 260 个。

### 设计决策：破坏性变更的缓解策略

`enabled: true` 是破坏性默认值——以下场景会失败：
- 项目根不是 git repo（`WorktreeManager.ensure_git_repo` 抛 `WorktreeError`）
- 项目分支不是 `base_branch`（默认 `main`，找不到分支会失败）
- 用户首次 `pip install` 后 `ai-team run` 默认崩溃

**采用的缓解方案（组合 A+B）**：

1. **`runner.require_worktree` 开关** — production mode 下强制要求 worktree 启用（`engine/config.py:61-62, 69-71`），非 production 模式可选
2. **`WorktreeManager` 非 git repo 友好报错** — 抛出 `WorktreeError` 并附说明，而非静默失败
3. **配置文档化** — `templates/team.yaml` 注释说明 worktree 默认启用及回退方法

### 要改的文件
- `templates/team.yaml` — 保持 `enabled: true`（已实现）
- `engine/config.py` — `normalize_config` 默认 `{"enabled": True}` + `require_worktree` 校验（已实现）
- `engine/worktree.py` — `ensure_git_repo` 错误提示更友好

### 测试方案
- `tests/test_worktree.py`：create→路径存在+分支名正确；cleanup→目录+分支清除；非 git 仓库→WorktreeError；base_branch 不存在→错误提示
- `tests/test_quality_gates.py`：command 成功/失败；threshold 成功/失败；required=false→warning；max_retries 循环
- `tests/test_context_scanner.py`：实施清单解析；max_file_size 截断
- `tests/test_config.py`：项目级 .ai/agents/ 覆盖 prompt；normalize_config legacy provider；validate_production_config 错误
- `tests/test_events.py`：subscribe/emit 传递；unsubscribe 后不收到

### 验收标准
- `pytest --cov=engine tests/` 覆盖率 ≥ 80%
- 非 git repo 时抛出 `WorktreeError`（含 "Not a git repository"），不静默失败
- `require_worktree=true` + `worktree.enabled=false` → `ConfigError`

---

## 迭代 3：Runtime 多模型 + Fallback — ✅ 已完成

### 背景
当前所有 agent 默认 `runtime_id: auto`，由 runtime 配置中的 CLI 按 claude→codex→opencode 顺序选择第一个可用工具。模型级参数（如 claude-opus vs claude-sonnet）和 fallback 模型属于 runtime 配置，agent 只通过 `runtime_id` 引用 runtime，避免一种模型失败后整个流水线直接失败。

### CLI 参数验证（已确认）

| CLI | model 参数 |
|-----|-----------|
| claude | `--model <model>` |
| codex | `-m <MODEL>` |
| opencode | `-m, --model` |

`build_runtime_command` 实现：codex 用 `-m`，其他 CLI 用 `--model`，与 CLI 实际参数一致。

### 实际实现

1. `engine/models.py` AgentDefinition：
   - 只保留 `runtime_id`、`role`、`prompt`、`timeout` 等 agent 自身字段
   - 禁止再配置 `model` / `fallback_models`
2. runtime 配置：
   - `model` 为主模型
   - `fallback_models` 为同一 CLI/runtime 下的模型回退序列
3. `engine/models.py` AgentRun：
   - `model_used: Optional[str] = None`
4. `engine/runtimes.py` `build_runtime_command(runtime, prompt, model=None)`：
   - codex: `["-m", model]`，其他 CLI: `["--model", model]`
5. `engine/agent_runner.py` `AgentRunner.run`：
   - 先用 `runtime.model` 执行
   - 失败时按 `runtime.fallback_models` 顺序重试
   - 记录 `agent_run.model_used`
   - 发送 `agent:fallback` 事件
6. `templates/team.yaml` 示例已更新

### 测试方案
- `tests/test_provider_models.py`：指定 model 时 build_runtime_command 输出含 `--model claude-opus-4-7`；mock 主模型失败→fallback 到下一个→记录 model_used；所有 fallback 都失败→返回最后错误

### 验收标准
- 测试全通过
- `build_runtime_command(runtime_config, prompt, model="claude-opus-4-7")` 返回含 `--model` 的命令

---

## 迭代 4：持久化 ORM + API 鉴权 — 🟡 核心已完成，缺 model_used 迁移

### 背景
`persistence/__init__.py` 已有完整导出。`api/auth.py` 已有 JWT + API Key 鉴权。DB schema 已在 `persistence/migrations/001_init.up.sql` 定义了 6 张表 + 002_cost_tracking 表。

### ⚠️ 待修复：model_used 未落库

`engine/models.py` 的 `AgentRun` 有 `model_used` 字段，但：
- `persistence/migrations/001_init.up.sql` 的 `agent_run` 表 **无** `model_used` 列
- `persistence/models.py` 的 `AgentRunRecord` **无** `model_used` 字段
- 迭代 8 的 metrics 标签 `model` 因此无法从 DB 取到数据

### 需要新增的迁移

**新建 `persistence/migrations/003_agent_model.up.sql`**：
```sql
ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS model_used TEXT;
ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS model_requested TEXT;
```

**同步的 down.sql**：
```sql
ALTER TABLE agent_run DROP COLUMN IF EXISTS model_used;
ALTER TABLE agent_run DROP COLUMN IF EXISTS model_requested;
```

**`persistence/models.py` AgentRunRecord 新增**：
```python
model_used: Optional[str] = None
model_requested: Optional[str] = None
```

### 已完成的改动

**persistence/database.py** — asyncpg 连接池 + `init_db()`
**persistence/models.py** — 6 张表的 Pydantic 行映射
**persistence/repository.py** — CRUD 操作
**api/auth.py** — JWT + API Key（`AI_TEAM_API_KEYS` 环境变量逗号分隔）

### API Key 管理改进方案（规划中）

当前问题：API Key 用环境变量管理，无吊销机制、无用户绑定、无法审计。

建议方案（后续迭代）：
- 新增 `api_key` 表（`id`, `key_hash`, `user_id`, `label`, `enabled`, `created_at`, `revoked_at`）
- 环境变量保留 `AI_TEAM_BOOTSTRAP_API_KEY`（首次启动管理员用）
- API 新增 `POST/DELETE /api/api-keys` 管理端点

### 鉴权范围
- `/health`、`/api/auth/login` 不需要鉴权
- 所有其他 `/api/*` 需要 JWT
- WebSocket 需要 token
- 未设置 `AI_TEAM_API_KEYS` 时开发模式跳过鉴权

### 验收标准
- `docker compose up postgres` 后 `init_db()` 成功创建 6+2+1=9 张表
- 无 JWT 时 `/api/runs` 返回 401
- `model_used` 正确写入 DB

---

## 迭代 5：RQ 任务队列 + Docker — 🟡 核心已完成，缺 Worker 镜像 CLI

### 背景
`api/runtime.py:13,50-52` 用 `threading.Thread(daemon=True)` 和 `InMemoryEventStore`，进程崩溃即丢状态。需要替换为 RQ + Redis。

### job_timeout 参数策略（已实现）

`engine/task_queue.py:58-68` 实际实现：
```python
job = q.enqueue(
    execute_pipeline,
    ...
    job_timeout="24h",       # RQ 默认 180s，agent 执行可能 30 分钟，设为 24 小时
    result_ttl=86400,        # 结果保留 24 小时
)
```

策略说明：
- `job_timeout`：设为 `"24h"`（字符串形式），远大于 agent 最长执行时间（30 分钟）。更精细的做法是读取 `runner.agent_timeout_seconds * 1.5`，当前为保底用固定值
- `result_ttl`：结果在 Redis 中保留 24 小时，可调整为 30 天以支持长期历史查询
- `failure_ttl`：默认与 `result_ttl` 相同

### ⚠️ Docker Worker 镜像缺少 Agent CLI

**根本问题**：容器中的 worker 运行 `python -m engine.tasks` → `AgentRunner.run` → `shutil.which("claude")` → 找不到 CLI → `ConfigError: No supported agent CLI found`

当前 `docker/Dockerfile.api` 只装了 `git`，没有安装任何 agent CLI。

**建议方案**（采用选项 A）：

在 `docker/Dockerfile.api` 中增加：
```dockerfile
# Options A: 在镜像中预装 agent CLI
RUN npm install -g @anthropic-ai/claude-code @openai/codex opencode
```

如果镜像体积是关注点，新建 `docker/Dockerfile.worker` 专门给 worker 用，api 容器不装 CLI。

### 已实现部分

**engine/task_queue.py**：
- `get_queue()` → rq.Queue 实例（从 `AI_TEAM_REDIS_URL` 读地址），Redis 不可用时返回 None 降级
- `enqueue_run()` → 提交任务，支持 `yes`/`config_path`/`only_stage` 参数
- `get_job_status(job_id)` → 查询状态

**engine/tasks.py**：
- `execute_pipeline()` 任务函数，内部创建 Orchestrator + EventBus
- `if __name__ == "__main__"` 或 `rq worker` 启动

**api/runtime.py**：
- `InMemoryEventStore` 保留用于 WebSocket 实时推送
- `start_run_background` 改为调用 `enqueue_run()`，Redis 不可用时回退到本地线程

**docker-compose.yml**：
```yaml
worker:
  build: {context: ., dockerfile: docker/Dockerfile.api}
  command: ["python", "-m", "engine.tasks"]
  environment:
    AI_TEAM_DB_URL: postgresql://ai_team:ai_team@postgres:5432/ai_team
    AI_TEAM_REDIS_URL: redis://redis:6379/0
  depends_on: [redis, postgres]
  volumes: [.:/app, ai-team-output:/app/.ai/team-output]
```

### 验收标准
- `docker compose up` 后 5 容器（api/web/worker/postgres/redis）均 healthy
- 通过 API 提交 run → worker 日志显示执行
- Redis 连接失败时 API 优雅降级（回退到线程模式），不崩溃

---

## 迭代 6：API 层切换持久化 — ⬜ 未开始

### 背景
API routes 目前从文件系统读状态（`.ai/team-output/*/report.json`），需要改为从 DB 读取。同时 EventBus 需要从内存单机改为 Redis PubSub 跨 worker 同步。

### 要改的文件
- `api/routes/runs.py` — list_runs/get_run 从 DB 查
- `api/routes/artifacts.py` — run_id 通过 DB 验证
- `api/ws.py` — 历史事件从 DB 加载 + Redis PubSub 订阅实时事件
- `api/routes/settings.py`（新建）— GET/PUT 配置
- `api/routes/pipelines.py`（新建）— Pipeline CRUD
- `api/app.py` — 注册新路由

### 具体改动

**api/routes/runs.py**：
- `list_runs` → `RunRepo.list(page, size)` + 分页
- `get_run` → `RunRepo.get(run_id)` 含 stages/agents/gates
- `create_run` → `enqueue_run()` 返回 run_id + status="pending"

**api/ws.py**：
- 连接时从 DB 加载历史事件
- 通过 Redis PubSub 订阅实时事件
- 发送到前端

**新路由**：
- `GET/PUT /api/settings`：读取/更新运行配置
- `GET/POST /api/pipelines`、`GET/PUT/DELETE /api/pipelines/{id}`

### 验收标准
- API 重启后历史 run 不丢失
- 创建 run 后 Dashboard 实时看到状态变化

---

## 迭代 7：前端接真实 API — ⬜ 未开始

### 背景
Web 5 个页面（Dashboard/Runs/RunDetail/Pipelines/Settings）用 mock 数据。需要替换为真实 API 调用 + 新增 Login 页。

### 要改的文件
- `web/src/lib/api.ts` — 添加 auth header、login、fetchPipelines 等
- `web/src/lib/mockData.ts` — 删除或降级为 fallback
- `web/src/pages/Dashboard.tsx` — mock→real
- `web/src/pages/Runs.tsx` — mock→real + 分页
- `web/src/pages/RunDetail.tsx` — mock→real + WebSocket
- `web/src/pages/Pipelines.tsx` — mock→real
- `web/src/pages/Settings.tsx` — mock→real
- `web/src/pages/Login.tsx`（新建）— API Key 输入→JWT
- `web/src/App.tsx` — 添加 /login 路由 + auth guard

### 原型对齐验收（spec 4.2.3 要求）

**必须完成的验收步骤**：
1. 将 `/private/tmp/ai-team-prototype/index.html` 归档到 `docs/prototypes/ai-team-dashboard/index.html`
2. 用 Playwright 截图验证三个关键页面：
   - `/dashboard` — Dashboard 页
   - `/runs/{id}` — Run 详情页
   - `/settings` — 设置页
3. 截图存到 `tests/e2e/screenshots/`，与原型对照确认视觉一致性

### 测试方案
- `npm run build` 无 TS 错误
- Docker Compose 环境中所有 5 页面 + Login 展示真实数据
- 无 API 连接时显示错误提示而非白屏
- Playwright e2e：登录→创建 run→查看实时输出→查看产物

### 验收标准
- 前端 build 通过
- 所有页面展示真实数据
- 无 token 时跳转登录页
- 三个关键页面截图与原型对齐验收通过

---

## 迭代 8：结构化日志 + Metrics + 测试补全（api + persistence） — ⬜ 未开始

### 背景
无结构化日志、无 metrics。当前 engine 覆盖率 ~78%，已达目标；需补 api 和 persistence 模块测试。

### 测试分工说明
- **迭代 2**：engine 模块测试（已完成，engine 覆盖率 ≥ 80%，共 260 个测试）
- **迭代 8**：api + persistence 模块测试 + metrics 相关测试，目标**全局覆盖率 ≥ 80%**

### 要改/新建的文件
- `engine/logging.py`（新建）— structlog JSON 配置
- `engine/metrics.py`（新建）— prometheus_client 计数器/直方图
- `engine/orchestrator.py`（改）— 关键路径加日志
- `engine/agent_runner.py`（改）— 加 metrics
- `api/app.py`（改）— 添加 `/metrics` 端点
- `pyproject.toml`（改）— 加 structlog、prometheus-client
- 多个 `tests/test_*.py` — 补 api + persistence 测试到 80%

### 具体改动

**engine/logging.py**：
- structlog 配置 JSON 输出
- `get_logger(run_id, stage_id=None)` 工厂
- 每条日志含 run_id、stage_id、agent_name

**engine/metrics.py**：
- `ai_team_runs_total`（counter，label: status）
- `ai_team_stage_duration_seconds`（histogram，label: stage_id）
- `ai_team_agent_duration_seconds`（histogram，label: agent_name, model）
- `ai_team_quality_gate_results`（counter，label: gate_name, status）
- **注意**：label `model` 依赖迭代 4 的 `model_used` 迁移（`003_agent_model.up.sql`）落库后才能真正取到

**测试补全目标**：
- api 覆盖率从当前 ~63-96% 补到 ≥ 80%
- persistence 覆盖率从当前 ~65% 补到 ≥ 80%
- 总 case 数从 260 增长到 320+

### 验收标准
- `curl /metrics` 返回 prometheus 格式
- 日志为 JSON 格式含 run_id
- `pytest --cov=engine --cov=api --cov=persistence tests/` 全局 ≥ 80%

---

## 迭代 9：Pipeline 编辑器 + 模板库 + Webhook — ⬜ 未开始

### 背景
Phase 2 核心：可视化编辑 Pipeline、模板管理、外部触发。

### 1. Pipeline 编辑器

**要改/新建的文件**：
- `web/src/pages/PipelineEditor.tsx`（新建）
- `web/src/components/flow/` 目录（新建 4 个组件）
- `web/src/lib/pipelineSchema.ts`（新建）— TypeScript 类型 + 验证
- `web/package.json`（改）— 加 @xyflow/react、zod

**功能**：
- React Flow v12 DAG 渲染
- 自定义节点：StageNode（名称+状态）、AgentNode（runtime+model）、GateNode
- LoopbackEdge：带 trigger 标签的回环连线
- 右侧面板：属性编辑器
- 底部：YAML 源码预览（只读或可编辑）
- 保存通过 API 存入 DB

### 2. 模板库

**背景**：除内置 `templates/team.yaml` 外，用户可在项目中创建、管理自定义 Pipeline 模板。

**要改/新建的文件**：
- `api/routes/templates.py`（新建）— 模板 CRUD
- `persistence/migrations/004_templates.up.sql`（新建）— 模板表

**DB schema**：
```sql
CREATE TABLE template (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL DEFAULT 'general',
    config JSONB NOT NULL,          -- 完整的 team.yaml 配置
    author TEXT,
    is_public BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**API**：
- `GET /api/templates` — 列出可用模板（含内置 + 用户创建），支持 category 过滤
- `POST /api/templates` — 从当前 Pipeline 或上传 YAML 创建模板
- `GET/PUT/DELETE /api/templates/{id}` — 模板 CRUD
- `POST /api/templates/{id}/apply` — 将模板应用为项目 `.ai/team.yaml`

**元数据索引**：`templates/` 目录下新增 `index.yaml` 描述内置模板列表和分类：
```yaml
- name: team
  category: full-pipeline
  description: "完整的多 Agent 协作流水线"
- name: code-review
  category: review
  description: "仅代码审查流水线"
```

### 3. Webhook

**要改/新建的文件**：
- `api/routes/webhooks.py`（新建）
- `engine/webhook.py`（新建）— 签名验证 + 分发
- `persistence/migrations/005_webhook.up.sql`（新建）
- `api/app.py`（改）— 注册路由

**功能**：
- `POST /api/webhooks`：注册（URL + secret + events）
- `POST /api/webhooks/trigger`：接收外部 webhook 触发 run
- HMAC-SHA256 签名验证
- 支持 GitHub/GitLab push + pull_request 事件

**DB migration 005**：
```sql
CREATE TABLE webhook (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url TEXT NOT NULL,
    secret TEXT NOT NULL,
    events JSONB NOT NULL DEFAULT '[]',
    pipeline_id UUID REFERENCES pipeline(id),
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 验收标准
- Pipeline Editor 可视化渲染 team.yaml
- 保存 pipeline 到 DB
- 模板 CRUD API 可用，模板可导出/导入
- Webhook 触发创建 run

---

## 迭代 10：CI/CD 集成 + Agent 评估 — ⬜ 未开始

### 背景
Phase 2 收尾：自动创建 PR、Agent 质量评分。

### 要改/新建的文件
- `engine/ci_cd.py`（新建）— GitHub CLI 集成
- `engine/agent_eval.py`（新建）— 评估框架
- `api/routes/eval.py`（新建）
- `persistence/migrations/006_eval.up.sql`（新建）— **同时提供 down.sql**
- `engine/orchestrator.py`（改）— 成功后 CI/CD hook
- `engine/worktree.py`（改）— push_branch 方法

### 具体改动

**engine/ci_cd.py**：
- `GitHubIntegration` 类：
  - `create_pr(worktree_path, title, body)` → `gh pr create`
  - `merge_pr(pr_number)` → `gh pr merge`
  - `list_pr_checks(pr_number)` → CI checks 状态
- 配置：
```yaml
ci_cd:
  provider: github
  create_pr: true
  wait_for_checks: false
  auto_merge: false
```

**engine/agent_eval.py**：
- `EvalSuite`：标准测试任务集
- `run_eval_suite(agent_name, suite)` → 评估
- 维度：完成率、输出质量（规则评分）、响应时间、token 用量
- 内置 3 个标准套件：代码生成、代码审查、测试编写

**DB migration 006**（提供 down.sql 回滚能力）：
```sql
CREATE TABLE eval_suite (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    tasks JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE eval_result (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    suite_id UUID REFERENCES eval_suite(id),
    agent_name TEXT NOT NULL,
    model TEXT,
    scores JSONB NOT NULL DEFAULT '{}',
    executed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 验收标准
- 有 `gh` CLI 的环境中 run 成功后自动创建 PR
- Agent 评估 API 可用并返回评分

---

## 技术决策速查

| 决策 | 选择 | 理由 |
|------|------|------|
| ORM | asyncpg + 手写 SQL | 6-8 张表，查询简单，性能优先 |
| 任务队列 | RQ (Redis Queue) | 轻量，Python 原生 |
| job_timeout | "24h" 字符串形式 | agent 最长 30min，24h 足够；可改为 `agent_timeout_seconds * 1.5` |
| result_ttl | 86400s (24h) | 默认；可调整为 2592000（30 天）支持长期历史 |
| 鉴权 | API Key + JWT | API Key 用于初始+Webhook，JWT 用于前端 |
| 鉴权增强 | API Key 落 DB + 吊销 | 规划中（`api_key` 表），当前仅环境变量 |
| 实时事件 | Redis PubSub + WebSocket | 跨 worker 同步 |
| Pipeline 编辑器 | React Flow v12 | DAG 可视化标准 |
| Worker 镜像 CLI | npm install agent CLI | 选项 A：预装到 Dockerfile；或本地 bind mount |
| 日志 | structlog JSON | 便于 ELK/Loki 采集 |
| Metrics | prometheus_client | Prometheus 生态标准 |
| CI/CD | gh CLI 子进程 | 不依赖 SDK |
| 反馈截断 | 配置驱动 `max_loopback_feedback_chars` | 不硬编码 |

## DB 迁移版本追踪

| 编号 | 文件 | 内容 | 状态 | 迭代 |
|------|------|------|------|------|
| 001 | `001_init.up.sql` | 6 张核心表 | ✅ 已部署 | 4 |
| 002 | `002_cost_tracking.up.sql` | cost_tracking 表 | ✅ 已部署 | 4 |
| 003 | `003_agent_model.up.sql` | agent_run 加 model_used/model_requested | ⬜ 待创建 | 4 补充 |
| 004 | `004_templates.up.sql` | template 表 | ⬜ 待创建 | 9 |
| 005 | `005_webhook.up.sql` | webhook 表 | ⬜ 待创建 | 9 |
| 006 | `006_eval.up.sql` | eval_suite + eval_result 表 | ⬜ 待创建 | 10 |

> **迁移规范**：每个 migration 必须同时提供 `xxx.up.sql` 和 `xxx.down.sql`，确保可回滚。

## 关键文件索引

- 编排核心：`engine/orchestrator.py`（loopback 反馈 `_render_loopback_feedback:356-389`、CI/CD hook）
- Agent 执行：`engine/agent_runner.py`（model 参数 `build_command:41-59`、fallback `AgentRunner.run:85-143`）
- 数据模型：`engine/models.py`（AgentDefinition 只引用 runtime；AgentRun 含 model_used/model_requested）
- 配置：`engine/config.py`（normalize_config:123-142、validate_production_config:207-214）
- Quality Gates：`engine/quality_gates.py`（render_gate_feedback:134-151 反馈格式参考）
- 任务队列：`engine/task_queue.py`（enqueue_run:44-69 含 job_timeout="24h"）
- DB schema：`persistence/migrations/001_init.up.sql`
- ORM 模型：`persistence/models.py`（6 表 Pydantic 映射）
- 鉴权：`api/auth.py`（JWT + API Key + 开发模式跳过）
- API 后台：`api/runtime.py`（threading→RQ + Redis 降级）
- 流水线配置：`templates/team.yaml`
- Agent prompt：`templates/agents/*.md`
