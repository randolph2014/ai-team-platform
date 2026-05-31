# Public Issue Drafts for OSS Readiness

These drafts prepare the first public issue set for AI Team Platform. They are not public GitHub issues until a maintainer creates them in `randolph2014/ai-team-platform`.

## 1. Roadmap: v0.1.x OSS readiness

Suggested labels: `roadmap`, `enhancement`, `needs-triage`

```markdown
## Problem

AI Team Platform is public and pre-1.0. The project needs a visible v0.1.x roadmap so contributors and users can understand what is stable, what is being hardened, and where help is useful.

## Proposed outcome

Create and maintain a public roadmap covering:

- v0.1.0 release readiness
- CLI and workflow engine stabilization
- API and WebSocket hardening
- dashboard usability
- Harness governance boundaries
- Codex-assisted maintainer workflows

## Acceptance criteria

- [ ] README links to the active roadmap or milestone.
- [ ] The roadmap separates committed scope from future ideas.
- [ ] Each roadmap item points to an issue, spec, or validation artifact when available.
- [ ] Pre-1.0 limitations are stated clearly.

## Validation plan

```bash
bash scripts/check_repo_hygiene.sh
```
```

## 2. Good first issue: improve quickstart verification path

Suggested labels: `good first issue`, `documentation`, `needs-triage`

```markdown
## Problem

The README documents setup, CLI usage, API startup, frontend startup, tests, smoke checks, and Docker Compose. New contributors would benefit from a shorter "first successful local check" path.

## Proposed outcome

Add a concise quickstart verification section that helps a new contributor prove the repository works locally before running the heavier full-stack checks.

## Acceptance criteria

- [ ] The README includes a short first-check path for Python-only setup.
- [ ] The README includes a short first-check path for frontend setup.
- [ ] The section explains when to use full pytest, frontend build, real-backend smoke, and real-stack smoke.
- [ ] The text does not introduce commands that are unsupported by the repository.

## Validation plan

```bash
bash scripts/check_repo_hygiene.sh
```
```

## 3. Security hardening: document and test auth-sensitive API boundaries

Suggested labels: `security`, `hardening`, `api`, `needs-triage`

```markdown
## Scope

Strengthen documentation and regression coverage around auth-sensitive API boundaries, especially admin routes, JWT handling, CORS, WebSocket access, and production guards.

## Expected improvement

Reduce the risk that future API changes accidentally weaken authentication, authorization, or production safety behavior.

## Acceptance criteria

- [ ] Identify auth-sensitive routes and production guards in current code.
- [ ] Add or update focused route tests for the highest-risk boundaries.
- [ ] Document validation commands in the PR.
- [ ] Avoid publishing exploit details or secrets.

## Validation plan

```bash
./.venv/bin/python -m pytest tests/test_routes.py tests/test_harness_routes.py
bash scripts/check_repo_hygiene.sh
```
```

## 4. Documentation: add architecture overview for contributors

Suggested labels: `documentation`, `architecture`, `needs-triage`

```markdown
## Problem

AI Team Platform spans engine, CLI, API, persistence, dashboard, templates, and Harness governance. Contributors need a short architecture overview that explains ownership boundaries before they change code.

## Proposed outcome

Add a contributor-facing architecture document that summarizes:

- workflow engine responsibilities
- CLI responsibilities
- API and WebSocket responsibilities
- persistence and migration boundaries
- dashboard responsibilities
- template and Harness governance boundaries
- validation commands by change type

## Acceptance criteria

- [ ] The architecture document links to README and AGENTS.md.
- [ ] It does not redefine Harness as a DB-backed configuration source.
- [ ] It distinguishes default templates, run-time settings, and project governance assets.
- [ ] README links to the new document.

## Validation plan

```bash
bash scripts/check_repo_hygiene.sh
```
```

## 5. Codex integration: maintainer automation workflow design

Suggested labels: `codex`, `maintainer-workflow`, `enhancement`, `needs-triage`

```markdown
## Problem

AI Team Platform is a workflow engine for AI-assisted software delivery. Codex can improve maintainer workflows, but the integration should be scoped and verifiable rather than a broad automation claim.

## Proposed outcome

Design a Codex-assisted maintainer workflow for issue-to-implementation, PR review, quality-gate repair, test generation, security review, and release-note generation.

## Acceptance criteria

- [ ] Define the first Codex-assisted workflow in a design document or issue comment.
- [ ] List required inputs, outputs, human gates, and quality gates.
- [ ] Include security boundaries for repository access, secrets, and command execution.
- [ ] Identify the first implementation slice and its validation commands.

## Validation plan

```bash
bash scripts/check_repo_hygiene.sh
```
```
