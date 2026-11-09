# E0111 — Resource accounting, original free, and a lifetime mismatch

Date: 2026-11-06. Native USB reads, offline original execution, read-only native
capture helpers. No im.elf application calls, application RAM patches or SD writes.

## Resource and synchronization contracts

The original resource-manager accounting now executes: its virtual result768
is added to233472, producing234240; the captured peak323968 stays unchanged.
Exact-PC mutations admit manager+0x18 at0x64c2fa8 and+0x1c at0x64c2fac only.
The probe observes operands and stores independently and rejects disagreement.

Original mutex lock/unlock paths restore their captured lock, owner and user
count fields. A second actual mutex0x36fdac is initially five zero words; the
original participation operation increments object0x36fd88+0x18 and its release
decrements it. Original condition broadcast operates on the captured all-zero
48-byte condition object0x36fdc8; its internal lock returns to zero. No waiting
thread or futex success is invented. All eight tracked synchronization fields
return to their captured values before the later boundary.

## Actual linked-list capture, not a supplied lookup result

Original0x64bb4e6 takes root0x6c8cc and searches for payload0x36fe30. Source
accessors prove root head/tail at+0/+4 and node next/prev/payload at+0/+4/+8.
New capture_native_resource_list.py preserves469 actual nodes, verifies
reciprocal links, tail, bounds/cycles and unchanged root before/after. The
whole traversal is explicitly non-atomic. Original code then performs its own
search; the host never supplies a matching node as its reply.

The original search finds middle node0x27837c80, next0x0b2f4640,
prev0x27837ca0, payload0x36fe30. Original0x64c8300 unlinks it using only four
scoped pointer writes at0x64c8314/831a/831c/8322. It then enters real libc free
for that bookkeeping node. This does not establish a new texture allocation.

## Why a new allocator snapshot was necessary

A later arena-prefix read conflicted at0x27800018 with an older retained read.
The runner rejected it before execution. The conflicting reads remain archived
in native-resource-arena-e0111-conflicting.json; they were not silently merged.

New native_resource_snapshot.c briefly stops all enumerated PID149 CPU threads,
checks the set again, reads a bounded arena prefix/chunk/list-root subset and
detaches every thread before file output. First attempt exceeded its128-thread
bound before any attach and produced ENUM_FAILED. The revised512 bound capture
reports175 enumerated/confirmed/resumed threads, result0, elapsed1287ms, END0.
Its1192-byte output is native-resource-snapshot-e0111.bin, SHA256
`d855a5e47f03fee7b42071d572738edb93d063437f46d674d4d679c720461519`.

The coherent subset covers27800000+450,27837c70+50,6c8cc+8. It does not freeze
DMA/hardware or make the rest of the older MENU/USB inputs atomic. Source record
native-resource-snapshot-e0111-v2-run.json preserves deployment/read-back/logs.

prepare_resource_snapshot_control.py produces a separately labelled input:
native-menu-activation-dependencies-e0111.json. The original dependency dataset
is retained. Refresh is restricted to bytes covered by that explicit snapshot;
executable bytes cannot be refreshed, and the old list root/selected node must
still agree. Its manifest lists six differing overlapping observations. Further
reads outside those regions remain later non-atomic USB reads.

`--main-thread-control --resource-snapshot` selects this control explicitly.
Original kernel cmpxchg obtains the arena lock. The source-equal libc fastbin
path clears flags bit0, stores the former bin head in the freed chunk, and stores
that chunk in bin0. Only the actual flags/chunk-fd/bin-head fields are admitted
at0x4319c16/9c1c/9c1e. The original free returns; resource0x36fe30's original
16-bit use/reference increment0x64bdfd8 then executes. No generic heap writes,
fake allocation address or skipped lock is used.

## Current stopping point: zero reference count on an older image

The next resource release reaches original0x64be068 with resource0x1a2cace0.
Its captured16-bit reference count at+0xc is zero. Original instructions test
zero and issue a diagnostic before subtracting one. Initially the write guard
stopped at0x64be08c before admitting0xffff; the improved invariant guard now
stops at function entry after20,938 instructions, before that diagnostic and
underflow. The acquisition tool stops on an invariant boundary rather than
trying to fill more bytes or grant the write.

Read provenance identifies the source pointer in the E0106 menu at0x10f737bc,
**menu+0x127b4**, read by original0x6359724. This pointer is present in the MENU
snapshot; its resource header was read later in USB. A cross-mode lifetime
mismatch is a plausible explanation, not yet a proven physical firmware defect.
Do not set the count to one or allow the underflow to claim progress.

Reports: menu-activation-resource-snapshot-probe.json records the explicit
variant, original accounting, synchronization observations and reference-pointer
provenance. Earlier reports/failed captures remain separate. The activation
method has not returned; physical menu touch remains incomplete.

Next targeted physical capture must obtain the active menu and the resource
behind menu+0x127b4 together, before USB destroys/changes menu ownership. E0112
describes the prepared observer and the precise callback procedure.

Regression replays still pass145/145 original geometry,252 hit checks plus page
selection controls, and original active-layout binding. Native helper builds
pass warnings-as-errors; the one-shot coherent subset and V3 waiting state are
separately hardware-verified as described above/E0112. No completed V3 MENU
capture is claimed before the user's callback.
