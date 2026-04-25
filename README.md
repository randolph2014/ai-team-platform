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

```bash
# 安装平台依赖（Python 3.11+）
python3 -m pip install -e .

# 运行 pipeline
ai-team run "实现一个需求" --project /path/to/project --yes

# 从 spec 文件读取需求
ai-team run --spec-file docs/spec.md --project /path/to/project --yes

# 查看状态
ai-team status --project /path/to/project

# 启动 API
ai-team serve --host 127.0.0.1 --port 8000
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
python3 -m unittest discover -s tests -v
cd web && npm run build
```

Docker Compose：

```bash
docker compose up --build
```

## 技术栈

- 编排引擎：Python 3.11+ / Pydantic
- HTTP 服务：FastAPI / WebSocket
- 数据库：PostgreSQL 17（Phase 1 migration 已归档）
- 前端：React + TypeScript + Tailwind CSS
- 代码隔离：Git Worktree (per-run)
- 部署：Docker Compose

## 文档

- [需求规格说明书 v2.1](docs/spec.md)
- [已认可前端原型](docs/prototypes/ai-team-dashboard/index.html)
- [前端截图验收](docs/validation/README.md)

## 项目结构

```
ai-team-platform/
├── docs/                   # 文档
│   ├── spec.md             # 需求规格
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
