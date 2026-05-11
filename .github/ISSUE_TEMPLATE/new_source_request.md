---
name: New data source request
description: Propose adding a new health/fitness/nutrition data source
title: "New source: "
labels: ["new-source", "health-pipeline"]
---

## Source overview

- Source name:
- Access method/API/export:
- Auth/credential model:
- Official API or community/unsupported endpoint?

## Data to ingest

List fields/entities we should store:

- 

## Consent and privacy

- What personal data is pulled?
- What should be stored raw vs curated?
- How can collection be disabled?
- What would source revocation/purge need to remove?

## Schema proposal

- Raw table(s):
- Curated table/view(s):
- Sync state source name:
- Metrics to emit:

## QA and recovery

- What user-facing completeness checks matter?
- What failure modes should quarantine rather than block?
- What backfill/retry behavior is needed?

## Validation plan

- [ ] Unit/helper tests
- [ ] Isolated Postgres integration/bootstrap validation
- [ ] RUNBOOK docs
- [ ] CONSENT.md update
