#!/usr/bin/env bash
# Minimal reproducible setup helper.
#
# Design rationale:
# - New contributors/operators should reach a runnable state quickly.
# - Keeps setup deterministic (local venv + requirements) before env/credential wiring.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "Bootstrap complete."
echo "Next: copy .env.example to .env and set credentials, then run scripts/health_primary_sync_safe.sh"
