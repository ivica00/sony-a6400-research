"""Sony ZV-E10 reference UVC-enabled target profile."""
from __future__ import annotations

from src.a6400.targets.bodies._common import (
    E0135,
    E0316,
    E0320,
    E0321,
    ZVE10_ENABLEMENT,
    ref,
)
from src.a6400.targets.profile import (
    STATUS_REFERENCE,
    EvidenceRef,
    ModuleComponent,
    TargetProfile,
)

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
        "firmware_version": ref(E0321, "inputs: extracted ZV-E10 2.03 firmware"),
        "kernel_version": ref(E0316, "vermagic equal for a6400 8.2.5.7 and ZV-E10 2.03 chains"),
        "kallsyms.usb_gadgetcore_register_driver": ref(E0135, "decoded ZV-E10 kallsyms: 0x602bcaac"),
        "kallsyms.startFuncDrv_fromIfClasses": ref(E0135, "decoded ZV-E10 function start: 0x602bd2ec"),
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
