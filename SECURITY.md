# Security Policy

AI Team Platform includes a CLI, FastAPI service, WebSocket surface, dashboard, authentication-related code, project governance assets, worktree handling, and quality gates. Please report security issues responsibly.

## Supported versions

The project is currently pre-1.0. Security fixes are applied to the default branch and included in the next tagged release.

## Reporting a vulnerability

Please do not report suspected vulnerabilities in public issues with exploit details.

Preferred reporting path:

1. Use GitHub private vulnerability reporting for this repository if it is available.
2. If private reporting is unavailable, open a minimal public issue asking for a private security contact, without exploit details, secrets, payloads, or affected private systems.

Include as much safe detail as possible:

- Affected component, such as CLI, API, WebSocket, dashboard, persistence, worktree handling, quality gates, webhook delivery, or Harness governance.
- Reproduction steps using non-sensitive sample data.
- Expected and actual impact.
- Relevant commit, version, or deployment context.
- Whether the issue is already public or being actively exploited.

Do not send or attach production secrets, private repository contents, access tokens, database dumps, customer data, or local `.env` files.

## Security review areas

Security-sensitive changes include:

- Authentication, authorization, JWT, sessions, and admin endpoints.
- CORS, WebSocket access, webhook handling, and external callbacks.
- Secret storage, redaction, logging, and audit events.
- Database migrations and persistence semantics.
- Worktree creation, file access, shell command execution, and quality gate execution.
- Harness rules, skills, checks, baselines, and task memory acceptance.
- CI, release, Docker, and deployment configuration.

Changes in these areas should include focused tests and explicit validation notes.

## Disclosure process

After a report is received, maintainers will:

1. Confirm receipt when a private reporting channel is available.
2. Reproduce and assess impact.
3. Prepare a fix on a private or minimally disclosed path when appropriate.
4. Add regression coverage where practical.
5. Publish release notes or an advisory when the issue is fixed and disclosure is appropriate.

This repository does not yet claim a formal production SLA or incident response guarantee.
