"""Data provider for project status visualizations.

Two independent outputs share this module:

* ``get_a6400_project_status_data()`` feeds the treemap PNG
  (``tools/research/generate_status_image.py`` -> ``docs/images/status_a6400.png``).
  Its integer "done/total" counters deliberately keep their original scope.
* ``STATUS_SNAPSHOT`` feeds the narrative status card
  (``tools/research/render_research_status.py`` -> ``docs/images/research-status.svg``)
  and is the single source of truth that ``tests/test_research_status_sync.py``
  checks against ``README.md``.

``STATUS_SNAPSHOT`` carries plain claims, evidence references and the recorded
suite count; it never converts them into a compatibility percentage.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.a6400.visualization.status_renderer import Category, Panel

ROOT = Path(__file__).resolve().parents[2]


def get_anyps5_reference_data() -> list[Panel]:
    """Reconstructs the reference AnyPS5 status dataset matching the user's reference image."""
    sys_cats = [
        Category("libc", 1480, 1620),
        Category("libkernel", 680, 740),
        Category("Agc", 290, 290),
        Category("Json2", 180, 180),
        Category("Net", 140, 155),
        Category("Http", 125, 135),
        Category("Font", 110, 120),
        Category("Pad", 85, 95),
        Category("Audi", 80, 90),
        Category("Vid", 60, 60),
        Category("Lib", 55, 60),
        Category("Usbd", 50, 58),
        Category("Ngs", 48, 55),
        Category("NpM", 42, 48),
        Category("Ajm", 38, 44),
        Category("Rtc", 35, 35),
        Category("Hmd", 30, 36),
        Category("Ssl", 25, 30),
        Category("Ampr", 40, 52),
        Category("NpUn", 35, 45),
    ]

    gpu_cats = [
        Category("VOPC", 160, 160),
        Category("DS", 145, 145),
        Category("VOP1", 135, 135),
        Category("MUBUF", 125, 125),
        Category("SOP1", 115, 115),
        Category("MIMG", 110, 110),
        Category("VOP3", 100, 100),
        Category("GLOBAL", 90, 90),
        Category("SOP2", 80, 80),
        Category("SOPP", 55, 55),
        Category("VOP3P", 50, 50),
        Category("FLAT", 45, 45),
        Category("VOP2", 40, 40),
        Category("SOPK", 30, 30),
        Category("SMEM", 25, 25),
        Category("SOPC", 20, 20),
        Category("SCRATC", 16, 16),
        Category("MTBUF", 10, 10),
    ]

    # Force exact 3480/3853 for system libraries matching the reference
    cur_done = sum(c.done for c in sys_cats)
    cur_total = sum(c.total for c in sys_cats)
    sys_cats[0].done += (3480 - cur_done)
    sys_cats[0].total += (3853 - cur_total)

    # Force exact 1166/1166 for GPU shaders matching the reference
    cur_gpu = sum(c.total for c in gpu_cats)
    gpu_cats[0].done += (1166 - cur_gpu)
    gpu_cats[0].total += (1166 - cur_gpu)

    return [
        Panel(title="System libraries*", badge_label="libraries*", categories=sys_cats),
        Panel(title="GPU shader instructions", badge_label="shaders", categories=gpu_cats),
    ]


def get_a6400_project_status_data() -> list[Panel]:
    """Compiles real evidence-backed status metrics for the Sony a6400 execution project."""
    boot_trace_path = ROOT / "artifacts/inventory/boot-mount-trace.json"
    boot_mounts_count = 22
    devnodes_count = 88
    if boot_trace_path.exists():
        try:
            with open(boot_trace_path, encoding="utf-8") as f:
                data = json.load(f)
                boot_mounts_count = len(data.get("init_mounts_table", [])) or 22
                devnodes_count = data.get("devnodes_summary", {}).get("total_entries", 88)
        except Exception:
            pass

    guest_os_cats = [
        Category("preset_backup", 4, 4, weight=18.0),        # BK4PresetState, PresetBackedBackupService, write/read dispatch, authentic adr=0x35c6000
        Category("backup_boot", 3, 3, weight=18.0),         # Backup_load=0, arch_phys_to_cache RAM map, and Backup_write_core pipeline
        Category("backup_guard", 1, 1, weight=16.0),        # Stops before unsupplied backup replies; no service or persistent-state compatibility claim
        Category("inode_meta", 2, 2, weight=16.0),          # Opt-in regular rdev and selected read-only ext2 image timestamps; no physical mount claim
        Category("clone_return", 1, 1, weight=16.0),         # Child resumes original syscall-return code; guest libc owns dispatch/exit
        Category("tls_switch", 2, 2, weight=16.0),           # Hardware TPIDRURO and software TLS agree across thread switches
        Category("anon_discard", 1, 1, weight=16.0),        # Opt-in MADV_DONTNEED on owned private anonymous pages only
        Category("boot_commands", 7, 7, weight=18.0),       # Seven original bootin phase-command dispatch windows; no process launch or full boot claimed
        Category("arm_syscalls", 36, 36, weight=35.0),       # brk, uname, open, read, close, stat64, mmap2, mprotect, munmap, set_tls, set_tid_address, set_robust_list, rt_sigaction, rt_sigprocmask, ugetrlimit, ioctl, fcntl64, fstat64, write, writev, clone, gettid, prctl, sched_setscheduler, sched_setaffinity, futex, exit, nanosleep
        Category("ext2_guest_fs", 20, 20, weight=35.0),      # image lookup, inodes, stat64, verified st_dev, preflight, devnode boundary, cdev recognition
        Category("guest_mmap", 14, 14, weight=30.0),         # page alignment, MAP_FIXED, file-backed loading, protection, initial mapping registration, uipc shared pool
        Category("uipc_ipc_cdev", 13, 13, weight=28.0),      # connect, valloc, snd_sync_msg, free_msg, reg_msg_queue_cb, snd_sync_direct, wai_sem_tmo, sig_sem, stat_sem, snd_msg, rcv_msg_tmo, stat_msgq, dynamic_id
        Category("threads_nptl", 5, 5, weight=28.0),         # main thread + 4 Sony infrastructure threads (THREAD_INFRA0..3)
        Category("guest_stdio", 3, 3, weight=25.0),          # /dev/console metadata, TCGETS isatty, stdout/stderr vector logging
        Category("task94_phases", 1, 8, weight=28.0),        # Phase 1 event dispatch observed; remaining subsystem initialization is unverified
        Category("app_milestone", 1, 1, weight=25.0),        # im.elf entry point reached at 0x9140 (Thumb 0x9141) at instr 2,073,233
        Category("kuser_helpers", 5, 5, weight=25.0),        # 0xffff0000 high vectors, __kuser_cmpxchg64, memory_barrier, get_tls, version 5
        Category("kernel_identity", 6, 6, weight=18.0),       # UTS uname strings, arch, image verification
        Category("probe_policies", 9, 9, weight=20.0),       # stop, brk, brk-uname, files, metadata, mmap, kuser, uipc, threads
        Category("linker_contracts", 12, 12, weight=30.0),    # ld-linux.so: all 12 shared libraries loaded, relocated, RELRO protected, call_init completed
        Category("event_dispatch", 8, 8, weight=30.0),       # 0x9a5c callback: phase 1..8 event IDs, authentic event injection, 094_0 state transitions
        Category("imdb_plugins", 0, 198, weight=35.0),      # 198 static definitions; dependency opens and component log markers do not establish plugin initialization
        Category("bounded_run", 1, 1, weight=40.0), # One bounded original-code execution milestone; instruction counts are not completion units
    ]

    hardware_cats = [
        Category("entropy_device", 2, 4, weight=16.0),      # Image 1:9 identity and original dispatch; runtime pool/output unverified
        Category("emmc_driver", 18, 22, weight=32.0),        # RingBuffer, Dec_Scramble, worker kthread, major 252
        Category("boot_mounts", 15, boot_mounts_count, weight=30.0), # dnflasha7, nflasha7 fallback, usr, etc
        Category("devno_nodes", 28, devnodes_count, weight=38.0),    # flash block nodes, sio, dmac, ldec
        Category("kernel_drivers", 10, 37, weight=26.0),     # drivers1 (devno, dmac, ldec, emmc) + drivers2
        Category("flash_parts", 7, 30, weight=25.0),         # nflasha1-30: verified partitions
        Category("display_subsys", 2, 4, weight=30.0),       # Read-only OSD A/B capture (E0298) then GPES BAR/IRQ contracts + opt-in engine model (E0313/E0314); live guest rendering, GPU execution and camera comparison unverified
        Category("sdhci_dma", 10, 10, weight=20.0),         # CMD17/18/24/25, SDHCI_PRESENT_STATE (0x2c), ADMA2 8-byte descriptors (0x58), scatterlist pipeline
        Category("etc_overlay", 4, 5, weight=16.0),          # vfat rw detection, empty rootfs, preload boundary
    ]

    return [
        Panel(title="Guest OS & Linux ARM Contracts", badge_label="contracts", categories=guest_os_cats),
        Panel(title="Hardware & Storage Subsystems", badge_label="hardware", categories=hardware_cats),
    ]



# ---------------------------------------------------------------------------
# Documentation synchronization data (README <-> docs/images/research-status.svg)
# ---------------------------------------------------------------------------
#
# Each field is a claim that is also stated in README.md. tests/test_research_status_sync.py
# fails when the README, this snapshot and the generated SVG disagree on the latest
# evidence ID, the recorded suite count or the latest evidence record on disk.
#
# Update procedure for a new milestone:
#   1. write the evidence record under docs/evidence/,
#   2. add/refresh a card here and bump ``latest``, ``as_of`` and ``suite.test_count``,
#   3. run the full suite once and record its "Ran N tests" value,
#   4. regenerate the card:  python -m tools.research.render_research_status --write
#   5. the suite must stay green (tests/test_research_status_sync.py enforces the rest).


@dataclass(frozen=True)
class EvidenceRef:
    """One dated, bounded result shown on the status card.

    ``tier`` states what kind of evidence the claim rests on; the renderer prints it
    verbatim so an offline contract can never look like a physical observation.
    """

    evidence_id: str
    path: str
    date: str
    title: str
    demonstrated: str
    boundary: str
    tier: str


@dataclass(frozen=True)
class SuiteRecord:
    """The recorded full-suite result this documentation refresh is pinned to."""

    test_count: int
    recorded_at: str
    evidence_id: str
    command: str


@dataclass(frozen=True)
class StatusSnapshot:
    """Single source of truth for the narrative status card and its README sync."""

    schema_version: int
    as_of: str
    latest: EvidenceRef
    headline: str
    cards: tuple[EvidenceRef, ...]
    suite: SuiteRecord
    footer: str

    @property
    def title(self) -> str:
        return f"Sony a6400 research status through {self.latest.evidence_id}"

    @property
    def description(self) -> str:
        return (
            f"{self.suite.test_count} tests recorded passing. Offline original-code execution, "
            "read-only physical observation and authored demonstrations are reported separately. "
            "No emulator GUI frame and no UVC frame are claimed."
        )


STATUS_SNAPSHOT = StatusSnapshot(
    schema_version=1,
    as_of="2026-11-12",
    latest=EvidenceRef(
        evidence_id="E0424",
        path="docs/evidence/0424-cxd90045-pl011-primecell-and-ash-shell.md",
        date="2026-11-12",
        title="PL011 PrimeCell IDs, live ttyAM0 console and cmdline-override discovery",
        demonstrated=(
            "Added ARM PL011 PrimeCell identification registers at 0xF2000000+0xFE0..0xFFC "
            "(PeriphID 0x00141011, PCellID 0xB105F00D); the kernel then registered the console: "
            "uart0 ttyAM0 at MMIO 0xf2000000 (irq 150) is AMBA/PL011, console [ttyAM0] enabled. Live "
            "serial capture works (52,976 bytes) and scripted RX injection is read by the guest "
            "(help -> monitor help, shell -> 'shell is disabled', commands parsed). The live log also "
            "reveals setup_arch(): invalid cmdline override @ 0x60103000. Using default cmdline."
        ),
        boundary=(
            "init=/bin/ash still cannot be applied: Sony's setup_arch rejects the boot-params content "
            "at 0x103000 and uses the built-in kemco CONFIG_CMDLINE (init=/sbin/init), so boot panics "
            "with 'No init found' before userspace; the Sony override object format is still undecoded. "
            "The updater monitor's own shell is compiled out (EM_DEBUG). No /bin/ash shell claim."
        ),
        tier="OFFLINE BOUNDED UNICORN BRING-UP",
    ),
    headline="1476 tests recorded passing | No verified emulator GUI frame",
    cards=(
        EvidenceRef(
            evidence_id="E0406",
            path="docs/evidence/0406-bcm4339-wifi-bt-tuning-surface-readonly.md",
            date="2026-11-12",
            title="BCM4339 Wi-Fi/BT static surface",
            demonstrated=(
                "Hash-identified BCM4339 firmware and kernel modules from preserved images; string/symbol/table tuning "
                "surface recorded offline."
            ),
            boundary=(
                "No live runtime defaults, regulatory state or radio behaviour claimed; no camera access."
            ),
            tier="OFFLINE STATIC IMAGE",
        ),
        EvidenceRef(
            evidence_id="E0405",
            path="docs/evidence/0405-option-a-offline-preflight.md",
            date="2026-11-12",
            title="Option A offline pre-flight",
            demonstrated=(
                "Full gadgetcore+0x84 reference audit: only the 0xEE/compat MS OS handlers and the gadgetcore ioctl "
                "start/reconfiguration path touch the byte; no MSC or endpoint path does. Root entry layout confirmed as an "
                "internal per-speed record, so bcdUSB is generated at request time."
            ),
            boundary=(
                "bcdUSB source, tree extension, EP0 vendor queue, /dev/a6400_dbg ABI and MS OS 2.0 configuration subset "
                "remain unimplemented; B2/B3 were not started."
            ),
            tier="OFFLINE PRE-FLIGHT + BLOCKERS",
        ),
        EvidenceRef(
            evidence_id="E0404",
            path="docs/evidence/0404-b1b-mode-gate-and-b2-b3-blockers.md",
            date="2026-11-12",
            title="B1b mode-gate inspection",
            demonstrated=(
                "Read-only probe of the live gadgetcore state: MSC tree topology decoded (one interface, Bulk-Only, two "
                "bulk endpoints, max_speed=1) and the Microsoft OS mode gate gadgetcore+0x84 read as 0."
            ),
            boundary=(
                "The zero mode gate blocks the MS OS string/compat path in Mass Storage, so WinUSB auto-binding cannot "
                "proceed without an additional approved kernel write/hook or a different transport class."
            ),
            tier="READ-ONLY PHYSICAL + BLOCKER",
        ),
        EvidenceRef(
            evidence_id="E0403",
            path="docs/evidence/0403-winusb-control-transport-msc-verification.md",
            date="2026-11-12",
            title="WinUSB control transport (B1c)",
            demonstrated=(
                "Bounded 18-byte MS OS string patch in volatile kernel data, executed by a RAM-only helper module with "
                "save/CRC32/readback/restore; two Mass Storage load-unload cycles verified stock->patched->stock CRCs, with "
                "cycle 2 independently proving restoration."
            ),
            boundary=(
                "No vendor interface or /dev/a6400_dbg node; WinUSB was not bound and the winusb transport is untested. "
                "EP0 chunking and bcdUSB gates remain open; PC Remote untouched."
            ),
            tier="PHYSICAL B1C + STATIC AUDIT",
        ),
        EvidenceRef(
            evidence_id="E0402",
            path="docs/evidence/0402-always-on-winusb-debugger-feasibility-and-phase-a.md",
            date="2026-11-12",
            title="Always-on WinUSB debugger (Phase A)",
            demonstrated=(
                "Decoded gadgetcore driver registration/callback/descriptor-tree ABI; built vendor-interface + MS OS 1.0 "
                "descriptor contracts with 16 offline checks, a fail-closed host WinUSB transport, and daemon v2.1 with ping "
                "and a dual-transport loop; staged upgrade preserved a rollback copy."
            ),
            boundary=(
                "Bulk OUT completion and device-recipient vendor dispatch are still undecoded; no gadget module, no "
                "composite interface, no PC Remote reachability yet."
            ),
            tier="OFFLINE ABI + PHASE A DAEMON",
        ),
        EvidenceRef(
            evidence_id="E0401",
            path="docs/evidence/0401-usb-debugger-v2-ring-recover-and-mode-boundary.md",
            date="2026-11-12",
            title="USB Debugger v2",
            demonstrated=(
                "Warm klog ring readout with magic/write-position/CRC32 verification over USB (two boots captured); "
                "non-destructive dmesg, usb-state and process-context recover; staged v1->v2 upgrade with preserved "
                "rollback; same pid through an MSC->PC Remote->MSC round trip; Unicorn trampoline with byte-identical rollback."
            ),
            boundary=(
                "PC Remote exposes no debugger transport; composite-gadget work is required for always-on access there. "
                "No kernel-text write and no loaded-module teardown on hardware."
            ),
            tier="PHYSICAL + UNICORN",
        ),
        EvidenceRef(
            evidence_id="E0398",
            path="docs/evidence/0398-runb21-status-stage-and-disconnect-verdict.md",
            date="2026-11-12",
            title="Run B21 status/disconnect",
            demonstrated=(
                "GET_CUR data completes at 138.358552 act=26, SET_CUR class starts 5.011194 s later and completes act=0; "
                "GET_DESCRIPTOR/GET_CUR share flg=02, so status OUT remains the divergence. ev/trb fields still zero; no status "
                "records. Disconnect hook fired but synchronous restore hung (battery pull)."
            ),
            boundary=(
                "Open: deferred workqueue restore and status-stage hook."
            ),
            tier="PHYSICAL STATUS/DISCONNECT",
        ),
        EvidenceRef(
            evidence_id="E0395",
            path="docs/evidence/0395-runb19-reqflags-fix-verdict.md",
            date="2026-11-12",
            title="Run B19 reqflags verdict",
            demonstrated=(
                "req+0x1a bit1 is read by DWC3 complete_data, but setting it did not remove the 5 s wait: GET data actual=26, SET "
                "class 5.007 s later actual=0. Flag fix rejected; 0x8ac8 is standard config/interface, clear_halt_ep0 only gc+0x83. "
                "Battery pull at final MSC switch."
            ),
            boundary=(
                "Open: status-stage path with silent ring; no flag fix."
            ),
            tier="PHYSICAL FLAG-FIX TEST",
        ),        EvidenceRef(
            evidence_id="E0332",
            path="docs/evidence/0332-sync-callback-delivery-first-invocation.md",
            date="2026-11-11",
            title="UIPC / USB",
            demonstrated=(
                "Kernel-to-user sync callback delivery runs the original h4109 callback "
                "and completes it without fault."
            ),
            boundary=(
                "Open: ADJ packet format, the 0x0A4000 producer and the USB FSM "
                "transition (sync_callback_packet_format_unmodelled)."
            ),
            tier="OFFLINE ORIGINAL CODE",
        ),
        EvidenceRef(
            evidence_id="E0314",
            path="docs/evidence/0314-gpes-bar-irq-contract-engine-model.md",
            date="2026-11-10",
            title="GPES engine / display",
            demonstrated=(
                "GPES BAR and IRQ contracts decoded from read-only observations; the opt-in "
                "engine model reaches a second original guest signal."
            ),
            boundary=(
                "Open: keyed 0x820E completion, guest condition release, OSD mapping and "
                "the rasterizer."
            ),
            tier="READ-ONLY PHYSICAL + OPT-IN MODEL",
        ),
        EvidenceRef(
            evidence_id="E0349",
            path="docs/evidence/0349-p1-foreign-get-jpeg-succeeds-in-pc-remote.md",
            date="2026-11-11",
            title="PTP / composite USB",
            demonstrated=(
                "Pipelined PTP liveview: a foreign GET_JPEG sees real frames from the DMM "
                "unit at 29.8 FPS while the host stream runs."
            ),
            boundary=(
                "Open: the composite enumerates (E0350) but DirectShow cannot connect the "
                "UVC pins, so no UVC frame is claimed."
            ),
            tier="PHYSICAL OBSERVATION",
        ),
        EvidenceRef(
            evidence_id="E0386",
            path="docs/evidence/0386-runb16-depcmd-cmdstatus-and-ring-verdict.md",
            date="2026-11-12",
            title="Run B16 DEPCMD CmdStatus and ring verdict",
            demonstrated=(
                "Fixed ev double-deref gives valid lpos/cnt (GET complete 0x294/c, SET pre 0x2a0/c, SET complete 0x2a8/8); "
                "DEPCMD0/1 CmdStatus=0, XferRscIdx 0/1 at every sample -> no rejected STARTTRANSFER, missing check unexercised; "
                "CLASS lr=5f5694b4, no shadow in B16; SET actual=0 with bounce HWO=1 reproduced; 5 s host-side. Battery pull was "
                "needed; camera healthy MSC, logs/ETL preserved, receipt not clean."
            ),
            boundary=(
                "No firmware fix supported; host/XHC or word-level event trace remains. Battery pull required."
            ),
            tier="PHYSICAL + DEPCMD",
        ),
    ),
    suite=SuiteRecord(
        test_count=1476,
        recorded_at="2026-11-12",
        evidence_id="E0424",
        command="python -m unittest discover -s tests -q",
    ),
    footer=(
        "Independent results, not a compatibility percentage. "
        "Evidence and limits are linked from README.md."
    ),
)


def latest_evidence_id() -> str:
    """Latest evidence ID the status documentation is synchronized to."""
    return STATUS_SNAPSHOT.latest.evidence_id


def recorded_test_count() -> int:
    """Full-suite test count recorded for this documentation refresh."""
    return STATUS_SNAPSHOT.suite.test_count


# ===========================================================================
# Telemetry dashboard data (single source of truth for docs/images/research-status.svg)
# ===========================================================================
#
# Every grid cell, bar, KPI value and boundary count below is derived from a tracked
# inventory: the STATUS_SNAPSHOT above, the treemap category counters, the evidence
# directory, or the multi-device target registry. Nothing is a percentage of "firmware
# compatibility", and every group carries the evidence record that backs it.
#
# Cell states:
#   verified  -> hardware-verified AND/OR an offline contract that passes
#   decoded   -> read-only physical observation or a decoded contract
#   boundary  -> partially modelled; the named gate is still open
#   unmapped  -> uninitialised / unmapped inventory item

CELL_VERIFIED = "verified"
CELL_DECODED = "decoded"
CELL_BOUNDARY = "boundary"
CELL_UNMAPPED = "unmapped"
CELL_STATES = (CELL_VERIFIED, CELL_DECODED, CELL_BOUNDARY, CELL_UNMAPPED)

CELL_LABELS = {
    CELL_VERIFIED: "Verified",
    CELL_DECODED: "Decoded / Read-Only",
    CELL_BOUNDARY: "Active Boundary",
    CELL_UNMAPPED: "Unmapped Inventory",
}

DASHBOARD_TITLE = "Status & Bounded Telemetry"
DASHBOARD_SUBTITLE = (
    "Sony a6400 · BIONZ X CXD90045 · bounded contract inventories — not a compatibility score"
)
DASHBOARD_FOOTNOTE = (
    "* Counts reflect bounded contract inventories in a6400_status_data.py, "
    "not an overall firmware compatibility percentage."
)

# Recorded constants: each one is a fact stated by the named evidence record.
TEARDOWN_PHASES = 9          # E0353: [a6400_td] phases=0x1ff = all nine phases ran
TEARDOWN_PHASE_MASK = "0x1ff"
EP0_CLASS_CASES = 12         # E0351: 12/12 Unicorn CLASS-path cases
TRANSPORT_AUDIT_CHECKS = 117  # E0350: encoded transport audit, 117 checks
PIPELINE_CORES = "3.0.27_nl-rt106+"

EVIDENCE_RECORD_RE = re.compile(r"^(\d{4})-[^/]+\.md$")


@dataclass(frozen=True)
class KpiPill:
    """One two-tone shield badge: dark label segment + coloured value segment."""

    label: str
    value: str
    tone: str
    source: str


@dataclass(frozen=True)
class CellGroup:
    """A labelled sub-region of a cellular grid."""

    title: str
    cells: tuple[str, ...]
    source: str

    def __post_init__(self) -> None:
        if not self.cells:
            raise ValueError(f"cell group {self.title!r} has no cells")
        for cell in self.cells:
            if cell not in CELL_STATES:
                raise ValueError(f"cell group {self.title!r} has unknown state {cell!r}")

    def counts(self) -> dict[str, int]:
        counts = {state: 0 for state in CELL_STATES}
        for cell in self.cells:
            counts[cell] += 1
        return counts

    def done(self) -> int:
        return self.counts()[CELL_VERIFIED]

    def total(self) -> int:
        return len(self.cells)

    def summary(self) -> str:
        counts = self.counts()
        text = f"{counts[CELL_VERIFIED]}/{len(self.cells)} verified"
        if counts[CELL_BOUNDARY]:
            text += f" · {counts[CELL_BOUNDARY]} boundary"
        return text


@dataclass(frozen=True)
class ContractBar:
    """A horizontal 'verified contracts' bar; ratios are bounded inventory counts."""

    label: str
    done: int
    total: int
    detail: str
    source: str
    amber: int = 0

    def __post_init__(self) -> None:
        if self.total <= 0 or not 0 <= self.done <= self.total:
            raise ValueError(f"bar {self.label!r} has an invalid ratio {self.done}/{self.total}")
        if not 0 <= self.amber <= self.total - self.done:
            raise ValueError(f"bar {self.label!r} has an invalid amber segment {self.amber}")

    def ratio(self) -> float:
        return self.done / self.total


@dataclass(frozen=True)
class BoundaryGroup:
    """Tracked open boundaries for one area; the bar length is len(items)."""

    label: str
    items: tuple[str, ...]
    source: str

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError(f"boundary group {self.label!r} has no items")
        if len(set(self.items)) != len(self.items):
            raise ValueError(f"boundary group {self.label!r} repeats an item")

    @property
    def count(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class TelemetryDashboard:
    """Frozen dashboard payload; the renderer owns geometry, this owns facts."""

    title: str
    subtitle: str
    as_of: str
    latest_evidence: str
    test_count: int
    receipt_count: int
    pills: tuple[KpiPill, ...]
    firmware_groups: tuple[CellGroup, ...]
    pipeline_groups: tuple[CellGroup, ...]
    pipeline_summary: str
    contract_bars: tuple[ContractBar, ...]
    boundaries: tuple[BoundaryGroup, ...]
    legend: tuple[tuple[str, str], ...]
    footnote: str

    def description(self) -> str:
        return (
            f"{DASHBOARD_TITLE}: {self.test_count:,} tests recorded passing, "
            f"{self.receipt_count} evidence receipts through {self.latest_evidence}. "
            "Bounded telemetry, not a firmware compatibility percentage."
        )


def status_categories() -> dict[str, "Category"]:
    """Treemap category counters keyed by category name (bounded inventories)."""
    categories: dict[str, Category] = {}
    for panel in get_a6400_project_status_data():
        for category in panel.categories:
            categories[category.name] = category
    return categories


def evidence_record_ids(root: Path | None = None) -> tuple[int, ...]:
    """Numeric IDs of the evidence record files that exist on disk (gaps preserved)."""
    base = root if root is not None else ROOT / "docs" / "evidence"
    ids = []
    for entry in sorted(base.iterdir()):
        match = EVIDENCE_RECORD_RE.match(entry.name)
        if match:
            ids.append(int(match.group(1)))
    return tuple(ids)


def evidence_receipt_count(root: Path | None = None) -> int:
    """How many dated evidence records are actually stored (not the highest ID)."""
    return len(evidence_record_ids(root))


def registered_target_label() -> str:
    """Every target with real evidence, short model names, in registry order."""
    from src.a6400.targets import STATUS_REFERENCE, STATUS_VERIFIED, list_profiles

    names = []
    for profile in list_profiles():
        if profile.status in (STATUS_VERIFIED, STATUS_REFERENCE):
            short = profile.model_name.replace("Sony ", "").split(" (")[0]
            names.append(short)
    if not names:
        raise ValueError("the target registry has no verified or reference profile")
    return " + ".join(names)


def _build_telemetry() -> TelemetryDashboard:
    categories = status_categories()
    phases = categories["task94_phases"]
    plugins = categories["imdb_plugins"]
    display = categories["display_subsys"]
    if plugins.total != 198:
        raise ValueError(f"static-plugin inventory changed ({plugins.total}); update the dashboard copy")
    if phases.total != 8:
        raise ValueError(f"boot task-phase inventory changed ({phases.total}); update the dashboard copy")

    receipt_count = evidence_receipt_count()
    test_count = STATUS_SNAPSHOT.suite.test_count

    pills = (
        KpiPill("contract tests", f"{test_count:,} passing", "green", "offline suite receipts"),
        KpiPill("evidence receipts", f"{receipt_count} recorded", "blue", "docs/evidence/"),
        KpiPill("teardown sequencer", f"{TEARDOWN_PHASES}/{TEARDOWN_PHASES} phases ({TEARDOWN_PHASE_MASK})", "green", "E0353"),
        KpiPill("task phases", f"{phases.done}/{phases.total} observed", "amber", "task94_phases"),
        KpiPill("BIONZ X targets", registered_target_label(), "violet", "src/a6400/targets/"),
    )

    firmware_groups = (
        CellGroup(
            "UIPC / OSAL",
            (CELL_VERIFIED,) * 13 + (CELL_BOUNDARY,),
            "E0310 · E0331",
        ),
        CellGroup(
            "USB / Gadgetcore",
            (
                CELL_VERIFIED,   # MSC soft-disconnect teardown
                CELL_DECODED,    # gadgetcore ioctl dispatch -> FSM map
                CELL_DECODED,    # otgcore descriptor table
                CELL_DECODED,    # /dev/usb/event ABI + bridge
                CELL_DECODED,    # device-node namespace (248:32/33)
                CELL_DECODED,    # module inventory (usbg_video absent)
                CELL_BOUNDARY,   # host enumeration / inbound SET_CONFIG
                CELL_BOUNDARY,   # usbg_video buffer contract (ctx+0x2D)
                CELL_BOUNDARY,   # ZV-E10 overlay declared, non-executable
            ),
            "E0320 · E0323 · E0337 · E0353",
        ),
        CellGroup(
            "DMM / JPEG",
            (
                CELL_VERIFIED,   # P1 foreign GET_JPEG at 29.8 FPS
                CELL_VERIFIED,   # DMM Rule5 / SET_PATH
                CELL_DECODED,    # OSAL queue 0x0167046a
                CELL_DECODED,    # DMM UnitType 0x274
                CELL_BOUNDARY,   # sensor feeder still unwired
            ),
            "E0340 · E0349",
        ),
        CellGroup(
            "GPES / Display",
            (
                CELL_VERIFIED,   # OSD A/B ptrace capture
                CELL_DECODED,    # BAR / IRQ contract map
                CELL_BOUNDARY,   # opt-in engine model (labelled)
                CELL_BOUNDARY,   # keyed 0x820E completion
                CELL_UNMAPPED,   # GPU rasterizer semantics
                CELL_UNMAPPED,   # THREAD_APP / view tier
            ),
            "E0298 · E0313 · E0314",
        ),
        CellGroup(
            "Boot Task Phases (8)",
            (CELL_VERIFIED,) * phases.done + (CELL_UNMAPPED,) * (phases.total - phases.done),
            "task94_phases",
        ),
        CellGroup(
            "Static Plugins (198)",
            (CELL_UNMAPPED,) * plugins.total,
            "imdb_plugins",
        ),
    )

    pipeline_groups = (
        CellGroup(
            "Track A: PTP LiveView & 0x9207 Controls",
            (CELL_VERIFIED,) * 6,
            "E0151 · E0343 · E0349",
        ),
        CellGroup(
            "Teardown 9-Phase Sequencer (0x1ff)",
            (CELL_VERIFIED,) * TEARDOWN_PHASES,
            "E0353",
        ),
        CellGroup(
            "EP0 Class / Probe / Commit",
            (CELL_VERIFIED,) * EP0_CLASS_CASES,
            "E0351",
        ),
        CellGroup(
            "DMM 0x0167046a Frame Source",
            (CELL_VERIFIED,) * 4,
            "E0349",
        ),
        CellGroup(
            "Track B: DirectShow Pin / 0x84 Start",
            (CELL_VERIFIED,) + (CELL_BOUNDARY,) * 2,
            "E0350 · E0354",
        ),
    )

    pipeline_cells = sum(len(group.cells) for group in pipeline_groups)
    pipeline_verified = sum(group.done() for group in pipeline_groups)
    pipeline_boundary = sum(group.counts()[CELL_BOUNDARY] for group in pipeline_groups)
    pipeline_summary = (
        f"{pipeline_cells} pipeline cells · {pipeline_verified} verified · "
        f"{pipeline_boundary} active boundaries"
    )

    contract_bars = (
        ContractBar("USB Soft-Disconnect Teardown", TEARDOWN_PHASES, TEARDOWN_PHASES,
                    f"{TEARDOWN_PHASES}/{TEARDOWN_PHASES} phases ({TEARDOWN_PHASE_MASK})", "E0352 · E0353"),
        ContractBar("PTP LiveView + 0x9207 Controls", 1, 1, "verified · 29.8 FPS", "E0151 · E0349"),
        ContractBar("EP0 UVC Class & Descriptor Audit", TRANSPORT_AUDIT_CHECKS, TRANSPORT_AUDIT_CHECKS,
                    f"{TRANSPORT_AUDIT_CHECKS}/{TRANSPORT_AUDIT_CHECKS} checks", "E0350 · E0351"),
        ContractBar("UIPC / MWF Sync Callback Path", 1, 2, "h4109 reached", "E0332 · E0334", amber=1),
        ContractBar("GPES / SMAPH-S30 Display Model", display.done, display.total,
                    "OSD A/B + BAR/IRQ", "E0298 · E0313 · E0314", amber=1),
        ContractBar("im.elf Boot Task Phases", phases.done, phases.total,
                    f"{phases.done}/{phases.total} phases", "task94_phases"),
    )

    boundaries = tuple(sorted((
        BoundaryGroup(
            "GPES / Display (condvar, 0x820E, OSD map)",
            (
                "guest condvar release",
                "keyed 0x820E completion",
                "OSD A/B mapping",
                "GPU rasterizer semantics",
            ),
            "E0312 · E0314",
        ),
        BoundaryGroup(
            "UIPC / USB FSM (h4109 packet, 0x0A4000)",
            (
                "h4109/h4110 packet payload",
                "0x0A4000 producer",
                "USB FSM transition",
            ),
            "E0332 · E0334 · E0338",
        ),
        BoundaryGroup(
            "Track B UVC (DirectShow pins, WPD MI_00)",
            (
                "DirectShow RenderStream pin connect",
                "composite MI_00 WPD binding",
                "MSC recovery after failed pin connect",
            ),
            "E0350 · E0354",
        ),
        BoundaryGroup(
            "Boot / Runtime (tzset, THREAD_APP, plugins)",
            (
                "fresh-path tzset",
                "THREAD_APP / view tier",
                "198 static plugin inits",
            ),
            "E0302 · E0309 · status data",
        ),
    ), key=lambda group: (-group.count, group.label)))

    return TelemetryDashboard(
        title=DASHBOARD_TITLE,
        subtitle=DASHBOARD_SUBTITLE,
        as_of=STATUS_SNAPSHOT.as_of,
        latest_evidence=STATUS_SNAPSHOT.latest.evidence_id,
        test_count=test_count,
        receipt_count=receipt_count,
        pills=pills,
        firmware_groups=firmware_groups,
        pipeline_groups=pipeline_groups,
        pipeline_summary=pipeline_summary,
        contract_bars=contract_bars,
        boundaries=boundaries,
        legend=tuple((state, CELL_LABELS[state]) for state in CELL_STATES),
        footnote=DASHBOARD_FOOTNOTE,
    )


TELEMETRY = _build_telemetry()
