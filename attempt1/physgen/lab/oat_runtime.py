"""Native OptimizeAnyTopology inference wrapper."""

from __future__ import annotations

from dataclasses import dataclass
import time
from pathlib import Path
from typing import Any

import numpy as np

from .artifacts import sha256_array, validate_density
from .problem import CanonicalProblem


@dataclass(frozen=True)
class OATMeasurements:
    model_load_seconds: float
    cold_seconds: float
    warm_seconds: float
    peak_gpu_allocated_bytes: int
    peak_gpu_reserved_bytes: int
    cuda_free_before_bytes: int
    cuda_free_after_bytes: int
    cuda_total_bytes: int
    deterministic_replay: bool
    replay_hashes: tuple[str, ...]


def generate_density_family(
    problem: CanonicalProblem,
    *,
    oat_root: Path,
    ae_model: Path,
    ldm_model: Path,
    seed: int,
    count: int,
    sampling_steps: int,
    device: str,
) -> tuple[list[np.ndarray], OATMeasurements, dict[str, Any]]:
    """Generate and immediately replay one seeded family through OAT's API."""
    if count < 3:
        raise ValueError("OAT runtime proof requires at least three candidates")
    if sampling_steps < 1:
        raise ValueError("sampling_steps must be positive")
    for label, path in (("OAT source", oat_root), ("NFAE", ae_model), ("LDM", ldm_model)):
        if not path.exists():
            raise FileNotFoundError(f"{label} path is missing: {path}")

    import sys

    source = str(oat_root)
    if source not in sys.path:
        sys.path.insert(0, source)

    import torch
    from PIL import Image
    from OAT.DataUtils import DiffusionCollator, NFAECollator, OpenTO
    from OAT.Models import CTOPUNet, NFAE
    from OAT.Pipelines import DDIMPipeline, OATPipeline

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but PyTorch cannot see a CUDA device")
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True)

    height, width = problem.grid_shape
    blank = Image.new("1", (width, height), color=0)
    dataset = OpenTO(
        [
            {
                "topology": blank,
                "volume fraction": problem.material_fraction,
                "boundary conditions": problem.oat_boundary_conditions(),
                "loads": problem.oat_loads(),
            }
        ],
        full_sampling=True,
    )
    collator = DiffusionCollator(
        unconditional_prob=0.0,
        inference=True,
        inference_collator=NFAECollator(zero_centering=False, full_sampling=True, coords_only=True),
    )
    conditions, decoder_batch = collator([dataset[0]])

    if device == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        free_before, total = torch.cuda.mem_get_info()
    else:
        free_before = total = 0

    started = time.perf_counter()
    load_started = time.perf_counter()
    ae = NFAE.from_pretrained(str(ae_model), local_files_only=True).to(device=device, dtype=dtype).eval()
    ldm = CTOPUNet.from_pretrained(str(ldm_model), local_files_only=True).to(device=device, dtype=dtype).eval()
    _sync(torch, device)
    model_load_seconds = time.perf_counter() - load_started
    pipeline = OATPipeline(diffusion_model=ldm, nfae=ae, DDIM=DDIMPipeline())

    first = _infer(
        torch,
        pipeline,
        decoder_batch,
        conditions,
        seed=seed,
        count=count,
        sampling_steps=sampling_steps,
        device=device,
        dtype=dtype,
    )
    _sync(torch, device)
    cold_seconds = time.perf_counter() - started

    warm_started = time.perf_counter()
    replay = _infer(
        torch,
        pipeline,
        decoder_batch,
        conditions,
        seed=seed,
        count=count,
        sampling_steps=sampling_steps,
        device=device,
        dtype=dtype,
    )
    _sync(torch, device)
    warm_seconds = time.perf_counter() - warm_started

    first_arrays = [validate_density(item) for item in first]
    replay_arrays = [validate_density(item) for item in replay]
    expected_shape = problem.grid_shape
    if any(item.shape != expected_shape for item in first_arrays + replay_arrays):
        shapes = [item.shape for item in first_arrays + replay_arrays]
        raise RuntimeError(f"OAT returned unexpected density shapes: {shapes}; expected {expected_shape}")
    first_hashes = tuple(sha256_array(item) for item in first_arrays)
    replay_hashes = tuple(sha256_array(item) for item in replay_arrays)

    if device == "cuda":
        peak_allocated = torch.cuda.max_memory_allocated()
        peak_reserved = torch.cuda.max_memory_reserved()
        free_after, _ = torch.cuda.mem_get_info()
    else:
        peak_allocated = peak_reserved = free_after = 0

    model_info = {
        "ae_class": type(ae).__name__,
        "ae_parameters": sum(parameter.numel() for parameter in ae.parameters()),
        "ldm_class": type(ldm).__name__,
        "ldm_parameters": sum(parameter.numel() for parameter in ldm.parameters()),
        "device": device,
        "dtype": str(dtype),
        "sampling_method": "DDIM",
        "sampling_steps": sampling_steps,
        "classifier_free_guidance": 1.0,
    }
    measurements = OATMeasurements(
        model_load_seconds=model_load_seconds,
        cold_seconds=cold_seconds,
        warm_seconds=warm_seconds,
        peak_gpu_allocated_bytes=peak_allocated,
        peak_gpu_reserved_bytes=peak_reserved,
        cuda_free_before_bytes=free_before,
        cuda_free_after_bytes=free_after,
        cuda_total_bytes=total,
        deterministic_replay=first_hashes == replay_hashes,
        replay_hashes=replay_hashes,
    )
    return first_arrays, measurements, model_info


def _infer(torch: Any, pipeline: Any, decoder_batch: Any, conditions: Any, *, seed: int, count: int, sampling_steps: int, device: str, dtype: Any) -> list[np.ndarray]:
    context = torch.autocast(device_type="cuda", dtype=dtype) if device == "cuda" else _NullContext()
    with torch.inference_mode(), context:
        predictions, _ = pipeline.inference(
            neural_field_inputs=decoder_batch,
            conditions=conditions,
            n_samples=count,
            num_sampling_steps=sampling_steps,
            classifier_free_guidance=1.0,
            ddpm=False,
            random_seed=seed,
            clamp_latents=False,
            remap_latents=False,
        )
    return [prediction.float().numpy().squeeze() for prediction in predictions[0]]


def _sync(torch: Any, device: str) -> None:
    if device == "cuda":
        torch.cuda.synchronize()


class _NullContext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: Any) -> None:
        return None
