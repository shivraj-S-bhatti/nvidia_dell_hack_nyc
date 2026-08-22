"""Deterministic artifact serialization and hashing."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_array(array: np.ndarray) -> str:
    canonical = np.ascontiguousarray(array, dtype=np.float32)
    return hashlib.sha256(canonical.tobytes(order="C")).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.write_text(serialized, encoding="utf-8")


def write_density(path: Path, density: np.ndarray) -> dict[str, Any]:
    canonical = validate_density(density)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, canonical, allow_pickle=False)
    preview_path = path.with_suffix(".png")
    preview = np.rint((1.0 - canonical) * 255.0).astype(np.uint8)
    Image.fromarray(preview, mode="L").save(preview_path, optimize=False, compress_level=9)
    return {
        "array": {"path": path.name, "sha256": sha256_file(path)},
        "preview": {"path": preview_path.name, "sha256": sha256_file(preview_path)},
        "content_sha256": sha256_array(canonical),
        "shape": list(canonical.shape),
        "dtype": str(canonical.dtype),
        "minimum": float(canonical.min()),
        "maximum": float(canonical.max()),
        "mean": float(canonical.mean(dtype=np.float64)),
    }


def write_manifest(output_root: Path) -> None:
    manifest_path = output_root / "manifest.json"
    entries = []
    for path in sorted(item for item in output_root.rglob("*") if item.is_file() and item != manifest_path):
        entries.append(
            {
                "path": path.relative_to(output_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    write_json(manifest_path, {"algorithm": "sha256", "artifacts": entries})


def validate_density(density: np.ndarray) -> np.ndarray:
    array = np.asarray(density, dtype=np.float32)
    if array.ndim != 2:
        raise ValueError(f"density field must be 2-D, got shape {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError("density field contains non-finite values")
    minimum = float(array.min())
    maximum = float(array.max())
    if minimum < 0.0 or maximum > 1.0:
        raise ValueError(f"density field is outside [0, 1]: min={minimum}, max={maximum}")
    if not math.isfinite(float(array.mean(dtype=np.float64))):
        raise ValueError("density field mean is not finite")
    return np.ascontiguousarray(array)
