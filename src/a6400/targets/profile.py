"""BIONZ X (``CXD90045``) target-profile schema.

A :class:`TargetProfile` is a *declaration of verified, per-body invariants*: the
model identity, the firmware/kernel versions it was read from, the kernel symbol
addresses and UIPC queue IDs the execution platform needs, its USB identity and its
hash-pinned module components.

Design rules (enforced in ``__post_init__``, not by convention):

* Every populated field is a **claim** and every claim must reference at least one
  :class:`EvidenceRef`. A claim without a source cannot be constructed.
* An ``unverified`` profile may not carry any claim at all. New bodies start as an
  explicit stub; nothing is guessed to make a table look complete.
* Only one SoC family exists here: a profile *is* a BIONZ X ``CXD90045`` body, and
  ``soc_verified`` records whether that body-level identity is evidence-backed.

Nothing in this module touches a camera, a firmware image or the network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

SOC_BIONZ_X = "CXD90045"

#: A profile that carries only evidence-backed values.
STATUS_VERIFIED = "verified"
#: A profile used as a reference component set (not runnable as a target).
STATUS_REFERENCE = "reference"
#: A declared stub: identity only, no claims, explicitly not verified.
STATUS_UNVERIFIED = "unverified"

TARGET_STATUSES = (STATUS_VERIFIED, STATUS_REFERENCE, STATUS_UNVERIFIED)

TARGET_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

_UINT32_MAX = 0xFFFFFFFF


@dataclass(frozen=True)
class EvidenceRef:
    """A file in this repository plus the specific detail it supports."""

    path: str
    detail: str

    def __post_init__(self) -> None:
        if not self.path or not self.detail:
            raise ValueError("an evidence reference needs a repo-relative path and a detail")


@dataclass(frozen=True)
class ModuleComponent:
    """A hash-pinned module or library the target is known to contain/reference."""

    size: int
    sha256: str
    role: str

    def __post_init__(self) -> None:
        if self.size <= 0:
            raise ValueError(f"module size must be positive, got {self.size}")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError(f"module sha256 must be 64 lowercase hex characters, got {self.sha256!r}")
        if not self.role:
            raise ValueError("module role must say what the component does")


#: PID present in the stock USB descriptor set read from the firmware image.
PID_TIER_STOCK = "stock_descriptor"
#: PID physically observed on the host bus in a given camera mode.
PID_TIER_OBSERVED = "observed"
#: PID introduced by this project's own composite module/overlay, not by Sony.
PID_TIER_PROJECT_AUTHORED = "project_authored"
USB_PID_TIERS = (PID_TIER_STOCK, PID_TIER_OBSERVED, PID_TIER_PROJECT_AUTHORED)


@dataclass(frozen=True)
class UsbPid:
    """One USB product id, with the tier that justifies it.

    The tier keeps a stock descriptor value from being conflated with a host-observed
    mode identity or with this project's authored composite identity.
    """

    value: int
    tier: str

    def __post_init__(self) -> None:
        if not 0 < self.value <= 0xFFFF:
            raise ValueError(f"pid must be a 16-bit integer, got {self.value:#x}")
        if self.tier not in USB_PID_TIERS:
            raise ValueError(f"pid tier must be one of {USB_PID_TIERS}, got {self.tier!r}")


@dataclass(frozen=True)
class UsbIdentity:
    """USB identity of the body in the modes this project has observed or authored."""

    vid: int
    pids: Mapping[str, UsbPid]
    bcd_device: int | None = None

    def __post_init__(self) -> None:
        if not 0 < self.vid <= 0xFFFF:
            raise ValueError(f"vid must be a 16-bit integer, got {self.vid:#x}")
        for name in self.pids:
            if not name:
                raise ValueError("every usb pid needs a mode name")
        if self.bcd_device is not None and not 0 <= self.bcd_device <= 0xFFFF:
            raise ValueError(f"bcd_device must be a 16-bit integer, got {self.bcd_device:#x}")


@dataclass(frozen=True)
class TargetProfile:
    """Verified per-body invariants and the evidence that backs each claim."""

    target_id: str
    model_name: str
    status: str
    soc_verified: bool
    soc: str = SOC_BIONZ_X
    #: Opaque Sony GetModelInfo wire code, not the updater container's model id.
    product_code: str | None = None
    firmware_version: str | None = None
    live_build_version: str | None = None
    kernel_version: str | None = None
    kallsyms: Mapping[str, int | None] = field(default_factory=dict)
    uipc_queues: Mapping[str, int | None] = field(default_factory=dict)
    usb: UsbIdentity | None = None
    modules: Mapping[str, ModuleComponent] = field(default_factory=dict)
    sources: Mapping[str, tuple[EvidenceRef, ...]] = field(default_factory=dict)
    boundaries: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not TARGET_ID_PATTERN.match(self.target_id):
            raise ValueError(f"target_id must be lower snake case, got {self.target_id!r}")
        if not self.model_name:
            raise ValueError(f"{self.target_id}: model_name is required")
        if self.status not in TARGET_STATUSES:
            raise ValueError(f"{self.target_id}: status must be one of {TARGET_STATUSES}, got {self.status!r}")
        if self.soc != SOC_BIONZ_X:
            raise ValueError(f"{self.target_id}: only the {SOC_BIONZ_X} BIONZ X family is modeled, got {self.soc!r}")
        if self.status == STATUS_VERIFIED and not self.soc_verified:
            raise ValueError(f"{self.target_id}: a verified profile must set soc_verified")
        if self.status == STATUS_UNVERIFIED and self.soc_verified:
            raise ValueError(f"{self.target_id}: an unverified stub must not claim a verified SoC identity")

        for name, value in self.kallsyms.items():
            if value is not None and not 0 < value <= _UINT32_MAX:
                raise ValueError(f"{self.target_id}: kallsyms[{name!r}] must be a 32-bit address, got {value!r}")
        for name, value in self.uipc_queues.items():
            if value is not None and not 0 < value <= _UINT32_MAX:
                raise ValueError(f"{self.target_id}: uipc_queues[{name!r}] must be a 32-bit id, got {value!r}")

        claims = self.claims()
        missing = sorted(set(claims) - set(self.sources))
        if missing:
            raise ValueError(
                f"{self.target_id}: claims without an evidence source: {missing}; "
                "either add the source or leave the field unknown"
            )
        unsourced = sorted(set(self.sources) - set(claims))
        if unsourced:
            raise ValueError(
                f"{self.target_id}: evidence sources for fields that are not populated: {unsourced}"
            )
        for claim, refs in self.sources.items():
            if not refs:
                raise ValueError(f"{self.target_id}: claim {claim!r} has an empty evidence list")

        if self.status == STATUS_UNVERIFIED:
            if claims:
                raise ValueError(
                    f"{self.target_id}: an unverified stub must carry no claims, found {sorted(claims)}"
                )
            if not self.boundaries:
                raise ValueError(f"{self.target_id}: an unverified stub must state its boundaries")
        if self.status == STATUS_VERIFIED and not any(value is not None for value in self.kallsyms.values()):
            raise ValueError(f"{self.target_id}: a verified profile needs at least one resolved kallsyms address")

    def claims(self) -> dict[str, object]:
        """Every populated field mapped to the claim name used in ``sources``."""
        found: dict[str, object] = {}
        if self.product_code is not None:
            found["product_code"] = self.product_code
        if self.firmware_version is not None:
            found["firmware_version"] = self.firmware_version
        if self.live_build_version is not None:
            found["live_build_version"] = self.live_build_version
        if self.kernel_version is not None:
            found["kernel_version"] = self.kernel_version
        for name, value in self.kallsyms.items():
            if value is not None:
                found[f"kallsyms.{name}"] = value
        for name, value in self.uipc_queues.items():
            if value is not None:
                found[f"uipc_queues.{name}"] = value
        if self.usb is not None:
            found["usb"] = self.usb
        for name, component in self.modules.items():
            found[f"modules.{name}"] = component
        return found

    def as_dict(self) -> dict[str, object]:
        """JSON-ready view; unknown (``None``) values are kept explicit."""
        return {
            "target_id": self.target_id,
            "model_name": self.model_name,
            "status": self.status,
            "soc": self.soc,
            "soc_verified": self.soc_verified,
            "product_code": self.product_code,
            "firmware_version": self.firmware_version,
            "live_build_version": self.live_build_version,
            "kernel_version": self.kernel_version,
            "kallsyms": dict(self.kallsyms),
            "uipc_queues": dict(self.uipc_queues),
            "usb": None
            if self.usb is None
            else {
                "vid": self.usb.vid,
                "pids": {
                    name: {"value": pid.value, "tier": pid.tier}
                    for name, pid in self.usb.pids.items()
                },
                "bcd_device": self.usb.bcd_device,
            },
            "modules": {
                name: {"size": component.size, "sha256": component.sha256, "role": component.role}
                for name, component in self.modules.items()
            },
            "sources": {
                claim: [{"path": ref.path, "detail": ref.detail} for ref in refs]
                for claim, refs in self.sources.items()
            },
            "boundaries": list(self.boundaries),
            "notes": self.notes,
        }


class TargetRegistry:
    """Immutable registry of target profiles keyed by ``target_id``."""

    def __init__(self, profiles: tuple[TargetProfile, ...]):
        if not profiles:
            raise ValueError("a target registry needs at least one profile")
        seen: dict[str, TargetProfile] = {}
        for profile in profiles:
            if profile.target_id in seen:
                raise ValueError(f"duplicate target_id {profile.target_id!r}")
            seen[profile.target_id] = profile
        self._profiles = seen

    def get(self, target_id: str) -> TargetProfile:
        try:
            return self._profiles[target_id]
        except KeyError:
            known = ", ".join(self.ids())
            raise KeyError(f"unknown target {target_id!r}; registered targets: {known}") from None

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))

    def list(self) -> tuple[TargetProfile, ...]:
        return tuple(self._profiles[target_id] for target_id in self.ids())

    def by_status(self, status: str) -> tuple[TargetProfile, ...]:
        if status not in TARGET_STATUSES:
            raise ValueError(f"unknown status {status!r}; expected one of {TARGET_STATUSES}")
        return tuple(profile for profile in self.list() if profile.status == status)
