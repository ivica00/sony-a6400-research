"""Shared evidence path constants and helpers for per-body target profiles."""
from __future__ import annotations

from src.a6400.targets.profile import EvidenceRef

E0068 = "docs/evidence/0068-gpio-contract-and-usbg-buspower-module-boundary.md"
E0135 = "docs/evidence/0135-uvc-port-device-node-and-gadget-callback-abi.md"
E0152 = "docs/evidence/0152-uvc-ptp-coexistence-boundary.md"
E0158 = "docs/evidence/0158-owned-usb-identity-and-native-string-serialization.md"
E0207 = "docs/evidence/0207-first-physical-composite-pcremote-enumeration.md"
E0310 = "docs/evidence/0310-team-cycle-buspower-lane-and-second-path.md"
E0315 = "docs/evidence/0315-usb-ptp-descriptor-firmware-evidence.md"
E0316 = "docs/evidence/0316-zve10-uvc-chain-inventory-and-a6400-enablement.md"
E0320 = "docs/evidence/0320-zve10-devno-usb-video-node-and-guest-usb-video-contract.md"
E0321 = "docs/evidence/0321-zve10-uvc-enablement-manifest.md"
E0334 = "docs/evidence/0334-sync-callback-lane-is-usb-adjustment.md"
E0347 = "docs/evidence/0347-host-bindable-composite-pid0322.md"
E0348 = "docs/evidence/0348-uvc-monitor-architecture-probe-and-reference-client.md"
E0416 = "docs/evidence/0416-cxd90045-qemu-updater-bringup.md"
E0477 = "docs/evidence/0477-bionz-x-platform-map-13-updaters.md"
E0479 = "docs/evidence/0479-uvc-is-a-module-package-delta.md"
E0482 = "docs/evidence/0482-three-stubs-gain-sourced-values.md"
ZVE10_ENABLEMENT = "src/a6400/execution/zve10_uvc_enablement.py"

ILCE_6XXX_BOUNDARIES = (
    "Offline packaged firmware only: a camera in the field may run a different build, and these "
    "addresses are exact for the packaged image named in E0482 table 1, not for an arbitrary boot.",
    "A resolved kallsyms symbol is presence evidence, not loadability or callability proof.",
    "uipc_queues is empty: the queue handles the a6400 profile records come from a live "
    "/proc/osal/uipc read and are per-boot, so no offline value is claimed here.",
    "soc_verified rests on the package's own crypterName: CXD90045 statement, which is stronger "
    "than a model name and weaker than reading /proc/cpuinfo on the body.",
    "The kernel symbols match the a6400's on the USB gadget-core region; that is a measured "
    "region equality on distinct images, not evidence that these bodies share an execution target. "
    "Their device tables and command tables differ (E0477).",
)


def ref(path: str, detail: str) -> tuple[EvidenceRef, ...]:
    return (EvidenceRef(path=path, detail=detail),)
