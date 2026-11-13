# E0456 — Workqueue initialisation fix for the E0446 observer and E0399 deferred restore (offline)

Date: 2026-11-13. OFFLINE only: no camera, no USB, no module load. Build through
the existing WSL ARM toolchain; no camera was touched.

## 1. Root cause being fixed

Run B23 (docs/evidence/0453) rebooted the camera during the daemon's
`uvc_stop` teardown. The warm klog ring's boot-0 tail contains:

```
Illeagle Instruction at 0x60111104
[current task] program: /tmp_bt/a6400-lived (pid 2023)
 <- 0x6014a060 [caller 0x6014a3c8]   __queue_work
 <- 0x6014a38c [caller 0x6014a4a8]   queue_work_on
 <- 0x6014a474 [caller 0x6014a4d4]   queue_work
 <- 0x6014a4b8 [caller 0x5f5863f4]   schedule_work
 <- 0x5f581000 + 0x53f4              usbg_video `invoke` (DISCONNECT branch)
```

Disassembly of the retained live vmlinux (base `0x60108000`) pins the exact
check the module violated (`__queue_work+0x220`, VA `0x6014a280`):

```
0x6014a26c  ldr  r2, [r5, #4]     ; work->entry.next
0x6014a270  add  r3, r5, #4       ; &work->entry
0x6014a274  cmp  r2, r3
0x6014a27c  beq  0x6014a28c       ; list_empty(&work->entry)
0x6014a280  bl   __bug_noarg      ; BUG_ON(!list_empty(&work->entry))
```

`struct work_struct` on this 32-bit ARM kernel is
`{data, entry.next (+4), entry.prev (+8), func (+12)}`. Both E0446 work items
were static zero-initialised words with only `func` written, so
`entry.next == 0 != &entry`; the first `schedule_work()` BUGs in kernel context
and the Sony exception monitor reboots the camera. The E0446 observer had the
same defect, so it could not have been validated on hardware even with a
`GET_CUR` (E0453 §4).

## 2. Fix (only tracked file changed: `tools/native_camera/uvc_callback_bridge.c`)

Added `struct a6400_work_struct { uvc_u32 data, next, prev, func; };` plus

```c
static void a6400_work_init(struct a6400_work_struct *w, void (*fn)(void *))
{
    w->data = 0;                 /* WORK_DATA_INIT: no pool, not pending   */
    w->next = (uvc_u32)&w->next; /* entry.next -> &entry                   */
    w->prev = (uvc_u32)&w->next; /* entry.prev -> &entry                   */
    w->func = (uvc_u32)fn;
}
```

* `g_obs_work` and `g_restore_work` are now `struct a6400_work_struct` (were
  zeroed `uvc_u32[8]`); both call sites initialise before `schedule_work()`.
* `a6400_uvc_schedule_restore()` is idempotent (`g_restore_scheduled` guard set
  before scheduling, cleared at `a6400_uvc_restore_work_fn()` entry), so a
  second DISCONNECT cannot queue an already-pending item (the other trigger for
  the same BUG).
* Observer behaviour is unchanged: read-only polling of
  ep0state/next_event/eps flags/event lpos with `ktime_get_ts`, one printk per
  change, `g_obs_started` one-shot guard, no writes into dwc/eps/event objects.
* The deferred-restore settle loop (`in_flight` poll, 20 x `msleep(10)`) and
  all E0399/E0446 semantics are unchanged.

Diff scope: declarations + initialiser + two schedule sites + the guard; no
other file in the tree was modified for the fix.

## 3. Build environment boundary (why a bridge was needed)

Windows Python cannot spawn `wsl.exe` in this sandbox (verified: any grandchild
process gets `Wsl/E_ACCESSDENIED`, while a direct harness-shell `wsl.exe` call
works). The unmodified build tooling was therefore run with its WSL calls
proxied: `artifacts/analysis/e0455-build-bridge/wsl_executor.py` is started
directly by the harness shell and serves queued argv commands over workspace
files; `artifacts/analysis/e0455-build-bridge/run_build_host.py` loads
`tools.research.build_uvc_composite_module`, replaces only its `subprocess`
reference with the queued proxy, and calls `main()`. The build script itself was
not edited; 21 commands were bridged (objcopy/gcc/ld).

## 4. New module

* `artifacts/native/uvc-transport-e0455-obs-fixed/usbg_video_a6400_shared_candidate.ko`
  **82,532 B**, SHA-256 `2c6f82e9ce6a1cbffa2b0f608badb3a4172b88ce23ad1a4f212e9fe0496da7fe`.
* Same build flags as the E0446 candidate:
  `--shared-ptp-enumeration-candidate --composite-transport` (trace off,
  owned-coherent allocation, `start_probe_only=false`).
* Full manifest `artifacts/native/uvc-transport-e0455-obs-fixed/manifest.json`
  records all input hashes (bridge source hash changed only by this fix).

## 5. Audit

`tools.research.audit_uvc_ptp_module` was run with the sandbox-safe flow:
`--prepare-only` (writes the guard fixture and the exact gcc/ld commands), the
two commands executed by a direct WSL call, then the audit with
`--linked-elf artifacts/analysis/uvc-transport-e0455-obs-fixed-audit/module-guards.elf`.

Result (`artifacts/analysis/uvc-transport-e0455-obs-fixed-audit/manifest.json`):

```
status=offline_module_audit_passed  audit_mode=transport
count=117  skipped=8  failures=0
module_sha256=2c6f82e9…96da7fe  module_bytes=82532
```

## 6. Unicorn observer harness (extended with the workqueue invariant)

`artifacts/analysis/e0455-workqueue-init-unicorn/e0455-workqueue-init-unicorn.py`
executes the compiled observer from the new `callback-bridge.o` against the same
scripted timeline (including the +5 s status complete) and now also checks the
fixed work item before `schedule_work`:

```
null_ep_ignored                      true
schedule_called_once_on_start        true
work_data_zero                       true
work_entry_self_linked               true
  entry=0x70520030  data=0x0  next=0x70520030  prev=0x70520030  func=0x705005ec
old_zeroed_layout_would_bug          true   (model: entry.next 0 != &entry)
second_start_noop                    true
writes_into_watched_kernel_objects   []     (observer stays read-only)
recorded_rows                        5      (ep0s 0,2,2,3,1 incl. +5 s status complete)
pass                                 true
```

Result: `artifacts/analysis/e0455-workqueue-init-unicorn/e0455-workqueue-init-unicorn.json`.

## 7. Tests

* New `tests/emulator/test_workqueue_work_init.py` (3 tests): zero-initialised
  work item trips the list-empty model (the B23 BUG), initialised item is
  eligible (`data` = WORK_DATA_INIT = 0), and an item already linked into a
  worklist is rejected again. 3/3 OK.
* UVC test set `python -m unittest discover -s tests -p 'test_uvc*.py'`: **31 OK**.
  E0351 Unicorn UVC suite: **18 OK**.
* Full suite `python -m unittest discover -s tests -q`: **Ran 1540 tests,
  FAILED (failures=9)**. All 9 failures are the status-card/README/SVG sync
  tests (`test_research_status_dashboard`, `test_research_status_sync`) caused
  by the concurrent offline track adding newer evidence documents without
  regenerating the status card; none is related to this change (no test of the
  bridge, module, or workqueue fails). Log:
  `artifacts/analysis/e0455-workqueue-init-unicorn/full-suite.log`. The status
  card was intentionally not regenerated from this run to avoid clobbering the
  concurrent track.

## 8. Next

Host-side B24 harness (wait for the authored composite `054C:0322`, one ffmpeg
attempt, auto-restore wait, ETW/timeline decode) and then **one** new supervised
camera session, which needs a fresh explicit go-ahead. The B24 success criterion
is unchanged from E0446: `OBS` timestamps for the ep0state 2→3 (status armed)
and status XferComplete events compared with the host's ~5.01 s Stop Endpoint in
the ETL, yielding S1, S2 or a precise Inconclusive reason.
