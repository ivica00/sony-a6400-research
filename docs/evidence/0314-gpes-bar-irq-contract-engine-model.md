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
* Remaining dependency: the 0x72BAF0 wait needs a **different ctx** to be
  completed by a cross-thread/keyed 0x820E (kernel nonzero-key path walks the
  task list and compares `[obj+0x108]` with the key; our guest-side signal so
  far is key 0 = caller ctx), plus the heap-cond release path for TID1011
  (0x72E704 indirect; must stay guest-side). These are the next evidence
  targets (`futex_0x99e34_release_unmodelled`, keyed-ctx signal).


## 4. Boundaries (current)

| boundary | state |
| --- | --- |
| `gles_kick_completion_unmodelled` | engine completion decoded + opt-in model; whether it advances the guest chain is being measured (e0383 engine2) |
| `gles_wait_signal_keymap_unmodelled` | unchanged; no matching post-wait 0x820E yet |
| `futex_0x99e34_release_unmodelled` | NEW: heap condvar completion object; only the guest broadcast path releases it |
| `rm_dispatcher_consumer_unidentified` | unchanged |
| `rm_hw_log_start_not_reached` | unchanged (teardown-only) |
| `usb_vbus_changed_mwf_0x0a4000_producer_not_derivable` | stands; physical registration view decoded, producer/message still unobserved |
| `mwf_monitor_input_poll` | unchanged |

## 5. Next

* Analyze e0383 engine2: did 0xC0048203 return `0x40000000`, did the guest
  broadcast 0x99E34, did TID1011 resume and TID1054 exit? If not, identify the
  exact remaining dependency (event-wait caller thread/scheduling vs engine
  timing) with the next trace.
* Continue read-only physical work: full `/proc/osal/uipc` pages, `/log` ULOG
  records for the real USB 0x6103/0x0A4000-family flow, full PID maps and
  libosal pool scan for live queue objects/messages.
