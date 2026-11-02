# E0016 — ARM Linux High Vectors (Kuser) Helpers, TLS, and Shared Library Initialization

Date: 2026-10-18. Scope: bounded guest process execution under the explicit `kuser` syscall policy (`--syscalls kuser`). Original ELF interpreter `ld-2.11.2.so` and Sony application `/usr/bin/im.elf`. No camera write, updater execution, or synthetic application logic is invoked.

## Findings

1. **Extraction of the Architecture High Vector Helper Template**:
   ARM Linux kernel provides architecture helper routines in the high vector page (`0xffff0000..0xffff1000`) at offset `0xf60`.
   The 160-byte helper template was extracted directly from the verified kernel image (`vmlinux.bin` at offset `0x388fe0`):
   - SHA256: `f9e6a6128970c915c1b372dbeb16ebed77e032b9be042e21f1540c466d5f4297`
   - `0xffff0f60`: `__kuser_cmpxchg64` (`push {r4-r7}`, `ldrd`, `dmb sy`, `ldrexd`, `strexdeq`, `pop {r4-r7}`, `bx lr`)
   - `0xffff0fa0`: `__kuser_memory_barrier` (`dmb sy; bx lr`)
   - `0xffff0fc0`: `__kuser_cmpxchg` (`dmb sy`, `ldrex`, `subs`, `strexeq`, `rsbs`, `b #0xffff0fa0`)
   - `0xffff0fe0`: `__kuser_get_tls` (`ldr r0, [pc, #8]; bx lr; mrc p15, #0, r0, c13, c0, #3`)
   - `0xffff0ff0`: software TLS storage slot word
   - `0xffff0ffc`: helper version word = `5` (`0x00000005`)

2. **ARM Private TLS Syscall Contract**:
   Implemented `sys_arm_set_tls` (syscall `0xf0005` / `0x009f0005`).
   During dynamic linker startup at 145,539 instructions, `ld-2.11.2.so` calls `sys_arm_set_tls(0x503204c0)`.
   The contract updates both the hardware CP15 C13 User Read-Only Thread ID register (`arm.UC_ARM_REG_C13_C0_3`) and the memory slot word at `0xffff0ff0`, allowing subsequent code to read the thread pointer via either instruction sequence.

3. **Pre-Existing Process Mapping Registration & GNU_RELRO**:
   During dynamic relocation of all 12 loaded libraries, the dynamic linker applies read-only memory protection (`PROT_READ`) to GNU_RELRO segments after relocations complete.
   At instruction 1,997,182, `ld-2.11.2.so` calls `mprotect(0x4001f000, 0x1000, PROT_READ)` to protect its own data section.
   `GuestMmap` now registers initial ELF segments (`im.elf`, `ld-2.11.2.so`) and the stack range (`0x7fe00000..0x7ff00000`) in `mapped_pages`, allowing post-relocation protection updates to succeed without triggering `ENOMEM`.

4. **Thread Lifecycle and Initialization Syscall Contracts**:
   After relocations complete across all 12 libraries, the dynamic linker initiates library initialization via `call_init` in dependency order:
   - `sys_set_tid_address` (syscall 256): returns guest process PID (`1000`).
   - `sys_set_robust_list` (syscall 338): validates `sizeof(struct robust_list_head) == 12`, records head pointer, and returns `0`.
   - `sys_rt_sigaction` (syscall 174): services registration of NPTL cancellation/restart signals 32 (`SIGRTMIN`) and 33, validates `sigsetsize == 8`, and returns `0`.
   - `sys_rt_sigprocmask` (syscall 175): services signal mask configuration, validates `sigsetsize == 8`, and returns `0`.
   - `sys_ugetrlimit` (syscall 191): for `RLIMIT_STACK` (resource 3), returns the standard Linux default 8 MiB limit (`struct rlimit { 8*1024*1024, 0xffffffff }`).

5. **Transition into Sony OSAL Shared Library and the `/dev/uipc` Boundary**:
   With relocations and runtime thread initialization complete, `ld-2.11.2.so` executes shared library constructors.
   Execution advances through `libpthread-2.11.2.so` and `libc-2.11.2.so` into `/usr/lib/libosal_uipc.so`.
   At **2,029,074 instructions**, execution halts cleanly at `PC: 0x5008bc3c` (inside `open` in `libpthread-2.11.2.so` called from `/usr/lib/libosal_uipc.so` constructor) on an explicit, fail-closed filesystem boundary:
   - `status`: `unsupported_filesystem`
   - `reason`: `open_flags_not_read_only_subset`
   - `path`: `/dev/uipc`
   - `flags`: `2` (`O_RDWR`)
   - `r7`: `5` (sys_open)

   The device node `/dev/uipc` is a character special device (`mode: 8703`) in partition 7 (`nflasha7`), backed in the kernel by `/usr/kmod/osal_uipc.ko`. Writable character device operations are outside the read-only guest filesystem contract and require explicit device/IPC contracts.

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
| `mmap` | 56,230 | `memory_boundary` (unmapped `__kuser_cmpxchg` at `0xffff0fa0`) |
| **`kuser`** | **2,029,074** | `unsupported_filesystem` (`open("/dev/uipc", O_RDWR)`) |

## Reproduction

```powershell
.\venv\Scripts\python.exe -m tools.research.probe_interpreter --syscalls kuser --instructions 5000000 --timeout-us 30000000
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Execution report is preserved in `artifacts/execution/interpreter-kuser.json`. The complete test suite contains **167 passing tests** (0 failures).
