# Contributing to AI Team Platform

Thank you for considering a contribution to AI Team Platform. This project is an open-source workflow engine, CLI, API, and dashboard for AI-assisted software delivery.

## Ways to contribute

- Report reproducible bugs.
- Improve documentation, setup instructions, and examples.
- Add tests for existing behavior.
- Propose focused enhancements to the workflow engine, CLI, API, dashboard, or governance layer.
- Help triage issues and review pull requests.

## Before opening an issue

Search existing issues and pull requests first. If you are reporting a bug, include:

- The command or UI flow you used.
- The expected behavior.
- The actual behavior.
- Relevant logs, screenshots, or failing test output.
- Your OS, Python version, Node.js version, and browser when relevant.

Do not include secrets, private repository contents, `.env` values, tokens, database dumps, or local run artifacts.

## Development setup

Install Python dependencies:

```bash
python3 -m pip install -e .
```

Install development dependencies:

```bash
./.venv/bin/python -m pip install -e ".[dev]"
```

Run the CLI:

```bash
ai-team run "implement a requirement" --project /path/to/project --yes
ai-team status --project /path/to/project
```

Start the API:

```bash
ai-team serve --host 127.0.0.1 --port 8000
```

Install and run the frontend:

```bash
cd web
npm install
npm run dev
```

## Validation

Run the checks that match your change.

Python:

```bash
./.venv/bin/python -m pytest
```

Frontend:

```bash
cd web && npm run test
cd web && npm run build
```

Repository hygiene:

```bash
bash scripts/check_repo_hygiene.sh
```

For changes that affect the real backend, database, Redis, RQ worker, or browser flows, run the relevant smoke command documented in `README.md`.

## Pull request expectations

- Keep the change focused and explain the motivation.
- Include tests or a clear reason tests are not applicable.
- Preserve existing project boundaries: `engine/`, `cli/`, `api/`, `persistence/`, `web/`, `templates/`, and `.ai/harness/**` have distinct responsibilities.
- Do not commit generated artifacts, local run output, virtual environments, caches, local databases, secrets, or `web/node_modules/`.
- Do not change public API behavior, authentication, permissions, database schema, release process, CI, Docker, or governance semantics without prior discussion.

## Governance boundaries

Harness Governance Layer assets live under `.ai/harness/**`. They may provide project rules, skills, checks, baselines, and task memory, but they must not bypass AGENTS instructions, platform safety policy, human gates, or quality gates.

Task Board accepted memory should only come from final accepted states. Failed QA, rejected reviews, cancelled runs, and draft experiments must not pollute accepted memory.
