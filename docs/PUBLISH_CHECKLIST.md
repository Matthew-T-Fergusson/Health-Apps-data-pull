# Publish Checklist (GitHub)

## 1) Pre-push safety checks
```bash
# Ensure no env/token/key files are tracked
git ls-files | grep -E '(^\.env$|tokenstore|garmin_tokens\.json|\.pem$|\.key$|\.p12$|\.pfx$)' || true

# Optional: quick grep for obvious PAT patterns in tracked files
git ls-files -z | xargs -0 grep -nE 'github_pat_|ghp_[A-Za-z0-9]{20,}' || true
```

## 2) Verify core docs/files exist
- `README.md`
- `LICENSE`
- `.env.example`
- `.gitignore`
- `docs/reports/health-sync-progress-2026-04-08.md`

## 3) Commit
```bash
git add README.md .gitignore LICENSE docs/reports/health-sync-progress-2026-04-08.md docs/PUBLISH_CHECKLIST.md scripts/garmin_activity_details_sync.py scripts/sync_activity_routes.py
git commit -m "Harden Garmin/Strava ingest for mixed activity IDs; restore QA green"
```

## 4) Create new GitHub repo + push
```bash
# Replace with your repo name
gh repo create athlete-ingest-poc --public --source . --remote origin --push
```

If remote already exists:
```bash
git remote add origin git@github.com:Matthew-T-Fergusson/athlete-ingest-poc.git
git branch -M main
git push -u origin main
```

## 5) Pin and polish
- Add repo topics: `garmin`, `strava`, `postgres`, `data-pipeline`, `health-tech`
- Pin repo on profile
- Add one screenshot/diagram in README
