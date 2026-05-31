# AI Team Platform

> 说一个需求，交付一个可上线的版本。

将 ai-team 从 Agent skill 演进为独立平台：核心是平台仓库内的编排引擎，前端是自建轻量面板，不依赖任何第三方平台。

## 当前实现

- `engine/`：平台侧 Workflow Engine，包含配置加载、Agent 执行、Context Scanner、Worktree、Quality Gates 和 report 产物。
- `cli/`：`ai-team run / status / serve / cleanup / install-skill`。
- `api/`：FastAPI REST + WebSocket，文件系统模式读取 `.ai/team-output/*/report.json`。
- `web/`：React + Tailwind + Vite 面板，保留已认可原型的深色运维面板信息架构。
- `templates/`：平台内置默认 team.yaml 和 agent prompts，不依赖 `~/.agents/skills/ai-team`。
- `adapters/ai-team-skill/`：可选 skill 兼容入口，只转发到平台 CLI。

## 快速开始

最小 Quickstart（不需要 PostgreSQL、Redis、Web 服务、Docker 或 Playwright）：

```bash
python3.12 -m venv .venv  # any Python 3.11+ works
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
ai-team --help
pytest tests/ -q
```

DB、Redis、Web 面板、Docker 和浏览器 smoke 属于进阶验证，不是首次体验必需。完整本地运行：

```bash
# 安装平台依赖（Python 3.11+）
python3 -m pip install -e .

# 运行 pipeline
ai-team run "实现一个需求" --project /path/to/project --yes

# 从 spec 文件读取需求
ai-team run --spec-file docs/spec_1.1.md --project /path/to/project --yes

# 查看状态
ai-team status --project /path/to/project

# 启动 API
ai-team serve --host 127.0.0.1 --port 8000
```

本地 API + DB + Redis + Worker：

```bash
# 依赖本机已启动 PostgreSQL 和 Redis
# 若手工启动 Redis，不要在仓库根目录启动；指定仓库外工作目录以避免生成 ./dump.rdb
# mkdir -p /tmp/ai-team-redis
# redis-server --dir /tmp/ai-team-redis --dbfilename dump.rdb
export AI_TEAM_DB_URL=postgresql://ai_team:ai_team@127.0.0.1:5432/ai_team
export AI_TEAM_REDIS_URL=redis://127.0.0.1:6379/0

# 执行数据库迁移
./.venv/bin/python -c "import asyncio; from persistence.migration import run_migrations; asyncio.run(run_migrations())"

# 终端 1：启动 API
./.venv/bin/ai-team serve --host 127.0.0.1 --port 8000

# 终端 2：启动 RQ worker
./.venv/bin/python -m engine.tasks

# 健康检查应看到 database.reachable=true、queue.redis_reachable=true、queue.workers>=1
curl -fsS http://127.0.0.1:8000/health
```

前端：

```bash
cd web
npm install
npm run dev
```

默认访问 `http://127.0.0.1:5173/dashboard`。

验证：

```bash
# Python 测试
./.venv/bin/python -m pip install -e ".[dev]"
./.venv/bin/python -m pytest

# 前端测试与构建
cd web && npm run test && npm run build

# 前端构建
cd web && npm ci && npm run build

# 真实前后端浏览器 smoke（启动 FastAPI + Vite，不 mock API）
cd web && npm run smoke:real-backend

# 真实全栈浏览器 smoke
# 默认启动隔离的 Postgres + Redis/RQ + worker + FastAPI + Vite；需要 Docker CLI/Daemon。
cd web && npm run smoke:real-stack

# 无 Docker 的本机可显式复用一次性/非生产 Postgres 与 Redis；脚本会清理本次 smoke 的 run/project/Redis job 记录。
PLAYWRIGHT_REAL_STACK_DATABASE_URL=postgresql://ai_team:ai_team@127.0.0.1:5432/ai_team \
PLAYWRIGHT_REAL_STACK_REDIS_URL=redis://127.0.0.1:6379/0 \
  npm run smoke:real-stack
```

仓库卫生检查：

```bash
bash scripts/check_repo_hygiene.sh
```

Docker Compose：

```bash
docker compose build
docker compose up
```

## 技术栈

- 编排引擎：Python 3.11+ / Pydantic
- HTTP 服务：FastAPI / WebSocket
- 数据库：PostgreSQL 17（Phase 1 migration 已归档）
- 前端：React + TypeScript + Tailwind CSS
- 代码隔离：Git Worktree (per-run)
- 部署：Docker Compose

## 文档

- [需求规格说明书 v1.1](docs/spec_1.1.md)
- [已认可前端原型](docs/prototypes/ai-team-dashboard/index.html)
- [前端截图验收](docs/validation/README.md)
- [Roadmap](ROADMAP.md)
- [Changelog](CHANGELOG.md)
- [License](LICENSE)
- [v0.1.0 Release Notes](docs/releases/v0.1.0.md)
- [Public Issue Drafts for OSS Readiness](docs/roadmap/public-issue-drafts.md)
- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)

## 项目结构

```
ai-team-platform/
├── docs/                   # 文档
│   ├── spec_1.1.md         # 需求规格
│   └── prototypes/         # 前端原型基线
├── engine/                 # [Phase 0] 编排引擎
├── api/                    # [Phase 0] REST API + WebSocket
├── cli/                    # [Phase 0] 平台 CLI
├── templates/              # 平台内置 team/prompt 模板
├── adapters/               # 可选 skill adapter
├── persistence/            # [Phase 1] 持久化层
├── web/                    # [Phase 1] 前端
└── tests/                  # 核心引擎测试
```

## 分阶段计划

- **Phase 0**：质量优先 — Context Scanner / Worktree / Quality Gates / Prompt 增强 / 简单 API
- **Phase 1**：持久化 + 前端 — PostgreSQL / WebSocket / Dashboard
- **Phase 2**：高级能力 — 可视化编辑器 / CI/CD 集成 / Webhook / 模板库

## 许可证

本项目使用 [MIT License](LICENSE)。
