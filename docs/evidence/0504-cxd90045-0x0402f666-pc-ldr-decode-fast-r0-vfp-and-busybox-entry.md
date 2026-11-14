# E0504 — `0x0402F666` Thumb `USR` (`T=1`) PC-relative `ldr.w` decode, fast-syscall `r0` preserve, ARM VFP (`__sigsetjmp`), uaccess/high-vector PT walk, and BusyBox `_start` (`0x0000C439`) + `libc.so.6` execution (`svc_hits = 71`)

Date: 2026-11-14. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0503 offline chain, the read-only dump set in
`artifacts/dumps/a6400-nflasha-readonly/` (full `/proc/kallsyms`).

## 0. Short answer

1. **`cpsr` recorded in `fault_classification_trace` and `e0504_trace` hook added at `0x0402F660..0x0402F670` [C].**
   Every fetch at `0x0402F660`, `0x0402F664`, and `0x0402F666` enters in **Thumb `USR` mode**
   (`cpsr = 0x60000030`, `T = 1`, `M = 0x10`, `sp = 0x5E864B50`, `lr = 0x0403D7D1`) [C].
   This refutes the hypothesis that `0x0402F666` itself was entered in ARM (`T = 0`) mode [C].
2. **Root cause #1 — `0x0402F666` is a Thumb-2 PC-relative literal load (`ldr.w r4, [pc, #0xbec]`) faulting on unmapped data page `0x04030000` [C].**
   The instruction bytes at `0x0402F666` are `df f8 ec 4b` (`ldr.w r4, [pc, #0xbec]`), which
   reads literal pool word `((0x0402F666 + 4) & ~3) + 0xBEC = 0x04030254` on page `0x04030000` [C].
   Because `_decode_fault_address()` did not handle `base_name == 'pc'` (or Capstone register aliases
   `sb`/`sl`/`fp`/`ip`), it returned `None` and misclassified the data-read translation fault as a
   **Prefetch Abort** at `0x0402F666` (`IFAR = 0x0402F666`) instead of a **Data Abort** at
   `0x04030254` (`DFAR = 0x04030254`) [C]. Once `_decode_fault_address()` computes ARM/Thumb aligned
   `PC` (`(((pc & ~1) + 4) & ~3)` for Thumb, `((pc & ~3) + 8)` for ARM), `0x0402F666` is classified
   as `data-decoded` (`address = 0x04030254`), the kernel demand-pages `0x04030000` (`L2 = 0x00430E7E`),
   and `0x0402F666` executes **once** on retry and advances through `0x0402F66A -> 0x0402F66C -> 0x0402F670` [C].
3. **Root cause #2 — `_capture_fast_syscall_frame` at `0x6010DEC0` clobbered syscall return `r0` [C].**
   At `ret_fast_syscall` (`0x6010DEC0: str r0, [sp]`), the kernel writes the syscall return value to
   `[sp+0]` while `[sp+8]` (`pt_regs->ARM_r0`) still holds the entry argument (`0` for `sys_brk(0)`) [C].
   Reading `frame_words` from `sp + 8` without updating `frame_words[0] = uc.reg_read(UC_ARM_REG_R0)`
   restored `r0 = 0` instead of `0x00055000`, causing `ld-2.11.2.so` to call `brk(0)` twice and fail
   heap initialization [C]. Preserving live `r0` in `frame_words[0]` makes the first `brk(0)` return
   `0x00055000` and advance immediately to `uname` (`r7 = 122`), `mmap2` (`r7 = 192`), `access` (`r7 = 33`),
   `open` (`r7 = 5`), and `stat64` (`r7 = 195`) [C].
4. **Root cause #3 — Genuine ARM-mode (`T = 0`) routines in `ld-2.11.2.so` and VFP `vstmia` in `__sigsetjmp` (`0x0403F034`) [C].**
   `ld-2.11.2.so` switches to ARM mode (`T = 0`, `cpsr = 0x20000010`) via `blx` for internal wrappers
   (`0x0403EF7C`, `0x0403EEB8`, `0x0403ED9C`, `__sigsetjmp` at `0x0403F010`) [C]. At `0x0403F034`,
   `vstmia ip!, {d8-d15}` (`0xECAC8B10`) raised `UC_ERR_INSN_INVALID` because `FPEXC.EN` was `0`, and
   `_should_recover_insn_invalid()` forced Thumb mode on recovery [C]. Enabling `UC_ARM_REG_FPEXC = 0x40000000`
   at userspace `UC_TLB_VIRTUAL` activation (and in ARM-mode `UC_ERR_INSN_INVALID` recovery when `T = 0`)
   lets ARM VFP context save/restore run natively [C].
5. **Root cause #4 — Kernel `uaccess` demand-paging (`__strncpy_from_user`) and high-vector (`0xFFFF0000`) PT walk [C].**
   - `sys_open` calls `__strncpy_from_user` (`0x602602A8`), which faulted reading unmapped `ld-2.11.2.so`
     string page `0x04043398`; adding all kernel `__ex_table` `uaccess` helpers (`__strncpy_from_user`,
     `__strnlen_user`, `__get_user_*`, `__put_user_*`, etc.) to `demand_page_helpers` routes SVC data faults
     on user VAs to `_deliver_data_abort` instead of returning `-EFAULT` via `__ex_table` fixup [C].
   - Under `UC_TLB_VIRTUAL`, `_translate_virtual()` previously identity-mapped `vaddr >= 0xFFFF0000`, so
     timer IRQ delivery to `0xFFFF0018` executed zeroed physical memory `0xFFFF0018..0xFFFF0FA0` in IRQ mode
     (`CPSR = 0xD2`) and hit the kuser `memory_barrier` hook with kernel `LR` [C]. Consulting
     `_walk_kernel_pt(vaddr)` first resolves `0xFFFF0000 -> PA 0x1FFFE000` (the real vector stub page) [C].
6. **Outcome: `ld-2.11.2.so` dynamic linking completes and BusyBox `_start` (`0x0000C439`) + `/lib/libc.so.6` execute in `USR` mode [C]!**
   In the standard 800M run, the dynamic linker opens and maps `/lib/libc.so.6` (`0x040FC000..0x041F4000`),
   completes relocations, and jumps to **BusyBox `_start` (`0x0000C438`/`0x0000C439`)** [C]. Execution
   proceeds across BusyBox (`0x0000C438..0x0002FDC2`) and `libc.so.6` (`0x04119C18..0x041C3C08`), reaching
   **`svc_hits = 71`**, **`kuser_hits = 35`**, **`pt_frame_gen = 330`** (`consumed = 328`),
   **`user_restores = 214`**, **`tlb_fills = 530,636`**, and **`jiffies_injected = 2,633`** [C].
   At the end of the trace, `libc.so.6` (`LR_usr = 0x0412EB07`, `SP_usr = 0x5E864530`) branches to
   `0x041F2000` (an unmapped/non-executable `libc.so.6` `.got`/`.data` page), which triggers a fatal user
   prefetch abort into `em_exception_monitor` (`stop_reason = instruction_limit` at `__delay+0x8`,
   `serial_bytes = 0`, no shell prompt yet) [C].

## 1. Command & Artifact Hashes

Standard command executed offline:

```powershell
python -m tools.research.run_nflasha1_boot --limit 800000000 --no-exclusive-fallback --sony-override `
  --svc-dispatch --cmdline-extra "init=/bin/ash console=ttyAM0,115200n8" --trace-user-mode `
  --serial-input "uname -a`nid`nls -la /`n" `
  --output artifacts/analysis/e0504/nflasha1-boot-report.json `
  --serial-output artifacts/analysis/e0504/nflasha1-ttyAM0.log
```

| Artifact / Source | SHA-256 | Size |
| --- | --- | --- |
| `artifacts/analysis/e0504/nflasha1-boot-report.json` | `26180ae018f5962ddff680172d340ddf2eae7028eb6c2bd06c313c66b4d58573` | `442,425 B` [C] |
| `artifacts/analysis/e0504/nflasha1-ttyAM0.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | `0 B` [C] |
| `src/a6400/execution/unicorn_machine.py` | `1b1140e8c2739ae2de2dae46e89226c424e9ca78ffe68f633cfbd873d5ce7cea` | `197,106 B` [C] |
| `tests/emulator/test_virtual_tlb.py` | `a8bae629800ba8416853203e5052929a277c2f6d1b3746e338b5cc991e196ab6` | `22,329 B` [C] |
| `tests/emulator/test_data_abort.py` | `e62d25a46c891c60ab7e5efd0269d42e2e0c4a0998e406e489f4f9909cabf4ac` | `21,617 B` [C] |
| Kernel zImage (`nflasha1`) | `7d61feae2ac580cf8a9775f2fbd2a3f916f37a56333cd96738f696e7c079311f` | `3,581,952 B` [C] |

## 2. Evidence (`[C]` Confirmed / `[I]` Inferred)

### 2.1 `e0504_trace` at `0x0402F660..0x0402F670` and `fault_classification_trace` (`cpsr` logged)

`e0504_trace` (`total = 7` hits across the entire 800M run) proves `0x0402F666` is entered in Thumb `USR`
mode (`T = 1`, `M = 0x10`), faults once on `0x04030254` (`ldr.w r4, [pc, #0xbec]`), and executes once after
demand-paging `0x04030000` [C]:

```json
[
  {"pc": "0x0402f660", "cpsr": "0x60000030", "thumb": true, "mode": "0x10", "sp": "0x5e864c10", "lr": "0x0403d7d1"},
  {"pc": "0x0402f664", "cpsr": "0x60000030", "thumb": true, "mode": "0x10", "sp": "0x5e864bec", "lr": "0x0403d7d1"},
  {"pc": "0x0402f666", "cpsr": "0x60000030", "thumb": true, "mode": "0x10", "sp": "0x5e864b50", "lr": "0x0403d7d1"},
  {"pc": "0x0402f666", "cpsr": "0x60000030", "thumb": true, "mode": "0x10", "sp": "0x5e864b50", "lr": "0x0403d7d1"},
  {"pc": "0x0402f66a", "cpsr": "0x60000030", "thumb": true, "mode": "0x10", "sp": "0x5e864b50", "lr": "0x0403d7d1"},
  {"pc": "0x0402f66c", "cpsr": "0x60000030", "thumb": true, "mode": "0x10", "sp": "0x5e864b50", "lr": "0x0403d7d1"},
  {"pc": "0x0402f670", "cpsr": "0x60000030", "thumb": true, "mode": "0x10", "sp": "0x5e864b50", "lr": "0x0403d7d1"}
]
```

And `fault_classification_trace` around `0x0402F660..0x0402F666` now includes `cpsr` [C]:

```json
{"pc": "0x0402f660", "cpsr": "0x60000030", "address": null, "kind": "prefetch", "write": false},
{"pc": "0x0402f666", "cpsr": "0x60000030", "address": null, "kind": "prefetch", "write": false},
{"pc": "0x0402f666", "cpsr": "0x60000030", "address": "0x04030254", "kind": "data-decoded", "write": false}
```

### 2.2 Loader → BusyBox `_start` (`0x0000C438`) → `/lib/libc.so.6` progression

| Metric | E0503 (Before) | E0504 (After) | Status |
| --- | --- | --- | --- |
| `e0504_trace` hits at `0x0402F666` | infinite repeat | **2** (1 pre-fault + 1 post-fault retry) | `[C]` |
| `svc_hits` | `2` (2× `brk(0)`) | **`71`** (`brk`, `uname`, `mmap2`, `access`, `open`×15, `stat64`×13, `mprotect`, `set_tls`, ...) | `[C]` |
| `kuser_hits` | `3` | **`35`** (`__kuser_cmpxchg`, `__kuser_memory_barrier`, `__kuser_get_tls`) | `[C]` |
| `pt_frame_gen` / `pt_frame_consumed` | `30` / `29` | **`330` / `328`** (`user_restores = 214`) | `[C]` |
| `tlb_fills` / `cputlb_flushes` | `~21,000` / `28` | **`530,636` / `616`** (`page_cache_drops = 680`) | `[C]` |
| `prefetch_aborts_delivered` | `9` | **`55`** (across `ld-2.11.2.so`, `BusyBox`, `libc.so.6`) | `[C]` |
| `data_aborts_delivered` (SVC/uaccess) | `2` | **`3`** (`0x00048AC6`, `0x0404E85C`, `0x04043398` in `__strncpy_from_user`) | `[C]` |
| BusyBox `_start` (`0x0000C438`) reached | No | **Yes** (`prefetch_abort_trace`: `0x0000C438`, `0x0002E238`, `0x00018EE8`, `0x0002FDC2`, `0x0001194C`, `0x00012F6C`, `0x00015014`) | `[C]` |
| `libc.so.6` (`0x040FC000+`) reached | No | **Yes** (`0x0419A1C0`, `0x041586C8`, `0x04120EE4`, `0x0411EC00`, `0x041C3C08`, `0x04150640`, `0x04119C18`, ...) | `[C]` |
| `last_dfar` / `last_ifar` | `0x0404DF48` / `0x0402F666` | **`0x000566DC` (BusyBox heap) / `0x041F2000` (`libc.so.6` RW page)** | `[C]` |
| `serial_bytes` (`ttyAM0`) | `0 B` | **`0 B`** (stops after `0x041F2000` abort in `__delay+0x8`) | `[C]` |

## 3. Implemented Changes

* `src/a6400/execution/unicorn_machine.py`:
  1. Added `'cpsr': f'0x{cpsr:08x}'` to both `self.fault_classification_trace.append(...)` dictionaries
     and installed `UC_HOOK_CODE` on `0x0402F660..0x0402F670` populating `self.e0504_trace`.
  2. Extended `_decode_fault_address()` with `_REG_BY_NAME` aliases (`sb`, `sl`, `fp`, `ip`),
     ARM/Thumb `base_name == 'pc'` alignment, shifted register offsets, and `push`/`pop`/`stm`/`ldm`/`vst`/`vld`.
  3. Updated `_capture_fast_syscall_frame()` at `0x6010DEC0` to overwrite `frame_words[0]` with live
     `UC_ARM_REG_R0` so `ret_fast_syscall` at `0x6010DEF8` returns the kernel's syscall result instead of
     the entry `r0`.
  4. Queued `_pending_evict_pages` and `_pending_cputlb_flush = True` in `_deliver_data_abort()`.
  5. Enabled `UC_ARM_REG_FPEXC = 0x40000000` on userspace `UC_TLB_VIRTUAL` activation and in ARM-mode
     (`T = 0`) `UC_ERR_INSN_INVALID` recovery.
  6. Added kernel `__ex_table` `uaccess` routines (`__strncpy_from_user`, `__strnlen_user`, `__get_user_1/2/4`,
     `__put_user_1/2/4/8`, etc.) to `self.demand_page_helpers`.
  7. Updated `_translate_virtual()` for `vaddr >= 0xFFFF0000` to consult `self._walk_kernel_pt(vaddr)`
     before identity fallback, and added `__irq_usr` to `banked_store` + USR `SP`/`LR` capture in `_try_inject_irq()`.
* `tests/emulator/test_virtual_tlb.py` & `tests/emulator/test_data_abort.py`:
  - Added `test_decode_fault_address_thumb2_pc_relative_ldr`, `test_capture_fast_syscall_frame_preserves_live_r0`,
    and expanded `test_user_copy_helpers_are_demand_page_whitelisted`.

## 4. Next Step (E0505)

1. **Trace the `libc.so.6` call site (`LR_usr = 0x0412EB07`, `SP_usr = 0x5E864530`) that jumps to `0x041F2000` [I]:**
   `0x041F2000` lies in `libc.so.6`'s RW data/GOT segment (`0x041F2000`), and `0x0412EB07` is inside `libc.so.6`
   Thumb code (`0x0412ED42`/`0x0412F5FE`/`0x0412B984` neighborhood). Disassemble `libc.so.6` at VA `0x0412EAE0..0x0412EB20`
   (offset `0x32AE0..0x32B20` in `/lib/libc.so.6`) and inspect what function pointer or PLT/GOT slot holds `0x041F2000`
   (or whether a relocation / `mmap2` page-offset in `libc.so.6` resolved to the base of the RW segment instead of
   the target routine).
2. Fix that PLT/GOT or syscall return contract so BusyBox `/bin/ash` completes `libc` initialization and reaches
   `write(1/2, ...)` and `read(0, ...)` on `ttyAM0`.
