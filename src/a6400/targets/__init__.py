"""Multi-device Sony BIONZ X (``CXD90045``) target profiles.

The execution platform was built against one body (Sony ILCE-6400). This package makes
the per-body invariants explicit so other owners can join without forking the code:

    from src.a6400.targets import get_profile, list_profiles

    profile = get_profile("ilce_6400")
    profile.kallsyms["usb_gadgetcore_ioctl"]   # 0x602B8844, sourced from E0348
    profile.uipc_queues["usb_control"]         # 0x00CA8192

``list_profiles()`` returns every registered target. Stubs are returned too, with
``status == "unverified"`` and no claims, so a caller can never mistake "registered"
for "supported".

See ``docs/ADDING_A_BIONZX_CAMERA.md`` for how to add a body.
"""
from __future__ import annotations

from src.a6400.targets.catalog import (
    DEFAULT_REGISTRY,
    ILCE_6100,
    ILCE_6400,
    ILCE_6600,
    ILCE_7M3,
    ZV_E10,
)
from src.a6400.targets.profile import (
    PID_TIER_OBSERVED,
    PID_TIER_PROJECT_AUTHORED,
    PID_TIER_STOCK,
    STATUS_REFERENCE,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    SOC_BIONZ_X,
    TARGET_STATUSES,
    EvidenceRef,
    BootLayoutSpec,
    ModuleComponent,
    TargetProfile,
    TargetRegistry,
    USB_PID_TIERS,
    UsbIdentity,
    UsbPid,
)

__all__ = [
    "DEFAULT_REGISTRY",
    "PID_TIER_OBSERVED",
    "PID_TIER_PROJECT_AUTHORED",
    "PID_TIER_STOCK",
    "ILCE_6100",
    "ILCE_6400",
    "ILCE_6600",
    "ILCE_7M3",
    "SOC_BIONZ_X",
    "STATUS_REFERENCE",
    "STATUS_UNVERIFIED",
    "STATUS_VERIFIED",
    "TARGET_STATUSES",
    "USB_PID_TIERS",
    "ZV_E10",
    "EvidenceRef",
    "BootLayoutSpec",
    "ModuleComponent",
    "TargetProfile",
    "TargetRegistry",
    "UsbIdentity",
    "UsbPid",
    "get_profile",
    "list_profiles",
    "profile_ids",
    "registry_dict",
]


def get_profile(target_id: str) -> TargetProfile:
    """Return the registered profile for ``target_id`` (raises ``KeyError`` when unknown)."""
    return DEFAULT_REGISTRY.get(target_id)


def list_profiles() -> tuple[TargetProfile, ...]:
    """Every registered profile, ordered by ``target_id``."""
    return DEFAULT_REGISTRY.list()


def profile_ids() -> tuple[str, ...]:
    """Registered ``target_id`` values, ordered."""
    return DEFAULT_REGISTRY.ids()


def registry_dict() -> dict[str, dict]:
    """JSON-ready view of the whole registry (evidence paths included)."""
    return {profile.target_id: profile.as_dict() for profile in list_profiles()}
