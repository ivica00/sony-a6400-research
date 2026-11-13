# E0451 — `init_section_page_cgroup` loop trace: valid heap pointers, one anomalous NULL call

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0450.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The loop runs 647 iterations and every normal iteration carries a valid kernel
   heap pointer [C].** Traces at the loop head `0x60361574` and the pre-call
   `0x603615CC` show `r4 = 0x7FCxxxxx` (e.g. `0x7FC225B0`) and `r0 = r4 + 0x20`
   (e.g. `0x7FC225D0`) for all but the last entry. **This weakens the
   `_walk_kernel_pt()` mistranslation hypothesis:** the `mem_section`/page-cgroup data
   is being read correctly through the virtual TLB — the pointers are real heap
   addresses, not garbage from a wrong page-table base.
2. **The failing entry is anomalous in three ways [C]:**
   * `r0 = 0` (the NULL `__rt_mutex_init` argument),
   * `r6 = 0` although the preceding instruction `add r6, r4, #0x20` should have set it
     from the valid `r4 = 0x7FC225B0`,
   * `sp = 0x60472800` (vs `0x60463E60` for normal iterations) and
     `lr = 0x603615C4` (vs `0x603615B8`), i.e. a **different invocation context**, not
     the same loop iteration.
3. **Interpretation [I]:** the NULL does not come from a mistranslated high VA in this
   loop. It comes from a separate `init_section_page_cgroup` invocation (different stack
   and return address) whose `r6` was 0 — most likely the `mem_section` / page-cgroup
   pointer for that node is genuinely zero at that point under the virtual-TLB boot
   ordering, or the code at that PC executes a runtime-patched/alternate sequence
   (SMP/errata patching) that sets `r6 = 0`.
4. **No shell [C]:** `serial 0 B`, `svc_hits = 0`, `user_entries = 0`;
   `tlb_fills`/`tlb_fill_misses` unchanged from E0450 (`98326`/`1`, the VA-0 write).

## 1. Evidence

| item | value |
| --- | --- |
| loop-head trace | 647 hits, `r4` from `0x7FC0xxxx` to `0x7FC225B0`, `lr=0x603615B8` [C] |
| pre-call trace | 647 hits, `r0 = r4+0x20` valid for 646, one `r0 = 0` [C] |
| failing entry | `r4 0x7FC225B0`, `r6 = 0`, `sp 0x60472800`, `lr 0x603615C4` [C] |
| allocator trace `0x6019E744` | no hits recorded in this run (alloc happens before the loop) [C] |
| new blocker | `__rt_mutex_init+0x10`, VA `0x0` write; `tlb_fill_misses = 1` [C] |
| suite | **1530 tests OK** (no source change this round) |

## 2. Implemented

No production code change this round; the traces are stored in
`artifacts/analysis/e0451/nflasha1-boot-report.json`.

## 3. Next step

1. **Instruction-level hook** at `0x603615B8..0x603615CC` (after each store and after
   `add r6, r4, #0x20`) dumping `r4`, `r6`, `r7`, `sp`, `lr` for the anomalous
   invocation; confirm whether the executing instruction sequence matches the static
   image at `0x601614B4` (runtime text patching / alternatives) or whether the
   invocation is a different call path.
2. Trace the **second invocation's caller** (`lr = 0x603615C4` belongs inside the same
   function range, so inspect the stack at that SP for the real return address), and
   read `mem_section` / `node_page_cgroup` values for that node.
3. If the pointer is genuinely zero, identify the init step that failed to populate it
   under `virtual_tlb_enabled=True` (compare with the E0446 non-virtual boot), fix it,
   then continue to `ld-2.11.2.so` syscalls, BusyBox `_start` (`0x0000C439`) and live
   `/bin/ash` over `ttyAM0`.
