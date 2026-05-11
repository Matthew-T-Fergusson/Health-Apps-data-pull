#!/usr/bin/env python3
import os
from datetime import date, timedelta
from pathlib import Path

from garminconnect import Garmin


def load_env(env_path: Path) -> None:
    if not env_path.exists():
        raise RuntimeError(f"Missing env file: {env_path}")
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> None:
    workspace_dir = Path(__file__).resolve().parents[1]
    env_path = Path(os.getenv("ENV_PATH", str(workspace_dir / ".env")))
    load_env(env_path)

    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError("Missing GARMIN_EMAIL or GARMIN_PASSWORD in .env")

    client = Garmin(email=email, password=password)
    client.login()

    d = (date.today() - timedelta(days=1)).isoformat()
    sleep = client.get_sleep_data(d)
    hr = client.get_heart_rates(d)
    stats = client.get_stats(d)

    print("OK login")
    print("date:", d)
    print("sleep type:", type(sleep).__name__)
    print("hr points:", len(hr) if isinstance(hr, list) else type(hr).__name__)
    print("stats type:", type(stats).__name__)


if __name__ == "__main__":
    main()
