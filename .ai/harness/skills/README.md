# Harness Skills

Skills describe reusable project methods. They are not authority layers and must not override AGENTS.md, platform policy, human gates, or quality gates.

## Naming

- Use lowercase dotted IDs or lowercase hyphenated IDs: `governance.phase-scoped-implementation`.
- Keep one skill focused on one repeatable method.
- Do not put temporary task instructions in skill files.

## Required Metadata

Each skill file must declare:

```yaml
id: governance.example
title: Short Title
type: skill
status: active
allowed_agents:
  - planner
  - coder
forbidden_capabilities:
  - bypass_human_gate
  - bypass_quality_gate
```

The same `allowed_agents` and `forbidden_capabilities` must be reflected in `.ai/harness.yaml` so the Harness loader can validate the metadata.
