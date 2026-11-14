"""Sony ILCE-6400A (a6400A) offline-qualified reference target profile."""
from __future__ import annotations

from src.a6400.targets.bodies._common import E0506, E0509, ref
from src.a6400.targets.profile import (
    EvidenceRef,
    ModuleComponent,
    PID_TIER_OBSERVED,
    PID_TIER_STOCK,
    STATUS_REFERENCE,
    TargetProfile,
    UsbIdentity,
    UsbPid,
)

ILCE_6400A = TargetProfile(
    target_id="ilce_6400a",
    model_name="Sony ILCE-6400A (a6400A)",
    status=STATUS_REFERENCE,
    soc_verified=True,
    product_code="0032858730",
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
            "stock_0f0e": UsbPid(0x0F0E, PID_TIER_STOCK),
            "stock_0f0f": UsbPid(0x0F0F, PID_TIER_STOCK),
            "mass_storage": UsbPid(0x0F0F, PID_TIER_OBSERVED),
        },
        bcd_device=0x0200,
    ),
    modules={
        "devno.ko": ModuleComponent(
            size=4308,
            sha256="74096566ca4132ef3e947dc122427b6f3044ae5ab2d1657f5c6eb12945b1efa5",
            role="packaged device-node table: 88 rows, 17 USB rows, no video/audio row",
        ),
        "usb_extcmd.ko": ModuleComponent(
            size=14796,
            sha256="d47d05ec891d18c8582baf19e413967c5d3fd5c36438d76f6d2e8a7f112428e3",
            role="packaged native USB command driver; not identity-equivalent to the original a6400",
        ),
        "libusbcmd.so": ModuleComponent(
            size=15996,
            sha256="23b94deb094d31f160cfe1d46330f2425e94d4801dfccb66720c4cf4b81cfb7e",
            role="packaged USB API; original packing function exercised offline on fixture buffers",
        ),
    },
    sources={
        "product_code": ref(E0509, "physical GetModelInfo: opaque five-byte code 0032858730; not updater fdat.model"),
        "firmware_version": ref(E0506, "own config.yaml fdat.version 1.01; dat.crypterName CXD90045"),
        "kernel_version": ref(E0506, "own devno.ko vermagic; packaged main kernel build 8.2.7.6"),
        "kallsyms.usb_gadgetcore_ioctl": ref(E0506, "own kernel 9d51ab60...: 0x602bc864"),
        "kallsyms.usb_gadgetcore_register_driver": ref(E0506, "own kernel 9d51ab60...: 0x602bc630"),
        "kallsyms.usb_gadgetcore_unregister_driver": ref(E0506, "own kernel 9d51ab60...: 0x602bc584"),
        "kallsyms.usb_gcw_start": ref(E0506, "own kernel 9d51ab60...: 0x602c1818"),
        "kallsyms.usb_gcw_stop": ref(E0506, "own kernel 9d51ab60...: 0x602c1854"),
        "kallsyms.setup_req": ref(E0506, "own kernel 9d51ab60...: 0x602bd4c4"),
        "kallsyms.make_config_desc": ref(E0506, "own kernel 9d51ab60...: 0x602bfc74"),
        "usb": (
            EvidenceRef(E0506, "own package's eight normal descriptor pairs; operating modes not inferred"),
            EvidenceRef(E0506, "read-only Windows PnP: Mass Storage 054C:0F0F, REV_0200, USBSTOR"),
        ),
        "modules.devno.ko": ref(E0506, "own packaged module size, SHA-256 and relocation-aware table decode"),
        "modules.usb_extcmd.ko": ref(E0506, "own packaged module size/SHA-256; old identity guard must not be bypassed"),
        "modules.libusbcmd.so": ref(E0506, "own packaged library size/SHA-256 and source-identified Unicorn packing trace"),
    },
    boundaries=(
        "Reference profile only: not a verified full-emulator or camera-deployment target.",
        "SoC identity is the package's CXD90045 statement and ARM machine descriptor, not a live /proc/cpuinfo read.",
        "The camera's displayed 1.01 version and USB identity do not establish its live kernel/module bytes.",
        "All seven listed USB kernel entry addresses differ from the original a6400; do not reuse old hooks or checkpoints.",
        "The native debugger bootstrap is not qualified for this body. usb_extcmd.ko fails the old strict identity comparison.",
        "The updater prefix stops at unsupported UART MMIO after 3001 instructions; no kernel boot, shell or GUI is claimed.",
        "uipc_queues stays empty and live_build_version stays unknown; no live kernel, memory or partition reads were performed.",
        "Stock descriptor membership does not identify a USB mode. Only Mass Storage was observed; PC Remote and UVC were not tested.",
        "The observed wire product_code 0032858730 and updater fdat.model 0x81030017 are distinct namespaces.",
    ),
    notes=(
        "E0506 qualifies a future BIONZ X research candidate. E0507 maps main/updater builds, "
        "static partition/MMIO contracts and moved exception hooks; no physical dumps or "
        "first-class runnable-machine profile are claimed. E0509 verifies normal model information "
        "through unchanged Windows USBSTOR; the earlier delayed-read boundary is superseded, "
        "but root/debugger/dump access remains unverified."
    ),
)
