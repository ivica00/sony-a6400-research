# E0301 — UIPC lifecycle, original kernel IDs and camera-observed startup arguments

Date: 2026-11-10. Offline firmware execution plus targeted **read-only native
USB debugger** checks. No physical mode switch, driver open, helper upload,
camera write or SD write. **No emulator GUI frame is established.**

## Corrections to the previous lead

The camera's actual `/proc/149/cmdline` is:

```
im.elf\0debug\0s\0g\0r\0u\0l\0i\0a\0lazy-global\0
```

Thus E0298's claim that phase `i` merely needed a USB trigger was too strong.
The observed camera process includes **all phases and lazy-global**, whereas
the retained `i` experiments exercised one supported argument-selected path.
E0025's distinct `bootin` commands are still real static/executed observations;
they were not evidence of the current camera's full command line. The new
runner retains `/usr/bin/im.elf` as argv[0] and copies the observed remaining
arguments. Environment, prior processes and kernel state are still partial.

The VBUS queue `0x012002da` callback is **libUsbBusPower.so**, not
libInfraUsbCmn.so. The E0300 address `0x5b783dcd` lies in the former's recorded
mapping; its symbol is `UsbBusPower::RsrcUsbBusPowerCB`. A camera read at
`0x05cd7dcc` matched all 88 original bytes. It relays a 20-byte body
`{0x120,a,b,c,d}` to guest-local queue `0x012182eb`, then frees the original
message. The guest service thread, not the host, processes it.

## Contracts added under explicit opt-in

`--uipc-pool-options kernel-e0301` preserves `legacy-empty` and E0300's
completion boundary as separate baselines. It adds:

* **Ordinary async completion:** original `finish_callback` decrements callback
  activity, clears queue busy and redispatches. For non-broadcast queues it
  does not inspect/free the message. Four original ARM controls reproduce
  precisely the callback-count/queue-flag stores, with explicit lookup/lock/
  redispatch fixtures. Queues are serialized across proxies. Sync-registered
  callbacks occupy queue+0x18, not the async list at queue+8, and no longer
  falsely consume async messages. Broadcast and multiple async consumers stay
  explicit boundaries.
* **Same-process sync callback ABI:** kernel `__k_4u_snd_sync_msg` returns
  `{message,callback,user_data}` to `u_osal_snd_sync_msg`. The **original OSAL
  wrapper calls the callback** and makes the completion ioctl. Message flag
  `0x80` brackets this interval. Identity/tuple/ownership guards protect the
  bounded implementation. `probe_uipc_sync_wrapper` executes the original
  wrapper with a constructed guest callback and observes ioctl → guest callback
  → completion; no host invocation of a guest callback.
* **Kernel dynamic IDs:** original `.data` descriptors establish ordinary queue
  range `0x6000..0x6fff`, broadcast `0x7000..0x7fff`, and semaphore
  `0x6000..0x7fff` in distinct bitmaps. ID is `(key<<16)|lowest_free_slot`.
  Eight original ARM controls cover allocation, separate pools, release/reuse
  and invalid inputs with explicit helper fixtures. `CONNECT` now returns its
  allocated `type=0x2a,key=0x3f` callback-control queue instead of zero. This
  allocator starts in a **declared empty emulated namespace**, not the camera's
  global bitmap. The camera's observed control queue is `0x003f6091`; the fresh
  model's is `0x003f6000`. Unknown/stale frees stop at a provenance guard.
* **urandom TCGETS:** the original kernel `urandom_fops+0x20` points to
  `random_ioctl` at `0x602971a0`. Direct ARM execution returns **-EINVAL** for
  `0x5401`, without accessing even an unmapped output pointer. This exact
  negative response is opt-in; no entropy/hardware status is fabricated.

Existing external-service assumptions (including unverified synchronous
acknowledgements outside these recipients) remain explicitly experimental.
These contracts do not establish a full kernel, global process namespace,
signal/timing model or complete UIPC compatibility.

## Checkpoint retry defect and controls

An all-blocked UIPC stop left live PC after SVC, although the scheduler's saved
thread PC had been rewound. Saving context overwrote that rewind. Restoring
then ran the blocked caller past an **unanswered syscall**, potentially treating
an argument register as the result. One provisional late-VBUS resume reached
`tgkill(...,SIGFPE)` before consuming the stimulus. It is a failed diagnostic,
not USB behavior: `e0301-vbus-idle-trigger.*`.

Version-2 checkpoints now record stop semantics. Recognized unanswered SVCs
are retried only after checking original ARM/Thumb SVC-zero bytes and the stop
PC relationship. Invalid retry metadata is rejected. `begin()` schedules a
woken runnable guest thread instead of executing a still-blocked caller; with
none runnable it remains stopped. E0301 requires matching revision/version-2
checkpoints or a fresh boot. Its restore disables the historical synthetic
MonDrv-buffer repair; no MonDrv reinitialization is used on this path.

Constructed ARM and Thumb replay controls prove the unanswered ioctl executes
once and the following instruction sees its supplied reply. A full-camera-argv
retry from the early kikilog-open boundary **still diverged into an executable
heap fault**, also with matching trace hooks (`e0301-kikilog-resume-trace-control`).
A fresh run reaches the expected next ioctl. This residual checkpoint/CPU
continuation defect is unresolved; do not claim arbitrary-boundary checkpoint
equivalence. Fresh runs and bounded budget resumes are identified separately.

## Read-only physical observations

All operations used `tools/camera_debugger.py` / its `connect()` API only.
Receipts under `artifacts/analysis/e0301-camera-*` retain bytes/manifests:

* `info`: native debugger PID 703, root, USB extcmd feature 0x23.
* Process snapshot confirms im.elf PID 149, actual loaded libraries and OSD
  mappings. Command-line bytes are preserved separately.
* 88 callback bytes and 128 private OSAL state bytes were read. Reading 32
  bytes from im.elf's existing `/dev/uipc` mapping returned **-EIO**; it was
  **not repeated**. The manifest is partial. Uptime advanced 6861.27 → 6888.30
  and the debugger remained responsive. No `/dev/stream` open was attempted.
* `ls -ld` confirms `/setting` and `/setting/gps` exist; `/setting/sen` and
  `/setting/sen/smode` do not. New `--setting-overlay observed-e0301` answers
  **F_OK only** for these exact observed paths. Other runtime paths/permission
  queries remain unknown. An `ls` exit 1 here records the observed absence.
* Private singleton capture (`GetInstance` anchor checked before/after, not an
  atomic process snapshot) confirms `UsbBusPower+0x48` port type **3**, `+0x5c`
  detectable port 0, `+0x60=1`, `+0x64=0`, `+0x34=0`. The earlier constructed
  VBUS body with mapped type 0 instead sets `+0x34=1`; it is not the observed
  physical MSC state. Body `{0,1,3,0}` is a producer-format control consistent
  with the observed service state, not a captured kernel notification.
* `ps | grep KIKILOG`: existing `KIKILOG_MAIN` PID 946 and `KIKILOG_NOTIFY`
  PID 995. No process was started, stopped or changed.

## Full-argument startup and kikilog boundary

The camera-observed arguments select additional original startup components.
A fresh run stops at **4,044,150** opening `/dev/usb/kikilog` O_RDWR.
`kikilog.ko` SHA-256
`ca17036303074e8830521ad612d230fcbda92a10977336a61782eedb091d6980` has
original no-side-effect open/close routines returning zero. The image node is
verified as character 248:10. `--kikilog-device open-only` binds only these
operations and a fresh run stops at **4,046,846**, ioctl `0x80044a21`, arg 0.

Original `kikilog_resume` initializes two mutexes, resets get flag and timer/
status lists. It creates/opens logging storage and starts the main thread only
if that thread is absent, and allocates a notify queue only if absent. The
physical thread observations support a separate **observed-running-e0301**
profile: existing opaque main/notify resources, bounded resume stores only.
It supplies no existing log bytes, executes no native kernel worker and stops
at unknown logging/notification ioctls. This is a captured-state prerequisite,
not proof of kernel logger startup or persistent-storage behavior.

Exact reproduction/policies are retained in:

* `artifacts/analysis/e0301-run-observed.py`: phase-i control.
* `artifacts/analysis/e0301-run-camera-argv.py`: observed argument suffix,
  existing explicit device/entropy/backup/GRM/media policies and no boot stimuli.
* Fresh full-argument profile run and bounded continuation:
  `e0301-camera-argv-kikilog-running.*`, `e0301-camera-argv-next.*` (reports under
  `artifacts/execution`, logs under `artifacts/analysis`, separate checkpoints).

Phase-i controls with final kernel IDs reach idle at **111,842,050** and execute
real same-process sync callbacks during initialization. Producer-format VBUS
type-3 and subtype-2 controls consume their bytes/callbacks, then block again
without OSD. They do not substitute for the newly observed full argument list.

## Verification and remaining work

Reusable original-code probes:
`tools.research.probe_uipc_callback_finish` (4 ARM controls),
`tools.research.probe_uipc_dynamic_id` (8 ARM controls), and
`tools.research.probe_uipc_sync_wrapper` (original wrapper + guest fixture).
Each requires a new `--report` path and checks the input digest. Successful and
failed REA batches under `artifacts/analysis/e0301-*` retain exact target hashes,
queries, instruction evidence, Ghidra 12.1.4 profile and diagnostics. The two
mistargeted libInfraUsbCmn queries remain failed evidence; the corrected
libUsbBusPower exact-address batch succeeds.

Full-suite results and latest full-argument boundary are recorded in the current
checkpoint instructions. Earlier permission/test-import failures are retained;
no camera is used by ordinary tests. The next GUI work follows the real full
startup arguments and its concrete boundaries. OSD A/B remain unmapped in the
recorded runs; the independent SMAPH-S30 rasterizer boundary is unchanged.
