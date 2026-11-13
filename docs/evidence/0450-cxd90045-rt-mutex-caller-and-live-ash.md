# E0450 — Caller of the `__rt_mutex_init(NULL)` write: `init_section_page_cgroup+0x11c`

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0449.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Disassembled `__rt_mutex_init` [C]** (`0x6015EE8C`):
   `mov r3,#0; str r3,[r0,#0x10]; add r3,r0,#8; str r3,[r0,#8]; str r3,[r0,#0xc]; ldm sp,...`
   — the fault at `0x6015EE9C` is the `str r3,[r0,#0x10]` with **`r0 = 0`**.
2. **Captured the live caller and its argument [C].** A `--trace-reg 0x6015EE9C:...`
   capture shows `__rt_mutex_init` being called **hundreds of times normally** with
   `r0 = 0x7Fxxxxxx` (kernel heap pointers), `r1 = 0x603E...` (lock name strings),
   `sp = 0x60463E60`, `lr = 0x603615D0`. The final (failing) call has **`r0 = 0`** with
   `lr = 0x603615D0`, i.e. the caller is `init_section_page_cgroup+0x11c`
   (`0x603614B4` base).
3. **Call site read [C]:** `init_section_page_cgroup` builds a page-cgroup structure in
   a loop:
   `0x603615C0: add r6, r4, #0x20` → `0x603615C8: ldr r1, [pc,#0x64]` (lock name) →
   `0x603615CC: bl __rt_mutex_init` (returns to `0x603615D0`). The NULL means `r6`,
   i.e. the loop's page-cgroup element pointer `r4 + 0x20`, became `0` (or wrapped),
   while the normal instances get real heap pointers from the preceding allocation
   (`bl 0x6019E744` → `r5`, used as the loop base when nonzero).
4. **Interpretation [I]:** under `virtual_tlb_enabled=True` an earlier kernel high-VA
   (`>= 0x80000000`, e.g. the page-cgroup array or a `kmap_atomic`/`__memzero` result)
   resolves to 0/wrong value in `init_section_page_cgroup`, so the loop initialises a
   mutex at NULL. The kernel booted past this point in E0446 (no virtual TLB) and
   reached `ld-2.11.2.so`, which points to a virtual-TLB translation difference rather
   than a kernel bug. Candidate suspects: the page-table walk's accepted PA for a
   section/small page, or a high-VA read whose physical page our fill maps but whose
   memory has not been initialised the same way (the fixmap/`__memzero` path is the
   most recent behavioural difference).
5. **No shell [C]:** `serial 0 B`, `svc_hits = 0`, `user_entries = 0`.

## 1. Evidence

| item | value |
| --- | --- |
| `__rt_mutex_init` | `0x6015EE8C`, `str r3,[r0,#0x10]` at `0x6015EE9C` (r3=0) [C] |
| normal calls | hundreds, `r0 = 0x7Fxxxxxx`, `lr = 0x603615D0`, `sp = 0x60463E60` [C] |
| failing call | **`r0 = 0`**, same `lr = 0x603615D0` [C] |
| caller | `init_section_page_cgroup+0x11c` (`0x603614B4`), call at `0x603615CC` [C] |
| argument | `r0 = r6 = r4 + 0x20` from the page-cgroup loop [C] |
| live counters | `tlb_fills = 98326`, `tlb_fill_misses = 1` (VA 0 write) |
| suite | **1530 tests OK** (unchanged; no source change this round) |

## 2. Implemented

No production code change this round: E0450 is an investigation round that pins the
caller, the call site and the failing argument of the `<__rt_mutex_init(NULL)>` write.
Artifacts: `artifacts/analysis/e0450/` (full register trace, run log, report).

## 3. Next step

1. Trace `init_section_page_cgroup` loop state: set `--trace-reg` at `0x60361574`
   (loop head), `0x603615CC` (before the failing call) and `0x603615A4`/`0x603615E0`
   to capture `r4`, `r5`, `r6`, `r8`, `fp` and the loop bound; compare the last
   iteration with a normal one.
2. Trace the allocation at `0x6019E744` and the reads that feed `r4`/section count
   (`mem_section`, `node_page_cgroup`); verify which high-VA read returns 0 under
   virtual TLB and why the fill maps it to an uninitialised page.
3. Fix that translation/memory-initialisation difference, re-run, and confirm the kernel
   reaches `run_init_process` → `ld-2.11.2.so` syscalls → BusyBox `_start`
   (`0x0000C439`) → live `/bin/ash` over `ttyAM0`.
