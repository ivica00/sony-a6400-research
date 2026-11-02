# E0015 — Guarded ARM EABI mmap2, dynamic linker library loading, and kernel helper boundary

Date: 2026-10-18. Scope: bounded guest process execution under the explicit `mmap` syscall policy (`--syscalls mmap`). Original ELF interpreter `ld-2.11.2.so` and Sony application `/usr/bin/im.elf`. No camera write, updater execution, or synthetic application logic is invoked.

## Findings

1. **Resolution of the 6,493-Instruction Deduplication Boundary**:
   Under `--syscalls metadata`, execution stopped at 6,493 instructions when `ld-2.11.2.so` attempted to read the guarded `st_dev` field at `0x40004b9e` in `_dl_map_object_from_fd`.
   Supplying verified major-252 device numbers sourced from Evidence Record 0014 (`boot-mount-trace.json`):
   - `/lib` (partition 7, `nflasha7`): `st_dev = 0x0000fc07`
   - `/usr` (partition 15, `nflasha15`): `st_dev = 0x0000fc0f`
   satisfies the linker's `(st_dev, st_ino)` deduplication check and activates the dynamic segment loader at 6,710 instructions.

2. **Guarded `GuestMmap` Engine**:
   Implemented `src/a6400/execution/guest_mmap.py`, providing explicit contracts for:
   - `mmap2` (ARM EABI syscall 192): page-aligned virtual allocations, `MAP_FIXED` over mapped ranges, anonymous zero-filling, and file-backed payload loading from verified filesystem snapshot descriptors (`VerifiedContent`).
   - `mprotect` (syscall 125): page-aligned protection updates across mapped ranges (`PROT_READ`, `PROT_WRITE`, `PROT_EXEC`, `PROT_NONE`).
   - `munmap` (syscall 91): page unmapping and tracking.
   - Descriptor cleanup via `close` (syscall 6).
   Allocations are confined within `0x50000000..0x70000000` to prevent collisions with interpreter code, application text, or stack memory.

3. **Emulator Thumb-2 ITSTATE Quirk Resolution**:
   At instruction 7,499, `ld-2.11.2.so` executes a 4-instruction conditional block `itttt ne` at `0x40004e3e` with mixed 16-bit and 32-bit Thumb-2 instructions (`ldr`, `ldr.w`, `add`, `str.w`). Due to an emulator translation block quirk in Unicorn 2.x, the remaining `ITSTATE` in CPSR failed to clear at `0x40004e4c` (`cmp r0, #0`), causing subsequent non-IT instructions (specifically `0x40005346: ldr.w lr, [r7, #0x40]`) to be falsely evaluated under stale conditional execution.
   An explicit guard in `InterpreterProbe._code` clears stale IT bits from CPSR at `0x40004e4c`, allowing the dynamic linker to correctly load `Elf32_Ehdr` pointers.

4. **Dynamic Linker Advancement (56,230 Instructions)**:
   The original interpreter advances from 6,493 to **56,230 instructions**, locating, opening, reading, mapping, and closing all 12 dependent shared libraries required by `/usr/bin/im.elf`:
   - `libjemalloc_ds.so.1` (closed fd=3 at 7,943 instructions)
   - `libIMDB.so` (closed fd=3 at 11,068 instructions)
   - `libosal_uipc.so` (closed fd=3 at 15,389 instructions)
   - `libosal_utm.so` (closed fd=3 at 18,879 instructions)
   - `libbackup.so` (closed fd=3 at 22,412 instructions)
   - `libdl-2.11.2.so` (closed fd=3 at 25,823 instructions)
   - `libpthread-2.11.2.so` (closed fd=3 at 30,596 instructions)
   - `libstdc++.so.6.0.14` (closed fd=3 at 35,393 instructions)
   - `libm-2.11.2.so` (closed fd=3 at 39,086 instructions)
   - `libgcc_s.so.1` (closed fd=3 at 42,828 instructions)
   - `libc-2.11.2.so` (closed fd=3 at 47,257 instructions)
   - `librt-2.11.2.so` (closed fd=3 at 51,397 instructions)

5. **The Next Boundary (`__kuser_cmpxchg` at 0xffff0fa0)**:
   Execution halts cleanly at 56,230 instructions with:
   - `status`: `memory_boundary`
   - `access`: `21` (`UC_MEM_FETCH_UNMAPPED`)
   - `pc`: `4294905760` (`0xffff0fa0`)
   Address `0xffff0fa0` is Linux's architecture-defined `__kuser_cmpxchg` kernel helper vector in the high vector page (`0xffff0000..0xffff1000`), invoked during pthread and TLS initialization.

## Regression Baselines

All historical baselines remain intact:

| Policy | Instructions | Boundary / Status |
| --- | --- | --- |
| `stop` | 1,183 | `syscall_boundary` (r7=45 / `brk`) |
| `brk` | 2,222 | `syscall_boundary` (r7=122 / `uname`) |
| `brk-uname` | 3,091 | `syscall_boundary` (r7=33 / `access` -> `/etc/ld.so.preload`) |
| `files` | 5,078 | `unsupported_filesystem` (`stat64` on `/lib`) |
| `metadata` | 6,493 | `unverified_metadata_read` (guarded `st_dev` on `/lib`) |
| `--respect-runtime-mounts` | 3,091 | `unsupported_filesystem` (unsupplied `/etc`) |
| **`mmap`** | **56,230** | `memory_boundary` (unmapped `__kuser_cmpxchg` at `0xffff0fa0`) |

## Reproduction

```powershell
.\venv\Scripts\python.exe -m tools.research.probe_interpreter --syscalls mmap
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Execution output is preserved in `artifacts/execution/interpreter-mmap.json`. The complete test suite contains **161 passing tests**.
