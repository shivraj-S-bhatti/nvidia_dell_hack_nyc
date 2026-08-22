"""Fetch + cache NYC open-data records for offline replay.

The curated, cited values the demo uses live in `evidence.py` (so a fresh checkout
has real evidence with no network). This module refreshes the RAW Socrata
responses into a local cache when you want to re-verify them against live data.
Offline posture (config.OFFLINE) skips the network and reads only the cache.

Field-name mapping from raw Socrata rows into the curated schema is deliberately
left as a marked follow-up — we do not assert column names we have not verified
against a live response.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from . import config
from .evidence import BBL

# Raw Socrata resource endpoints (from issue #15 sources).
ENDPOINTS = {
    "mappluto": f"https://data.cityofnewyork.us/resource/64uk-42ks.json?bbl={BBL}",
    "footprint": f"https://data.cityofnewyork.us/resource/5zhs-2jue.json?base_bbl={BBL}",
}

CACHE_DIR = config.DATA_DIR / "nyc_cache"


def _cache_path(name: str):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{name}.json"


def _fetch(url: str, timeout: float = 15.0) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def refresh(names: tuple[str, ...] = tuple(ENDPOINTS)) -> dict[str, str]:
    """Pull raw records into the cache. Returns {name: status}. Never uses cloud AI."""
    status: dict[str, str] = {}
    for name in names:
        if config.OFFLINE:
            status[name] = "skipped (offline)"
            continue
        try:
            rows = _fetch(ENDPOINTS[name])
            _cache_path(name).write_text(json.dumps(rows, indent=2))
            status[name] = f"cached {len(rows)} row(s)"
        except (urllib.error.URLError, TimeoutError, KeyError) as exc:
            status[name] = f"failed ({exc})"
    return status


def cached(name: str) -> Any | None:
    path = _cache_path(name)
    return json.loads(path.read_text()) if path.exists() else None
