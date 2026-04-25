---
name: ai-team
description: "AI Team Platform 兼容入口：把 Agent 会话里的 ai-team 请求转发到平台 CLI/API，不承载核心编排实现。"
---

# AI Team Platform Adapter

这是 `ai-team` skill 的兼容适配层。核心 runner、workflow engine、quality gates、worktree、API 都在平台仓库中维护。

## 使用方式

```bash
python3 scripts/run.py "实现一个需求" --workdir /path/to/project
python3 scripts/run.py --spec-file docs/spec.md --workdir /path/to/project --production
python3 scripts/health-check.py
```

如果需要更新 adapter，请在平台仓库运行：

```bash
ai-team install-skill --target ~/.agents/skills/ai-team --force
```

不要在安装目录内新增核心编排逻辑。
