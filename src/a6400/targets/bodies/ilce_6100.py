"""Sony ILCE-6100 (a6100) offline-sourced target profile."""
from __future__ import annotations

from src.a6400.targets.bodies._common import E0482, ILCE_6XXX_BOUNDARIES, ref
from src.a6400.targets.profile import (
    PID_TIER_STOCK,
    STATUS_REFERENCE,
    TargetProfile,
    UsbIdentity,
    UsbPid,
)

ILCE_6100 = TargetProfile(
    target_id="ilce_6100",
    model_name="Sony ILCE-6100 (a6100)",
    status=STATUS_REFERENCE,
    soc_verified=True,
    firmware_version="1.01",
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
            "stock_0bfe": UsbPid(0x0BFE, PID_TIER_STOCK),
            "stock_0bff": UsbPid(0x0BFF, PID_TIER_STOCK),
            "stock_0ca7": UsbPid(0x0CA7, PID_TIER_STOCK),
            "stock_0ca8": UsbPid(0x0CA8, PID_TIER_STOCK),
            "stock_0d0d": UsbPid(0x0D0D, PID_TIER_STOCK),
            "stock_0d0e": UsbPid(0x0D0E, PID_TIER_STOCK),
            "stock_0d11": UsbPid(0x0D11, PID_TIER_STOCK),
            "stock_0d12": UsbPid(0x0D12, PID_TIER_STOCK),
            "stock_0f0a": UsbPid(0x0F0A, PID_TIER_STOCK),
            "stock_0f0b": UsbPid(0x0F0B, PID_TIER_STOCK),
        },
    ),
    modules={},
    sources={
        "firmware_version": ref(E0482, "packaged updater 1.01; config.yaml model 0x81030018"),
        "kernel_version": ref(E0482, "vermagic in this body's own vmlinux.bin (build 8.2.7.6, 2026-05-02)"),
        "kallsyms.usb_gadgetcore_ioctl": ref(E0482, "decoded from this body's vmlinux.bin 51c1289c..."),
        "kallsyms.usb_gadgetcore_register_driver": ref(E0482, "decoded from this body's vmlinux.bin 51c1289c..."),
        "kallsyms.usb_gadgetcore_unregister_driver": ref(E0482, "decoded from this body's vmlinux.bin 51c1289c..."),
        "kallsyms.usb_gcw_start": ref(E0482, "decoded from this body's vmlinux.bin 51c1289c..."),
        "kallsyms.usb_gcw_stop": ref(E0482, "decoded from this body's vmlinux.bin 51c1289c..."),
        "kallsyms.setup_req": ref(E0482, "decoded from this body's vmlinux.bin 51c1289c..."),
        "kallsyms.make_config_desc": ref(E0482, "decoded from this body's vmlinux.bin 51c1289c..."),
        "usb": ref(E0482, "normalUsbDescriptors in this body's config.yaml; 12 pairs, vid 0x54C"),
    },
    boundaries=ILCE_6XXX_BOUNDARIES + (
        "devno.ko (4,308 B, 74096566...) publishes 17 /dev/usb nodes and no video/audio row, so a "
        "kernel-side UVC node does not exist on this body (E0482 section 3, E0479).",
    ),
    notes="Offline-sourced from its own packaged updater; no live probe has been run on this body.",
)
