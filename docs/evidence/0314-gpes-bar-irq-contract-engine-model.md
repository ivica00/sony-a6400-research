# E0314 — GPES BAR/IRQ contract decoded; opt-in engine-completion model

Date: 2026-11-10. Offline cycle (Lead + four teammates) with the E0313 read-only
physical evidence as the new input. No camera writes, no mode switch; the only
camera access in this cycle was read-only (`camera_debugger.py mem/exec/read`).
**No GUI frame yet**; USB boundary unchanged.

## 1. Decoded driver/guest contract (evidence)

`grm_gles.ko` (16,040 B) and libObj/retained state decode:

* **BAR map** (BAR = `[dev+0xF8]`, mmap 0xF1000000): `+0x00` identity (physical
  `0x000b0000`); `+0x10`/`+0x14` engine counters (physical idle
  `0x0405C040`/`0x0406EC40`); `+0x1C` ack for status `0x04000000`; `+0x34` IRQ
  status; `+0x3C`/`+0x44` sem ack (status `&0x0F`); `+0xC0` kick
  (`arg|0x20000000`); `+0x1000`/`+0xC18` ack for `0x40000000`;
  `+0xE8..0x170` command/ring block (`+0xE8` header, 0x80-byte descriptor at
  `+0xF4`).
* **IRQ 0x658**: reads BAR+0x34; `0x40000000` → write 0 to `+0x1000`/`+0xC18`;
  `0x04000000` → write 0 to `+0x1C`; `&0x0F` → write 1 to `+0x3C`/`+0x44`;
  accumulates `(status>>16)<<16 | [dev+0xA8] | …`; `__wake_up(dev+0x4C)`.
  Physical poll of BAR+0x34 (2,000,000 samples) saw exactly `0x40000000`
  (793×) and `0x80000000` (492×); IRQ 76 fired 1,107,089 times.
* **0xC0048203 event wait** (driver handler 0xAD0): guest passes mask
  `0x04000000`, requires `mask & 0xC4000000`, waits on `dev+0x4C`, checks
  `[dev+0xA8]`, returns status word. Guest caller libObj **0x72B660** inspects
  out bits `0x01000000`/`0x04000000`/`0x40000000` (acks 0x1000/0xC18).
* **ctx wait 0xC004820D**: fast flag `ctx->[0x10]` is written **only** by the
  0x820E signal handler; completion `ctx+0x14` only by 0x820E/open/release.
  IRQ never completes a guest ctx. → the hw-log wait needs a guest 0x820E.
* **Completion object**: the BAR descriptor embeds `0x99E10`/`0x99E30`;
  `0x99E30` is a heap `pthread_cond_t` (libObj 0x72E690 mallocs/init; futex
  word `0x99E34=1`; signal/broadcast/wait at 0x72E6F4/0x72E704/0x72E714).
  TID1011 submits the BAR command, then blocks on this condvar futex.
* **Intended chain**: command submit → engine status/IRQ → dev+0x4C wake →
  0xC0048203 returns status → guest RM condvar broadcast → TID1011 resumes →
  guest 0x820E → TID1054 exits 0x72BAF0 → THREAD_APP chain.
* **Access profile (e0377)**: 87 reads/49 writes; command block written once
  (deterministic hash `d38fef042304f2ae`), **0x34 never read/written**; the
  guest signal helper 0x72BB50 is hit right after the BAR writes with key 0.
* **Physical queue hunt (partial)**: real ASLR-free bases/offsets verified
  read-only: `libUsbControl 0x0486749c` word0 `0x00CA8192`; `libBusPower
  0x05CE4E28` words `0x012282F6`,`0x00CA8192`; `libInfraUsbCmn 0x04170A3D`
  `0x012002DA`; `libUsbBusPower 0x05CD738C/0x05CD7E20` `0x012002DA`. Live OSAL
  queue objects/messages were not yet located (registration view only) →
  USB producer boundary stands.

## 2. Implemented this cycle (opt-in, tested)

* **Decoded `0xC0048203` event-wait semantics** in `GuestGles` (mask
  `0xC4000000`, returns status word; historical non-mask values keep the old
  release-reply behaviour).
* **`--gles-engine-model command-completion`**: opt-in GPES device-work model.
  When the guest has submitted the command (BAR+0xE8=1, +0xEA=5), the first
  event-wait reports the physically observed IRQ class `0x40000000`, performs
  the decoded IRQ ack writes to BAR+0x1000/+0xC18 and consumes the ring header
  (physical idle is 0). It **never** completes a guest ctx and injects no
  signal; every completion is logged as an `engine-command` transaction.
* **BAR window detection**: the observed real mapping (128 KiB, pgoff 0) is now
  recognized as the 0xF1000000 window (`bar_virtual`, `bar_length`
  min(length, 0x4000)); the identity word `0x000b0000` is seeded only when the
  guest maps it.
* **Checkpoint compatibility**: `GuestGles.__setstate__` restores pre-BAR
  checkpoints (missing fields get safe defaults); getattr guards in the event
  path. This fixed an `AttributeError: bar_virtual` on restored e0315.
* Tests **880 OK** (18.5 s); default/baseline semantics unchanged.

## 3. Experiments

* `e0377` (usb-harness-runner): BAR access profiles, bar5/bar10 from
  `boot-e0315-live-block` (308,622,155) and bar-final/signal-trace from
  `boot-e0350-grm-decoded` (488,299,004). Signal helper HIT at +1,266
  (TID1011, key 0, LR 0x72BE1B); command block deterministic; 0x34 untouched.
* `e0383 engine2..engine11` (Lead): iterative engine-model runs. Key results:
  descriptor presence (guest memory 0x28160000+0xF4/0x16C/0x170) is the
  evidence-backed submission marker; `engine4`/`engine9` fired one
  `engine-command` completion; `engine10` (consume-on-return) made the waiter
  park again instead of spinning; **`engine11`** (`0x45000000` =
  `0x04000000` event-wait class + `0x40000000` physical IRQ class +
  `0x01000000` command-result bit, assumption label
  `command_result_bit_0x01000000`) made the guest exit the 0x72B660 loop: the
  caller path ran, **the guest itself issued a second 0x820E** (0x820E 1→2),
  TID1054 reached a **new 0x72BAF0 wait** (LR 0x72BB19), and the executor
  loop advanced. TID1011 stayed blocked on the heap cond futex 0x99E34.
* `e0420 engine13` (Lead, in flight): resume `boot-e0315-live-block` with the
  same model plus a **process-shared GLES ctx** change (see below).

### Process-shared ctx correction

E0345/E0370 modelled the 0x820D/0x820E ctx per thread. The driver resolves
the ctx through the user descriptor (`P=[arg+0xC]`, `ctx=[P+0x108]`); no
tgid/task-group keying exists in the kernel. Decoded mode now keys by the
**resolved ctx pointer** (with a labelled tgid fallback only when the
descriptor is inaccessible), and signals/waits log `ctx_ptr/task_ptr/key`.
Suite **880 OK**.

## 3b. Engine-model results (e0383 engine2..engine15)

* `engine11` (resume `boot-e0383-engine4.ckpt`, status `0x45000000` = event
  `0x04000000` + physical IRQ `0x40000000` + result `0x01000000`): the guest
  exited the 0x72B660 event-wait loop, ran the caller path, **issued a second
  guest 0x820E** (0x820E 1→2), and TID1054 reached a new 0x72BAF0 completion
  wait (LR 0x72BB19). TID1011 stayed blocked on the heap cond futex 0x99E34.
* `engine13`/`engine14` (resume `boot-e0315-live-block`, tgid vs resolved-ctx
  keying): single 0x8203 call parked because readiness required
  `dev_a8 & mask` while the resumed mask word was 0x80000000.
* `engine15` (same base, "any pending status" readiness): the event wait
  returned `0x45000000`, TID1054 exited the loop, **the guest ran the caller
  path and a second 0x820E appeared with a resolved ctx**
  (`task_ptr=0x579CE960`, `ctx_ptr=0x1F800`), and TID1054 returned to a
  **blocked_gles_wait** at 0x72BAF0 (LR 0x72BB19). 0x820E=2, 0x820D=1004,
  dev_a8 consumed to 0; TID1011 still futex 0x99E34; TID1009/INFRA0 blocked;
  no THREAD_APP/sem/view yet.
* `ctxfix1` (resume `boot-e0421-new-BB50.ckpt` 308,692,133, 1M): the kernel
  wait resolves its ctx from the **current task**, while the signal resolves
  through the user descriptor, so the model marks both the resolved ctx and
  the process-level ctx on a key-0 signal (assumption
  `gles_ctx_process_completion_assumption`). Result: TID1054's 0x72BAF0 wait
  returned completed (twice), **0x820E=3 / 0x820D=1006**, TID1054 advanced to
  an event-wait again (blocked_gles_event), TID1011 still futex 0x99E34. More
  executor cycles now run; the remaining dependency is the guest-side cond
  release (0x72E704) that would unblock TID1011, then the lazy-init/INFRA0 →
  main → sem 0x0083037A → THREAD_APP chain.

* Remaining dependency: the 0x72BAF0 wait needs a **different ctx** to be
  completed by a cross-thread/keyed 0x820E (kernel nonzero-key path walks the
  task list and compares `[obj+0x108]` with the key; our guest-side signal so
  far is key 0 = caller ctx), plus the heap-cond release path for TID1011
  (0x72E704 indirect; must stay guest-side). These are the next evidence
  targets (`futex_0x99e34_release_unmodelled`, keyed-ctx signal).


## 3c. Round 2 (progressive lineage, seed, event-present bit)

* The **progressive lineage** is `boot-e0421-new-BB50.ckpt` →
  `boot-e0434-prog-E704.ckpt` (308,692,133 / 310,121,241). Under the current
  model it advances: TID1054 exits the 0x72BAF0 wait to caller 0x72B824,
  runs `0x72D6E0` with status `0xC5000000`, `0x820E=8`, `0x820D=1017`,
  **THREAD_INFRA0 running**, TID1011 moves off the record cond 0x99E34 to
  `0x5548680C`. Slot `libObj+0x13F0868=0`, sem `0x0083037A` absent,
  THREAD_APP/view absent.
* **Evidence-backed BAR command-block seed** added
  (`--gles-engine-seed-observed-block`, exact e0377 bytes, sha256
  `f34ffe4614ad2ea3db7048775a09bfb1bdc18f5edb9d914c40ca533ebe417baf`).
  A seed alone does not advance the quiescent ctxfix1 lineage.
* `0x72B660` dispatch decoded (task-68): event id 1/7/8 wait on `0x80000000`,
  id 2 on `0x40000000`, id 3 on `0x04000000`, ids 4-6 return immediately;
  **the wait must return `status & 0x01000000`** (event-present) or the guest
  re-issues the wait and never reaches `0x72D6E0`/`0x72D07E`
  (`pthread_cond_signal([rec+0x7c])`, the intended TID1011 release).
* The bounded engine-state event now includes `0x01000000`
  (`event_bit | 0x01000000`); engine21 (20M from prog-E704) nevertheless
  produced **no new 0x8203/0x820E activity** because the resume state has no
  runnable caller of 0x8203: TID1054 is back in the 0x72BAF0 completion wait,
  TID1011 blocks on a different libObj cond, INFRA0 is runnable but the
  main↔INFRA0 rendezvous (libObj 0x780D60, sem 0x0083037A, main 0xa0d6-0xa0de)
  has not completed. This is the current stall.
* Remaining boundaries: `futex_0x99e34_release_unmodelled` /
  INFRA0-main handshake, `gles_wait_signal_keymap_unmodelled`,
  `usb_vbus_changed_mwf_0x0a4000_producer_not_derivable` (physical
  /dev/uipc pool read at phys 0x08800000 found only 0x008F013A messages;
  queue objects live in kernel vmalloc, /proc/kcore absent).


## 3d. Round 3 (gate decode, long progression runs, camera reboot incident)

* `0x72B1D0` decoded as the 0x72D010 gate predicate: loads a global count;
  `count<=0` → return 0 (drained) so `0x72BD88 bl 0x72D010` runs; otherwise
  it calls ioctl 0x8004820A and returns its value. `0x72D010` then requires
  `0x72CA70(r7)==0`, record `flags&1`, `[rec+0x78]` mutex and `[rec+0x7C]`
  cond, then locks and `pthread_cond_signal([rec+0x7C])` via 0x72E6F0.
* Long progression runs from `boot-e0421-new-BB50.ckpt` (engine22, 50M) and
  from `boot-e0434-prog-E704.ckpt` (engine20, 30M) are **stalled**: counters
  stay `0x8203=8`, `0x820D=1017`, `0x820E=8`; TID1054 re-parks in the
  0x72BAF0 completion wait, TID1011 blocks on a libObj cond (0x5548680C),
  THREAD_INFRA0 stays runnable, main blocked, slot 0, sem/THREAD_APP/view
  absent. The executor never reaches 0x72BD80 because its 0x820D wait has no
  completer in the modelled device (the 0x8203 event path is not the same
  wait); this is the current stall.
* **Camera incident (E0454):** a read-only bulk `/dev/mem` scan (16 MiB chunk)
  dropped the camera's USB and the camera **rebooted** (uptime reset to 61 s);
  it recovered and stayed responsive, no persistent modification. Bulk
  `/dev/mem` sweeps are now excluded from the standing read-only allowance;
  only bounded/small reads and /proc//sys/kallsyms views remain. The kernel
  module `osal_uipc` has no data/bss symbols; its vmalloc region
  (`0x5f046000`, 45 KiB) is not linear-mapped and `/proc/kcore` is absent, so
  the LMSGQ 0x6004/USB queue objects remain unreadable → USB producer boundary
  stands.


| boundary | state |
| --- | --- |
| `gles_kick_completion_unmodelled` | engine completion decoded + opt-in model; whether it advances the guest chain is being measured (e0383 engine2) |
| `gles_wait_signal_keymap_unmodelled` | unchanged; no matching post-wait 0x820E yet |
| `futex_0x99e34_release_unmodelled` | NEW: heap condvar completion object; only the guest broadcast path releases it |
| `rm_dispatcher_consumer_unidentified` | unchanged |
| `rm_hw_log_start_not_reached` | unchanged (teardown-only) |
| `usb_vbus_changed_mwf_0x0a4000_producer_not_derivable` | stands; physical registration view decoded, producer/message still unobserved |
| `mwf_monitor_input_poll` | unchanged |

## 3e. Round 4 breakthrough (timer preemption, THREAD_APP, heap assertion)

* Root cause of the long stall (E0473): the cooperative scheduler only switched
  on block/yield/≥100 ms sleep, so a non-blocking UIPC poll loop (332k ioctls
  from one PC) monopolised execution and never scheduled the runnable
  THREAD_INFRA0/ULOGIOD. Real Linux timer preemption is the missing behaviour.
* Implemented **opt-in `--thread-timeslice N`** deterministic preemption in
  `InterpreterProbe._block/_code` (`0` = historical baseline), with
  `thread_preemptions` accounting and a focused clone/loop unit test
  (**881 tests OK**).
* With `--thread-timeslice 50000` from `boot-e0460-engine22.ckpt` + engine
  model + seed, run e0484-preempt1 (10M) reaches **88 threads**: THREAD_INFRA0
  **terminated**, **sem 0x0083037A present**, **THREAD_APP (TID1086) +
  Appframework (TID1087) created**, `gui.so` and fonts (`Sony_DI_Icons.ttf`,
  `UniversOTS`, `HeiseiKakuGoth`, `MYingHeiC`) loaded.
* Corrected the Linux ARM affinity syscall mapping (**241 =
  sched_setaffinity, 242 = sched_getaffinity**); UTM had logged
  `***UTM ERROR*** set <tid> to cpu any = -1024!` for every thread.
* The app then stops at `syscall_boundary` **r7=268 tgkill(1000,1087,SIGABRT)**
  after a 3878-byte UTM/GPE monitor dump (`C3P_PACKET cmd 0x009400e1`,
  phys 0x20098000/0x200EB400/0x202e0000, dummywrite 0x02000000). Captured
  stderr: **`im.elf: malloc.c:4652: _int_malloc: Assertion
  '(unsigned long)(size) >= (unsigned long)(nb)' failed.`** — a glibc heap
  assertion, likely triggered by UTM/GPE monitor init (mapping/affinity/ioctl).
* Next: decode the UTM/monitor init and the heap-corruption trigger, then
  continue the now-unblocked app toward viewUnified2/OSD; USB producer
  boundary unchanged.

## 5. Next

* Trace the INFRA0/main rendezvous from `boot-e0434-prog-E704.ckpt`
  (INFRA0 running): libObj 0x780D60 body (0x780E0A cond signal / 0x780E2C
  cond wait), main futex (PC 0x5008D146 / LR 0x50085DFD), im.elf 0xa0d6 /
  0x94F8 (THREAD_APP), and the 0x72BD88/0x72D010 gate
  (0x72B1D0 return, record flags/mutex/cond). No fabricated sem/thread.
* Continue the read-only physical USB chase: kernel-vmalloc route to
  `osal_uipc` data or a bounded physical scan for the LMSGQ 0x6004/USB queue
  objects (owner u16 0x38, callback libObj+0x81E01D), then read pending
  Category-0x6103 / MessageId-0x0A4000-family payloads.
* The physical `/dev/uipc` pool read (phys 0x08800000) is characterised: only
  `0x008F013A`-targeted messages; no USB queue ids in that mapping.
