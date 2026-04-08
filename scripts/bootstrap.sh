#!/usr/bin/env bash
# Decision log (why this bootstrap exists)
# - Decision: one quick setup path (venv + requirements).
#   Why: reduce onboarding friction and setup variance.
# - Decision: keep credential wiring separate from package install.
#   Why: safer defaults for public repo usage and sharing.
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
