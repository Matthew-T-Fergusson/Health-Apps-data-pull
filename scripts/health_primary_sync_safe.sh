#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PY="$WORKSPACE_DIR/.venv/bin/python3"
ORCH="$SCRIPT_DIR/garmin_primary_ingest_orchestrator.py"

exec "$PY" "$ORCH" --workspace "$WORKSPACE_DIR" --with-strava
