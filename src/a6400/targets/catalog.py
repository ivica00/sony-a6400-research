"""Registered BIONZ X (``CXD90045``) target profiles.

Only the Sony ILCE-6400 is a *verified* execution target today. The ZV-E10 entry is a
reference component set (the UVC-enabled chain the a6400 lacks), and the remaining
bodies are declared stubs with **no claims** until an owner files evidence through
``docs/ADDING_A_BIONZX_CAMERA.md``.

Every address below is transcribed from a dated evidence record; the ``sources`` map
ties each claim to the record it came from, and ``TargetProfile`` refuses to construct
a profile with a claim that has no source.
"""
from __future__ import annotations

from src.a6400.targets.profile import (
    PID_TIER_OBSERVED,
    PID_TIER_PROJECT_AUTHORED,
    PID_TIER_STOCK,
    STATUS_REFERENCE,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    EvidenceRef,
    ModuleComponent,
    TargetProfile,
    TargetRegistry,
    UsbIdentity,
    UsbPid,
)

# ---- evidence records used below ------------------------------------------------
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
ZVE10_ENABLEMENT = "src/a6400/execution/zve10_uvc_enablement.py"


def _ref(path: str, detail: str) -> tuple[EvidenceRef, ...]:
    return (EvidenceRef(path=path, detail=detail),)


# ---------------------------------------------------------------------------------
# Primary verified target: Sony ILCE-6400 (a6400)
# ---------------------------------------------------------------------------------
ILCE_6400 = TargetProfile(
    target_id="ilce_6400",
    model_name="Sony ILCE-6400 (a6400)",
    status=STATUS_VERIFIED,
    soc_verified=True,
    firmware_version="8.2.5.7",
    live_build_version="8.2.6.0",
    kernel_version="3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7",
    kallsyms={
        # From the live read-only /proc/kallsyms read in E0348 (976,469 bytes).
        "usb_gadgetcore_ioctl": 0x602B8844,
        "usb_gadgetcore_register_driver": 0x602B8610,
        "usb_gadgetcore_unregister_driver": 0x602B8560,
        "usb_gcw_start": 0x602BD7F8,
        "usb_gcw_stop": 0x602BD834,
        "osal_snd_msg": 0x5F04916C,
        "osal_rcv_msg_tmo": 0x5F0494F0,
        "setup_req": 0x602B94A4,
        "make_config_desc": 0x602BBC54,
        "dma330_mem_transfer_async": 0x5F49D768,
    },
    uipc_queues={
        # Local user-space queues decoded in E0310; sync-channel handles in E0334.
        "usb_control": 0x00CA8192,
        "usb_bus_power": 0x012182EB,
        "bus_power": 0x012282F6,
        "buspower_event_lane": 0x012002DA,
        "usb_relay": 0x008F013A,
        "usb_control_sync_adjust": 0x00CA0288,
        "usb_control_sync_input": 0x00CA01A4,
    },
    usb=UsbIdentity(
        vid=0x054C,
        pids={
            # 0x0CA8 is in the stock descriptor set and is also the observed MSC identity.
            "mass_storage": UsbPid(0x0CA8, PID_TIER_STOCK),
            # 0x0CAA is physically observed in PC Remote but is not in the stock list.
            "pc_remote": UsbPid(0x0CAA, PID_TIER_OBSERVED),
            # 0x0322 is this project's authored composite identity (E0347), not a Sony PID.
            "uvc_composite": UsbPid(0x0322, PID_TIER_PROJECT_AUTHORED),
        },
        bcd_device=0x0200,
    ),
    modules={
        "devno.ko": ModuleComponent(
            size=4308,
            sha256="3b36fcea8687d7f29112a7008ce61fde9229679ebc24c65ec2d21cf3af632f56",
            role="device-node table; a6400 build has no /dev/usb/video or /dev/usb/audio rows",
        ),
        "usbg_buspower.ko": ModuleComponent(
            size=14068,
            sha256="81fee5ccc6b14bc9f46e7f8315308b2476ba056763bf16e84ccaf053e38cea41",
            role="USB bus-power module mapped by the application; present in the stock kmod set",
        ),
    },
    sources={
        "firmware_version": _ref(E0315, "inputs: extracted a6400 8.2.5.7 firmware (nflasha15 image)"),
        "live_build_version": _ref(E0348, "live kernel banner gcc tag: Sony CE Linux 8.2.6.0"),
        "kernel_version": _ref(E0316, "kernel vermagic observed on the a6400 8.2.5.7 module chain"),
        "kallsyms.usb_gadgetcore_ioctl": _ref(E0348, "live /proc/kallsyms: 0x602b8844 (entry-hook target)"),
        "kallsyms.usb_gadgetcore_register_driver": _ref(E0348, "live /proc/kallsyms: 0x602b8610"),
        "kallsyms.usb_gadgetcore_unregister_driver": _ref(E0348, "live /proc/kallsyms: 0x602b8560"),
        "kallsyms.usb_gcw_start": _ref(E0348, "live /proc/kallsyms: 0x602bd7f8"),
        "kallsyms.usb_gcw_stop": _ref(E0348, "live /proc/kallsyms: 0x602bd834"),
        "kallsyms.osal_snd_msg": _ref(E0348, "live /proc/kallsyms: 0x5f04916c"),
        "kallsyms.osal_rcv_msg_tmo": _ref(E0348, "live /proc/kallsyms: 0x5f0494f0"),
        "kallsyms.setup_req": _ref(E0348, "live /proc/kallsyms: 0x602b94a4"),
        "kallsyms.make_config_desc": _ref(E0348, "live /proc/kallsyms: 0x602bbc54"),
        "kallsyms.dma330_mem_transfer_async": _ref(E0348, "live /proc/kallsyms: 0x5f49d768"),
        "uipc_queues.usb_control": _ref(E0310, "UsbControl receiver queue 0x00CA8192 (bit-15 local queue)"),
        "uipc_queues.usb_bus_power": _ref(E0310, "UsbBusPower local queue 0x012182EB"),
        "uipc_queues.bus_power": _ref(E0310, "BusPower local queue 0x012282F6"),
        "uipc_queues.buspower_event_lane": _ref(E0310, "buspower event lane 0x012002DA (a power lane, not connect)"),
        "uipc_queues.usb_relay": _ref(E0310, "0x008F013A is the UFW relay/ULOG queue, not UsbControl inbound"),
        "uipc_queues.usb_control_sync_adjust": _ref(E0334, "sync callback handle 4109 -> queue 0x00CA0288 (ADJ channel)"),
        "uipc_queues.usb_control_sync_input": _ref(E0334, "sync callback handle 4110 -> queue 0x00CA01A4 (input callback)"),
        "usb": (
            EvidenceRef(path=E0152, detail="Mass Storage 054c:0ca8, single configuration/interface"),
            EvidenceRef(path=E0207, detail="PC Remote 054C:0CAA composite PC Remote enumeration"),
            EvidenceRef(path=E0158, detail="bcdDevice 0x0200 retained on the owned identity"),
            EvidenceRef(path=E0347, detail="project-authored composite identity 054C:0322 parent + MI_00/MI_01"),
        ),
        "modules.devno.ko": _ref(E0320, "a6400 devno.ko sha256; major 248 minors 0..31, no video/audio rows"),
        "modules.usbg_buspower.ko": _ref(E0068, "usbg_buspower.ko size 14,068 bytes and SHA-256 as mapped by the app"),
    },
    boundaries=(
        "Addresses are per-boot kernel/library values; only kallsyms addresses are ASLR-free. "
        "Library bases and the gadgetcore fd change between boots.",
        "A resolved symbol is presence evidence, not loadability or callability proof.",
        "The uvc_composite USB PID is the project-authored composite identity, not a stock Sony PID.",
        "The extracted 8.2.5.7 image and the live 8.2.6.0 build are different bases: offline "
        "addresses come from the image, live kallsyms values from the boot that was read.",
        "usbg_cmn.ko is not in the runtime /proc/modules set: the usbg_cmn_* symbols appear as "
        "local copies in usbg_sen/stillimage/buspower/storage, so no runtime export is claimed here.",
        "Module hashes/sizes not listed in the catalog are local artifact measurements, not profile claims.",
    ),
    notes="Primary verified execution target.",
)


# ---------------------------------------------------------------------------------
# Reference UVC-enabled chain: Sony ZV-E10
# ---------------------------------------------------------------------------------
ZV_E10 = TargetProfile(
    target_id="zv_e10",
    model_name="Sony ZV-E10",
    status=STATUS_REFERENCE,
    soc_verified=True,
    firmware_version="2.03",
    kernel_version="3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7",
    kallsyms={
        "usb_gadgetcore_register_driver": 0x602BCAAC,
        "startFuncDrv_fromIfClasses": 0x602BD2EC,
    },
    uipc_queues={},
    usb=None,
    modules={
        "usbg_video.ko": ModuleComponent(
            size=20668,
            sha256="d385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb",
            role="UVC gadget video driver (iso-in, DMA330, /dev/usb/video)",
        ),
        "usbg_audio.ko": ModuleComponent(
            size=20456,
            sha256="8f73572784aab15da291c9f311a945d4ec56d2dd4162218164bc2aa18cc5fae0",
            role="UVC audio gadget driver",
        ),
        "libInfraStreamingUsb.so": ModuleComponent(
            size=52524,
            sha256="0a9448e364e8f014db02edc8e164470c70f2d2143ce5de74697e9ffba697cce8",
            role="UVC host start/stop, PROBE/COMMIT state machine, VideoEsManager",
        ),
        "libInfraUsbCmn.so": ModuleComponent(
            size=94612,
            sha256="af830315ce51c38b010995f2147d556286364323734f64b877fcc3bb1a916c02",
            role="CUsbGadgetStreaming, PAL/NTSC tables, video buffer API",
        ),
        "devno.ko": ModuleComponent(
            size=4368,
            sha256="273db657a8e2c9c8752b0ace56817357ddea38285a52b5cb7007a3fcf9df33c1",
            role="device-node table with /dev/usb/audio 248:32 and /dev/usb/video 248:33",
        ),
    },
    sources={
        "firmware_version": _ref(E0321, "inputs: extracted ZV-E10 2.03 firmware"),
        "kernel_version": _ref(E0316, "vermagic equal for a6400 8.2.5.7 and ZV-E10 2.03 chains"),
        "kallsyms.usb_gadgetcore_register_driver": _ref(E0135, "decoded ZV-E10 kallsyms: 0x602bcaac"),
        "kallsyms.startFuncDrv_fromIfClasses": _ref(E0135, "decoded ZV-E10 function start: 0x602bd2ec"),
        "modules.usbg_video.ko": (
            EvidenceRef(path=E0320, detail="ZV-E10 UVC module chain inventory"),
            EvidenceRef(path=ZVE10_ENABLEMENT, detail="ZVE10_UVC_COMPONENTS size+sha256 pin"),
        ),
        "modules.usbg_audio.ko": (
            EvidenceRef(path=E0321, detail="ZV-E10 UVC enablement manifest components"),
            EvidenceRef(path=ZVE10_ENABLEMENT, detail="ZVE10_UVC_COMPONENTS size+sha256 pin"),
        ),
        "modules.libInfraStreamingUsb.so": (
            EvidenceRef(path=E0321, detail="ZV-E10 UVC enablement manifest components"),
            EvidenceRef(path=ZVE10_ENABLEMENT, detail="ZVE10_UVC_COMPONENTS size+sha256 pin"),
        ),
        "modules.libInfraUsbCmn.so": (
            EvidenceRef(path=E0320, detail="library present in both chains, hashes differ"),
            EvidenceRef(path=ZVE10_ENABLEMENT, detail="ZVE10_UVC_COMPONENTS size+sha256 pin"),
        ),
        "modules.devno.ko": (
            EvidenceRef(path=E0320, detail="ZV-E10 devno.ko registers /dev/usb/video 248:33 and /dev/usb/audio 248:32"),
            EvidenceRef(path=ZVE10_ENABLEMENT, detail="ZVE10_UVC_COMPONENTS size+sha256 pin"),
        ),
    },
    boundaries=(
        "kallsyms addresses for usb_gadgetcore_ioctl, osal_snd_msg, osal_rcv_msg_tmo and setup_req "
        "have not been recovered for the reference image; they stay unknown here.",
        "The UVC chain is reference data: no physical load, no overlay execution and no UVC frame is "
        "claimed for the a6400 (see E0321/E0322).",
        "Equal vermagic and matching exported symbol names are not loadability proof.",
    ),
    notes=(
        "Reference UVC-enabled CXD90045 chain. Offline component comparison only; "
        "see docs/evidence/0346-uvc-ptp-composite-transport-roadmap.md for the transport plan."
    ),
)


def _stub(target_id: str, model_name: str) -> TargetProfile:
    return TargetProfile(
        target_id=target_id,
        model_name=model_name,
        status=STATUS_UNVERIFIED,
        soc_verified=False,
        boundaries=(
            "Unverified stub: no model, firmware, kernel, kallsyms, UIPC, or USB claim exists in this "
            "repository for this body; do not reuse the a6400 values.",
            "SoC/firmware generation is the owner's report, not a repository observation.",
            "Register it through docs/ADDING_A_BIONZX_CAMERA.md (offline firmware symbols plus a "
            "read-only /proc probe) before any execution claim.",
        ),
        notes="Declared stub; contributes no claims and no compatibility statement.",
    )


ILCE_6100 = _stub("ilce_6100", "Sony ILCE-6100 (a6100)")
ILCE_6600 = _stub("ilce_6600", "Sony ILCE-6600 (a6600)")
ILCE_7M3 = _stub("ilce_7m3", "Sony ILCE-7M3 (a7 III)")

DEFAULT_REGISTRY = TargetRegistry((ILCE_6400, ZV_E10, ILCE_6100, ILCE_6600, ILCE_7M3))
