"""Importing this package populates the verb registry.

Order matters only in that ``product`` and ``camera`` register module aliases
pointing at modules defined earlier.
"""

from __future__ import annotations

from . import camera, core, flow, imageproc, product, serialbus, shell, uiverbs, visa
from .legacy import adopt, adopt_directory

__all__ = [
    "camera", "core", "flow", "imageproc", "product", "serialbus", "shell",
    "uiverbs", "visa", "adopt", "adopt_directory", "summary",
]


def summary() -> dict[str, int]:
    """Verb count per module -- used by ``ngwart verbs`` and the About box."""
    from ..engine.registry import REGISTRY

    out: dict[str, int] = {}
    for spec in REGISTRY.all():
        out[spec.module] = out.get(spec.module, 0) + 1
    return dict(sorted(out.items()))
