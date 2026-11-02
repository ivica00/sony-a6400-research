# Evidence 0046: Original open requires DMM and its returned handle

## Result

Original captured `ma_dmm_open_impl` and `ma_dmm_open_send_recv` execute **26 instructions** for the startup-shaped request (opcode1, unit **0x280**, flags0, name `gl_common`). They stop before **osal_valloc_msg_wait**, with arguments queue **0x0061003c**, output pointer **0x08002f9c**, payload size **0x18**, flags **1**, at runtime call PC **0x5f3f822c**.

The only non-stack write before this boundary is reply status **-9999** at full packet +28. Other reply words retain sentinels; no object retain count is changed. This is an explicit unsupported import, not successful open or a new main-process instruction milestone. No transport allocation is invented. Existing captured `gl_common` does not bypass DMM on this original open path.

## Source and research method

Same hash-checked WBI/module/kernel inputs and explicitly selected page-table root as [E0045](0045-wbi-page-tables-and-original-grm-lookup.md). Full non-relocated module-text comparison, captured page backing, original instruction trace, bounds and post-run identity checks remain in effect. The new `--operation open` enters the implementation directly; callback mutex, IPC dispatch and DMM are not executed.

Planner attempt `artifacts/analysis/wbi-grm-open-plan` resolved zero functions for the proposed name `ma_open_impl`. ELF symbols establish the actual name **ma_dmm_open_impl**. A corrected plan at `artifacts/analysis/wbi-grm-dmm-open-plan` records 12 functions, with truncation explicit. Generated native WSL batch `artifacts/tools/rea/plan-cec107b24672bfa5-0` completed all 24 queries, reusing eight existing results; retained instruction listings are checked against local symbols/original words.

The callback's opcode1 calls open directly under its mutex. The original open calls DMM send/receive before `ma_list_add`; it contains no name lookup. The send/receive builds opcode1 / unit0x280 / reply queue0x014c0424 / sequence / flags1 after successful message allocation, as previously observed in E0035. None of those later operations executes in this bounded run because message allocation is unsupported.

## Decompiled argument correction

REA pseudocode displays `ma_dmm_open_send_recv` with only three arguments at the call site and `ma_list_add(0, ...)`. **Do not use those inferred arguments as the contract.** Original instructions show:

- Open initializes a stack halfword, passes its address in **r3** to send/receive, and later loads it with **ldrh r0, [fp, #-0x1e]** before calling `ma_list_add`.
- Send/receive's success path reads the DMM reply's handle halfword and writes through that fourth argument. The stack slot's initial zero is not necessarily its value after the call.
- Therefore the object identifier comes from the DMM reply, in addition to physical base and size. Captured object's identifier **0x0417** is not established as the current request's allocation result.

Existing retained DMM handler evidence (`artifacts/tools/rea/dmm-allocation-request`) distinguishes `dmm_ctrl_AllocUnitNewHdlr` from `dmm_ctrl_GetUnitHandleHdlr`. Opcode1 allocates and proceeds through access-info handling; it is not a name-based reuse operation. E0036–E0042's timer dependencies remain relevant. Complete reply/sequence/ownership and state transitions must be verified before any selected service policy is added.

## Reproduction and validation

```
python -m tools.research.wbi_grm_consumer --operation open --report-dir artifacts/execution/NEW_DIRECTORY
```

Reports `artifacts/execution/wbi-grm-open-first/report.json` and `wbi-grm-open-repeat/report.json` match exactly: SHA-256 **49d13e725232423d11e84d58705dda33ea57346cb016db753f281fa76d85c85c**. They record request bytes, inputs, stop PC/arguments, original trace and writes.

The added import guard initially stopped the existing lookup at its verified `strncmp` call; that failed regression report is retained at `wbi-grm-lookup-open-regression`. The exact previously verified comparison call is now permitted only for lookup. Fresh `wbi-grm-lookup-open-verified` again returns the E0045 result after 285 instructions. Other imports still stop before execution.

Full suite: **342 passing tests**, `artifacts/execution/wbi-grm-open-final-suite.txt`. Status image regenerated with unchanged capability counts and no-UI title. No backend or main execution policies changed.

Next: connect the captured DMM unit table and handle construction to unit0x280, then bound original allocation/access-info behavior against that selected state. Do not replace allocation with the already captured pool or supply a timestamp to pass the remaining timer boundary.
