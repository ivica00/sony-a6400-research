# E0309 — blocked-UIPC dependency map at 308.6M: the app is service-idle, waiting for producers

Date: 2026-11-10. Offline checkpoint/report analysis only; no camera access, no
code change. No GUI frame.

## 1. Method

`artifacts/analysis/e0309-blocked-uipc-map.py` unpickles
`boot-e0315-live-block.ckpt` (308,622,155), maps every thread's `PC`/`LR` and
blocked target through the retained `e0315-live-block.json` mapping list
(270 regions), groups UIPC waiters by queue and cross-references the registered
callback map and pending message queues.

## 2. State at 308.6M

| item | value |
| --- | --- |
| threads | 68 |
| states | 37 `blocked_futex`, 21 `blocked_uipc`, 3 `blocked_poll`, 1 `blocked_read`, 3 `runnable`, 1 `running`, 2 `terminated` |
| UIPC policy | `kernel-e0301`, 73 callbacks |
| pending messages | 546 total, but **0 on all queues that have waiters** |
| runnable | `ULOGIOD_MAIN`, `mwf_monitor_inpu`, `thread_1054`, `monio(input)` (monitor/log only) |

## 3. Who waits on which queue

| queue | waiting service(s) | callback registered | pending |
| --- | --- | --- | --- |
| `-1` | `uipc_proxy_0..3` | n/a | 0 |
| `0x0055001F` | `InfraAvbbcIf` | no | 0 |
| `0x0055011E..0x00550123`, `0x005502F2` | `InfraAudioDecode`, `InfraAvEffector`, `InfraDecoder`, `InfraMovieEditor`, `InfraMovieEncode`, `InfraStillEncode`, `InfraMovieEncThm` | no | 0 |
| `0x0080003B` | `grm_dn_vdf_if` (GRM/VDF) | no | 0 |
| `0x009A015A` | `HDMI Msg Thread` | no | 0 |
| `0x00A3035A` | `THREAD_INFRA1` | no | 0 |
| `0x00A3035B` | `psm_dig_level_ma` | no | 0 |
| `0x00A506FD` | `WlanResource_Irq` | no | 0 |
| `0x00BD017A` | `InfraOnDmdLdr` | no | 0 |
| `0x0102021F` | `CameraBackground` | no | 0 |
| `0x012C032F` | `StlDateEvtLoop` (libObj date-event loop) | no | 0 |
| `0x018104BB` | `InfraNfc` | **yes**, handle 4119 (`flags=1`) | 0 |

`UsbControl` (1018), `UsbBusPower` (1016) and `BusPower` (1022) are not on a
queue: they are `blocked_futex` inside `libosal_uipc` (`LR=libosal_uipc+0x50AF`),
i.e. waiting on an OSAL event/condition the model never signals.

## 4. Named wait sites (stack evidence)

* `StlDateEvtLoop` waits on `0x012C032F`; the id is a literal in **libObj.so**
  (around `libObj+0x1EF3E1/0x13EC95C` call chain, with `libosal_utm` frames).
  This is libObj's own date/event queue.
* `THREAD_INFRA1` waits on `0x00A3035A` from a **libdig_level.so** call chain
  (`+0x5625`, `+0x235F`, `+0x2423`, `+0x5B34`, `+0x3B09`, `+0x591C`, `+0x4F37`,
  with `libIMDB.so+0xECD8`); `psm_dig_level_ma` waits on the adjacent
  `0x00A3035B`. The two adjacent ids are a candidate dig-level request/reply
  pair; both sides currently wait, and neither queue has a pending message.
* All other waiters are ordinary OSAL `rcv_msg_tmo` wrappers
  (`libosal_uipc+0x2721`) on their own service queues.

## 5. Meaning

The app is **service-initialized and idle**: the graphics/media/audio/HDMI/NFC/
WLAN/GPS/IFsys/IMM services are up and waiting for work messages; the USB
control tier never received the event that would move it. The missing pieces are
**producers**, not consumers:

1. the senders for libObj's `0x012C032F` and the libdig_level pair
   `0x00A3035A`/`0x00A3035B`;
2. the OSAL event/condition that wakes `UsbControl`, `UsbBusPower`, `BusPower`
   (their `libosal_uipc+0x50AF` wait path);
3. the kernel-module/USB-side messages that would give those services work.

No message is injected to break the wait, and no timeout expiry is fabricated.

## 6. Limits

* The map is a single checkpoint snapshot, not an atomic trace; thread registers
  were saved at cooperative switch points.
* Queue-to-service attribution is by thread name + wait site, not by symbol
  names for every queue.
* `0x012C032F`/`0x00A3035A` receivers are identified structurally (literals in
  libObj/libdig_level, stack frames); their senders are not yet decoded.

## 7. Next

1. Decode libdig_level `0x00A3035A`/`0x00A3035B` send/receive call sites
   (REA/Ghidra, identity-pinned `libdig_level.so` SHA from the inventory) and
   determine whether the pair is a request/reply contract or an external input.
2. Decode libObj's `0x012C032F` date-event sender and the osal_utm call chain.
3. Inspect the `libosal_uipc+0x50AF` wait for the USB tier and identify the
   OSAL event/registration that must be signalled (no host-forced callback).
4. Keep the USB lane contracts (receive id/inbound SETCONFIG, buspwr port type,
   `0x008F013A` consumer) as the UVC/PTP-adjacent path.

## 8. Artifacts

* `artifacts/analysis/e0309-blocked-uipc-map.py` / `.txt` / `.json`
* `artifacts/analysis/e0309-locate-ufw-ids.py` / `.log`
* `artifacts/analysis/e0309-stack-unwind.py`, `e0309-thread-states.py`
* No source/test changes in this step; suite remains **874 tests OK**
  (20.629 s).
