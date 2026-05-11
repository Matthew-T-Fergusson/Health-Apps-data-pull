#!/usr/bin/env bash
set -euo pipefail

WORKDIR="${WORKSPACE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
OUTDIR="$WORKDIR/data/apple_health/inbox"
mkdir -p "$OUTDIR"

QUERY='subject:"iphone health data" has:attachment newer_than:30d'

# Get newest matching message
MSG_JSON=$(gog gmail messages search "$QUERY" --max 1 --json --results-only)
MSG_ID=$(python3 - <<'PY' "$MSG_JSON"
import json,sys
arr=json.loads(sys.argv[1])
print(arr[0]["id"] if arr else "")
PY
)

if [[ -z "$MSG_ID" ]]; then
  echo "NO_MATCHING_EMAIL"
  exit 0
fi

ATT_JSON=$(gog gmail get "$MSG_ID" --json --results-only)
read -r ATT_ID ATT_NAME <<<"$(python3 - <<'PY' "$ATT_JSON"
import json,sys
arr=json.loads(sys.argv[1])
zip_att=[a for a in arr if a.get('filename','').lower().endswith('.zip')]
if not zip_att:
    print(' ')
else:
    a=zip_att[0]
    print(a.get('attachmentId',''), a.get('filename','apple_health_export.zip'))
PY
)"

if [[ -z "${ATT_ID:-}" ]]; then
  echo "NO_ZIP_ATTACHMENT"
  exit 1
fi

DEST="$OUTDIR/${MSG_ID}_${ATT_NAME}"
if [[ ! -f "$DEST" ]]; then
  gog gmail attachment "$MSG_ID" "$ATT_ID" --out "$OUTDIR" --name "${MSG_ID}_${ATT_NAME}" >/dev/null
  echo "DOWNLOADED:$DEST"
else
  echo "ALREADY_DOWNLOADED:$DEST"
fi

python3 "$WORKDIR/scripts/apple_health_phase1_import.py" --zip "$DEST"
