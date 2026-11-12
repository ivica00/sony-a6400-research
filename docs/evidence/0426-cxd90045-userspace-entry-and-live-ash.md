# E0426 — PID-1 userspace entry diagnosis, `/bin/busybox` ELF and cramfs symlink decode

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0425 boot.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **`/bin/busybox` is a valid, dynamically linked ARM EABI ELF [C].** Decoded from
   `boot/initrd.img` (cramfs zlib blocks; raw copy in
   `artifacts/analysis/e0426-ash-live/busybox.bin`): `ET_EXEC`, `e_machine = ARM (0x28)`,
   entry `0xC439` (**Thumb bit set**), `e_flags = 0x05000002` (EABI 5), and
   **`PT_INTERP = "//lib/ld-linux.so.3"`** — so it is *not* static. Loaded segments:
   `0x8000-0x40368 r-x`, data at `0x48368`.
2. **`/bin/ash` resolves to `busybox` [C].** The cramfs symlink inode (`mode 0120777`,
   size 7) points at a compressed block whose zlib decompression is exactly `busybox`;
   the target is `/bin/busybox`.
3. **The interpreter chain exists in the cramfs `/lib` [C].** The `/lib` directory
   names include `ld-2.11.2.so`, `ld-linux.so.3`, `libc-2.11.2.so`, `libc.so.6`, etc.;
   decoding `/lib/ld-linux.so.3` (symlink, size 12) gives target `ld-2.11.2.so`, and
   `ld-2.11.2.so` is present as a directory entry. So the interpreter path is *not*
   trivially missing.
4. **PID-1 never reaches user mode [C].** With low-VA user-mode code tracing enabled
   (`--trace-user-mode`), a boot with `init=/bin/busybox` reports
   **`user_mode_entries = []`** — no instruction ever executes with `CPSR.M == 0x10`.
   The panic register dump is **SVC mode** (`cpsr 0x00000053`) and follows
   `Failed to execute /bin/busybox. Attempting defaults...` → `Kernel panic - not syncing:
   No init found`. Therefore the failure is inside the kernel's ELF loader /
   `kernel_execve` (before `start_thread`/`ret_to_user`), **not** kuser helpers, VFP/
   CPACR, or `/dev/console`.
5. **No interactive shell yet.** `ttyAM0` console and RX injection work (E0424), but
   `/bin/ash`/`/bin/busybox` never yields a userspace process; next step is to capture the
   `kernel_execve` errno and the `load_elf_interp` failure for the `//lib/ld-linux.so.3`
   path.

## 1. Evidence

| item | value |
| --- | --- |
| busybox ELF | `ET_EXEC`, ARM, entry `0xC439` (Thumb), `e_flags 0x05000002` (EABI 5), 233,448 B |
| PT_INTERP | `//lib/ld-linux.so.3` |
| /bin/ash | symlink 0120777 size 7 → zlib target `busybox` |
| /lib | `ld-2.11.2.so`, `ld-linux.so.3` (→ `ld-2.11.2.so`), `libc-2.11.2.so`, … |
| PID-1 | `Failed to execute /bin/busybox` → `No init found` panic |
| user mode | `--trace-user-mode`: `user_mode_entries = []`; panic CPSR `0x53` (SVC) |
| kernel log | `VFP support v0.3: implementor 41 architecture 3 part 30 variant 9 rev 0` |
| tests | cramfs symlink + busybox ELF + user-mode transition — suite **1480 OK** |

## 2. Implemented

* `unicorn_machine.py`: `trace_user_mode` — a bounded `UC_HOOK_CODE` on the low user VA
  window (`0x1000..0x80000`) that records user-mode entries (`user_mode_entries`), so the
  absence/presence of user execution is observable without slowing the kernel path.
* Runner: `--trace-user-mode`.
* Tests: `tests/emulator/test_cramfs_busybox.py` — cramfs symlink zlib target
  (`/bin/ash` → `busybox`), busybox ELF header/`PT_INTERP`, and a synthetic
  user-mode transition test (`user_mode_entries` records `CPSR.M == 0x10`).

## 3. Next step

1. **Capture the exec errno**: patch the `kernel_init` call site after
   `kernel_execve("/bin/busybox", …)` to store `r0` in a known RAM word, then read it
   post-run (expected `-ENOENT`/`-ELIBBAD`). This distinguishes a path-resolution problem
   (`//lib/...`, symlink chain) from an ELF validation failure.
2. **Trace `load_elf_interp`** in the emulated kernel for the interpreter open/map path and
   verify the `/lib/ld-linux.so.3` symlink target read through cramfs.
3. Once `start_thread` is reached, `user_mode_entries` will become non-empty; then check
   kuser helper (`0xFFFF0FC0`) usability and VFP `CPACR` (both irrelevant until then), and
   the bidirectional `ttyAM0` gives the interactive BusyBox shell.
