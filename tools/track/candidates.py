"""candidates.py -- Track's own stand-in candidate family and survivor manifest.

Lab (#12) and Factory (#13) are being built concurrently. Track must be provable
*today*, so this module authors a small family of occupancy masks directly from
the frozen fixture and emits a `track.survivor-manifest/1` document labelled
`producedBy: "track-fixture"`.

This is a stand-in for Factory's output, and it says so everywhere it appears. It
is NOT a second Factory: it runs exactly one check -- load-path connectivity --
and it runs it for one reason, so that the rejected candidate in the family is
rejected by a real measurement rather than by an assertion typed into a JSON
file. When Factory lands, `evaluate.py --survivors <factory manifest>` consumes
its manifest unchanged and this module stops being an input.

The candidates are defined by geometric *intent*. Nothing here reads a compliance
number, so the ranking that comes out is a measured result rather than a
self-fulfilling one.
"""
import os
import sys
from collections import deque

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import domain  # noqa: E402
import manifest as mf  # noqa: E402

STAND_IN_PRODUCER = "track-fixture"


def _grid_xz(transform):
    """Model-space (x, z) of every cell centre, as two (nely, nelx) arrays."""
    nelx, nely = int(transform["nelx"]), int(transform["nely"])
    xs = float(transform["x0"]) + (np.arange(nelx) + 0.5) * float(transform["hx"])
    zs = float(transform["z0"]) + (np.arange(nely) + 0.5) * float(transform["hz"])
    gx = np.repeat(xs[None, :], nely, axis=0)
    gz = np.repeat(zs[:, None], nelx, axis=1)
    return gx, gz


def _dist_to_segment(gx, gz, ax, az, bx, bz):
    """Perpendicular distance from every cell centre to segment AB."""
    vx, vz = bx - ax, bz - az
    denom = vx * vx + vz * vz
    if denom <= 0.0:
        return np.hypot(gx - ax, gz - az)
    t = ((gx - ax) * vx + (gz - az) * vz) / denom
    t = np.clip(t, 0.0, 1.0)
    return np.hypot(gx - (ax + t * vx), gz - (az + t * vz))


def _rect(gx, gz, x0, z0, x1, z1):
    return (gx >= x0) & (gx <= x1) & (gz >= z0) & (gz <= z1)


def _disk(gx, gz, cx, cz, r):
    return (gx - cx) ** 2 + (gz - cz) ** 2 <= r * r


def make_family(fx):
    """Four candidate masks derived from the frozen fixture's baseline.

    Returns a list of dicts: {'id', 'intent', 'mask'}. Protected (required-solid)
    cells are restored after every operation, so a candidate can only fail
    connectivity by severing the *web* between pads -- never by deleting a pad,
    which would be a fixture violation rather than a design one.
    """
    base = baseline_mask(fx)
    gx, gz = _grid_xz(fx.transform)
    prot = fx.protected
    pad_x, pad_z = fx.params["payloadPadMm"]
    mounts = [(c["x"], c["z"]) for c in fx.clusters]

    zmin, zmax = float(fx.transform["z0"]), float(fx.transform["zmax"])
    xmin, xmax = float(fx.transform["x0"]), float(fx.transform["xmax"])
    zspan = zmax - zmin

    fam = []

    # (a) Scallop the two long edges. These sit outside every payload-to-mount
    # load path, so this is the "cheap mass" hypothesis.
    cut = np.zeros_like(base, dtype=bool)
    for cz_edge in (zmin, zmax):
        for k in range(7):
            cx_s = xmin + (k + 0.5) * (xmax - xmin) / 7.0
            cut |= _disk(gx, gz, cx_s, cz_edge, 0.13 * zspan)
    fam.append({"id": "cand-a-edge-scallops",
                "intent": "scallop the two long edges, away from the "
                          "payload-to-mount paths",
                "mask": _apply(base, cut, prot)})

    # (b) Two windows straddling the payload pad, oriented across the diagonal
    # paths. The mass saving is comparable to (a); the placement is not.
    cut = np.zeros_like(base, dtype=bool)
    w, h = 0.16 * (xmax - xmin), 0.30 * zspan
    for sign in (-1.0, 1.0):
        cx_w = pad_x + sign * 0.20 * (xmax - xmin)
        cut |= _rect(gx, gz, cx_w - w / 2, pad_z - h / 2,
                     cx_w + w / 2, pad_z + h / 2)
    fam.append({"id": "cand-b-centre-window",
                "intent": "two windows either side of the payload pad, across "
                          "the diagonal load paths",
                "mask": _apply(base, cut, prot)})

    # (c) Keep only a rim plus bands joining the payload pad to each arm mount.
    # The aggressive-lightening hypothesis.
    band = np.zeros_like(base, dtype=bool)
    half = 0.055 * zspan
    for (mx, mz) in mounts:
        band |= _dist_to_segment(gx, gz, pad_x, pad_z, mx, mz) <= half
    rim = ~((gx > xmin + 0.045 * (xmax - xmin)) & (gx < xmax - 0.045 * (xmax - xmin))
            & (gz > zmin + 0.075 * zspan) & (gz < zmax - 0.075 * zspan))
    fam.append({"id": "cand-c-diagonal-truss",
                "intent": "rim plus four bands from payload pad to arm mounts, "
                          "everything else voided",
                "mask": _apply(base, ~(band | rim), prot)})

    # (d) Ring one arm mount with void. Visually it is still a plausible
    # lightening pattern; structurally the mount is an island.
    mx, mz = mounts[0]
    ring_r = float(fx.params["supportRadiusMm"]) + max(
        float(fx.transform["hx"]), float(fx.transform["hz"])) * 2.0
    cut = _disk(gx, gz, mx, mz, ring_r + 0.055 * zspan) & ~_disk(gx, gz, mx, mz, ring_r)
    fam.append({"id": "cand-d-severed-mount",
                "intent": "annular relief around one arm mount",
                "mask": _apply(base, cut, prot)})

    return fam


def baseline_mask(fx):
    """The fixture's rasterised baseline as a binary occupancy mask."""
    return domain.occupancy(fx.baseline_coverage,
                            fx.params["coverageThreshold"]).astype(np.uint8)


def _apply(base, cut, protected):
    out = base.copy()
    out[cut] = 0
    out[protected] = base[protected]      # never delete a pad
    return out


# --- the one check this stand-in runs -------------------------------------
def load_path_connected(mask, fx):
    """4-connected flood fill from the payload pad through solid cells.

    Seeded from every solid cell under the load pad and targeted at every solid
    cell under each arm-mount pad, because the geometric centre of a bolt pattern
    is a clearance hole, not material.

    Returns (ok, reached_mounts, total_mounts). A candidate whose load pad cannot
    reach every arm mount through material has no load path, and no compliance
    number computed on it would mean anything.
    """
    from scipy import ndimage

    solid = mask.astype(bool)
    seed = fx.load_pad & solid
    total = len(fx.support_pads)
    if not seed.any():
        return False, 0, total

    lbl, _ = ndimage.label(solid)          # 4-connectivity is the default
    live = set(np.unique(lbl[seed]).tolist()) - {0}
    reached = sum(1 for pad in fx.support_pads
                  if bool(live & (set(np.unique(lbl[pad & solid]).tolist()) - {0})))
    return reached == total, reached, total


def stand_in_manifest(fx, out_dir, run_id="track-fixture-run-1"):
    """Write masks + a schema-valid survivor manifest. Returns (doc, path)."""
    out_dir = os.path.abspath(out_dir)
    mask_dir = os.path.join(out_dir, "masks")
    os.makedirs(mask_dir, exist_ok=True)

    base_mask = baseline_mask(fx)
    base_ref = mf.write_mask(base_mask, os.path.join(mask_dir, "baseline.npy"))
    ok, reached, total = load_path_connected(base_mask, fx)
    if not ok:
        raise RuntimeError("baseline fails its own connectivity check "
                           "(%d/%d mounts reached) -- fix the fixture, not the check"
                           % (reached, total))

    def entry(cid, parent, ref, checks, notes):
        return {"candidateId": cid, "parentId": parent, "verdict": "pass",
                "mask": {"path": os.path.relpath(ref.path, out_dir),
                         "format": ref.format, "sha256": ref.sha256,
                         "shape": list(ref.shape)},
                "evidencePath": None, "factoryChecks": checks, "notes": notes}

    doc = {
        "schemaVersion": mf.SCHEMA_VERSION,
        "runId": run_id,
        "producedBy": STAND_IN_PRODUCER,
        "problemId": fx.params["fixtureId"],
        "problemHash": fx.hash(),
        "domainShape": [fx.nely, fx.nelx],
        "units": "mm",
        "baseline": entry(
            "baseline", None, base_ref,
            [{"check": "load-path-connectivity", "result": "pass",
              "measured": float(total), "tolerance": float(total),
              "units": "mounts reached"}],
            "unmodified BOTTOM-PLATE-S500 footprint, same domain and fixture"),
        "survivors": [],
        "rejected": [],
    }

    for cand in make_family(fx):
        ok, reached, total = load_path_connected(cand["mask"], fx)
        path = os.path.join(mask_dir, cand["id"] + ".npy")
        ref = mf.write_mask(cand["mask"], path)
        if ok:
            doc["survivors"].append(entry(
                cand["id"], "baseline", ref,
                [{"check": "load-path-connectivity", "result": "pass",
                  "measured": float(reached), "tolerance": float(total),
                  "units": "mounts reached"}],
                cand["intent"]))
        else:
            doc["rejected"].append({
                "candidateId": cand["id"], "parentId": "baseline",
                "verdict": "fail",
                "reasonCode": "STANDIN.LOAD_PATH_DISCONNECTED",
                "measured": float(reached), "tolerance": float(total),
                "units": "arm mounts reachable from the payload pad through material",
                "implicated": ["BOTTOM-PLATE-S500", "arm-mount-pads"],
                "evidencePath": os.path.relpath(path, out_dir),
            })

    path = os.path.join(out_dir, "survivors.json")
    mf.dump_manifest(doc, path)
    return doc, path
