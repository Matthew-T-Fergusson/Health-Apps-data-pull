---
name: Data quality failure
description: Report missing, stale, conflicting, or suspicious health data
title: "Data quality: "
labels: ["data-quality", "health-pipeline"]
---

## What looks wrong?

- Source/system:
- Date range affected:
- User-facing metric(s):
- Expected value/behavior:
- Actual value/behavior:

## Evidence

Paste relevant query output, QA artifact snippet, screenshot, or log summary.

```text

```

## Severity

- [ ] Critical: core metrics missing or misleading
- [ ] Warning: partial/null-rate/schema drift concern
- [ ] Info: suspicious but not blocking

## Suggested handling

- [ ] Backfill
- [ ] Quarantine
- [ ] Merge/resolve conflict
- [ ] Parser/source fix
- [ ] Documentation only

## Validation after fix

- [ ] `make test`
- [ ] `make test-integration`
- [ ] QA output reviewed
- [ ] Relevant SQL/readback checked
