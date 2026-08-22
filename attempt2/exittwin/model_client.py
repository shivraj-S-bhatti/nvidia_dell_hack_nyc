"""OpenAI-compatible client for the GB10-local Qwen endpoint.

Compatibility contract (verified on the event GB10, recorded in issue #10 / README):
  * Host process route:    http://127.0.0.1:8000/v1   (default here)
  * OpenShell sandbox route: http://host.openshell.internal:8000/v1
    -> set EXITTWIN_LLM_BASE_URL to switch; the sandbox container must be on the
       Docker network `openshell-docker`.
  * Served model name MUST be exactly `nvidia/Qwen3.6-35B-A3B-NVFP4`.
  * The server enforces --max-num-seqs 4 -> keep concurrent calls <= 4.
  * Qwen spends tokens on reasoning before final content, so keep max_tokens
    generous (a 64-token probe used its whole budget before answering).
  * There is NO cloud fallback and there must never be one.

Stdlib-only (urllib) so the deterministic backbone stays dependency-light and this
file imports cleanly on a laptop even though the endpoint only exists on the box.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from . import config

DEFAULT_BASE_URL = config.LLM_BASE_URL
DEFAULT_MODEL = config.LLM_MODEL


class ModelUnavailable(RuntimeError):
    """Raised when the local endpoint cannot be reached. Never fall back to cloud."""


def _post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover - needs GB10
        raise ModelUnavailable(f"local endpoint {url} unreachable: {exc}") from exc


class ExitTwinModel:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def list_models(self, timeout: float = 5.0) -> dict[str, Any]:
        url = f"{self.base_url}/models"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover - needs GB10
            raise ModelUnavailable(f"local endpoint {url} unreachable: {exc}") from exc

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        tools: list[dict[str, Any]] | None = None,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return _post(f"{self.base_url}/chat/completions", payload, timeout)
