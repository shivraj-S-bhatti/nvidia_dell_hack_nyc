"""NYC building evidence, local observations, and the rules that turn them into
recommendations — the "retrieval that changes behavior" half of issue #15.

The seed values are the exact records enumerated in issue #15 (BBL 1006720001 /
BIN 1012268) with their provenance, so a fresh checkout has real, cited evidence
offline. `nyc_data.refresh()` can re-pull them live; the demo posture uses these.

`derive_guidance` is the load-bearing part: change a retrieved record (e.g. drop
landmark status, or introduce a conflicting height) and the recommendation or the
verification task it emits changes. That is the acceptance criterion.
"""

from __future__ import annotations

from typing import Any

SNAPSHOT = "2026-08-22T00:00:00Z"  # event-day snapshot; refresh() restamps on live pull

BBL = "1006720001"
BIN = "1012268"


def seed_building_evidence() -> list[dict[str, Any]]:
    return [
        {
            "id": "mappluto",
            "category": "identity",
            "source": "MapPLUTO 26v1",
            "url": f"https://data.cityofnewyork.us/resource/64uk-42ks.json?bbl={BBL}",
            "retrieved_at": SNAPSHOT,
            "confidence": "official_record",
            "address": "601 West 26 Street",
            "year_built": 1931,
            "num_floors": 19,
            "gross_sqft": 1_835_150,
            "office_sqft": 1_814_700,
            "alteration_year": 2023,
            "demo_use": "identity and provenance only",
        },
        {
            "id": "landmark",
            "category": "landmark",
            "source": "LPC landmark report LP-1295",
            "url": "https://s-media.nyc.gov/agencies/lpc/lp/1295.pdf",
            "retrieved_at": SNAPSHOT,
            "confidence": "official_record",
            "landmarked": True,
            "designation": "Individual landmark, West Chelsea Historic District",
            "demo_use": "prefer reversible layout interventions over building-fabric change",
        },
        {
            "id": "footprint",
            "category": "height",
            "source": "Building Footprints",
            "url": f"https://data.cityofnewyork.us/resource/5zhs-2jue.json?base_bbl={BBL}",
            "retrieved_at": SNAPSHOT,
            "confidence": "derived_dataset",
            "roof_height_ft": 297.48,
            "demo_use": "flag source disagreement; not for floor-level egress math",
        },
        {
            "id": "env_review",
            "category": "height",
            "source": "City environmental review (FEIS)",
            "url": "https://www.nyc.gov/assets/planning/download/pdf/applicants/env-review/starrett-lehigh/02-feis.pdf",
            "retrieved_at": SNAPSHOT,
            "confidence": "official_record",
            "height_low_ft": 140,
            "height_high_ft": 219,
            "stories_low": 11,
            "stories_high": 19,
            "demo_use": "shows why verified plans beat silent data reconciliation",
        },
        {
            "id": "dob",
            "category": "compliance_context",
            "source": "DOB complaints and violations",
            "url": "https://data.cityofnewyork.us/Housing-Development/DOB-Violations/3h2n-5cm9",
            "retrieved_at": SNAPSHOT,
            "confidence": "official_record",
            "complaints_closed": 129,
            "violations_active": 2,
            "active_detail": "2025 facade item; 2003 elevator item",
            "demo_use": "facilities follow-up context only; not a 10th-floor egress hazard",
        },
        {
            "id": "fdny_eap",
            "category": "policy",
            "source": "FDNY comprehensive fire safety / emergency action plan requirement",
            "url": "https://nyc-business.nyc.gov/nycbusiness/description/comprehensive-fire-safety-and-emergency-action-plan",
            "retrieved_at": SNAPSHOT,
            "confidence": "official_record",
            "applies_to_large_office": True,
            "demo_use": "request the building's existing plan and FLS contacts, do not invent procedures",
        },
    ]


def seed_observations() -> list[dict[str, Any]]:
    # The user's local reports. Stored as UNVERIFIED. We never infer a future
    # alarm is false (issue #15 guardrail).
    return [
        {
            "id": "obs-false-alarms",
            "kind": "false_alarm_reports",
            "observed_at": SNAPSHOT,
            "source": "occupant report",
            "confidence": "unverified",
            "note": "repeated false alarms reported; not usable to predict any future alarm",
        },
        {
            "id": "obs-attendance",
            "kind": "high_attendance",
            "observed_at": SNAPSHOT,
            "source": "occupant report",
            "confidence": "unverified",
            "note": "attendance reported unexpectedly high; raises density sensitivity",
        },
    ]


def _by_category(evidence: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    return [e for e in evidence if e.get("category") == category]


def derive_guidance(
    evidence: list[dict[str, Any]], observations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Turn retrieved evidence into recommendation posture + verification tasks.

    This is deterministic and evidence-driven: the output changes when the inputs
    change, which is exactly what makes the retrieval "change behavior".
    """
    verification_tasks: list[str] = []

    # Landmark status steers toward reversible, movable changes.
    landmarked = any(e.get("landmarked") for e in _by_category(evidence, "landmark"))
    if landmarked:
        posture = "reversible_furniture_only"
        posture_reason = (
            "Landmark designation retrieved: prefer seating/movable-obstacle changes "
            "over any change to building fabric."
        )
    else:
        posture = "structural_options_allowed"
        posture_reason = "No landmark designation retrieved for this parcel."

    # Conflicting height records -> explicit verification task (never silent reconcile).
    heights: list[tuple[str, float]] = []
    for e in _by_category(evidence, "height"):
        for field in ("roof_height_ft", "height_high_ft", "height_low_ft"):
            if field in e:
                heights.append((e["source"], float(e[field])))
    if heights:
        lo = min(h for _, h in heights)
        hi = max(h for _, h in heights)
        if hi - lo > 20:  # ft; disagreement beyond survey noise
            srcs = sorted({s for s, _ in heights})
            verification_tasks.append(
                f"Reconcile conflicting height records ({lo:.0f}–{hi:.0f} ft across "
                f"{', '.join(srcs)}) against stamped plans; do not use footprint "
                "height for floor-level egress math."
            )

    # Large-office emergency-planning requirement -> request existing plan + FLS.
    procedure_note = ""
    if any(e.get("applies_to_large_office") for e in _by_category(evidence, "policy")):
        procedure_note = (
            "Request the building's existing emergency action plan and Fire and Life "
            "Safety contacts rather than inventing evacuation procedures."
        )

    # Observed attendance raises density sensitivity.
    density_note = ""
    if any(o.get("kind") == "high_attendance" for o in observations):
        density_note = (
            "Observed attendance is high (unverified): treat route-demand and "
            "congestion proxies as sensitivity cases, not fixed truth."
        )

    return {
        "recommendation_posture": posture,
        "posture_reason": posture_reason,
        "verification_tasks": verification_tasks,
        "procedure_note": procedure_note,
        "density_note": density_note,
    }
