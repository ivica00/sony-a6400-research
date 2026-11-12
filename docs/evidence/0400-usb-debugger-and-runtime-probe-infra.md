# E0400 — USB debugger / runtime-probe infrastructure: audit and phased design (NOT IMPLEMENTED)

Date: 2026-11-12. Offline audit/design only. No camera run, no kernel-text patch, no
new module, no hardware verification. The requested milestone contains four
independent infrastructure changes, one of which writes live kernel text; that cannot
be responsibly delivered and hardware-verified in the same turn. This file records the
current state, the exact blockers, and the execution order; it does **not** claim that
`teardown_uvc`, `dump_ring`, `hook_add`/`hook_clear`, or decompiled files exist.

## 1. Battery-pull root cause (audit)

- The debugger's control channel is a vendor-specific USB interface on the composite
  device. In PC-Remote/UVC mode B18–B22 showed `Debugger: [Errno 2] Entity not found`
  once the camera was in PC Remote; the debugger only became reachable again after the
  camera reached MSC (or after a battery pull/reboot).
- Therefore a teardown command issued **from the host through the same USB debugger**
  cannot run while PC Remote has replaced/renumbered that interface. Any in-band
  `teardown_uvc` must be delivered **before** the camera switches modes, while the
  debugger interface is still present.
- The B22 synchronous `disconnect_cb` restore ran after the host had begun detaching and
  hung (`DISCONNECT restore trigger started=0 in_flight=1`); the deferred workqueue was
  built in e0399, but B22's no-battery-pull result was confounded by an apparent camera
  reboot, and no `DEFERRED restore work` line was captured.
- Correct order for an in-band teardown: (1) host sends `teardown_uvc` while still in
  PC Remote/with debugger reachable, (2) module stops the daemon, unhooks diagnostics,
  runs `a6400_uvc_restore_descriptors()`/`rmmod` in process context, (3) only then the
  camera initiates the MSC switch. The current daemon/`disconnect_cb` path performs
  restore too late or in atomic context.

## 2. Warm-RAM ring (design only)

- Requires a fixed physical scratch region preserved across warm reboot. A 64 KiB
  high-RAM region must be chosen from the verified memory map, not guessed; the
  existing module already allocates coherent DMA at `phys=09840000` (B18/B22 logs).
- Header: magic, version, monotonic sequence, head/tail, CRC32/checksum; records are
  fixed-size and lockless (single writer, 32-bit aligned).
- Debugger `dump_ring` would need a host command and an in-guest reader that maps the
  same physical page; none is implemented. Reading warm DRAM after reboot also depends
  on the bootloader not zeroing that region, which is unverified.

## 3. Runtime ARM trampoline engine (design only; high risk)

- Sony's kernel has no kprobes. A reversible instruction hooker must:
  save the original 32-bit ARM instruction; reject PC-relative/PC-modified
  instructions unless relocated; write an ARM branch to a generic stub; flush
  D-cache/`flush_icache_range`; the stub saves r0–r12/sp/lr/cpsr, records selected
  dereferences into the warm ring (zero printk), executes the saved instruction, and
  returns; `hook_clear`/`rmmod` restores all bytes and flushes.
- Kernel text is normally read-only; writing it requires an explicit
  `set_memory_rw`-equivalent path or a temporary mapping, and a failure mid-patch can
  leave the CPU executing a partially written instruction. The B12–B22 history already
  shows camera reboots during teardown; this must be Unicorn-proven and rollback-tested
  before any hardware write, and should be a separate approved milestone.
- Unicorn verification plan: hook `0x602b253c` (`do_control_status`) and `0x602b334c`
  (status giveback), execute original bytes, compare all patched bytes before/after
  `hook_clear`, and verify no PC-relative relocation mismatch. Not executed here.

## 4. Decompilation (not available in this environment)

- No `analyzeHeadless`, `ghidraRun`, or Ghidra installation is present on the host or in
  WSL; no alternate ARM decompiler is configured. `docs/decompiled/` was not created.
- The existing workflow remains REA/Ghidra via `tools.research.rea_wsl_batch` only
  after a Ghidra install is provided; manual disassembly remains the current tool.

## 5. Deliverable status

| Requested | Status |
|---|---|
| `teardown_uvc` in-band command | not implemented; debugger interface absent in PC Remote |
| `dump_ring` warm-RAM command | not implemented; physical scratch region unselected |
| `hook_add` / `hook_clear` / trampoline | not implemented; kernel-text write risk |
| `docs/decompiled/dwc3_ep0.c`, `gadgetcore.c`, `usbg_video.c` | not produced; no decompiler |
| zero-battery-pull hardware verification | not run |
| live `do_control_status` hook capture | not run |

## 6. Recommended phased execution

1. **Safe first:** add `teardown_uvc` to the debugger protocol while the debugger
   interface is alive, running daemon stop + `rmmod`/restore in process context; verify
   zero-battery-pull roundtrip (no kernel-text write).
2. **Warm ring:** select/verify a physical scratch region, add header/CRC and
   `dump_ring`; test a deliberately rebooted run.
3. **Trampoline:** Unicorn prototype first, then one approved hardware write with
   rollback; do not combine with UVC hypothesis runs.
4. **Decompilation:** install/point to Ghidra, then export the requested files.

No claim of completion is made for E0400.
