# E0351 — Offline verdict: Track B's RenderStream dies at START endpoint selection (not EP0 class); crash-safe logging + host USB trace ready

Date: 2026-11-11. **Offline only**: disassembly + Unicorn on the shipped objects and ZV-E10
reference. No camera, no USB, no module load, no debugger. Follow-up to E0350.

## Claim

1. **Ranking for where `Could not RenderStream to connect pins` originates:**
   (b) **START endpoint selection** — most likely; (a) EP0 UVC class probe/commit — unlikely;
   (c) undecidable without live kernel logs — fallback.
   In the shipped transport build the live START selector is
   `a6400_uvc_ptp_select_endpoint` (via `shared_endpoint`). It **fails closed**: any mismatch
   returns 0 and `uvc_callback_bridge.c:79-85` then skips the reference START callback, so
   `usbg_cmn_make_ep_list` never runs and the 0x84 bulk-IN pipe is never armed. It is silent
   (no printk) and adds a `*(dep+0x4C)&1` endpoint-enabled read **that the physically validated
   B3 selector (E0143, ~30 FPS UVC-only stream) did not perform**.
2. **EP0 class handling is byte-identical to the reference that physically streamed**: the
   shipped `core_cb_class` (708 B, SHA-256 `82124f7d…8c5b09`) equals the ZV-E10 build's, the
   bridge forwards class/interface requests for interfaces 1/2 in the transport build
   (12/12 Unicorn cases), and SET_CUR probe/commit plus GET_CUR(probe) return 0.
   One correctness defect exists but is tolerated on this host: with `wLength=34` the handler
   copies 34 bytes from a **26-byte** probe template, so the last 8 bytes
   (`dwClockFrequency`/version fields) are unrelated stack (poison `A5` in the fixture) —
   E0143 proves usbvideo.sys accepts this from the same handler.
3. `a6400_uvc_ptp_select_endpoint` **returns the wrapper under the expected live layout**
   (23/23 Unicorn cases); each single precondition violation was independently reproduced
   (endpoint address not 0x84, maxpacket ≠512, non-bulk/interrupt, dep flag clear, wrapper
   ownership mismatch, duplicate owners, gadget speed ≠3, nulls, count bounds).
4. Crash-safety for the next live run is prepared: the daemon can log JSONL + receipt to a
   vfat SD target with `O_SYNC` behind strict gates (PC Remote only, `/dev/mmca1` only,
   never internal flash), and a host-side capture tool selects Windows USB ETW (USBPcap/Npcap
   are not installed on this host) with dry-run and manifest receipts.

Status: offline verified (analysis + tooling). No hardware claim.

## Method

| Input | Size / SHA-256 |
| --- | --- |
| ZV-E10 reference `usbg_video.ko` | 20,668 B, `d385a051…f4fb` |
| shipped `usbg_video_a6400_shared_candidate.ko` | 71,960 B, `a1d95975…b6692` |
| `uvc_ptp_adapter.o` / `uvc_ptp_session.o` / `callback-bridge.o` / `reference.rebound.o` | `4d97373f…`, `558206a6…`, `54bd60e9…`, `800299aa…` |

1. Disassembly of reference `.text` 0x17B0–0x1AC8 (`core_cb_class`), 0x1390–0x17B0
   (GET helper) and 0x11BC–0x1390 (probe template helper) with capstone, annotated from the
   297 `.rel.text` entries (raw `bl` words are placeholder `ebfffffe`).
2. The real objects are linked into flat fixtures and executed under Unicorn 2.1.4 with
   synthetic kernel objects: `selector-unicorn.elf` (adapter+session, 23 cases),
   `bridge-unicorn.elf` (12 cases), `reference-class-unicorn.elf` (10 cases, bounded 600
   instructions).
3. Tool: `tools/research/unicorn_uvc_ep0_select.py` (stdlib + capstone + unicorn; built-in
   ELF32 reader so the venv interpreter needs no WSL). Receipts:
   `artifacts/analysis/unicorn-uvc-e0351/{REPORT.md,unicorn-uvc-e0351.json}`.

## Observation (key rows)

**EP0 class dispatch (`core_cb_class`, .text 0x17B0).** Gate at 0x17C8–0x17E8: class bit
(`bmRequestType & 0x20`) and recipient 1/2, else return 2 (NOT_HANDLED). `SET_CUR`
(0x21/0x22, bRequest 0x01) allocates an EP0 request, `buf = this_ex+0x1C`, `length = wLength`,
queues with `uvc_ep0_comp`; **no selector/wIndex/length check** → 0. `wValue==0x0200`
(COMMIT) additionally notifies user callback slot 7. `GET_CUR/MIN/MAX` with `wIndex != 0` and
`wValue 0x0100/0x0200` (VS PROBE/COMMIT) replies from a 26-byte `.rodata+0x7A` template
(`bFormatIndex=1, bFrameIndex=1, dwFrameInterval=333333, dwMaxVideoFrameSize=14745600,
dwMaxPayloadTransferSize=300000`) with `dwFrameInterval` patched from `this_ex+0xA8`
(state 1 → 333333 / 30 fps, state 2 → 400000 / 25 fps). Entity-ID `wIndex` (`high byte != 0`)
→ 1 stall; GET_RES/LEN/INFO/DEF → 1 stall.

**Unicorn case counts:** selector 23/23, bridge CLASS 12/12, bounded reference class 10/10.
Expected-live selector layout returns wrapper `0x60103000`; violations rejected.

**The two reads that the E0143-proven selector did not do** (the top suspects):
`*(u32*)(dep+0x4C) & 1` (endpoint-enabled flag at START time) and
`*(u8**)(dep+0x1C)` (descriptor expected `7,5,0x84,bulk,interval 0,maxpacket 512`).
`shared_endpoint` also requires `*(u32*)(gadget+0x20)==3` (USB_SPEED_HIGH — matches the live
`dwc3.0 current_speed=high-speed`).

**Crash-safe logging (camera-daemon, offline).** New flags `--sd-log`, `--sd-mount`
(explicit consent), `--sd-dev` default `/dev/mmca1`, `--sd-mountpoint` default `/tmp_bt/sd`.
Gates: both flags AND PC Remote `054c:0caa` AND not dry-run AND INIT not started; device must
be the block node `/dev/mmca1` (250:11) and not `/dev/nflasha*`; `/proc/mounts` must not
already contain device/mountpoint; mountpoint only under `/tmp_bt` (rootfs is read-only);
`mount("vfat")` + exact `/proc/mounts` re-read + `O_SYNC` sentinel write/read-back.
Sink `A6400LD.LOG` `O_WRONLY|O_CREAT|O_APPEND|O_SYNC` (fsync fallback), 128 KiB cap with one
rotation, every completed JSONL line mirrored; a failed write drops the sink (counted) but
never blocks the frame loop. Receipt copied `O_SYNC` as `A6400RCPT.JSON`; receipt gained
`sd_log{...}` + `log_sd_lines`/`log_sd_errors`. Unmount runs on every teardown path,
including the stop-attestation park. ARM build 629,592 B `aa2c1cb0…`, host tests 399/399.

**Host capture (offline).** `tools/research/renderstream_capture.ps1` detects
USBPcapCMD/dumpcap/ETW; this host: `USBPcapCMD` and `dumpcap` absent, `logman`/`wpr` present,
all three USB ETW providers registered, session elevated → selects ETW
(`logman create trace … -pf providers.txt -o usb-capture.etl -ets`; `logman stop/delete`).
`-DryRun` verified (exit 0, manifest with `dry_run:true`); live path would capture the
RenderStream attempt with ffmpeg stderr + PnP/dshow snapshots in one manifest. Plan:
`artifacts/analysis/trackb-diag-e0351/HOST_CAPTURE_PLAN.md`.

## Alternative explanations

- EP0 could still be the blocker **outside** class probe/commit: the standard-descriptor hook
  (`bind_ep0` patches four kernel sites) or SET_INTERFACE handling. Not disproven offline.
- The descriptor topology (VS alternate settings) was considered: the 173-byte composite puts
  the bulk endpoint in VS alternate 0, which is legal for bulk UVC, and E0143's UVC-only build
  streamed with the same handler; no offline evidence selects it as the cause.
- `dep+0x4C`/`dep+0x1C` contents at START dispatch live in `vmlinux` and could not be read
  here — this is precisely why (c) remains a fallback.

## Confidence and limitations

- High: EP0 class handler is byte-identical and the bridge forwards probe/commit; the selector
  returns 0 on any precondition mismatch and does so silently.
- Medium: that the live `dep+0x4C`/`dep+0x1C` differ from the strict expectation (needs the
  vmlinux check below or a live printk/trace).
- Synthetic kernel objects only; gadgetcore return-code mapping and `this_ex+0xA8` writer
  remain undecidable from these binaries. No hardware effects are claimed.

## Next check and fix candidates

1. **Highest-value offline check**: disassemble a6400 `vmlinux.bin` using the linear read
   already proven by `probe_ptp_endpoint_contract.py` (offset = VA − 0x60108000) at
   `0x602B92F0`/`0x602B8ECC` (start/startFuncDrv), `0x602BA6EC` (`ep_ctrl_enable_ep`) and the
   `dwc3_wIndex_to_dep` caller. Answer: is `dep+0x4C` bit0 set **before** the START callback,
   and is `dep+0x1C` the `7,5,0x84,bulk,512` descriptor at that moment? If either is no,
   verdict (b) is confirmed without a session and the fix is to drop those two reads (accept
   the wrapper gadgetcore already validated, as the E0143-proven selector did).
2. Live Run A/B/C with SD logging + ETW armed (see E0352 for the bounded plan) — only after
   the user's go-ahead; this record does not run anything.
