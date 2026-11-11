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
    as_of="2026-11-11",
    latest=EvidenceRef(
        evidence_id="E0353",
        path="docs/evidence/0353-run-a-teardown-success.md",
        date="2026-11-11",
        title="Track B Run A: clean soft-disconnect teardown on hardware",
        demonstrated=(
            "First physical daemon session with the unconfigure-first soft disconnect: INIT, "
            "composite enumeration (MI_00 + MI_01), [a6400_td] phases=1ff failed=9 reconnect=1, "
            "clean exit, and Mass Storage returned without a battery pull."
        ),
        boundary=(
            "Open: no UVC frame yet (no host liveview consumer in Run A) and DirectShow "
            "RenderStream has not been retested; SD receipt content not yet read back."
        ),
        tier="PHYSICAL, RAM-ONLY",
    ),
    headline="1283 tests recorded passing | No verified emulator GUI frame",
    cards=(
        EvidenceRef(
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
            evidence_id="E0353",
            path="docs/evidence/0353-run-a-teardown-success.md",
            date="2026-11-11",
            title="Track B teardown (physical)",
            demonstrated=(
                "Run A: fresh-boot DMA window, INIT, composite enumeration, clean "
                "unconfigure-first soft disconnect and reconnect; MSC returned without a battery pull."
            ),
            boundary=(
                "Open: UVC frames and DirectShow RenderStream; next is Run B with a host "
                "stream, ETW capture and the receipt-fixed daemon."
            ),
            tier="PHYSICAL, RAM-ONLY",
        ),
    ),
    suite=SuiteRecord(
        test_count=1283,
        recorded_at="2026-11-11",
        evidence_id="E0353",
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
