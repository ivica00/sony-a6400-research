"""Sony ILCE-7M3 (a7 III) offline-sourced target profile."""
from __future__ import annotations

from src.a6400.targets.bodies._common import E0482, ILCE_6XXX_BOUNDARIES, ref
from src.a6400.targets.profile import (
    PID_TIER_STOCK,
    STATUS_REFERENCE,
    TargetProfile,
    UsbIdentity,
    UsbPid,
)

ILCE_7M3 = TargetProfile(
    target_id="ilce_7m3",
    model_name="Sony ILCE-7M3 (a7 III)",
    status=STATUS_REFERENCE,
    soc_verified=True,
    firmware_version="4.04",
    kernel_version="3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7",
    kallsyms={
        "usb_gadgetcore_ioctl": 0x602BC864,
        "usb_gadgetcore_register_driver": 0x602BC630,
        "usb_gadgetcore_unregister_driver": 0x602BC584,
        "usb_gcw_start": 0x602C1818,
        "usb_gcw_stop": 0x602C1854,
        "setup_req": 0x602BD4C4,
        "make_config_desc": 0x602BFC74,
    },
    uipc_queues={},
    usb=UsbIdentity(
        vid=0x054C,
        pids={
            "stock_0448": UsbPid(0x0448, PID_TIER_STOCK),
            "stock_047d": UsbPid(0x047D, PID_TIER_STOCK),
            "stock_07c7": UsbPid(0x07C7, PID_TIER_STOCK),
            "stock_07c8": UsbPid(0x07C8, PID_TIER_STOCK),
            "stock_0bee": UsbPid(0x0BEE, PID_TIER_STOCK),
            "stock_0bef": UsbPid(0x0BEF, PID_TIER_STOCK),
            "stock_0bfe": UsbPid(0x0BFE, PID_TIER_STOCK),
            "stock_0bff": UsbPid(0x0BFF, PID_TIER_STOCK),
            "stock_0c01": UsbPid(0x0C01, PID_TIER_STOCK),
            "stock_0c02": UsbPid(0x0C02, PID_TIER_STOCK),
        },
    ),
    modules={},
    sources={
        "firmware_version": ref(E0482, "packaged updater 4.04; config.yaml model 0x71030014"),
        "kernel_version": ref(E0482, "vermagic in this body's own vmlinux.bin (build 8.2.7.6, 2026-05-02)"),
        "kallsyms.usb_gadgetcore_ioctl": ref(E0482, "decoded from this body's vmlinux.bin 175df4fc..."),
        "kallsyms.usb_gadgetcore_register_driver": ref(E0482, "decoded from this body's vmlinux.bin 175df4fc..."),
        "kallsyms.usb_gadgetcore_unregister_driver": ref(E0482, "decoded from this body's vmlinux.bin 175df4fc..."),
        "kallsyms.usb_gcw_start": ref(E0482, "decoded from this body's vmlinux.bin 175df4fc..."),
        "kallsyms.usb_gcw_stop": ref(E0482, "decoded from this body's vmlinux.bin 175df4fc..."),
        "kallsyms.setup_req": ref(E0482, "decoded from this body's vmlinux.bin 175df4fc..."),
        "kallsyms.make_config_desc": ref(E0482, "decoded from this body's vmlinux.bin 175df4fc..."),
        "usb": ref(E0482, "normalUsbDescriptors in this body's config.yaml; 10 pairs, vid 0x54C"),
    },
    boundaries=ILCE_6XXX_BOUNDARIES + (
        "devno.ko (3,988 B, 65933cda...) publishes 17 /dev/usb nodes and no video/audio row, so a "
        "kernel-side UVC node does not exist on this body (E0482 section 3, E0479).",
        "The stock id set does not include 0x0CA8, which the a6400 records as its mass-storage "
        "identity; do not assume one mass-storage pid across the family.",
    ),
    notes=(
        "Offline-sourced from its own packaged updater. This is the model the owner's issue #7 "
        "named; the a7 III page exposes ten per-version changelog entries (E0481)."
    ),
)
