# Backup, Restore, and Rollback Runbook

This runbook is the release safety baseline for AI Team Platform production.

## Scope

- PostgreSQL state: pipelines, runs, stages, gates, events, decisions, costs, webhooks, and audit logs.
- Runtime artifacts: `.ai/team-output` or the value of `AI_TEAM_OUTPUT_DIR`.
- Configuration: `.ai/team.yaml`, deployment environment variables, Docker image tag, and release commit SHA.

## Backup Before Release

1. Record the release input:

   ```bash
   git rev-parse HEAD
   docker image inspect ai-team-api:<tag> --format '{{.Id}}'
   ```

2. Back up PostgreSQL:

   ```bash
   pg_dump "$DATABASE_URL" --format=custom --file "backups/ai-team-$(date -u +%Y%m%dT%H%M%SZ).dump"
   ```

3. Back up runtime artifacts:

   ```bash
   tar -czf "backups/team-output-$(date -u +%Y%m%dT%H%M%SZ).tar.gz" "${AI_TEAM_OUTPUT_DIR:-.ai/team-output}"
   ```

4. Back up runtime config without printing secrets:

   ```bash
   cp .ai/team.yaml "backups/team-$(date -u +%Y%m%dT%H%M%SZ).yaml"
   env | grep '^AI_TEAM_' | sed -E 's/(SECRET|TOKEN|KEY|PASSWORD)=.*/\1=***REDACTED***/' > "backups/env-redacted.txt"
   ```

## Restore

1. Stop API and worker processes so no new run writes race with restore.
2. Restore PostgreSQL into the target database:

   ```bash
   pg_restore --clean --if-exists --dbname "$DATABASE_URL" backups/ai-team-<timestamp>.dump
   ```

3. Restore runtime artifacts:

   ```bash
   rm -rf "${AI_TEAM_OUTPUT_DIR:-.ai/team-output}"
   mkdir -p "${AI_TEAM_OUTPUT_DIR:-.ai/team-output}"
   tar -xzf backups/team-output-<timestamp>.tar.gz -C /
   ```

4. Restart API and worker processes, then verify:

   ```bash
   python -m compileall engine api cli persistence
   python -m pytest tests/test_run_lifecycle.py tests/test_persistence.py tests/test_routes.py
   curl -fsS http://127.0.0.1:8000/health
   ```

## Rollback

1. Prefer image rollback when the previous release image is available:

   ```bash
   docker ps --filter "name=^/ai-team-api$"
   docker stop ai-team-api
   docker rm ai-team-api
   docker run --name ai-team-api --env-file .env.production ai-team-api:<previous-tag>
   ```

2. If the release already changed database schema, restore the matching pre-release database backup before restarting the older image.
3. If rollback is for a single PR, use a revert commit instead of force-pushing:

   ```bash
   git revert <merge-commit>
   ```

4. Confirm rollback:

   ```bash
   curl -fsS http://127.0.0.1:8000/health
   python -m pytest tests/test_auth.py tests/test_run_lifecycle.py tests/test_metrics.py
   ```

## Stop Conditions

- Do not proceed if `pg_dump` or artifact backup fails.
- Do not proceed if `release-readiness.json` is missing for the release Run.
- Do not proceed if production guard fails.
- Do not proceed if CI reports dependency audit, secret scan, Docker build, backend tests, or frontend checks as failed.
