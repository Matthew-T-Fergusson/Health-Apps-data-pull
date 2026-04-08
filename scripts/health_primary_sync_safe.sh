#!/usr/bin/env bash
# Wrapper entrypoint used by cron and operators.
#
# Design rationale:
# - Keep one stable command for scheduled runs (reduces scheduler drift/misconfig).
# - Force orchestrator execution via repo-local virtualenv for reproducibility.
# - Route all primary domains through a single safety-hardened path.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PY="$WORKSPACE_DIR/.venv/bin/python3"
ORCH="$SCRIPT_DIR/garmin_primary_ingest_orchestrator.py"

exec "$PY" "$ORCH" --workspace "$WORKSPACE_DIR" --with-strava
