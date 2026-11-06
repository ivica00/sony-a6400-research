# E0109 — Original activation reaches thread and resource-management contracts

Date: 2026-11-06. Normal USB reads, offline original execution, and one-shot
read-only main-thread context helper. Main-menu touch remains incomplete.

## Activation replay and bounded dependency acquisition

New `tools.research.menu_activation_snapshot_probe` enters original ListTab
method0x15b92044 with the complete E0106 menu and the selected node0x33b0f8
from the later retained USB model. This is an explicit caller control, not the
original physical event/action/thread route. All captures remain non-atomic.

The runner rejects conflicting overlapping bytes, unknown code, uncaptured
reads, and writes beyond captured menu/model fields or explicit address/PC/size
contracts. No missing function result is supplied. Original code writes the
node to menu+0x186b0 and proceeds through content queries, English-language
checking, popup/widget state preparation and graphics resource lookup.

`tools.research.capture_menu_activation_dependencies` performs bounded steps:
rerun offline, preserve the boundary, then read only its missing code/data.
Code must match the camera ELF in the explicitly identified module. Data is
labelled later USB state; small aligned16/32-byte windows retain actual reads.
The tool stops at writes, emulator scratch reads, unknown modules and reads
outside the verified user limit0x5f000000. History and dependencies are retained:

* artifacts/analysis/menu-activation-dependency-history.json
* artifacts/hardware/native-menu-activation-dependencies.json

Additional exact-PC emulator-only mutations are individually recorded for the
original process-data accessor ID/descriptor, GraphicsEngine invalidation byte,
resource reference count, last resource ID, graphics helper format/alignment
state, and a captured pthread mutex. They are not camera writes or success
replies. The process-data initializer0x15a2d920 is exported as
CmnViewProcessDataElementNormal::initProcessDataElement;0x159faa74 is
WrapperSettingUtil::isSetLangEnglish. GraphicsEngine singleton getter is
0x6303fe8. Preserve distinctions between verified names and inferred purposes.

## Broad source-comparison qualification

File-equal libObj components64b0000+16000,6300000+5000,6110000+5000 were accepted.
The attempted5e14000+9000 window differed in54 bytes, starting5e1cc71, in its
tail containing addresses. That broad window was rejected as executable input;
individual source-equal needed code windows remain usable. Raw live/file bytes
and differences are archived in activation-code-mismatch-0x5e14000.bin,
activation-code-file-0x5e14000.bin and activation-broad-code-audit.json.
Do not silently bless the whole differing region as original code or claim a
new application patch from this comparison alone.

## Actual thread context and kernel helper

Without TLS the original pthread path reaches13,744 instructions, then reads
0xfffffba8 at PC0x407fbbe. Disassembly proves why: MRC reads TPIDRURO as zero,
then pthread subtracts0x4c0 and reads+0x68 for its thread identity. This is
missing architectural/thread context, not a camera data address to fill.
An initial attempted read returnedEIO/no bytes; the acquisition guard now rejects
such out-of-user-range data reads before contacting the camera.

New devcrashday_a6400/native_thread_context.c uses PTRACE_ATTACH, GET_THREAD_AREA,
GETREGS and a bounded read, then detaches. It calls no im.elf application function
and sets no application registers/memory. Built with the installed WSL ARM
compiler, warnings-as-errors, existing debug_start.S and original Sony libc.
It was uploaded to /setting/native_thread_context.elf and read-back compared.
The first helper's buffered output was empty despite status0; that is retained
in native-main-thread-context.json and is not used as valid context. The fixed
unbuffered helper yields native-main-thread-context-v2.json:

    CONTEXT tid=149 tls=041444c0 pc=0435c17c sp=5ec35bfc cpsr=00000010
    address=04144060 data=88310904883109049500000095000000
    END result=0 errno=0

The data has TID149 at TLS-0x4c0+0x68. Status/flags0; detach succeeded. This
proves main-thread context, not the identity of the originating UI worker.

The160-byte live kernel helper template at0xffff0f60 was captured through normal
debugger ptrace reads into native-kuser-template.bin. SHA256:
`ff21fed2594b7d4bf88fd7dd7b865888a019521cc2ad2c41a2af73980385f739`.
This differs from the project's unpatched kernel-image template; use the actual
captured runtime instructions for this control. Its compare/exchange at
0xffff0fc0 executes DMB/LDREX/STREX, not a supplied atomic success result.

## Separate explicit main-thread control and next boundary

`python -m tools.research.menu_activation_snapshot_probe --main-thread-control`
sets TPIDRURO from the successful capture and supplies the captured kernel
helper. It verifies the captured pthread TID. The original mutex lock completes
on the emulator copy: exact writes allowed only to captured mutex0x12abf0,
owner0x12abf8 and user count0x12ac00 at the original kernel/pthread PCs.

This control reaches13,994 instructions,36 non-stack writes, and stops BEFORE
the original write to0x12abb0 at0x64c2fa8 (value0x39300). Original disassembly
shows a resource-manager operation reading object+0x18/+0x1c, accumulating
the virtual+0x3c result, and updating accounting/high-water fields. That broader
resource-management mutation contract is not yet admitted. Do not identify the
write as a completed allocation or allow arbitrary global/heap writes.

Reports preserve both cases separately:
menu-activation-snapshot-probe.json and
menu-activation-main-thread-snapshot-probe.json under artifacts/analysis.
Neither returns from the activation method; neither proves physical activation.

Regression replay passes145/145 geometry,252 original hit checks, page binding,
root selection controls and all13 controller sync/selected-node states.
Next: the original resource-manager accounting/allocation contract and correct UI
worker context, then complete refresh/activation and physical input routing.
No observer is armed. No physical test is requested yet. Own helper file upload
only; no im.elf calls, camera RAM patches or SD writes.
