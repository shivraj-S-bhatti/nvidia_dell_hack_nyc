"""Single place to configure ExitTwin — the one file you edit to move sandboxes.

Precedence: real environment variables > values in `attempt2/.env` > defaults here.
Copy `.env.example` to `.env` and flip `EXITTWIN_LLM_BASE_URL` to the OpenShell
route when you run inside the harness sandbox. Nothing else needs to change.

Compatibility defaults come straight from the repo README's verified GB10 setup.
"""

from __future__ import annotations

import os
import pathlib

PACKAGE_DIR = pathlib.Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent  # attempt2/


def _load_dotenv(path: pathlib.Path) -> None:
    """Minimal KEY=VALUE loader (stdlib only) so there's no dotenv dependency."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # Real env wins over .env, matching 12-factor precedence.
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(PROJECT_DIR / ".env")

# --- Local inference endpoint (see README "Verified GB10 model inference"). ------
# Host route (default). Sandbox route: http://host.openshell.internal:8000/v1
LLM_BASE_URL = os.environ.get("EXITTWIN_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
LLM_MODEL = os.environ.get("EXITTWIN_LLM_MODEL", "nvidia/Qwen3.6-35B-A3B-NVFP4")
# The server runs --max-num-seqs 4; keep concurrent generations at or below this.
LLM_MAX_CONCURRENCY = int(os.environ.get("EXITTWIN_LLM_MAX_CONCURRENCY", "4"))

# --- Storage. Defaults to a zero-dependency JSON store so `pull && run` works. ---
# Set EXITTWIN_MONGODB_URI to use the real MongoDB collections on the box.
MONGODB_URI = os.environ.get("EXITTWIN_MONGODB_URI", "")
MONGODB_DB = os.environ.get("EXITTWIN_MONGODB_DB", "exittwin")

DATA_DIR = pathlib.Path(os.environ.get("EXITTWIN_DATA_DIR", str(PROJECT_DIR / ".artifacts")))

# When true, NYC-record refresh is skipped and only cached/seeded evidence is used.
# This is the demo posture: prove the judged path with networking disabled.
OFFLINE = os.environ.get("EXITTWIN_OFFLINE", "0") == "1"


def summary() -> str:
    store = "mongodb" if MONGODB_URI else f"json:{DATA_DIR}"
    return (
        f"llm={LLM_BASE_URL} model={LLM_MODEL} "
        f"max_concurrency={LLM_MAX_CONCURRENCY} store={store} offline={OFFLINE}"
    )
