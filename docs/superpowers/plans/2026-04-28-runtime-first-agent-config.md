# Runtime First Agent Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make runtime (CLI tool) a first-class configurable abstraction and make agents reference it through `runtime_id`.

**Architecture:** Runtime config owns command execution details such as `cli`, `args`, `prompt_mode`, `default_model`, and mock response. Agent config owns role, prompt, model choices, and `runtime_id`; pipeline stages still reference agents by name. Legacy `providers` and `agents[].provider` are accepted only while loading old config and are normalized into the new shape.

**Tech Stack:** Python 3.11, Pydantic, FastAPI, PyYAML, React 18, Vite, TypeScript.

---

### Task 1: Backend Runtime Config And Runner

**Files:**
- Create: `engine/runtimes.py`
- Modify: `engine/config.py`
- Modify: `engine/models.py`
- Modify: `engine/agent_runner.py`
- Modify: `engine/orchestrator.py`
- Modify: `engine/logging_config.py`
- Modify: `templates/team.yaml`
- Test: `tests/test_config.py`
- Test: `tests/test_agent_runner.py`
- Test: `tests/test_provider_models.py`
- Test: `tests/test_engine.py`

- [x] Write failing tests for `runtimes` normalization, legacy `providers` migration, invalid runtime references, and command building from runtime config.
- [x] Run the focused tests and confirm they fail because `runtimes` and `runtime_id` do not exist.
- [x] Implement `engine/runtimes.py` with runtime normalization, `runtime_config()`, availability, auto CLI resolution, and command building.
- [x] Update models and execution chain to use `runtime_id` and `runtime_cli`.
- [x] Replace the platform template with `runtimes` and `agents[].runtime_id`.
- [x] Run focused backend tests and confirm they pass.

### Task 2: API Settings And Validation

**Files:**
- Modify: `api/routes/settings.py`
- Modify: `api/routes/config.py`
- Modify: `tests/test_routes.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_auth.py`

- [x] Write failing route tests for `/api/settings` returning `runtimes`, `/api/config/runtimes`, rejecting invalid runtime references, and old config normalization.
- [x] Run focused route tests and confirm they fail.
- [x] Add `runtimes` to settings schema and structured response, remove `providers` from new writes, and validate cross references.
- [x] Replace `/api/config/providers` with `/api/config/runtimes`.
- [x] Update route fixtures to new config syntax.
- [x] Run focused route tests and confirm they pass.

### Task 3: Persistence Runtime Fields

**Files:**
- Modify: `persistence/models.py`
- Modify: `persistence/repository.py`
- Modify: `persistence/migrations/001_init.up.sql`
- No change needed: `persistence/migrations/001_init.down.sql` drops the table set wholesale.
- Create: `persistence/migrations/006_agent_runtime_fields.up.sql`
- Create: `persistence/migrations/006_agent_runtime_fields.down.sql`
- Test: `tests/test_persistence.py`

- [x] Write failing persistence tests for `runtime_id` and `runtime_cli` on agent runs.
- [x] Run focused persistence tests and confirm they fail.
- [x] Replace `provider` persistence fields with `runtime_id` and `runtime_cli`.
- [x] Add migration for existing development databases.
- [x] Run focused persistence tests and confirm they pass.

### Task 4: Frontend Runtime And Agent Settings

**Files:**
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/lib/pipelineSchema.ts`
- Modify: `web/src/pages/Settings.tsx`
- Modify: `web/src/pages/PipelineEditor.tsx`
- Modify: `web/src/pages/Pipelines.tsx`
- Modify: `web/src/components/PipelineTimeline.tsx`
- Modify: `web/src/components/flow/AgentNode.tsx`
- Modify: `web/src/styles.css`

- [x] Define typed `RuntimeConfig`, `AgentConfig`, and `SettingsConfig`.
- [x] Build editable Settings sections for runtimes and agents; runtime rows edit CLI details, agent rows select `runtime_id`.
- [x] Update pipeline editor and run timeline labels from provider to runtime.
- [x] Ensure save sends complete sections and does not round-trip masked secrets into runtime env.
- [x] Run `cd web && npm run build` and confirm it passes.

### Task 5: Integration Verification And Review

**Files:**
- Review all changed files.

- [x] Run `python3 -m unittest discover -s tests -v`.
- [x] Run `python3 -m pytest tests/test_persistence.py -q`.
- [x] Run `cd web && npm run build`.
- [x] Run `git diff --check`.
- [x] Review the diff for leftover runtime/provider ambiguity, especially `agents[].provider`, `providers`, and provider-config naming outside webhook/CI domains where provider still means GitHub/GitLab.
- [x] Confirm acceptance: runtime is first-class, agents select by `runtime_id`, old config only loads through migration, new UI/API/template write new shape.
