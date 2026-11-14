"""Registered BIONZ X (``CXD90045``) target profiles.

Each body lives in its own module under ``src/a6400/targets/bodies/`` and is
registered here in ``DEFAULT_REGISTRY``. Every claim is tied to an
``EvidenceRef`` and ``TargetProfile`` refuses to construct unsourced claims.
"""
from __future__ import annotations

from src.a6400.targets.bodies import (
    ILCE_6100,
    ILCE_6400,
    ILCE_6600,
    ILCE_7M3,
    ZV_E10,
)
from src.a6400.targets.profile import TargetProfile, TargetRegistry

DEFAULT_REGISTRY = TargetRegistry((ILCE_6400, ZV_E10, ILCE_6100, ILCE_6600, ILCE_7M3))

__all__ = [
    "DEFAULT_REGISTRY",
    "ILCE_6100",
    "ILCE_6400",
    "ILCE_6600",
    "ILCE_7M3",
    "TargetProfile",
    "TargetRegistry",
    "ZV_E10",
]
