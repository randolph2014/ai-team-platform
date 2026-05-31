# AI Team Platform Roadmap

AI Team Platform is a pre-1.0 open-source workflow engine, CLI, API, and dashboard for AI-assisted software delivery. This roadmap separates near-term OSS readiness from future platform capabilities.

## Current focus: v0.1.x OSS readiness

The v0.1.x line focuses on making the repository easier to inspect, run, contribute to, and maintain publicly.

- Publish the first `v0.1.0` GitHub Release after maintainer approval.
- Maintain MIT license metadata and release documentation.
- Keep `CONTRIBUTING.md`, `SECURITY.md`, issue templates, PR templates, release notes, and public issue drafts up to date.
- Improve quickstart verification paths for new contributors.
- Document architecture and ownership boundaries for engine, CLI, API, persistence, web, templates, and Harness governance.
- Track security hardening tasks for authentication, authorization, JWT, CORS, WebSocket, admin/API routes, worktree access, command execution, and governance assets.
- Design the first Codex-assisted maintainer workflow for issue-to-implementation, PR review, quality-gate repair, test generation, security review, and release-note generation.

## Stable project boundaries

- `engine/` owns workflow orchestration, agent execution, context scanning, worktree handling, quality gates, and report artifacts.
- `cli/` owns the `ai-team` command surface.
- `api/` owns FastAPI REST, WebSocket, authentication, runtime state, and route boundaries.
- `persistence/` owns database access and migrations.
- `web/` owns the React, TypeScript, Tailwind, and Vite dashboard.
- `templates/` owns platform default team, pipeline, agent prompt, and quality gate templates.
- `.ai/harness/**` owns project-level rules, skills, checks, baselines, and task memory.

Harness governance assets must not bypass AGENTS instructions, platform safety policy, human gates, or quality gates. DB-backed Settings are runtime configuration, not the source of truth for Harness governance.

## Planned v0.1.x public issues

The first public issue set is drafted in `docs/roadmap/public-issue-drafts.md`:

1. Roadmap: v0.1.x OSS readiness.
2. Good first issue: improve quickstart verification path.
3. Security hardening: document and test auth-sensitive API boundaries.
4. Documentation: add architecture overview for contributors.
5. Codex integration: maintainer automation workflow design.

## Future candidates

These items are not committed release scope yet:

- Visual pipeline editor.
- CI/CD and webhook integrations.
- Template library.
- Richer project workspace experience in the dashboard.
- Broader release readiness automation.
- More complete maintainer automation around issue triage, PR review, and release management.

## Validation policy

Changes should run the checks that match their risk:

```bash
./.venv/bin/python -m pytest
cd web && npm run test
cd web && npm run build
bash scripts/check_repo_hygiene.sh
```

Real backend, DB, Redis, RQ, and browser-flow changes should use the relevant smoke commands documented in `README.md`.
