# Portfolio Maturity Roadmap

Purpose: keep shipping real systems while steadily adding the “professional polish” signals employers/clients expect.

## Guiding principle
**Build first, polish in layers.**
Each repo should evolve from:
1) working prototype
2) reliable system
3) portfolio-grade engineering asset

---

## Phase 1 — While Actively Building (now)
Focus on output and learning speed.

### Required minimum per repo
- Clear `README` with problem statement + current scope
- `RUNBOOK` with setup/run/debug basics
- `.env.example` and hardened `.gitignore`
- `CHANGELOG` entries for meaningful changes
- Decision-log headers in key scripts explaining important tradeoffs

### For furniture sourcing expansion (Craigslist / AptDeco / Chairish)
Add these docs early (lightweight):
- `docs/SOURCE_COVERAGE.md`
  - Which sources are integrated
  - What fields are captured from each
  - Known blockers/rate limits per source
- `docs/PRICING_LOGIC.md`
  - How comps/price guidance is generated
  - Confidence levels + fallback behavior
- `docs/LEAD_SCORING.md`
  - How sourcing leads are prioritized
  - Filters and ranking criteria

---

## Phase 2 — Professional Reliability Signals
Add once core workflows are stable.

- Test harness:
  - unit tests for parsing/scoring
  - regression tests for edge cases
- CI pipeline (GitHub Actions):
  - lint + tests on PR
  - basic smoke check for scripts
- Data contracts:
  - schema definitions + migration notes
- Error taxonomy:
  - classify retriable vs fatal failures
  - explicit operator actions for each class

---

## Phase 3 — Portfolio/Client Credibility Layer
Add as repos mature and you want showcase quality.

- Architecture diagram (`docs/ARCHITECTURE.md` + visual)
- ADRs (`docs/adr/`) for major design choices
- Releases + tags + release notes
- PR template with validation evidence requirements
- Security checks:
  - secret scanning
  - dependency vulnerability checks

---

## Reusable standards across all repos
Use the same baseline everywhere to show professional consistency.

### Repo baseline checklist
- [ ] README explains business value and current maturity level
- [ ] Setup works from clean machine
- [ ] Runbook exists and is accurate
- [ ] Changelog updated
- [ ] Decision rationale documented in code/docs
- [ ] No credentials or local machine references leaked
- [ ] At least one validation artifact proving behavior

---

## Suggested weekly cadence (low overhead)
- **Mon–Thu:** build features and close functional gaps
- **Fri (30–60 min):** polish pass
  - update docs/changelog
  - add tests for bugs fixed that week
  - capture one architecture/decision improvement

This creates visible growth over time without slowing shipping.

---

## Positioning for employers/clients
When presenting a repo, emphasize:
1. What business/system problem it solves
2. How reliability is enforced
3. How decisions evolved (with evidence)
4. What you would improve next (professional honesty)

That narrative demonstrates engineering maturity, not just coding output.
