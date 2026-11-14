"""Per-body compatibility registry for the native Sony USB debugger.

Each qualified body/firmware entry pins the exact ``libusbcmd.so`` digest and
the metadata-normalized ``usb_extcmd.ko`` digest verified via
``compare_metadata_only``. Adding a new BIONZ X body requires pulling its
``usb_extcmd.ko`` and ``libusbcmd.so`` (read-only), verifying ABI/metadata
equivalence, and adding a ``DebuggerTargetSpec`` entry here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Mapping

from tools.research.elf_metadata_identity import (
    compare_metadata_only,
    normalize_elf_metadata,
)

# Shared normalized usb_extcmd.ko SHA-256 (after zeroing .note.gnu.build-id and .comment)
# and byte-identical libusbcmd.so SHA-256 observed across ILCE-6400 (2.00) and ILCE-7C (2.00).
VERIFIED_USB_EXTCMD_SIZE = 14808
VERIFIED_USB_EXTCMD_NORMALIZED_SHA256 = (
    "9d7c97bdb8015cde3882d39379a18ebb2b0678ba5b517e50e620a5f54019d0d8"
)
VERIFIED_LIBUSBCMD_SIZE = 15948
VERIFIED_LIBUSBCMD_SHA256 = (
    "9fbf3339792e40caa73faa63d6b2dfa962ca4c47853320b49ff589595283ba71"
)

DEFAULT_PAYLOAD_DAEMON = "devcrashday_a6400/a6400_usb_debugd.elf"
DEFAULT_PAYLOAD_LAUNCHER = "devcrashday_a6400/hook/usb_debug_launcher.so"

DEBUGGER_RELEASE_REPO = "ivica00/sony-a6400-research"
DEBUGGER_RELEASE_TAG = "usb-debugger-binaries-v1"
PAYLOAD_ASSETS: Mapping[str, Mapping[str, object]] = {
    DEFAULT_PAYLOAD_DAEMON: {
        "filename": "a6400_usb_debugd.elf",
        "size": 11384,
        "sha256": "c5bb9c143a0e354c6474c186f61afb1fca2fd775742372a38a0f1301e1838f5f",
        "url": f"https://github.com/{DEBUGGER_RELEASE_REPO}/releases/download/{DEBUGGER_RELEASE_TAG}/a6400_usb_debugd.elf",
    },
    DEFAULT_PAYLOAD_LAUNCHER: {
        "filename": "usb_debug_launcher.so",
        "size": 6284,
        "sha256": "a6f368cc3ce4efc00c1b4f094271a0b99aebba9a7940492c60dd7c50033fa5e4",
        "url": f"https://github.com/{DEBUGGER_RELEASE_REPO}/releases/download/{DEBUGGER_RELEASE_TAG}/usb_debug_launcher.so",
    },
}
PMCA_ARCHIVE_URL = "https://github.com/ma1co/Sony-PMCA-RE/archive/refs/heads/master.zip"


@dataclass(frozen=True)
class DebuggerTargetSpec:
    """Declarative compatibility contract for native USB debugger deployment."""

    target_id: str
    model_name: str
    firmware_versions: tuple[str, ...]
    qualification: str
    usb_extcmd_size: int
    usb_extcmd_normalized_sha256: str
    usb_extcmd_exact_sha256s: tuple[str, ...]
    usb_extcmd_reference_paths: tuple[str, ...]
    libusbcmd_size: int
    libusbcmd_sha256: str
    payload_daemon: str = DEFAULT_PAYLOAD_DAEMON
    payload_launcher: str = DEFAULT_PAYLOAD_LAUNCHER
    notes: str = ""


USB_DEBUGGER_TARGETS: Mapping[str, DebuggerTargetSpec] = {
    "ilce_6400": DebuggerTargetSpec(
        target_id="ilce_6400",
        model_name="ILCE-6400",
        firmware_versions=("2.00",),
        qualification="verified",
        usb_extcmd_size=VERIFIED_USB_EXTCMD_SIZE,
        usb_extcmd_normalized_sha256=VERIFIED_USB_EXTCMD_NORMALIZED_SHA256,
        usb_extcmd_exact_sha256s=(
            "fca6bfcf5e0c3c4098d33b810a2788eac1e8d8bbefe072e8792d203d69854719",
        ),
        usb_extcmd_reference_paths=(
            "firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/usb_extcmd.ko",
            "artifacts/hardware/ilce-7c-2.00-pull/usb_extcmd.ko",
        ),
        libusbcmd_size=VERIFIED_LIBUSBCMD_SIZE,
        libusbcmd_sha256=VERIFIED_LIBUSBCMD_SHA256,
        notes="Primary verified hardware target (E0092, E0401).",
    ),
    "ilce_7c": DebuggerTargetSpec(
        target_id="ilce_7c",
        model_name="ILCE-7C",
        firmware_versions=("2.00",),
        qualification="verified",
        usb_extcmd_size=VERIFIED_USB_EXTCMD_SIZE,
        usb_extcmd_normalized_sha256=VERIFIED_USB_EXTCMD_NORMALIZED_SHA256,
        usb_extcmd_exact_sha256s=(
            "db7383e9ad731cc23d5334dffdd4756e53dbb6aa9e32039dc503f2e2d8a246ef",
        ),
        usb_extcmd_reference_paths=(
            "artifacts/hardware/ilce-7c-2.00-pull/usb_extcmd.ko",
            "firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/usb_extcmd.ko",
        ),
        libusbcmd_size=VERIFIED_LIBUSBCMD_SIZE,
        libusbcmd_sha256=VERIFIED_LIBUSBCMD_SHA256,
        notes=(
            "Verified on live ILCE-7C (FW 2.00): libusbcmd.so is byte-identical to ILCE-6400; "
            "usb_extcmd.ko is metadata-only equivalent; info/ps/exec verified in normal MSC."
        ),
    ),
}


def list_debugger_targets() -> tuple[str, ...]:
    """Return sorted target IDs registered for native USB debugger deployment."""
    return tuple(sorted(USB_DEBUGGER_TARGETS))


def get_debugger_target(target_id: str) -> DebuggerTargetSpec:
    """Look up a registered debugger target spec by ID."""
    key = target_id.strip().lower().replace("-", "_")
    if key not in USB_DEBUGGER_TARGETS:
        known = ", ".join(list_debugger_targets())
        raise KeyError(
            f"Unknown debugger target {target_id!r}; qualified targets: {known}"
        )
    return USB_DEBUGGER_TARGETS[key]


def find_debugger_target_by_model(
    model_name: str,
    firmware_version: str | None = None,
) -> DebuggerTargetSpec | None:
    """Match a camera MSC model string (and optional firmware) to a registered spec."""
    normalized_model = model_name.strip().upper()
    if not normalized_model:
        return None
    fw = firmware_version.strip() if firmware_version else None
    candidates = [
        spec for spec in USB_DEBUGGER_TARGETS.values()
        if spec.model_name.upper() == normalized_model
    ]
    if not candidates:
        return None
    if fw is not None:
        for spec in candidates:
            if fw in spec.firmware_versions:
                return spec
    return candidates[0]


def load_reference_usb_extcmd(spec: DebuggerTargetSpec, root: Path) -> tuple[Path | None, bytes | None]:
    """Load the first existing reference ``usb_extcmd.ko`` for ``spec``, if present."""
    for rel in spec.usb_extcmd_reference_paths:
        candidate = root / rel
        if candidate.is_file():
            return candidate, candidate.read_bytes()
    return None, None


def verify_camera_debugger_compatibility(
    spec: DebuggerTargetSpec,
    actual_ko: bytes,
    actual_lib: bytes,
    reference_ko: bytes | None = None,
) -> dict:
    """Verify pulled camera ``usb_extcmd.ko`` and ``libusbcmd.so`` against ``spec``."""
    actual_ko_sha = hashlib.sha256(actual_ko).hexdigest()
    actual_lib_sha = hashlib.sha256(actual_lib).hexdigest()

    lib_match = (
        len(actual_lib) == spec.libusbcmd_size
        and actual_lib_sha == spec.libusbcmd_sha256
    )

    if reference_ko is not None:
        ko_comparison = compare_metadata_only(actual_ko, reference_ko)
        ko_norm = ko_comparison.get("normalized_camera_sha256")
        ko_equiv = bool(ko_comparison.get("equivalent"))
    else:
        norm_info = normalize_elf_metadata(actual_ko)
        ko_norm = norm_info.get("normalized_sha256")
        ko_equiv = bool(norm_info.get("valid")) and ko_norm == spec.usb_extcmd_normalized_sha256
        ko_comparison = {
            "equivalent": ko_equiv,
            "normalized_camera_sha256": ko_norm,
            "normalized_expected_sha256": spec.usb_extcmd_normalized_sha256,
            "reason": norm_info.get("reason"),
        }

    ko_match = (
        len(actual_ko) == spec.usb_extcmd_size
        and ko_equiv
        and ko_norm == spec.usb_extcmd_normalized_sha256
    )

    reasons: list[str] = []
    if not lib_match:
        reasons.append(
            f"libusbcmd.so mismatch (got {len(actual_lib)} B / {actual_lib_sha}, "
            f"expected {spec.libusbcmd_size} B / {spec.libusbcmd_sha256})"
        )
    if not ko_match:
        reasons.append(
            "usb_extcmd.ko mismatch: "
            + str(ko_comparison.get("reason") or f"normalized={ko_norm}")
        )

    return {
        "compatible": lib_match and ko_match,
        "target_id": spec.target_id,
        "model_name": spec.model_name,
        "qualification": spec.qualification,
        "libusbcmd_match": lib_match,
        "usb_extcmd_match": ko_match,
        "exact_usb_extcmd_match": actual_ko_sha in spec.usb_extcmd_exact_sha256s,
        "actual_usb_extcmd_bytes": len(actual_ko),
        "actual_usb_extcmd_sha256": actual_ko_sha,
        "actual_libusbcmd_bytes": len(actual_lib),
        "actual_libusbcmd_sha256": actual_lib_sha,
        "ko_comparison": ko_comparison,
        "reason": "; ".join(reasons) if reasons else None,
    }
