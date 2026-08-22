#!/usr/bin/env python3
"""Verify the GB10-local Qwen endpoint from wherever this process runs.

Mirrors the smoke test recorded in the repo README. Run it ON THE GB10 (host
route) or inside the OpenShell sandbox (set EXITTWIN_LLM_BASE_URL to the
host.openshell.internal route, or edit .env, first). It fails fast on a laptop
with no tunnel — expected; the endpoint only exists on the box.

    python check_endpoint.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from exittwin.model_client import DEFAULT_BASE_URL, ExitTwinModel, ModelUnavailable  # noqa: E402


def main() -> int:
    model = ExitTwinModel()
    print(f"endpoint: {DEFAULT_BASE_URL}  model: {model.model}")
    try:
        listing = model.list_models()
        ids = [m.get("id") for m in listing.get("data", [])]
        print(f"[ok] /models -> {ids}")
        if model.model not in ids:
            print(f"[warn] served model id {model.model!r} not in {ids}")

        resp = model.chat(
            [{"role": "user", "content": "Reply with exactly READY and no other text."}],
            max_tokens=256,  # Qwen reasons before final content; keep this generous.
            temperature=0.0,
        )
        content = (resp["choices"][0]["message"].get("content") or "").strip()
        ok = content == "READY"
        print(f"[{'ok' if ok else 'warn'}] chat -> {content!r}")
        return 0 if ok else 2
    except ModelUnavailable as exc:
        print(f"[fail] {exc}")
        print("If on a laptop this is expected — run on the GB10 or inside the sandbox.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
