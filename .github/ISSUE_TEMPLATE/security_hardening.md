---
name: Security hardening
about: Track non-sensitive security hardening work
title: "[Security hardening]: "
labels: security, hardening, needs-triage
assignees: ""
---

## Scope

<!-- Describe the hardening task without exploit details. Use SECURITY.md for vulnerability reporting guidance. -->

## Affected surface

Select all that apply:

- [ ] Authentication or authorization
- [ ] JWT or session handling
- [ ] CORS or WebSocket access
- [ ] Admin or API routes
- [ ] Secret storage or redaction
- [ ] Worktree or filesystem access
- [ ] Command execution or quality gates
- [ ] Webhooks or external callbacks
- [ ] Harness governance
- [ ] CI, release, Docker, or deployment

## Expected improvement

<!-- What risk is reduced? -->

## Validation plan

```bash
# Example:
# ./.venv/bin/python -m pytest tests/test_routes.py tests/test_harness_routes.py
# bash scripts/check_repo_hygiene.sh
```

## Disclosure note

Do not include active exploit details, production secrets, tokens, private repository contents, database dumps, or customer data in this public issue.
