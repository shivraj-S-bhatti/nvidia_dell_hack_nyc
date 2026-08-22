"""ExitTwin — privacy-preserving egress-risk triage twin (hackathon Attempt 2, issue #15).

The generative/LLM layer only parses intent and explains results. Every egress
number in the output contract is produced deterministically by `egress.compute`
so a scenario delta is reproducible and defensible. See README.md.
"""

from .contracts import InputContract, OutputContract
from .geometry import Layout, load_layout, geometry_revision
from .egress import compute

__all__ = [
    "InputContract",
    "OutputContract",
    "Layout",
    "load_layout",
    "geometry_revision",
    "compute",
]
