#!/usr/bin/env python3
import json
import os
from pathlib import Path

WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", Path(__file__).resolve().parents[1]))

paths = [
    WORKSPACE_DIR / 'output/garmin_primary_ingest_orchestrator_last_run.json',
    WORKSPACE_DIR / 'output/health_qa_daily_latest.json',
    WORKSPACE_DIR / 'output/garmin/lockout_state.json',
]

out = {}
for p in paths:
    if p.exists():
        try:
            out[str(p)] = json.loads(p.read_text())
        except Exception as e:
            out[str(p)] = {'error': str(e)}
    else:
        out[str(p)] = {'missing': True}

print(json.dumps(out, indent=2))
