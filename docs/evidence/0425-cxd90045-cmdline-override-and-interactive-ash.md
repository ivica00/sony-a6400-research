# E0425 — Sony `0x00103000` cmdline override contract decoded; `/bin/ash` exec attempt

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0424 boot.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The `0x00103000` contract is decoded and accepted [C].** Disassembly of `setup_arch`
   (literal pool at `0x604211B4..0x604211C0`) shows the validator:
   `strncmp("kemco", (char *)0x60103000, 5) == 0`; on success it logs
   `cmdline override at %p` with **`ptr + 5`** (`0x60103005`), then parses the string from
   there, converts CR/LF to spaces and stops at `'*'`. The magic string `"kemco"` is at
   `0x603D98BC`; the failure format string is at `0x603D98DD`.
   Live run: **`cmdline override at 60103005`** — the override is no longer rejected.
2. **`init=/bin/ash` is now parsed and attempted [C].** The recovered log shows
   `Kernel command line: ip=off …` (parsed from our payload) and then
   **`Failed to execute /bin/ash. Attempting defaults...`** → `Kernel panic - not syncing:
   No init found`. So the kernel's `execute_command` now really is `/bin/ash`; the remaining
   blocker is the **exec of the userspace binary itself**, not the cmdline.
3. **Kernel-side prerequisite chain is complete for parsing; userspace exec is the new
   boundary.** Cramfs metadata inspected directly from `boot/initrd.img`: `/bin` is a
   directory; **`/bin/ash` is a 7-byte symlink** (mode `0120777`); **`/bin/busybox` is a
   regular file** (mode `0100777`, 233,448 bytes); `/sbin/init` and `/bin/sh` are absent.
   `init=/bin/busybox` was also tried and loads (panic dump shows `busybox` mappings
   `00008000-00041000 r-x`, `00048000-00049000 rw-`) but still ends in
   `Failed to execute /bin/busybox` — so the failure is in the ELF/interpreter/symlink
   resolution path, not in filesystem lookup. **[C]**
4. **No interactive `/bin/ash` claim.** The `ttyAM0` console works (E0424) and the Sony
   exception monitor remains reachable, but the updater's `/bin/ash` never gets to run.

## 1. Evidence

| item | value |
| --- | --- |
| magic check | `strncmp("kemco", 0x60103000, 5)`; success pointer `0x60103005` |
| live log | `cmdline override at 60103005` |
| parsed cmdline | `ip=off initrd=0x00700000,0x00800000 root=/dev/ram0 …` + our tokens |
| init attempted | `Failed to execute /bin/ash` → `Kernel panic - not syncing: No init found` |
| /bin/ash | symlink, mode `0120777`, size 7 |
| /bin/busybox | file, mode `0100777`, size 233,448 |
| busybox exec | fails too; panic dump shows loaded `busybox` segments |
| /sbin/init, /bin/sh | absent in cramfs |
| tests | Sony payload test + all previous — suite **1477 OK** |

## 2. Implemented

* `machine_contract.py`: `kemco_cmdline`, `sony_cmdline` and `sony_payload` — the payload is
  the raw kemco text (starting with `"kemco"`) with the `init=` token rewritten; the kernel
  validates the magic and consumes the string from `ptr+5`.
* Runner: `--sony-override` writes that payload at `0x00103000` (instead of ATAGS), with
  `--serial-input` still driving the console.
* Tests: `test_sony_override_payload_keeps_kemco_magic` (magic prefix, `init=/bin/ash`,
  no `/sbin/init`, NUL terminator).

## 3. Next step

1. **Decode the `/bin/ash` symlink target from cramfs** (inode claims size 7 but the first
   data bytes are not the literal text `busybox`; the cramfs block-pointer layout for
   symlink data needs the same absolute-offset handling as files) and verify `/bin/busybox`
   is a static ARM EABI ELF (PT_INTERP absent) — if it has an interpreter, exec fails
   because that path is missing.
2. If busybox is dynamically linked, provide the interpreter path in the cramfs rootfs
   (already present?) or boot `/bin/busybox` with `init=/bin/busybox` plus applet argv to
   see the first userspace message; otherwise trace the ELF loader rejection in
   `search_binary_handler`/`load_elf_binary` in the emulated kernel.
3. Once `/bin/ash` executes, the already-working bidirectional `ttyAM0` gives the
   interactive shell prompt and command output live.
