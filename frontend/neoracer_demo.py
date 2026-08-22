"""OpenRouter-assisted NeoRacer replay backed by one precompiled artifact pack."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from uuid import uuid4

try:
    from .run_controller import LiveRunError, SAFE_RUN_ID, _atomic_json, _read_json
except ImportError:  # direct `python3 frontend/serve.py`
    from run_controller import LiveRunError, SAFE_RUN_ID, _atomic_json, _read_json


REPOSITORY = Path(__file__).resolve().parent.parent
PACK = REPOSITORY / "autoauto" / "run.integrated.json"
COMPONENT = "WING-MOUNT-L"
COMPONENT_ID = "component-651d2501fdff2aa4f1cd"
DEFAULT_MODEL = "openai/gpt-4.1-mini"
DEMO_BOM = {
    "WING-MOUNT-L": "aero",
    "WING-MOUNT-R": "aero",
    "STEERING_KNUCKLE_JOINT": "steering",
    "STEERING_LINK_SHAFT": "steering",
    "STEERING_OUTER_LINK": "steering",
    "SERVO_ARM": "controls",
    "SERVO_SPT5435LV_ASM": "controls",
    "ESC_GOOLRC_60A-13_ASM": "electronics",
}
STAGES = (
    ("object", "OB", "Object", "Resolving the selected wing mount and its four protected interfaces."),
    ("lab", "LB", "Lab", "Loading three precompiled OAT candidate fields."),
    ("cad", "CC", "CAD Compile", "Loading the compiled STEP solids and geometry hashes."),
    ("factory", "FX", "Factory", "Replaying the exact saved checks and one measured veto."),
    ("track", "TR", "Track", "Ordering Factory survivors by the saved Lab evaluator; Track remains pending."),
    ("review", "HU", "Human Review", "Waiting for a persisted human selection."),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _fallback_brief(objective: str, constraint: str, reason: str) -> dict[str, Any]:
    return {
        "normalizedObjective": objective,
        "normalizedConstraint": constraint,
        "candidateBriefs": {
            "C1": "Inspect the first precompiled OAT density field.",
            "C2": "Inspect the second precompiled OAT density field.",
            "C3": "Inspect the third precompiled OAT density field.",
        },
        "decisionSummary": "Choose only from candidates that passed the saved Factory checks.",
        "provider": "deterministic fallback",
        "model": None,
        "fallbackReason": reason,
    }


def _extract_json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model response did not contain a JSON object")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model response was not a JSON object")
    return value


def openrouter_brief(objective: str, constraint: str) -> dict[str, Any]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if not api_key:
        return _fallback_brief(objective, constraint, "OPENROUTER_API_KEY is not configured")
    prompt = {
        "component": COMPONENT,
        "objective": objective,
        "constraint": constraint,
        "candidateFamily": {"C1": "OAT 00", "C2": "OAT 01", "C3": "OAT 02"},
        "instruction": (
            "Return only JSON with normalizedObjective, normalizedConstraint, candidateBriefs keyed C1/C2/C3, "
            "and decisionSummary. Describe intent only. Never invent measurements, verdicts, rankings, or claims."
        ),
    }
    body = json.dumps({
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "You are the Lab proposal narrator in a CAD optimization demo."},
            {"role": "user", "content": json.dumps(prompt, separators=(",", ":"))},
        ],
    }).encode("utf-8")
    outgoing = urlrequest.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc",
            "X-Title": "autoauto NeoRacer demo",
        },
    )
    try:
        with urlrequest.urlopen(outgoing, timeout=30) as response:
            payload = json.load(response)
        result = _extract_json(payload["choices"][0]["message"]["content"])
        briefs = result.get("candidateBriefs")
        if not isinstance(briefs, dict) or any(not str(briefs.get(key, "")).strip() for key in ("C1", "C2", "C3")):
            raise ValueError("model response omitted candidate briefs")
        result.update({"provider": "OpenRouter", "model": model, "fallbackReason": None})
        return result
    except (OSError, KeyError, TypeError, ValueError, urlerror.URLError) as exc:
        return _fallback_brief(objective, constraint, f"OpenRouter unavailable: {type(exc).__name__}")


def capabilities() -> dict[str, Any]:
    pack = _read_json(PACK) if PACK.is_file() else {}
    source_bom = pack.get("integration", {}).get("object", {}).get("bom", [])
    bom = []
    for item in source_bom:
        name = item.get("name")
        if name not in DEMO_BOM:
            continue
        count = int(item.get("occurrenceCount", 1))
        bom.append({
            "name": name,
            "componentId": item.get("componentId"),
            "subsystem": DEMO_BOM[name],
            "detail": f"{count} occurrence" + ("s" if count != 1 else ""),
        })
    return {
        "schemaVersion": "LiveRunCapabilities/1",
        "ready": PACK.is_file(),
        "mode": "neoracer-demo",
        "modelGateway": {
            "provider": "OpenRouter",
            "configured": bool(os.environ.get("OPENROUTER_API_KEY", "").strip()),
            "model": os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
            "role": "request normalization and candidate narration only",
        },
        "components": [{
            "id": COMPONENT_ID,
            "name": COMPONENT,
            "assembly": "NeoRacer v0 full vehicle",
            "source": "precompiled NeoRacer artifact pack",
            "objectView": "/autoauto/vehicle-viewer.html",
            "objective": "Minimize compliance at a fixed 35% material target.",
            "constraint": "Preserve all four wing-mount interfaces and the assembly envelope.",
            "protectedInterfaces": ["mount-00", "mount-01", "mount-02", "mount-03"],
        }],
        "bom": bom,
        "pipeline": ["object", "lab", "cad", "factory", "track", "review"],
        "limitations": [
            "Geometry and Factory verdicts come from one precompiled NeoRacer artifact pack.",
            "Track has not run; survivor ordering uses the saved Lab evaluator and is not a simulation verdict.",
            "OpenRouter text cannot alter artifacts, checks, ordering, or selection eligibility.",
        ],
    }


def _metrics(material: float, compliance: float | None) -> dict[str, float | None]:
    return {"material_fraction": material, "compliance_n_mm": compliance, "max_von_mises_mpa": None}


def _veto_reason(source: dict[str, Any]) -> str:
    failures = source["factory"].get("failedChecks", [])
    if not failures:
        return f"{source['factory']['checksPassed']}/{source['factory']['checkCount']} saved checks passed."
    check = failures[0]
    return (
        f"{check['check_id']}: {check['measured']['value']:.3f} {check['measured']['unit']} "
        f"exceeds {check['threshold']['value']:.3f} {check['threshold']['unit']}."
    )


def _build_result(run_id: str, request_record: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    data = _read_json(PACK)["integration"]
    rows = []
    for index, source in enumerate(data["lab"]["proposals"]):
        metrics = _metrics(source["compile"]["materialFraction"], source["labEvaluation"]["complianceNmm"])
        rows.append({
            "id": source["id"],
            "label": source["label"],
            "role": source["role"],
            "parentId": data["compile"]["baseline"]["id"],
            "previewUrl": source["compile"]["image"]["url"].replace("assets/", "/autoauto/assets/"),
            "stepUrl": None,
            "densitySha256": source["densityImage"]["sha256"],
            "proposal": brief["candidateBriefs"].get(f"C{index + 1}", source["method"]),
            "compile": {
                "valid": source["compile"]["valid"],
                "solidCount": source["compile"]["solidCount"],
                "volumeMm3": source["compile"]["volumeMm3"],
                "sha256": source["compile"]["geometrySha256"],
                "source": "precompiled NeoRacer artifact pack",
            },
            "factory": {
                "candidateId": source["id"],
                "verdict": source["factory"]["verdict"],
                "failureCodes": source["factory"]["failureCodes"],
                "reason": _veto_reason(source),
            },
            "track": {"metrics": metrics, "source": "saved Lab evaluator; Track pending"} if source["trackEligible"] else None,
        })
    survivors = [row for row in rows if row["factory"]["verdict"] == "pass"]
    survivors.sort(key=lambda row: row["track"]["metrics"]["compliance_n_mm"])
    baseline_volume = data["compile"]["baseline"]["volumeMm3"]
    ranking = []
    for rank, row in enumerate(survivors, 1):
        metrics = row["track"]["metrics"]
        material_ratio = row["compile"]["volumeMm3"] / baseline_volume
        ranking.append({
            "candidateId": row["id"],
            "label": row["label"],
            "parentId": row["parentId"],
            "rank": rank,
            "score": 1.0 / metrics["compliance_n_mm"],
            "metrics": metrics,
            "relative": {"materialRatio": material_ratio, "complianceRatio": None, "specificStiffnessRatio": None},
        })
    feedback = data["factory"]["feedback"]
    return {
        "schemaVersion": "LiveDesignRun/1",
        "runId": run_id,
        "status": "awaiting_human_review",
        "executionMode": "openrouter-assisted-precompiled-pack",
        "truthBoundary": "OpenRouter proposed language. One NeoRacer pack supplied geometry, Factory verdicts, and saved Lab evaluations. Track is pending.",
        "request": request_record["request"],
        "modelProposal": brief,
        "object": {"assembly": data["object"]["assembly"], "component": COMPONENT, "componentId": COMPONENT_ID, "protectedInterfaceCount": 4},
        "problem": {"id": data["problem"]["id"], "objective": brief["normalizedObjective"], "constraint": brief["normalizedConstraint"], "materialFractionTarget": 0.35, "fixture": "Saved OAT Lab evaluation only; Track simulation has not run."},
        "candidates": rows,
        "factory": {"verdicts": [row["factory"] for row in rows], "rejectedCandidateIds": data["factory"]["rejectedCandidateIds"], "survivorCandidateIds": [row["id"] for row in survivors]},
        "revision": {
            "id": "Revision pending",
            "parentId": feedback["candidateId"],
            "feedback": f"Factory measured {feedback['measured']['value']:.3f} {feedback['measured']['unit']} against a {feedback['threshold']['value']:.3f} {feedback['threshold']['unit']} threshold.",
        },
        "track": {"baseline": {"candidateId": data["compile"]["baseline"]["id"], "metrics": _metrics(1.0, None)}, "ranking": ranking, "recommendation": ranking[0]["candidateId"], "physics": {"evaluator": "precompiled OAT Lab evaluator replay; Track pending", "live": False}},
        "measurements": {"totalWallSeconds": 0.0, "source": "precompiled artifact pack"},
        "inventory": {"proposalProvider": brief["provider"], "proposalModel": brief["model"], "learnedInferenceUsed": brief["provider"] == "OpenRouter", "simulationExecutedLive": False},
        "limitations": ["Track simulation has not run. Candidate ordering is a saved Lab-evaluator comparison, not a simulation verdict.", "The OpenRouter response cannot alter Factory verdicts, saved values, or selection eligibility."],
        "selectionEligibleCandidateIds": [row["id"] for row in survivors],
    }


class NeoRacerDemoController:
    def __init__(self, run_root: Path) -> None:
        self.run_root = run_root
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}

    def capabilities(self) -> dict[str, Any]:
        return capabilities()

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        component = str(payload.get("component", "")).strip()
        objective = str(payload.get("objective", "")).strip()
        constraint = str(payload.get("constraint", "")).strip()
        if component != COMPONENT:
            raise LiveRunError(f"NeoRacer demo supports only {COMPONENT}")
        if not objective or not constraint:
            raise LiveRunError("objective and constraint are required")
        with self._lock:
            if any(thread.is_alive() for thread in self._threads.values()):
                raise LiveRunError("a NeoRacer demo run is already active")
            run_id = f"run-demo-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}"
            root = self.run_root / run_id
            root.mkdir(parents=True, exist_ok=False)
            record = {"schemaVersion": "ChangeRequest/1", "requestId": f"change-{run_id.removeprefix('run-')}", "runId": run_id, "createdAt": _now(), "actorType": "human", "status": "running", "target": {"component": COMPONENT, "componentId": COMPONENT_ID}, "request": {"component": COMPONENT, "componentId": COMPONENT_ID, "objective": objective, "constraint": constraint}}
            _atomic_json(root / "request.json", record)
            _atomic_json(root / "status.json", {"schemaVersion": "LiveRunStatus/1", "runId": run_id, "status": "starting", "request": record["request"], "events": [], "resultPath": None, "error": None, "executionMode": "openrouter-assisted-precompiled-pack"})
            thread = threading.Thread(target=self._execute, args=(run_id,), daemon=True, name=f"autoauto-demo-{run_id}")
            self._threads[run_id] = thread
            thread.start()
        return self.get(run_id)

    def _execute(self, run_id: str) -> None:
        root = self.run_root / run_id
        record = _read_json(root / "request.json")
        status = _read_json(root / "status.json")
        try:
            brief = openrouter_brief(record["request"]["objective"], record["request"]["constraint"])
            _atomic_json(root / "model-proposal.json", brief)
            status["status"] = "running"
            for index, (stage, agent, name, message) in enumerate(STAGES):
                if index:
                    previous = status["events"][index - 1]
                    previous.update({
                        "status": "pending" if previous["stage"] == "track" else "completed",
                        "completedAt": _now(),
                    })
                if stage == "lab":
                    message = f"{brief['provider']} narrated three candidates from the precompiled pack."
                status["events"].append({"stage": stage, "agent": agent, "name": name, "status": "running", "message": message, "startedAt": _now(), "evidence": ["model-proposal.json"] if stage == "lab" else []})
                _atomic_json(root / "status.json", status)
                time.sleep(0.42 if stage != "review" else 0.1)
            _atomic_json(root / "run.json", _build_result(run_id, record, brief))
            status.update({"status": "awaiting_review", "resultPath": "run.json", "error": None})
            _atomic_json(root / "status.json", status)
        except Exception as exc:
            status.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            _atomic_json(root / "status.json", status)

    def get(self, run_id: str) -> dict[str, Any]:
        if not SAFE_RUN_ID.fullmatch(run_id):
            raise LiveRunError("invalid run ID")
        root = self.run_root / run_id
        if not root.is_dir():
            raise LiveRunError(f"unknown run: {run_id}")
        status = _read_json(root / "status.json")
        if (root / "run.json").is_file():
            status["result"] = _read_json(root / "run.json")
        return status

    def recent(self, limit: int = 12) -> list[dict[str, Any]]:
        if not self.run_root.is_dir():
            return []
        records = []
        for path in sorted(self.run_root.glob("run-*/status.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
            try:
                status = _read_json(path)
            except LiveRunError:
                continue
            records.append({"runId": status.get("runId"), "status": status.get("status"), "component": status.get("request", {}).get("component"), "objective": status.get("request", {}).get("objective")})
        return records

    def select(self, run_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], Path]:
        status = self.get(run_id)
        if status.get("status") != "awaiting_review":
            raise LiveRunError(f"run is not awaiting review: {status.get('status', 'unknown')}")
        result = status.get("result")
        candidate_id = str(payload.get("candidateId", "")).strip()
        if candidate_id not in result.get("selectionEligibleCandidateIds", []):
            raise LiveRunError("candidate did not survive Factory")
        candidate = next((item for item in result["candidates"] if item["id"] == candidate_id), None)
        record = {"schemaVersion": "HumanSelection/1", "selectionId": f"selection-{uuid4().hex[:12]}", "runId": run_id, "candidateId": candidate_id, "candidateLabel": candidate["label"], "decision": "selected", "actorType": "human", "selectedAt": _now(), "comment": None}
        root = self.run_root / run_id
        destination = root / "selection.json"
        _atomic_json(destination, record)
        result.update({"status": "completed", "selection": record})
        _atomic_json(root / "run.json", result)
        status["status"] = "completed"
        for event in status.get("events", []):
            if event.get("stage") == "review":
                event.update({"status": "completed", "message": f"Human selected {candidate['label']}; iteration closed.", "completedAt": _now()})
        status.pop("result", None)
        _atomic_json(root / "status.json", status)
        return record, destination
