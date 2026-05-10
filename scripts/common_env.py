#!/usr/bin/env python3
"""Shared environment-file loader for local development and cron runs.

This intentionally supports simple KEY=VALUE `.env` files without requiring
secrets to be committed to the repository.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | Path | None) -> None:
    """Load KEY=VALUE pairs into os.environ when they are not already set."""
    if not path:
        return
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
