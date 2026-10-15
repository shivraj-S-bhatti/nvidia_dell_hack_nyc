#!/usr/bin/env python3
"""Build and serve the offline frontend and its bounded local run controller."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import uuid4

try:
    from .build import main as build_frontend
    from .run_controller import LiveRunError, RunController, make_controller
except ImportError:  # direct `python3 frontend/serve.py`
    from build import main as build_frontend
    from run_controller import LiveRunError, RunController, make_controller


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent
DEFAULT_ARTIFACT_ROOT = REPOSITORY / ".artifacts" / "design-run"
MAX_BODY_BYTES = 32 * 1024
SAFE_ID = re.compile(r"[^a-zA-Z0-9_.-]+")


class RequestValidationError(ValueError):
    """The browser submitted an invalid local control record."""


def _required_text(payload: dict[str, Any], key: str, *, maximum: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RequestValidationError(f"{key} must be a non-empty string")
    value = value.strip()
    if len(value) > maximum:
        raise RequestValidationError(f"{key} exceeds {maximum} characters")
    return value


def _optional_text(payload: dict[str, Any], key: str, *, maximum: int) -> str | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise RequestValidationError(f"{key} must be a string")
    value = value.strip()
    if len(value) > maximum:
        raise RequestValidationError(f"{key} exceeds {maximum} characters")
    return value or None


def _text_list(payload: dict[str, Any], key: str, *, maximum_items: int = 32) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list) or len(value) > maximum_items:
        raise RequestValidationError(f"{key} must be a list with at most {maximum_items} items")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 160:
            raise RequestValidationError(f"{key} contains an invalid item")
        result.append(item.strip())
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_change_request(payload: dict[str, Any]) -> dict[str, Any]:
    component = _required_text(payload, "component", maximum=160)
    objective = _required_text(payload, "objective", maximum=2000)
    constraint = _required_text(payload, "constraint", maximum=1000)
    source_run_id = _optional_text(payload, "sourceRunId", maximum=200)
    request_id = f"change-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}"
    return {
        "schemaVersion": "ChangeRequest/1",
        "requestId": request_id,
        "sourceRunId": source_run_id,
        "createdAt": _utc_now(),
        "actorType": "human",
        "status": "queued",
        "target": {"component": component},
        "request": {
            "objective": objective,
            "constraint": constraint,
            "protectedInterfaces": _text_list(payload, "protectedInterfaces"),
        },
        "pipeline": {
            "nextStage": "request-normalizer",
            "execution": "pending",
            "note": "Queued locally; no generation or optimization result is claimed yet.",
        },
    }


def make_human_selection(payload: dict[str, Any]) -> dict[str, Any]:
    candidate_id = _required_text(payload, "candidateId", maximum=200)
    candidate_label = _required_text(payload, "candidateLabel", maximum=200)
    run_id = _required_text(payload, "runId", maximum=200)
    return {
        "schemaVersion": "HumanSelection/1",
        "selectionId": f"selection-{uuid4().hex[:12]}",
        "runId": run_id,
        "candidateId": candidate_id,
        "candidateLabel": candidate_label,
        "decision": "selected",
        "actorType": "human",
        "selectedAt": _utc_now(),
        "comment": _optional_text(payload, "comment", maximum=1000),
    }


class ArtifactStore:
    def __init__(self, root: Path = DEFAULT_ARTIFACT_ROOT) -> None:
        self.root = root

    def write(self, collection: str, record_id: str, record: dict[str, Any]) -> Path:
        directory = self.root / collection
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = SAFE_ID.sub("-", record_id).strip(".-")
        if not safe_name:
            raise RequestValidationError("record ID is not safe to persist")
        destination = directory / f"{safe_name}.json"
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{safe_name}-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(record, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, destination)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return destination

    def recent(self, collection: str, limit: int = 20) -> list[dict[str, Any]]:
        directory = self.root / collection
        if not directory.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                records.append(value)
        return records


class FrontendHandler(SimpleHTTPRequestHandler):
    store = ArtifactStore()
    controller = RunController()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _json(self, status: int, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise RequestValidationError("invalid Content-Length") from error
        if length <= 0 or length > MAX_BODY_BYTES:
            raise RequestValidationError(f"request body must be between 1 and {MAX_BODY_BYTES} bytes")
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as error:
            raise RequestValidationError("request body must be valid JSON") from error
        if not isinstance(payload, dict):
            raise RequestValidationError("request body must be a JSON object")
        return payload

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/frontend/")
            self.end_headers()
            return
        if path == "/healthz":
            self._json(200, {"ok": True, "ui": "frontend", "execution": "bounded-local"})
            return
        if path == "/api/capabilities":
            self._json(200, self.controller.capabilities())
            return
        if path == "/api/runs":
            self._json(200, {"runs": self.controller.recent()})
            return
        if path == "/api/change-requests":
            self._json(200, {"requests": self.store.recent("requests")})
            return
        if path.startswith("/api/runs/"):
            run_id = path.removeprefix("/api/runs/")
            try:
                self._json(200, self.controller.get(run_id))
            except LiveRunError as error:
                self._json(404, {"error": str(error)})
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        try:
            payload = self._read_json()
            response_status = 201
            if path == "/api/runs":
                record = self.controller.start(payload)
                destination = self.controller.run_root / record["runId"] / "request.json"
                response_status = 202
            elif path == "/api/change-requests":
                record = make_change_request(payload)
                destination = self.store.write("requests", record["requestId"], record)
            elif path == "/api/selections":
                run_id = str(payload.get("runId", ""))
                live_root = self.controller.run_root / run_id
                if live_root.is_dir():
                    record, destination = self.controller.select(run_id, payload)
                else:
                    record = make_human_selection(payload)
                    destination = self.store.write("selections", record["selectionId"], record)
            else:
                self._json(404, {"error": "unknown endpoint"})
                return
        except (RequestValidationError, LiveRunError) as error:
            self._json(400, {"error": str(error)})
            return
        except OSError as error:
            self._json(500, {"error": f"artifact persistence failed: {error}"})
            return
        response = dict(record)
        response["artifactPath"] = str(destination.relative_to(REPOSITORY))
        self._json(response_status, response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4414, type=int)
    parser.add_argument("--run", help="saved DesignRun envelope to embed")
    parser.add_argument(
        "--runner",
        choices=("live-fsai", "neoracer-demo"),
        default=os.environ.get("AUTOAUTO_RUNNER", "live-fsai"),
        help="execution adapter exposed by /api/runs",
    )
    arguments = parser.parse_args()
    build_frontend(arguments.run)
    FrontendHandler.controller = make_controller(arguments.runner)
    handler = partial(FrontendHandler, directory=str(REPOSITORY))
    server = ThreadingHTTPServer((arguments.host, arguments.port), handler)
    print(f"autoauto frontend ready at http://{arguments.host}:{arguments.port}/frontend/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
