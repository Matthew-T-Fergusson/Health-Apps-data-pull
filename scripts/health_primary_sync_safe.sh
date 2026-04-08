#!/usr/bin/env bash
# Decision log (why this wrapper exists)
# - Decision: expose one stable command for cron + operators.
#   Why: prevents scheduler drift and command mismatch across environments.
# - Decision: execute via repo-local virtualenv.
#   Why: reproducible dependency/runtime behavior.
# - Decision: always route through orchestrator.
#   Why: preserves safety controls, lockout handling, and consistent artifacts.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PY="$WORKSPACE_DIR/.venv/bin/python3"
ORCH="$SCRIPT_DIR/garmin_primary_ingest_orchestrator.py"

exec "$PY" "$ORCH" --workspace "$WORKSPACE_DIR" --with-strava
