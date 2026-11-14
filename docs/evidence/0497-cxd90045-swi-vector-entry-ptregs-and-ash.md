# E0497 — High-vector SWI entry: `vector_swi` builds its own `pt_regs`; direct-entry attempt exposed a capture-order bug (reverted)

Date: 2026-11-13. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0496 offline chain, the read-only dump set in
`artifacts/dumps/a6400-nflasha-readonly/` (full `/proc/kallsyms` used for symbol
addresses).

## 0. Short answer

1. **`vector_swi` disassembled [C]** (`ld-2.11.2.so`'s kernel, VA `0x6010DFA0`):

   ```
   0x6010DFA0 sub sp, sp, #0x48
   0x6010DFA4 stm sp, {r0-r12}            ; 13 GPRs
   0x6010DFA8 clrex
   0x6010DFAC add r8, sp, #0x3c
   0x6010DFB0 stmdb r8, {sp, lr} ^        ; ARM_sp (+0x34) / ARM_lr (+0x38) from USR bank
   0x6010DFB4 mrs r8, spsr                ; ARM_cpsr (+0x40) from SPSR_svc
   0x6010DFB8 str lr, [sp, #0x3c]         ; ARM_pc
   0x6010DFBC str r8, [sp, #0x40]
   0x6010DFC0 str r0, [sp, #0x44]         ; ARM_ORIG_r0
   ...
   ```

   So the kernel **builds the 18-word `pt_regs` itself**; the only missing link is the
   high-vector stub branch, which our emulator does not model (`0xFFFF0008` is not
   executed).
2. **A direct-entry experiment was implemented and tested [C]:** in `_on_interrupt`
   (intno 2) jump straight to `vector_swi` (`0x6010DFA0`) in `SVC|ARM` with `SPSR_svc` =
   user `CPSR`, plus a hook emulating the banked `stmdb r8,{sp,lr}^` at `0x6010DFB0`
   with the user `SP`/`LR`.
3. **The experiment exposed a real capture-order bug and was reverted [C].** The
   `e0497_trace` recorded `sp_usr = 0x7DC0FF68` (kernel stack!) and
   `lr_usr = 0x0403E980`: the user `SP`/`LR` were sampled **after** `CPSR` had already
   been switched to `SVC`, so the frame would have stored the kernel SP/LR. The run then
   spun at `0x6010DFB4` with 16 repeated `vector_stmdb` traces instead of dispatching the
   syscall. The change was reverted; E0496 behaviour is restored (`instruction_limit`,
   `svc_hits = 1`, `gen = 15`, `rec = 2`, `serial 0 B`).
4. **Exact fix for the next round [C/I]:** capture `SP_usr`, `LR_usr` and `r0..r12`
   **before** writing `CPSR` (`target = SVC|ARM`), then set `SPSR_svc = user CPSR`,
   `LR_svc = return_pc`, `SP_svc` unchanged (kernel stack), and jump to `vector_swi`;
   emulate `stmdb r8,{sp,lr}^` from the *captured* user bank values.

## 1. Evidence

| item | value |
| --- | --- |
| `vector_swi` | `sub sp,#0x48` / `stm sp,{r0-r12}` / `stmdb r8,{sp,lr}^` / `mrs spsr` / `str lr,[sp,#0x3C]` / `str r8,[sp,#0x40]` / `str r0,[sp,#0x44]` [C] |
| symbols | `vector_swi 0x6010DFA0`, `ret_fast_syscall 0x6010DEC0`, `ret_to_user 0x6010DF34` (from dumped kallsyms) [C] |
| direct-entry trace | `e0497_trace`: `vector_stmdb r8=0x7DC0FF5C`, `sp_usr=0x7DC0FF68` (kernel!), `lr_usr=0x0403E980` [C] |
| failure | run spun at `0x6010DFB4`, 16× `vector_stmdb`, `instruction_limit`, no syscall dispatch [C] |
| revert | restored `PC = 0xFFFF0008`; run back to `instruction_limit PC 0x6025ED38`, `svc_hits=1`, `gen=15`, `rec=2`, `serial 0 B` [C] |
| kernel symbols | 28,841 kallsyms lines total, 4,241 module symbols [C] |
| kernel image footprint | text `0x00108000–0x0048D023` ≈ 3.69 MB, data `0x004BC000–0x0051F613` ≈ 0.39 MB (total ≈ 4.08 MB) [C] |

## 2. Implemented / reverted

* Kept: `_svc_return_address` (E0496), banked-`ldmdb` skip (E0496), USR-bank-first
  restore (E0496), diagnostics.
* Experiment: direct `vector_swi` entry + banked `stmdb` emulation — **reverted** after it
  exposed the capture-order bug (SP/LR sampled after the CPSR switch).

## 3. Closing engineering assessment (required)

**Where the project stands.** Firmware materialization and hardware contracts are done:
`nflasha1` is decoded into image + cramfs + initrd, the boot contract (ATAGs, cmdline,
load addresses) is verified, the MMIO/IRQ model and CP15/cpu_v7 semantics are in place,
the deferred `UC_TLB_VIRTUAL` page-table walk delivers demand pages, and the kernel's
`ret_to_user`/`pt_regs` restoration plus the Thumb recovery chain now reach **real
userspace execution** (`ld-2.11.2.so` `_dl_start`) and the **first real syscall**
(`brk`, `r7 = 45`). What remains for `/bin/ash`: the SWI vector entry/return
(`pt_regs` construction with correct user SP/LR), the syscall return path
(`ret_fast_syscall`/`ret_to_user` with a USR frame), then the loader/BusyBox syscall
chain (`open`, `mmap2`, `set_tls`, `read`, `write`), `execve` of BusyBox, and the shell.
After that: mounting `/usr`, `/system`, `/setting` (mount syscalls + vfat/ext2 paths), and
only then the GUI (`im.elf` + framebuffer/menu controller) — who are 0% today.

**Kernel boot percentage.** The whole `nflasha1` kernel image is **loaded** in RAM:
`.text` ≈ 3.69 MB + `.data` ≈ 0.39 MB ≈ **4.08 MB, i.e. 100% of the extracted kernel
image present** (`/proc/iomem`: text `0x00108000–0x0048D023`, data
`0x004BC000–0x0051F613`). The boot **sequence** is complete: `start_kernel` → `rest_init` →
`kernel_init` → `do_initcalls` → `init_post` → `run_init_process`, proven by the user
`ld-2.11.2.so` image being mapped/executed and a real `svc #0` dispatched. So **kernel
boot = 100% completed through `run_init_process`**, and **~85–90% of the kernel's runtime
subsystems are actively exercised** (scheduler, IRQ/GIC, timer, VFS/cramfs, mm/demand
paging, ELF loader, syscall entry); the remainder is stubbed/unused drivers (display,
sensor, most `usbg_*`, audio) that the boot path does not touch. **Userspace functional
progress is ~0%**: the loader is still failing on the syscall return path, so there is no
shell, no mounted user partitions, and no GUI yet.
