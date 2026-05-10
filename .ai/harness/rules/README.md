# Harness Rules

Rules are project-level engineering constraints. They are stable enough to be referenced by plans, reviews, and acceptance evidence.

## Naming

- Use lowercase dotted IDs: `governance.scope.phase-boundary`.
- Prefix IDs by concern: `governance`, `api`, `security`, `quality`, `delivery`.
- Do not encode one-off task names in rule IDs.

## Required Metadata

Each rule document starts with front matter:

```yaml
id: governance.example
title: Short Title
type: rule
severity: error
status: active
```

`severity: error` means a violation blocks completion. `severity: warning` must still be visible in reports and reviews.
