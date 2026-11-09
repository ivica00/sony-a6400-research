# E0116 — V5 capture, original row entry and allocator boundary

Date: 2026-11-06. Physical menu touch remains incomplete.

## Actual returned capture

The returned helper was the rearmed V5 PID3119, not the older pending PID3074. Both volatile outputs were preserved before further work as `artifacts/hardware/native-layout-resource-snapshot-pid3119.log` and `.bin`, then decoded to `.json`. The callback manifest is retained alongside them.

Binary SHA256: `c58d4a98aed8b0bb382d96d4fe28aad63b524fb271f2edcf176e07a9343bf2f8`. Exact file length 201052 bytes; 1048 records; 188460 raw bytes. MENU attempt39/object `0x26f919b0`; active resource `0x1a2cace0`, owner `0x6c880`, references1. Unused-resource list491 nodes, nonzero references0, active resource absent. TLS `0x041444c0`, allocator `0x1a200010`. Libc data `0x043b7000/0x1000`, bss `0x043b8000/0x3000` captured. All176 attached threads resumed, elapsed1520ms. FREEZE/SNAPSHOT/BINARY/END result0. This freezes CPU threads, not DMA or every process. The observer finished; none is armed.

## Why return0 did not mean activation

Unlike V4, actual V5 menu byte+0x1d8 is1 and cached row+0x1f8 is-1. Original activation `0x15b92044` returns0 after8186 instructions through its flag check, without the resource path. This is a negative control, not successful option opening. Baseline retained as `artifacts/analysis/menu-activation-v5-no-row-entry.json`.

## Original navigation, without forced focus fields

The explicit offline control calls original `0x15b91572` using r0=result buffer, r1=actual menu, r2=1. The four actual TBB bytes are `1e 23 02 10`; direction1 reaches `0x15b91274`. An initial direction3 hypothesis was disproved: it changed category instead. Physical key IDs are not derived from these direction numbers.

Original direction1 changes flag1->0 and returns [4,1,0]. Original binding `0x15b91430` then derives cached row0 from the actual model. The harness checks agreement rather than writing the flag, row or model selection itself. Three original virtual selected-child calls derive `160f5cec -> 160efc9c -> 160fbaa0 -> 33b0f8`.

Reproduction:

```powershell
python -m tools.research.prepare_active_menu_control pid3119
python -m tools.research.menu_activation_snapshot_probe --main-thread-control --active-state artifacts/hardware/native-layout-resource-snapshot-pid3119.json --native-row-entry
```

## New execution boundary

After native row entry, activation reaches26235 original instructions. Resource accounting is233472+768=234240, peak323968. Original resource-list unlink and libc free proceed using V5 allocator data. Narrow guards admit only captured free-arena mutex CAS at original caller LR431c9e3/431ca0d, and three original fastbin stores at4319c16/4319c1c/4319c1e with their actual register-derived destinations. The arena is obtained by original free from the chunk's 1MiB heap header, checked against the captured bytes. These are emulator-only writes, not camera patches or general heap permission.

Original active-resource reference decreases1->0. The allocation path also derives arena `0x1a200010` from captured TLS+0x34; only its original CAS call sites (LR431c4cd/431c4fd) are admitted. Execution now stops before reading an uncaptured free-chunk header at `0x1a2bc704`, size4, PC `0x0431a2fc`. Report: `artifacts/analysis/menu-activation-v5-native-row-entry.json`. Next capture must include allocator-linked free-chunk headers in the same frozen MENU state. A later USB read must not silently fill this coupled heap input. Do not force mutex success or fabricate heap contents.

Remaining dependencies include older separately retained source-equal code and explicitly qualified later USB data; the whole input is not claimed atomic. Main-thread TLS is an explicit control, not proof of originating UI thread. No physical key routing, complete activation, popup rendering or touch adapter has been established. No application calls, application RAM patches or SD writes were performed.

## Validation

Repeated native-row-entry replay reaches the same26235-instruction boundary. Without row entry, the8186-instruction return0 negative control remains unchanged. Full project unittest suite:566 passed with normal host access. The first restricted run had four temporary-directory permission errors; rerun with required host access passed all tests.
