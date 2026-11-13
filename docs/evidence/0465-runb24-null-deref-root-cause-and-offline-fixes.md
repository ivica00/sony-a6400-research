# E0465 — B24 NULL-deref root cause, restore/observer fixes, offline verification

Date: 2026-11-13. OFFLINE only: no camera session, no USB, no module load. The
input is the B24 warm-kl log ring (`artifacts/analysis/e0457-runb24-ep0-observer/preflight/klog-ring.bin`).

## 1. Crash forensics (full oops from the ring)

Session boot segment, immediately after the module's deferred restore:

```
[ 1365.0756] [a6400_uvc] DISCONNECT schedule deferred restore started=0 in_flight=1
[ 1365.0762] [a6400_td] done phases=1ff failed=9 error=0 ep=1 list=00000000 id=0 count=1
             desc=1 root=68a844a0 retired=1 shadow=0 reconnect=1
[ 1365.0943] [a6400_uvc] DEFERRED restore work start in_flight=0
[ 1365.0944] [a6400_uvc] restore: reverting to Mass Storage...
[ 1365.0945] [a6400_uvc] demote_uvc_drivers: shadow0/shadow1 at tail of gc->drv_list
[ 1365.0947] [a6400_uvc] arm_ep0: enabling ep0-out=68a1c9c0 ep0-in=68a1c3c0 desc=604e4e24
[ 1365.0948] [a6400_uvc] arm_ep0: complete! EP0 ready for SETUP
[ 1365.0950] [a6400_uvc] restore: Mass Storage restored! gc->desc_tbl= (null) (b84=1 b85=1)
[ 1365.0951] [a6400_uvc] DEFERRED restore work done
[ 1365.403530] Unable to handle kernel NULL pointer dereference at virtual address 00000000
[ 1365.403768] pgd = 60104000
[ 1365.403829] [00000000] *pgd=00000000
[ 1365.403992] Internal error: Oops: 17 [#1] PREEMPT SMP
[ 1365.404079] Modules linked in: ... usbg_video(P)
[ 1365.404983] CPU: 0    Tainted: P             (3.0.27_nl-rt106+ #1)
[ 1365.405117] PC is at make_device_desc+0x70/0x10c
[ 1365.405203] LR is at setup_req+0xec/0xfbc
[ 1365.405283] pc : [<602bb9f8>]    lr : [<602b9590>]    psr: 60000013
[ 1365.405296] sp : 68aabdb8  ip : 68aabdf8  fp : 68aabdf4
[ 1365.405471] r10: 689e5880  r9 : 00000004  r8 : 68aa3e00
[ 1365.405562] r7 : 00000000  r6 : 00000000  r5 : ffdfe000  r4 : 68aa4ec0
[ 1365.405674] r3 : 00000001  r2 : 68aa3e00  r1 : ffdfe000  r0 : 00000000
[ 1365.405910] Control: 10c5387d  Table: 00aac04a  DAC: 00000015
[ 1365.406010] Process irq/229-dwc3 (pid: 55, stack limit = 0x68aaa128)
[ 1365.409066] [<602bb988>] (make_device_desc+0x0/0x10c) from [<602b9590>] (setup_req+0xec/0xfbc)
[ 1365.409363] [<602b94a4>] (setup_req+0x0/0xfbc) from [<602b8358>] (g_setup+0x30/0x3c)
[ 1365.409518] [<602b8328>] (g_setup+0x0/0x3c) from [<602bd364>] (gcw_setup+0x20/0x30)
[ 1365.409735] [<602bd344>] (gcw_setup+0x0/0x30) from [<602b291c>] (dwc3_ep0_delegate_req+0x38/0x50)
[ 1365.409893] [<602b28e4>] (dwc3_ep0_delegate_req+0x0/0x50) from [<602b3080>] (dwc3_ep0_interrupt+0x418/0x870)
[ 1365.410205] [<602b2c68>] (dwc3_ep0_interrupt+0x0/0x870) from [<602b1448>] (dwc3_thread_interrupt+0xd0/0x5a4)
[ 1365.411200] Code: e3a03012 e54b3036 e3a03001 e54b3035 (e1d730b0)
```

The parenthesised instruction is the fault: **`e1d730b0` = `ldrh r3, [r7]` with
`r7 = 0`** at VA `0x602bb9f8` (`make_device_desc+0x70`). It is not a jump to
0x0 and not a call through a NULL function pointer: the camera's gadget-core
device-descriptor builder read a halfword through a NULL **descriptor-table**
pointer while answering the host's `GET_DESCRIPTOR(device)` after the restore.

## 2. Event clock: the 28.7 s is the scheduled teardown, not a timeout

The module's EP0 ring recorder (RR lines dumped by `reference STOP`) carries
`ktime_get_ts` event times for the UVC class transfers:

* RR35 `t=1352.228815001` = GET_CUR setup, RR39 `t=1357.233969501` = SET_CUR setup
  → **5.005155 s apart**, matching the ETL decode (GET_CUR stop 5.005387 s,
  SET_CUR 5.011146 s; artifact `runb24-etl-analysis.json`).
* Anchoring that event clock to the ETL GET_CUR start (`00:13:41.206Z`) gives
  `UTC = ktime − 1352.2288 s + 00:13:41.206`: shared teardown `[a6400_td] done`
  at ktime ≈ `1380.63` → **UTC 00:14:09.6**; the crash printk `1365.403530`
  (printk clock = ktime − 15.555 s, fixed by the same anchor) → ktime
  `1380.96` → **UTC 00:14:09.94**, i.e. **0.33 s after the teardown step** and
  **28.73 s after GET_CUR**. The session was INIT at ktime ≈ 1335.5 + 45 s
  duration = 1380.5, so the crash is exactly at the scheduled teardown. It is
  **not** a 5 s/28 s EP0 timeout and not an EP0 completion racing a timeout.
* The race is instead **double teardown/ordering**: the shared session teardown
  raises the UDC DISCONNECT; the bridge's `disconnect_cb` schedules the E0399
  legacy deferred restore; that work waits only for `in_flight==0` and then runs
  asynchronously against the state the shared teardown has just restored and
  reconnected (19 ms later), re-driving the UDC and descriptor table.

## 3. Root cause

The B24 build is the **shared-PTP composite** (`--shared-ptp-enumeration-candidate
--composite-transport`). Its descriptor transaction is
`a6400_descriptor_install()` → native `save_desc_tbl` → `a6400_uvc_soft_disconnect()`,
which saves `s->original_root` (the stock PC Remote root) and restores it at the
end. The legacy `a6400_uvc_commit_descriptors()` (which is the only setter of
`g_saved_msc_desc_tbl`) **never runs in this build**, so `g_saved_msc_desc_tbl` is
NULL.

The E0399 legacy deferred restore then executes unconditionally:

1. It calls `a6400_uvc_restore_descriptors()`; the legacy table is NULL.
2. That function explicitly clears `gc+0x6c` to NULL ("static bundle, do not free"),
   and because the saved root is NULL it stays NULL.
3. It still starts the controller, calls `a6400_arm_ep0(dwc)` and raises D+
   (`a6400_usb_pullup(gc,1)`), so the host immediately re-enumerates.
4. `GET_DESCRIPTOR` → `dwc3_ep0_delegate_req` → `gcw_setup` → `g_setup` →
   `setup_req` → `make_device_desc+0x70` reads the NULL `gc->desc_tbl` through
   `ldrh r3,[r7]` → oops → Sony exception monitor → warm reboot.

The shared teardown had already produced a coherent state (`desc=1 root=68a844a0
reconnect=1`); the legacy restore destroyed it. This is the determinism of the
B24 reboot (the B23 `__queue_work` BUG was already fixed by E0456).

## 4. Fixes (two tracked files)

### 4.1 `tools/native_camera/uvc_composite_shim.c` — restore guard

`a6400_uvc_restore_descriptors()` now starts with:

```c
if (!g_saved_msc_desc_tbl) {
    printk("[a6400_uvc] restore: no legacy Mass Storage table saved; "
           "shared session owns descriptors, legacy restore skipped\n");
    return -6; /* -ENXIO */
}
```

and, as defence in depth, before starting the controller / arming EP0 / raising D+:

```c
if (*(void **)((char *)gc + 0x6c) == (void *)0) {
    printk("[a6400_uvc] restore: descriptor table is NULL; UDC stays disconnected\n");
    return -6;
}
```

Legacy builds (where `a6400_uvc_commit_descriptors()` did run and captured the
Mass Storage root) keep the exact previous behaviour.

### 4.2 `tools/native_camera/uvc_callback_bridge.c` — unbuffered observer

`a6400_uvc_obs_work_fn()` now prints **`[a6400_uvc] OBS work enter dwc=%08x` on
entry**, and prints **each `OBS <n>` row immediately when it is recorded** (the
end-of-loop dump loop is removed; `OBS done n=... iterations=...` remains). A
late crash/reboot can no longer erase the timeline — the B24 loss mechanism.

Source identities: `uvc_callback_bridge.c` sha256 `124fb2a22a975958de2533932a7746662952088d3a4d1482dc4f2396d32fc472`,
`uvc_composite_shim.c` sha256 `015569ec31d3776088d59aadc36166231e368cf6b16616c4f63f4475dd1e3688`.

## 5. Offline verification

* **Build** (unmodified tooling through the WSL executor bridge,
  `artifacts/analysis/e0455-build-bridge/`, 21 bridged gcc/ld/objcopy commands):
  `artifacts/native/uvc-transport-e0459-obs-unbuffered/usbg_video_a6400_shared_candidate.ko`
  **82,804 B**, sha256 `3ddb6bd545cbdb1ac7122eee0a0375a3d2e44b643c9395dd43b0235b80cc352f`.
  All four new strings are present in the linked module (checked directly).
* **Static audit**: `offline_module_audit_passed`, mode transport, **117 / 8 / 0**
  (`artifacts/analysis/uvc-transport-e0459-obs-unbuffered-audit/manifest.json`).
* **Unicorn observer harness** (`artifacts/analysis/e0459-obs-unbuffered-unicorn/`,
  runs the compiled `callback-bridge.o`): **pass = true** —
  `null_ep_ignored`, work item self-linked/data=0/func correct,
  old zeroed layout would BUG, second start is a no-op, no writes into watched
  kernel objects, and the unbuffered ordering:
  `obs_work_enter_printed=true`, `obs_work_enter_is_first_work_event=true`,
  `obs_start_printed_before_work_enter=true`,
  `obs_rows_flushed_immediately=true` with row iterations **{0,1,3,5,501}**
  (a buffered build would print all rows at 1500), `obs_done_after_rows=true`.
  Five transitions recorded, including the +5 s status-complete sample.
* **Unicorn restore-guard harness** (`artifacts/analysis/e0459-restore-guard-unicorn/`,
  executes the compiled `a6400_uvc_restore_descriptors_bridge`): **pass = true**
  * case A (shared build, `g_saved_msc_desc_tbl == 0`): returns `-6`,
    `gc+0x6c` keeps `0x6ABC0000`, flags/0x84/0x85 unchanged, **no** native
    call (pullup/disconnect/gcw_stop/start), no write to `gc`, and the exact
    skip printk;
  * case B (legacy saved root non-NULL): the guard does not block the legacy
    path — execution reaches the native `pullup(0)` call with `r1=0`.
  * the harness relocated all 312 object relocations with 0 skips.
* **Tests**: new `tests/emulator/test_restore_descriptor_guard.py` (5 tests:
  restore refused without saved root, no NULL table ever published, legacy path
  still restores/reconnects, unbuffered rows survive a late crash, work-enter
  precedes rows) — **5/5 OK**. Full suite `python -m unittest discover -s tests -q`:
  **1555 tests OK**.

## 6. Expected B25 discriminator (no camera action taken)

The next supervised session will now show whether the OBS work item executes:
`[a6400_uvc] OBS work enter` must appear immediately after `OBS start`, followed
by per-row prints with `ktime` timestamps. Anchoring GET_CUR with the ETL (as
above: camera ktime `1352.2288` = UTC `00:13:41.206`) then yields the S1/S2
comparison directly, and the restore guard should also remove the B24 reboot
mechanism. That last claim is **not** verified here — only a live session can
prove it.

## 7. Artifacts

* `artifacts/native/uvc-transport-e0459-obs-unbuffered/` (module + manifest + objects)
* `artifacts/analysis/uvc-transport-e0459-obs-unbuffered-audit/` (audit 117/8/0)
* `artifacts/analysis/e0459-obs-unbuffered-unicorn/` (harness + JSON + full-suite.log)
* `artifacts/analysis/e0459-restore-guard-unicorn/` (harness + JSON)
* `docs/evidence/0458-runb24-...md` (the run), `docs/evidence/0456-...md` (workqueue fix)
