# Module prerequisites for the camera-daemon

`camera-daemon` is the **client**. It cannot create the video node, the DMA
window, the session or the entry hook on its own: every one of those comes from
an authored kernel module that must already be loaded. This file states exactly
what that module has to be, what is broken about the current tooling, and which
protocol makes a session survivable.

Nothing here authorises a camera session. It is a prerequisite list.

---

## 1. What the module must provide

The daemon speaks only the ABI in `include/a6400_uvc.h`. It was transcribed from
`tools/native_camera/uvc_ptp_feed_runner.c`, `uvc_sensor_feeder_30fps.c`,
`uvc_ptp_entry_hook.h` and `uvc_composite_shim.c:989-1104`. The module must
export, on the char node **major 248 minor 33** (created by the helper when
`devno.ko` does not):

| ioctl | Arg | What the daemon needs from it |
| --- | --- | --- |
| `0x4038e000` INIT | 56-byte probe info | Starts the composite session. Returns `-1/EINVAL` in Mass Storage, so the daemon gates on identity first. |
| `0x0000e001` STOP | none | Ends the session. Must be followed by an all-zero session state. |
| `0x4008f000` REG_BUF | `{size, phys_addr}` | Registers the DMA window. `-22` means the window was rejected and the daemon fails closed. |
| `0x0000f006` ENABLE | none | Arms the bulk-IN pipe. |
| `0x0000f002` WAIT | none | Read-completion wait (**semantics undecoded, boundary B4**). |
| `0x4008f003` UPDATE | `{frame_size, phys_addr}` | Queues one frame. Must reject `frame_size + 12 > slot_capacity` with `-22`. |
| `0x0000f001` UNREG | none | Releases the registered window. |
| `0x8010f020` MOD_QUERY_DMA | 16-byte out | Owned-DMA window `{phys,total,slot,max_payload}`. **Only the authored shim has it**; the stock driver returns `-25/ENOTTY` and the daemon then needs `--dma-phys/--dma-size`. |
| `0x8010f028` QUERY_IDENTITY | `uint16[2]` | `{idVendor,idProduct}`; PC Remote is `0x054c:0x0caa`. |
| `0x8010f029` QUERY_USB_STATE | `uint32[4]` | `{flags, config, mode, speed}` health words. |
| `0x8010f022` QUERY_SESSION_STATE | `int[4]` | `{phase, pin, hooks, error}`. **All four must be 0 before hook retirement.** |
| `0xc020f026` HOOK_PUBLISH | 32-byte attest v2 | Publishes the entry hook, but only for a verified ptrace stop scope. |
| `0xc020f027` HOOK_RETIRE | 32-byte attest v2 | Retires it under the same scope. |
| `0xc020f023` ATTEST_STOPS | 32-byte attest v2 | Optional standalone attestation. |

The attestation block is `{version=2, owner=149, count<=512, tids*, registers=0,
siginfo=0, completed(out), error(out)}` and the module must verify, per TID,
that PID 149 is a member, `/proc/149/task/<tid>/status` says `Tgid: 149`,
`Pid: <tid>`, `Threads: <count>`, `ptrace(GETREGS)` shows user mode
(`CPSR & 31 == 16`) and `ptrace(GETSIGINFO)` shows `si_signo == 19`
(`tools/native_camera/uvc_ptp_stop_attest.c:54-113`). The daemon treats
`completed != count`, `error != 0` or a failed ioctl as a **failed** publish or
retire and never pretends otherwise.

## 2. How the module must be built

The only admissible builder is hash-pinned and offline:

```powershell
.\venv\Scripts\python.exe -m tools.research.build_uvc_composite_module `
    --output-dir artifacts/native/<new-name> `
    --shared-ptp-enumeration-candidate `
    --composite-transport

.\venv\Scripts\python.exe -m tools.research.audit_uvc_ptp_module `
    --build-dir artifacts/native/<new-name> `
    --output-dir artifacts/analysis/<new-name>-audit
```

`--shared-ptp-enumeration-candidate --composite-transport` is mandatory:

* `--shared-ptp-enumeration-candidate` selects the whole PTP/session/bridge
  object set and renames the legacy hooks (`USB_GADGET.md` §4.3).
* `--composite-transport` sets `-DA6400_COMPOSITE_TRANSPORT=1` and, **only when
  it is absent**, the builder defines `-DA6400_UVC_ENUMERATION_ONLY=1`
  (`tools/research/build_uvc_composite_module.py:196-208`). Without it the
  module forwards no `0x4008f000/f001/f002/f003/f006`, so the daemon would
  reach INIT and then fail at REG_BUF — the E0340 "enumeration only" state.

Optional but relevant:

* `--coherent-buffer-allocation` — `dma_alloc_coherent`, verified across three
  open/close cycles at 256 KiB (`docs/UVC_HANDOVER_PLAN.md:40`). Without it the shim
  falls back to the historical **fixed** window (`0x20000000`, 1294 KiB) which
  must not be used for new work (`docs/UVC_HANDOVER_PLAN.md:36-38`). The daemon
  refuses to guess a window when `MOD_QUERY_DMA` is absent.
* `--teardown-unconfigure-first` — the E0251/E0252 clean-teardown flag.
* `--producer-admission` — adds the opt-in `0x4008f004` admission ioctl. The
  daemon does **not** use it (it validates in userspace and then calls UPDATE).

## 3. Open boundary B5 — transport builds cannot be audited

This is the first blocker, and it is offline.

`tools/research/audit_uvc_ptp_module.py` refuses anything that is not an
enumeration candidate:

```python
if not manifest['shared_ptp_enumeration_candidate'] or not manifest['start_probe_only']:
    raise ValueError('Not an enumeration candidate')
```

and the builder forces `start_probe_only = True` for every non-transport build
(`build_uvc_composite_module.py:62-63`). Therefore **every transport build has
`start_probe_only: false` and cannot be audited at all**: the e0348/e0349
transport builds carry `"step-5 full guard audit deferred"` in their manifests.
Downstream tooling refuses a module whose audit hash does not match
(`p4_policy.py:33`, `run_uvc_ptp_session_test.py:84`,
`run_uvc_ptp_stop_diagnostics.py:32`, `run_pcremote_warmboot_test.py:91`).

Consequence: **under the project's own rules no transport module may be
deployed today.** A transport audit variant (or an `--allow-transport` mode with
transport-specific checks: forwarded-ioctl allow-list, `0x4008F000/F003/F006`
argument validation, START-bridge target, ENABLE→UPDATE ordering) has to be
written and pass offline first. The daemon in this directory does not change
that; it only removes the *userspace* excuse.

## 4. Open boundary B3 — the ENDPOINT defect that stops the stream

The transport builds **bind but produce no samples**. The best-supported cause is
a descriptor/bridge mismatch:

* The composite descriptor advertises the video-streaming bulk-IN endpoint as
  **`0x84`**.
* The START bridge matches **only `0x81`**:
  * `tools/native_camera/uvc_composite_shim.c:779-806` —
    `a6400_uvc_bulk_endpoint()` walks the endpoint array and
    `continue`s on any descriptor whose `desc[2] != 0x81`, then returns 0.
  * `tools/native_camera/uvc_callback_bridge.c:79-84` — on START the bridge
    calls that function and, when it returns 0, **drops the START**
    (`if (!bulk) return 0;`), so the reference `core_cb_start` is never invoked.
* Net effect: enumeration succeeds, the class driver binds, and no URB is ever
  submitted — exactly the observed "binds but never streams".

The daemon cannot fix this from userspace. If the bridge is not corrected, the
expected camera-side failure is: INIT succeeds, REG_BUF/ENABLE may succeed, and
`WAIT`/`UPDATE` never produce a completed transfer. The daemon counts that as a
transport error and, after 30 consecutive failures, exits 2 with a stage-failure
receipt — it does not retry forever and does not report success.

Settling evidence (all require a physical module session): an offline
Unicorn/audit fixture proving the bridge drops START for an `0x84` descriptor; a
kernel-side trace of `core_cb_start` arguments (the `printk`s at
`uvc_composite_shim.c:785,792-798` already exist) read back **before** any mode
change; a Windows USB ETW/DirectShow trace.

## 5. The E0340 reboot hazard

`docs/evidence/0340-uvc-fixedbuffer-and-mode-switch-reboot.md` records that
**switching the camera's USB mode to PC Remote while the UVC overlay was
streaming rebooted the camera**: uptime reset and `/tmp_bt` was cleared, so the
log was lost. The boundary is named
`uvc_mode_switch_during_overlay_unsafe`.

Rules that follow, and that the daemon is built around:

1. **Never change USB mode during a session.** Enter PC Remote by hand from the
   camera menu *before* loading the module and starting the daemon; return to
   Mass Storage only after the module is unloaded and the receipt is read.
2. **`/tmp_bt` does not survive a reboot.** The receipt must be written and read
   back before any step that can lose enumeration.
3. **The daemon never changes mode, never writes flash, never touches SD.**
   Its only write scope is `/tmp_bt` (the log enforces the prefix) plus the
   in-RAM device node it may create.
4. **A stop attestation failure parks the process** instead of retrying
   cleanup; a blind retry is how an unknown kernel state becomes a crash.

## 6. RAM-only deployment and the mandatory receipt protocol

| Rule | Detail |
| --- | --- |
| Write scope | `/tmp_bt` only (1 MiB tmpfs) by default. **No NAND, no `/system`, no `/setting`, no boot/preload.** The one opt-in exception is the SD card (`--sd-log --sd-mount`): `/dev/mmca1` only, mount point under `/tmp_bt/`, never `/dev/nflasha*`. |
| SD mount window | After PC Remote `054c:0caa` is confirmed and **before** INIT/streaming. Never in Mass Storage: the camera app owns the SD there and a mount can fail `EBUSY` or expose the wrong namespace. `--sd-mount` without `--sd-log` is refused. |
| SD verification | `stat` block identity 250:11, `/proc/mounts` must not already contain device or mount point, exact device+mount point after `mount(...,"vfat",...)`, sentinel write+read-back. Any failure unmounts and reports `mounted: 0`. |
| SD teardown contract | `sd_teardown()` runs on every teardown path (including the stop-attestation park, before blocking): rewrite the receipt while mounted, close the sink, `umount2(mountpoint, 0)`. A failed unmount is reported (`unmount_rc`, `mounted: 1`); never claim a clean unmount. The mount must be gone before returning to Mass Storage. |
| Battery-pull survival | A pull wipes `/tmp_bt` and erases the RAM log/receipt (E0350). With SD logging, `A6400LD.LOG` and `A6400RCPT.JSON` survive on the card. Because the receipt is `O_TRUNC`-copied, a pull during a write can leave a partial copy; the previous complete receipt is not preserved. |
| Deploy | `camera_debugger.py push` the daemon and the module into `/tmp_bt`, verify `sha256sum` there, `mknod /tmp_bt/video c 248 33` if absent, `insmod` from `/tmp_bt`. |
| Run | `--dry-run` first (discovery only), then `--arm-transport` with a bounded `--duration`. |
| Undeploy | `rmmod` **only** with a verified stop receipt (`stop_verified == 1`, session state all zero). Otherwise park: no `rmmod`, no retry, no mode change. |
| Recovery | Battery pull is the only guaranteed reset; it wipes `/tmp_bt`, so receipts must be read first (or recovered from the SD card). |
| Verification after recovery | MSC reachable, `/proc/uptime` monotonic (no reboot), 42 modules, `usbg_video` absent, `TracerPid: 0`, `/tmp_bt` back to baseline. |

Receipt fields the daemon writes (`/tmp_bt/a6400_lived_receipt.json`) that gate
teardown: `lifecycle.stop_verified`, `lifecycle.attest_completed` versus
`lifecycle.freeze_tid_count`, `lifecycle.hook_retired`, `status`, `exit_code`,
`fail_reason`, and the full statistics block. `tools/deploy.py` prints the exact
commands and verifies the binary hash, but never executes anything.

## 7. Module identity discipline

Never invent a module hash. The only transport hash retained in the evidence
base is `9a79fd2ee305640b732e10422f14b91f4f6fdb35161a4be83d3e4cf1b4fd940b`
(73,052 B, `USB_GADGET.md` §4.3) — and that build is precisely one of the
unauditable `start_probe_only: false` artifacts discussed in §3. Treat any
module whose audit hash is missing or mismatched as **not deployable**, and
record the hash you actually pushed in the session receipt.
