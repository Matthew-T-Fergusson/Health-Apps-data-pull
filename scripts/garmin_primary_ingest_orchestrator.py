#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from garminconnect import Garmin


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _utc_now()).isoformat()


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        if '=' in line and not line.strip().startswith('#'):
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")


def _is_rl(msg: str) -> bool:
    t = (msg or '').lower()
    return '429' in t or 'too many requests' in t or 'rate limit' in t or 'rate-limit' in t


def _summary(stderr: str) -> str:
    rows = [r.strip() for r in (stderr or '').splitlines() if r.strip()]
    return (rows[-1] if rows else 'none emitted')[:500]


@dataclass
class Step:
    name: str
    status: str
    exit: int
    stderr_summary: str
    started_at: str
    ended_at: str


def main() -> int:
    ap = argparse.ArgumentParser(description='Single-run Garmin+Strava ingest orchestrator')
    ap.add_argument('--workspace', default=os.getenv('WORKSPACE_DIR', str(Path(__file__).resolve().parents[1])))
    ap.add_argument('--env-file', default=os.getenv('ENV_PATH', ''))
    ap.add_argument('--with-strava', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--cooldown-seconds', type=int, default=int(os.getenv('GARMIN_LOCKOUT_COOLDOWN_SECONDS', '43200')))
    args = ap.parse_args()

    workspace = Path(args.workspace).resolve()
    env_file = Path(args.env_file).resolve() if args.env_file else (workspace.parent / '.env')
    _load_env(env_file)

    # DB preflight: fail fast with remediation guidance.
    db_cli = workspace / 'scripts' / 'db_cli.py'
    pre = subprocess.run([str(workspace / '.venv' / 'bin' / 'python3'), str(db_cli), 'validate'], cwd=str(workspace), capture_output=True, text=True)
    if pre.returncode != 0:
        print(pre.stdout.strip())
        if pre.stderr.strip():
            print(pre.stderr.strip())
        print('Preflight failed. Remediation: run `python3 scripts/db_cli.py bootstrap` then `python3 scripts/db_cli.py migrate`.')
        return 3

    run_id = str(uuid.uuid4())
    output_dir = workspace / 'output'
    output_dir.mkdir(parents=True, exist_ok=True)

    tokenstore_dir = Path(os.getenv('GARMIN_TOKENSTORE_DIR', str(output_dir / 'garmin' / 'tokenstore')))
    lockout_path = Path(os.getenv('GARMIN_LOCKOUT_STATE_PATH', str(output_dir / 'garmin' / 'lockout_state.json')))
    artifact_path = output_dir / 'garmin_primary_ingest_orchestrator_last_run.json'
    compat_artifact_path = output_dir / 'health_primary_sync_last_run.json'

    scripts_dir = workspace / 'scripts'
    py = str(workspace / '.venv' / 'bin' / 'python3')

    steps: list[Step] = []
    auth_429_count = 0
    started_at = _iso()

    def read_lockout() -> dict:
        if not lockout_path.exists():
            return {}
        try:
            return json.loads(lockout_path.read_text())
        except Exception:
            return {}

    def write_lockout(active: bool, reason: str = '', cooldown: int = 0) -> dict:
        lockout_path.parent.mkdir(parents=True, exist_ok=True)
        nxt = _utc_now() + timedelta(seconds=cooldown) if active else None
        obj = {
            'active': active,
            'reason': reason,
            'updated_at': _iso(),
            'next_allowed_attempt_at': _iso(nxt) if nxt else None,
        }
        lockout_path.write_text(json.dumps(obj, indent=2))
        return obj

    def lockout_active(obj: dict) -> bool:
        if not obj.get('active'):
            return False
        nxt = obj.get('next_allowed_attempt_at')
        if not nxt:
            return False
        try:
            return _utc_now() < datetime.fromisoformat(nxt)
        except Exception:
            return False

    def run_script(name: str, script: str) -> Step:
        st = _iso()
        if args.dry_run:
            return Step(name, 'DRY_RUN', 0, 'dry run', st, _iso())
        env = os.environ.copy()
        env['GARMIN_TOKENSTORE'] = str(tokenstore_dir)
        env['GARMIN_DISABLE_FALLBACK_LOGIN'] = '1'
        env['INGEST_RUN_ID'] = run_id
        p = subprocess.run([py, script], cwd=str(workspace), env=env, capture_output=True, text=True)
        status = 'OK' if p.returncode == 0 else 'FAIL'
        return Step(name, status, int(p.returncode), _summary(p.stderr), st, _iso())

    lockout = read_lockout()

    if args.with_strava:
        steps.append(run_script('strava_daily_sync.py', str(scripts_dir / 'strava_daily_sync.py')))

    if lockout_active(lockout):
        steps.append(Step('garmin_auth_bootstrap', 'SKIP_LOCKOUT', 0, f"lockout active until {lockout.get('next_allowed_attempt_at')}", _iso(), _iso()))
        steps.append(run_script('health_qa_daily.py', str(scripts_dir / 'health_qa_daily.py')))
    else:
        st = _iso()
        if args.dry_run:
            auth = Step('garmin_auth_bootstrap', 'DRY_RUN', 0, 'dry run', st, _iso())
            lockout = read_lockout()
        else:
            email = os.getenv('GARMIN_EMAIL')
            password = os.getenv('GARMIN_PASSWORD')
            if not email or not password:
                auth = Step('garmin_auth_bootstrap', 'FAIL', 1, 'missing GARMIN_EMAIL/GARMIN_PASSWORD', st, _iso())
            else:
                tokenstore_dir.mkdir(parents=True, exist_ok=True)
                g = Garmin(email=email, password=password)
                try:
                    try:
                        g.login(tokenstore=str(tokenstore_dir))
                        lockout = write_lockout(False, 'tokenstore login ok', 0)
                        auth = Step('garmin_auth_bootstrap', 'OK', 0, 'tokenstore login ok', st, _iso())
                    except FileNotFoundError:
                        g.login()
                        g.garth.dump(str(tokenstore_dir))
                        lockout = write_lockout(False, 'seeded tokenstore', 0)
                        auth = Step('garmin_auth_bootstrap', 'OK', 0, 'seeded tokenstore', st, _iso())
                except Exception as e:
                    msg = str(e)
                    if _is_rl(msg):
                        auth_429_count = 1
                        lockout = write_lockout(True, 'garmin_sso_429', args.cooldown_seconds)
                        auth = Step('garmin_auth_bootstrap', 'FAIL', 1, f'Garmin rate-limited: {msg[:350]}', st, _iso())
                    else:
                        auth = Step('garmin_auth_bootstrap', 'FAIL', 1, msg[:500], st, _iso())
        steps.append(auth)

        if auth.status in ('OK', 'DRY_RUN'):
            for nm in [
                'garmin_daily_sync.py',
                'garmin_activities_sync.py',
                'garmin_activity_details_sync.py',
                'garmin_readiness_sync.py',
                'garmin_lifting_sync.py',
            ]:
                steps.append(run_script(nm, str(scripts_dir / nm)))
        else:
            steps.append(Step('garmin_pipeline', 'SKIP_AUTH_FAILED', 0, 'auth failed; garmin pulls skipped for this run', _iso(), _iso()))

        steps.append(run_script('health_qa_daily.py', str(scripts_dir / 'health_qa_daily.py')))

    ended_at = _iso()
    has_fail = any(s.status == 'FAIL' for s in steps)

    artifact = {
        'run_id': run_id,
        'started_at': started_at,
        'ended_at': ended_at,
        'status': 'fail' if has_fail else 'ok',
        'auth': {'tokenstore': str(tokenstore_dir), 'auth_429_count': auth_429_count},
        'cooldown_state': lockout,
        'steps': [asdict(s) for s in steps],
    }
    artifact_path.write_text(json.dumps(artifact, indent=2))

    compat = {
        'started_at': started_at,
        'ended_at': ended_at,
        'steps': [{'name': s.name, 'status': s.status, 'exit': s.exit, 'stderr_summary': s.stderr_summary} for s in steps],
    }
    compat_artifact_path.write_text(json.dumps(compat, indent=2))
    return 1 if has_fail else 0


if __name__ == '__main__':
    raise SystemExit(main())
