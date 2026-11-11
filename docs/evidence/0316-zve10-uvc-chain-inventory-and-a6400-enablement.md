# E0316 — ZV-E10 2.03 UVC chain inventory and a6400 enablement plan

Date: 2026-11-11. Inputs: local ZV-E10 2.03 extraction
(`firmware/extracted_zve10_v203_linuxnames/`, E0134), local a6400 8.2.5.7
extraction, retained E0154 descriptor candidate. No camera writes, no USB mode
change, no module loading, no `/dev/mem`. Reference analysis only.

## 1. Answer in one paragraph

The complete UVC chain exists **only** in the ZV-E10 reference firmware and is
now inventoried: `usbg_video.ko` (UVC gadget video driver, iso-in, DMA330),
`libInfraStreamingUsb.so` (host start/stop, PROBE/COMMIT, `VideoEsManager`) and
the ZV-E10 `libInfraUsbCmn.so` (`CUsbGadgetStreaming`, PAL/NTSC descriptor
tables, video buffer registry). All three have the **same vermagic** as a6400
(`3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7`), their module-provided kernel
symbol dependencies (`dma330_mem_transfer_async`, `osal_snd_msg`,
`osal_valloc_msg_wait`, …) are exported by a6400's own `dma330.ko` and
`osal_uipc.ko`, and the kernel-level dependency surface is identical between the
two models. The UVC+PTP configuration descriptor is available as a compiled,
verified 173-byte serializer output (E0154, `cc99cbd9…`): PTP interface
`6/1/1` + 3 endpoints, IAD, UVC VideoControl `0x0E/1`, UVC VideoStreaming
`0x0E/2` with MJPEG 1280x720 and bulk-IN endpoint `0x82` 512 B. This supplies
the missing UVC descriptor evidence for the a6400 otgcore contract. Loading or
deploying the reference chain remains an explicit, unauthorized physical step;
the offline/emulator enablement path is listed in §6.

## 2. Chain inventory (hashes verified locally)

| Component | Size (B) | SHA-256 | In a6400 tree |
| --- | --- | --- | --- |
| ZV-E10 `kmod/usbg_video.ko` | 20,668 | `d385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb` | **absent** |
| ZV-E10 `kmod/usbg_audio.ko` | 20,456 | `8f73572784aab15da291c9f311a945d4ec56d2dd4162218164bc2aa18cc5fae0` | absent |
| ZV-E10 `lib/libInfraStreamingUsb.so` | 52,524 | `0a9448e364e8f014db02edc8e164470c70f2d2143ce5de74697e9ffba697cce8` | **absent** |
| ZV-E10 `lib/libInfraUsbCmn.so` | 94,612 | `af830315ce51c38b010995f2147d556286364323734f64b877fcc3bb1a916c02` | present as different build (85,876 B) |

a6400 has `usbg_cmn.ko`, `usbg_stillimage.ko`, `usbg_storage.ko`,
`usbg_buspower.ko` and `g_mass_storage.ko`, but **no video/audio gadget
function module and no streaming library**.

Proof points from the reference binaries:

- `usbg_video.ko`: `usbg_video_core.c`, `USB Gadget Video Streaming (Iso.-in)`,
  `usbg_video_core_open/write/ioctl/release`, `uvc_ep0_comp`,
  `usbg_video_get_ep_info`, `usbg_video_get_ep0_buffer`,
  `dma330_mem_transfer_async`, `uvc_transfer_dmac_cb`,
  `usb_gadgetcore_register_driver` / `_unregister_driver`,
  `/dev/usb/video`-style device identity.
- `libInfraStreamingUsb.so`: `UsbInfraStreaming_Init/Exit`,
  `StreamingGadget_init/fin`, `usb_streaming_register_gadget`,
  `StateMachine` `Idle/Ready/Started` handlers
  (`funcHostStartVideoEvt`, `funcHostStopVideoEvt`, `funcProbeReqVideoEvt`,
  `funcCommitReqVideoEvt`, `funcVideoStartBulkEvt`,
  `funcStartVideoDriverCmp`, `funcStopVideoDriverCmp`),
  `VideoEsManager::video_stream_prepare/start/stop`,
  `AudioEsManager` equivalents.
- ZV-E10 `libInfraUsbCmn.so`: `CUsbGadgetStreaming::on_create/on_delete`,
  `proc_kevent_video/audio`, `RegVideoDataBufInfo`,
  `UnregVideoDataBufInfo`, `UpdateVideoBufEvt`, `WaitVideoReadCmp`,
  `SendProbeInfo`, `SendCommitInfo`, `streaming_pal_desc_tbl`,
  `streaming_ntsc_desc_tbl`, `streaming_pal/ntsc_interface_desc`, `/dev/usb/video`.

## 3. UVC activation sequence (gap 1 map)

The reference chain implies the following original-firmware sequence (symbol
names are from the ZV-E10 binaries; exact instruction-level ordering is a next
step, not yet claim):

1. `StreamingGadget_init` / `usb_streaming_register_gadget` registers the UVC
   gadget function driver through `usb_gadgetcore_register_driver` (same API
   a6400 already uses for `usbg_stillimage`).
2. Host selects the UVC configuration (`SET_CONFIG`/descriptor path); the
   function driver receives class events via `proc_kevent_video` and
   `proc_class_event_video`.
3. Host-start video event → `StateMachine::Idle/Ready::funcHostStartVideoEvt`
   → `funcStartVideoDriverCmp` → `VideoEsManager::video_stream_start` →
   `set_path_sync` + video driver start.
4. UVC `PROBE` / `COMMIT` control requests → `funcProbeReqVideoEvt` /
   `funcCommitReqVideoEvt` → `SendProbeInfo` / `SendCommitInfo`
   (`usbg_video_probe_commit_ctrls`).
5. Stream start → `funcVideoStartBulkEvt`; data path registers buffers with
   `RegVideoDataBufInfo`, feeds `UpdateVideoBufEvt`, waits with
   `WaitVideoReadCmp`; `usbg_video` queues iso-in requests and completes DMA via
   `dma330_mem_transfer_async` / `uvc_transfer_dmac_cb`.
6. Host-stop / teardown: `funcHostStopVideoEvt` → `video_stream_stop` →
   `StreamingGadget_fin` / `usb_streaming_unregister_gadget`.

## 4. UVC+PTP configuration descriptor (gap 2 evidence)

Compiled, verified serializer output from E0154:
`artifacts/native/uvc-ptp-descriptors-e0154/uvc-ptp-hs-config.bin`,
173 bytes, SHA-256 `cc99cbd9ca3ed62b009de00e69095cf04fdc6986b337719dbda8e7c2d197231f`.
Parsed layout:

| Offset | Descriptor |
| --- | --- |
| 0x00 | configuration 9 B: `wTotalLength=0xAD`, 3 interfaces, value 1, attributes 0x80, 250 mA |
| 0x09 | PTP interface 9 B: `06/01/01`, interface 0, 3 endpoints |
| 0x12 | EP `0x81` bulk IN 512 |
| 0x19 | EP `0x02` bulk OUT 512 |
| 0x20 | EP `0x83` interrupt 32 interval 7 |
| 0x27 | IAD 8 B `{01,02,0E,03,00,00}` |
| 0x2F | UVC VideoControl interface `0x0E/1`, 0 endpoints |
| 0x38–0x57 | VC class-specific (header/input terminal/camera terminal/output terminal) |
| 0x60 | UVC VideoStreaming interface `0x0E/2`, 1 endpoint |
| 0x69–0xA0 | VS class-specific: input header, format MJPEG, frame 1280x720 (interval 0x01A5E = 333,333 → ~30 fps), color matching |
| 0xA6 | VS bulk IN `0x82` 512 B |

This matches the earlier experimental host composite capture, now with a
firmware-source serializer and full byte evidence; the PTP interface bytes also
match the a6400 physical PC Remote capture (E0154 24 checks).

## 5. Media buffers / DMA (gap 3 map)

The reference chain identifies the missing buffer ownership model:

- `usbg_video.ko` object names `usbg_video dma_info`, `usbg_video dma_req`,
  `usbg_video_buf_info`; transfer via `dma330_mem_transfer_async` and
  completion `uvc_transfer_dmac_cb`; cache helpers `arch_phys_to_noncache`,
  `arch_phys_to_cache`.
- ZV-E10 `CUsbGadgetStreaming`: `RegVideoDataBufInfo(usbg_video_buf_info*)`,
  `UnregVideoDataBufInfo`, `UpdateVideoBufEvt(usbg_video_data_info)`,
  `WaitVideoReadCmp` — a registered-buffer/lifetime/wait contract.
- a6400's `stream2`/`mcmn` path (E0303 R5) is a different media mapping device;
  the UVC path needs this video-buffer registration/DMA contract instead.

Concrete contract work: exact `usbg_video_buf_info`/`usbg_video_data_info` and
`usbg_video_probe_commit_ctrls` layouts, DMA330 source/destination ownership,
cache-mode transitions, buffer lifetime and the read-completion predicate, plus
PTP/JPEG source framing (DMM-owned frames, profile constraints).

## 6. a6400 enablement plan

1. **Static compatibility (done here):** identical vermagic; identical
   kernel-level dependency surface; module-provided dependencies present in
   a6400 (`dma330.ko` exports `dma330_mem_transfer_async`; `osal_uipc.ko`
   exports `osal_snd_msg`, `osal_valloc_msg_wait`, `osal_snd_sync_direct`,
   `osal_snd_sync_msg`, `osal_dynamic_id`, `osal_free_msg`,
   `osal_rcv_msg_tmo`). This is symbol-name/vermagic parity, not loadability or
   ABI proof.
2. **Offline/emulator route (no physical writes):** declare the ZV-E10 chain as
   hash-pinned reference inputs; add an opt-in kernel-export/load-order contract
   (`usbg_cmn` → `usbg_video`/`usbg_audio`; `libInfraStreamingUsb` +
   streaming-enabled `libInfraUsbCmn`); feed the E0154 173-byte descriptor
   through the original serializer/IAD path; model the host UVC control sequence
   (SET_CONFIG/INTERFACE, PROBE, COMMIT) as an explicit opt-in contract; back
   video buffers with the DMA330 ownership model and a native JPEG frame source
   from `tools/native_camera` (existing `uvc_sensor_feeder_30fps` /
   `uvc_stream_feeder` sources must be re-validated, not assumed).
3. **Physical route (explicitly not authorized here):** loading the ZV-E10
   modules onto the a6400 changes camera runtime (module load + USB re-enum);
   it requires its own scoped approval, recovery plan and teardown receipts.
4. **Checks/tests:** module import resolution vs a6400 exports (done
   statically); descriptor parse tests; UVC control state-machine tests; buffer
   lifecycle and DMA completion tests; PTP coexistence and teardown tests.

## 7. Boundaries (unchanged, explicit)

- ZV-E10 chain is **not loaded** on a6400; no UVC function is claimed.
- Full/SuperSpeed, endpoint `0x82` allocation, DMM/JPEG ownership, buffer
  lifetimes, Windows grouping and PTP coexistence remain unverified.
- `uvc-control`/`uvc-streaming`/composite `otgcore_template` stay unresolved;
  the descriptor evidence does not invent an otgcore io-type mapping.
- No camera writes, mode changes, module loads or `/dev/mem` were performed for
  this note.
