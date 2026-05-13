# Deprecated Usage Check

This Harness check scans repository text against the versioned deprecated usage registry at `.ai/harness/checks/deprecated-usage-registry.json`.

The registry is the source of truth for deprecated API, pattern, module, and project-entry usage. The scanner runs through `scripts/verify_project_governance.py` so CI and Harness verification use the same evidence path.
