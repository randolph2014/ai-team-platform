# Changelog

All notable public-facing changes to AI Team Platform will be tracked here.

This project is currently pre-1.0. Public API boundaries, operational workflows, and governance assets may still evolve.

## Unreleased

### Added

- Contribution guide for issue reports, development setup, validation, PR expectations, and governance boundaries.
- Security policy for vulnerability reporting, supported versions, security-sensitive change areas, and disclosure process.
- GitHub issue templates for bugs, feature requests, and public security hardening work.
- GitHub pull request template with affected areas, validation, risk notes, and maintainer checklist.
- Draft `v0.1.0` release notes.
- Public OSS readiness issue drafts for roadmap, quickstart, security hardening, architecture documentation, and Codex integration.
- Public roadmap for v0.1.x OSS readiness and future platform candidates.
- MIT license.

### Changed

- README documentation index now links to OSS readiness and maintainer workflow documents.

## 0.1.0 - Draft

### Planned release scope

- Workflow engine for agent-based delivery pipelines.
- CLI entrypoint through `ai-team run`, `ai-team status`, `ai-team serve`, `ai-team cleanup`, and `ai-team install-skill`.
- FastAPI REST and WebSocket service for run state and dashboard integration.
- React, TypeScript, Tailwind, and Vite dashboard.
- Per-run Git worktree isolation.
- Context Scanner support for project instruction files.
- Quality gates and report artifacts for delivery verification.
- PostgreSQL persistence, Redis/RQ worker support, and Docker Compose setup.
- Harness Governance Layer for project rules, skills, checks, baselines, and task memory.

### Known gaps

- The `v0.1.0` GitHub Release is not published yet.
- Public adoption signals are early: issue triage, PR review, and release workflows are still being established.
