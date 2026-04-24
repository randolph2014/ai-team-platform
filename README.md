# AI Team Platform

> 说一个需求，交付一个可上线的版本。

将 ai-team 从 CLI 工具演进为平台：核心是编排引擎，前端是自建轻量面板，不依赖任何第三方平台。

## 技术栈

- 编排引擎：Python 3.11+ / FastAPI
- 数据库：PostgreSQL 17
- 前端：React + Tailwind CSS + shadcn/ui
- 实时通信：WebSocket
- 代码隔离：Git Worktree (per-run)
- 部署：Docker Compose

## 文档

- [需求规格说明书 v2.0](docs/spec.md)

## 项目结构

```
ai-team-platform/
├── docs/                   # 文档
│   └── spec.md             # 需求规格
├── engine/                 # [Phase 0] 编排引擎
├── api/                    # [Phase 0] REST API + WebSocket
├── persistence/            # [Phase 1] 持久化层
├── web/                    # [Phase 1] 前端
└── docker/                 # [Phase 1] Docker Compose
```

## 分阶段计划

- **Phase 0**：质量优先 — Context Scanner / Worktree / Quality Gates / Prompt 增强 / 简单 API
- **Phase 1**：持久化 + 前端 — PostgreSQL / WebSocket / Dashboard
- **Phase 2**：高级能力 — 可视化编辑器 / CI/CD 集成 / Webhook / 模板库
