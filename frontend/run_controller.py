"""Start and inspect bounded local FS-AI part optimization runs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import threading
from typing import Any
from uuid import uuid4


REPOSITORY = Path(__file__).resolve().parent.parent
ARTIFACT_ROOT = REPOSITORY / ".artifacts" / "design-run"
RUN_ROOT = ARTIFACT_ROOT / "runs"
NUMBA_CACHE = ARTIFACT_ROOT / "numba-cache"
TEMPLATE_PROBLEM = REPOSITORY / ".artifacts" / "attempt1-physgen-fsai" / "design-problem" / "design-problem.json"
MASK_MANIFEST = REPOSITORY / ".artifacts" / "attempt1-physgen-fsai" / "design-problem" / "mask-manifest.json"
TARGET_MANIFEST = REPOSITORY / ".artifacts" / "attempt1-physgen-fsai" / "object" / "target-component.json"
OAT_ROOT = Path("/home/dell/Documents/hackathon-hdd/source/checkouts/OptimizeAnyTopology")
PYTHON = REPOSITORY / ".artifacts" / "attempt1-physgen" / "object" / "venv" / "bin" / "python"

SUPPORTED_COMPONENT = "Example Plate"
SUPPORTED_COMPONENT_ID = "component-68349c8f3ab4c731ff9c"
OBJECTIVE_WORDS = ("weight", "mass", "material", "light", "compliance", "stiff")
CONSTRAINT_WORDS = ("mount", "interface", "hole", "preserve")
PERCENT = re.compile(r"(?<!\d)(\d{1,2}(?:\.\d+)?)\s*%")
SAFE_RUN_ID = re.compile(r"^run-[0-9A-Za-z_.-]+$")


class LiveRunError(ValueError):
    """A requested live run is unsupported or unavailable."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LiveRunError(f"cannot read required artifact {path}: {error}") from error
    if not isinstance(value, dict):
        raise LiveRunError(f"required artifact is not an object: {path}")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def normalize_request(payload: dict[str, Any]) -> dict[str, Any]:
    component = str(payload.get("component", "")).strip()
    objective = str(payload.get("objective", "")).strip()
    constraint = str(payload.get("constraint", "")).strip()
    if component != SUPPORTED_COMPONENT:
        raise LiveRunError(
            f"live optimization currently supports only {SUPPORTED_COMPONENT}; {component or 'no component'} is not mapped"
        )
    lowered_objective = objective.lower()
    if not objective or not any(word in lowered_objective for word in OBJECTIVE_WORDS):
        raise LiveRunError("objective must request a bounded mass/material or compliance/stiffness change")
    lowered_constraint = constraint.lower()
    if not constraint or not any(word in lowered_constraint for word in CONSTRAINT_WORDS):
        raise LiveRunError("constraint must explicitly preserve the four mount holes/interfaces")
    match = PERCENT.search(objective)
    fraction = float(match.group(1)) / 100.0 if match else 0.35
    if not 0.20 <= fraction <= 0.80:
        raise LiveRunError("requested material fraction must be between 20% and 80%")
    return {
        "component": component,
        "componentId": SUPPORTED_COMPONENT_ID,
        "objective": objective,
        "constraint": constraint,
        "materialFractionTarget": fraction,
        "protectedInterfaces": [
            "interface.fsai-mount-00",
            "interface.fsai-mount-01",
            "interface.fsai-mount-02",
            "interface.fsai-mount-03",
        ],
        "normalizer": "deterministic bounded FS-AI request adapter",
    }


def capabilities() -> dict[str, Any]:
    ready = all(path.is_file() for path in (TEMPLATE_PROBLEM, MASK_MANIFEST, TARGET_MANIFEST, PYTHON)) and OAT_ROOT.is_dir()
    return {
        "schemaVersion": "LiveRunCapabilities/1",
        "ready": ready,
        "components": [
            {
                "id": SUPPORTED_COMPONENT_ID,
                "name": SUPPORTED_COMPONENT,
                "assembly": "FS-AI ADS-DV 2026",
                "source": "downloaded STEP component",
                "objectView": "/.artifacts/attempt1-physgen-fsai/progression-viewer/index.html",
                "objective": "Reduce material to 35% while minimizing compliance.",
                "constraint": "Preserve all four mount holes and interfaces.",
                "protectedInterfaces": [
                    "interface.fsai-mount-00",
                    "interface.fsai-mount-01",
                    "interface.fsai-mount-02",
                    "interface.fsai-mount-03",
                ],
            }
        ],
        "pipeline": ["object", "lab", "cad", "factory", "track", "review"],
        "limitations": [
            "Only the FS-AI Example Plate has a verified CAD-to-domain adapter in the current worktree.",
            "Track is a declared 2-D in-plane comparison fixture, not vehicle certification.",
        ],
    }


class RunController:
    def __init__(self, run_root: Path = RUN_ROOT) -> None:
        self.run_root = run_root
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}

    def capabilities(self) -> dict[str, Any]:
        return capabilities()

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = normalize_request(payload)
        missing = [path for path in (TEMPLATE_PROBLEM, MASK_MANIFEST, TARGET_MANIFEST, PYTHON) if not path.is_file()]
        if missing or not OAT_ROOT.is_dir():
            detail = ", ".join(str(path) for path in (*missing, *((OAT_ROOT,) if not OAT_ROOT.is_dir() else ())))
            raise LiveRunError(f"live runtime inventory is incomplete: {detail}")
        with self._lock:
            for run_id, thread in tuple(self._threads.items()):
                if not thread.is_alive():
                    self._threads.pop(run_id, None)
            if self._threads:
                active = next(iter(self._threads))
                raise LiveRunError(f"a live optimization is already running: {active}")
            run_id = f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}"
            root = self.run_root / run_id
            root.mkdir(parents=True, exist_ok=False)
            request_record = {
                "schemaVersion": "ChangeRequest/1",
                "requestId": f"change-{run_id.removeprefix('run-')}",
                "runId": run_id,
                "createdAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "actorType": "human",
                "status": "running",
                "target": {"component": request["component"], "componentId": request["componentId"]},
                "request": request,
            }
            _atomic_json(root / "request.json", request_record)
            problem = _read_json(TEMPLATE_PROBLEM)
            problem["run_id"] = run_id
            problem["id"] = f"design-problem.fsai-example-plate.{run_id}"
            problem["material_fraction_target"] = request["materialFractionTarget"]
            _atomic_json(root / "input" / "design-problem.json", problem)
            initial = {
                "schemaVersion": "LiveRunStatus/1",
                "runId": run_id,
                "status": "starting",
                "request": request,
                "events": [],
                "resultPath": None,
                "error": None,
            }
            _atomic_json(root / "status.json", initial)
            thread = threading.Thread(target=self._execute, args=(run_id,), daemon=True, name=f"autoauto-{run_id}")
            self._threads[run_id] = thread
            thread.start()
        return self.get(run_id)

    def _execute(self, run_id: str) -> None:
        root = self.run_root / run_id
        command = [
            str(PYTHON),
            "-m",
            "attempt1.physgen_fsai.live_run",
            "--problem",
            str(root / "input" / "design-problem.json"),
            "--masks",
            str(MASK_MANIFEST),
            "--target",
            str(TARGET_MANIFEST),
            "--request",
            str(root / "request.json"),
            "--output-root",
            str(root),
            "--oat-root",
            str(OAT_ROOT),
            "--offline",
        ]
        environment = os.environ.copy()
        environment.update({
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "NO_PROXY": "*",
            # The OAT checkout is intentionally read-only here.  Numba's
            # upstream decorators request caching, so keep that generated
            # state inside this run instead of beside the checkout.
            "NUMBA_CACHE_DIR": str(NUMBA_CACHE),
        })
        logs = root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        try:
            with (logs / "stdout.log").open("w", encoding="utf-8") as stdout, (logs / "stderr.log").open("w", encoding="utf-8") as stderr:
                completed = subprocess.run(
                    command,
                    cwd=REPOSITORY,
                    env=environment,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=15 * 60,
                    check=False,
                )
            if completed.returncode:
                status = self._status_or_default(run_id)
                if status.get("status") != "failed":
                    stderr_tail = ""
                    try:
                        stderr_tail = (logs / "stderr.log").read_text(encoding="utf-8")[-1200:].strip()
                    except OSError:
                        pass
                    raise RuntimeError(
                        f"live runner exited {completed.returncode}"
                        + (f": {stderr_tail}" if stderr_tail else "")
                    )
        except Exception as error:
            status = self._status_or_default(run_id)
            status.update({"status": "failed", "error": f"{type(error).__name__}: {error}"})
            _atomic_json(root / "status.json", status)

    def _status_or_default(self, run_id: str) -> dict[str, Any]:
        path = self.run_root / run_id / "status.json"
        if not path.is_file():
            return {"schemaVersion": "LiveRunStatus/1", "runId": run_id, "events": []}
        return _read_json(path)

    def get(self, run_id: str) -> dict[str, Any]:
        if not SAFE_RUN_ID.fullmatch(run_id):
            raise LiveRunError("invalid run ID")
        root = self.run_root / run_id
        if not root.is_dir():
            raise LiveRunError(f"unknown run: {run_id}")
        status = self._status_or_default(run_id)
        result_path = root / "run.json"
        if result_path.is_file():
            status["result"] = _read_json(result_path)
        return status

    def recent(self, limit: int = 12) -> list[dict[str, Any]]:
        if not self.run_root.is_dir():
            return []
        values = []
        for path in sorted(self.run_root.glob("run-*/status.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
            try:
                status = _read_json(path)
            except LiveRunError:
                continue
            values.append({
                "runId": status.get("runId"),
                "status": status.get("status"),
                "component": status.get("request", {}).get("component"),
                "objective": status.get("request", {}).get("objective"),
            })
        return values

    def select(self, run_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], Path]:
        status = self.get(run_id)
        if status.get("status") != "awaiting_review":
            raise LiveRunError(f"run is not awaiting review: {status.get('status', 'unknown')}")
        result = status.get("result")
        if not isinstance(result, dict):
            raise LiveRunError("run result is unavailable")
        candidate_id = str(payload.get("candidateId", "")).strip()
        eligible = result.get("selectionEligibleCandidateIds", [])
        if candidate_id not in eligible:
            raise LiveRunError("candidate did not survive Factory and Track")
        candidate = next((item for item in result.get("candidates", []) if item.get("id") == candidate_id), None)
        if not candidate:
            raise LiveRunError("candidate evidence is unavailable")
        comment_value = payload.get("comment")
        if comment_value is not None and not isinstance(comment_value, str):
            raise LiveRunError("comment must be a string")
        comment = comment_value.strip() if isinstance(comment_value, str) else None
        if comment and len(comment) > 1000:
            raise LiveRunError("comment exceeds 1000 characters")
        record = {
            "schemaVersion": "HumanSelection/1",
            "selectionId": f"selection-{uuid4().hex[:12]}",
            "runId": run_id,
            "candidateId": candidate_id,
            "candidateLabel": candidate.get("label", candidate_id),
            "decision": "selected",
            "actorType": "human",
            "selectedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "comment": comment or None,
        }
        root = self.run_root / run_id
        destination = root / "selection.json"
        _atomic_json(destination, record)
        result.update({"status": "completed", "selection": record})
        _atomic_json(root / "run.json", result)
        for event in status.get("events", []):
            if event.get("stage") == "review":
                event.update({
                    "status": "completed",
                    "message": f"Human selected {record['candidateLabel']}; iteration closed.",
                    "completedAt": record["selectedAt"],
                    "evidence": ["selection.json"],
                })
        status.pop("result", None)
        status.update({"status": "completed", "selectionPath": "selection.json", "error": None})
        _atomic_json(root / "status.json", status)
        return record, destination


def make_controller(mode: str, run_root: Path = RUN_ROOT) -> RunController:
    if mode == "live-fsai":
        return RunController(run_root)
    if mode == "neoracer-demo":
        try:
            from .neoracer_demo import NeoRacerDemoController
        except ImportError:  # direct `python3 frontend/serve.py`
            from neoracer_demo import NeoRacerDemoController
        return NeoRacerDemoController(run_root)
    raise LiveRunError(f"unknown run controller: {mode}")
