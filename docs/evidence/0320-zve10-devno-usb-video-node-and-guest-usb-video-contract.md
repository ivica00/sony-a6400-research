# E0320 — ZV-E10 `devno.ko` UVC device nodes (248:32/33), a6400 gap, and fail-closed `GuestUsbVideo`

Date: 2026-11-11. Inputs: extracted a6400 8.2.5.7 and ZV-E10 2.03 `devno.ko`
(nflasha7/initrd), ZV-E10 `usbg_video.ko`, E0319 ioctl decode. Offline only; no
camera writes, no module loading, no mode change.

## 1. Result

The UVC chain's device-node layer is now identified and the "only in ZV-E10"
difference is proven at byte level:

| Model | `devno.ko` SHA-256 | UVC nodes |
| --- | --- | --- |
| a6400 8.2.5.7 | `3b36fcea8687d7f29112a7008ce61fde9229679ebc24c65ec2d21cf3af632f56` | **absent** |
| ZV-E10 2.03 | `273db657a8e2c9c8752b0ace56817357ddea38285a52b5cb7007a3fcf9df33c1` | `/dev/usb/audio` **248:32**, `/dev/usb/video` **248:33** |

`devno.ko` exports the `udif_devnodes` table consumed by USB gadget drivers.
The table is an array of 12-byte entries `{name_offset, dev_t(word), flags}`;
for the `usb/*` group the flags word is `0x10000 | minor`. Decoded entries:

| Path | major:minor | flags word |
| --- | --- | --- |
| `/dev/usb/massstorage` | 248:0 | 0x10000 |
| `/dev/usb/sicd_core` | 248:1 | 0x10001 |
| … (kikilog 248:10 matches the camera's `/dev/usb/kikilog` node) | | |
| `/dev/usb/adb` | 248:16 | 0x10010 |
| `/dev/usb/audio` | **248:32** | 0x10020 |
| `/dev/usb/video` | **248:33** | 0x10021 |

The a6400 table contains the same other entries but not the audio/video rows,
so even if the ZV-E10 gadget modules were present, the a6400 node namespace has
no endpoint for them.

## 2. Module-side compatibility (unchanged from E0316)

- `usbg_cmn.ko` exports `usbg_cmn_reg`/`usbg_cmn_dereg`,
  `usb_sync_alloc_phys_buffer`/`usb_sync_free_phys_buffer` and
  `usbg_cmn_copy_probe_info`; both models export the same names.
- `usbg_video.ko` (ZV-E10, `d385a051…`) registers through `usbg_cmn_reg` and
  imports `dma330_mem_transfer_async` + `osal_*`, which a6400 provides
  (symbol-name/vermagic parity, E0316). This is still not loadability proof.

## 3. Implemented (fail-closed)

- `src/a6400/execution/guest_usb_video.py`:
  `GuestUsbVideo` char-device model with the verified identity
  (**248:33**, `/dev/usb/video`), open/close served and recorded, and every
  ioctl/write/read stopping with an explicit boundary
  (`usb_video_ioctl_contract_unresolved`,
  `usb_video_write_buffer_contract_unresolved`,
  `usb_video_read_completion_contract_unresolved`). Recognized commands are
  decoded with E0319's `decode_usb_video_ioctl`; unknown commands are recorded
  as generic `_IOC` only.
- `devno_usb_video_evidence()` returns both devno hashes, the ZV-E10 node rows
  and the a6400 missing-node list.
- Tests (`tests/test_guest_usb_video.py`): identity, open/close, known ioctl
  stop, unknown ioctl generic decode, write/read stop, unknown-owner rejection,
  devno evidence. **913 tests OK**.
- No success is fabricated: the driver's buffer/format updates are not modelled
  yet.

## 4. Enablement plan for a6400 (offline/modified overlay only)

1. Add the two `devno` entries (audio 248:32, video 248:33) via a declared
   modified overlay or an equivalent device-node namespace contract.
2. Provide ZV-E10 `usbg_video.ko`/`usbg_audio.ko` and the streaming user-space
   chain (`libInfraStreamingUsb.so`, streaming-enabled `libInfraUsbCmn.so`);
   keep PTP `usbg_stillimage` in the same gadgetcore configuration.
3. Model `usbg_video` behaviour only from decoded commands (E0319) and the
   buffer/completion layout (E0319 §7), with explicit stops until the probe/
   commit path and DMA producer are evidence-complete.
4. Physical module load still requires separate explicit authorization; no
   camera write, mode change or module load was performed here.

## 5. Boundaries

- `usb_video_ioctl_contract_unresolved`: 56-byte request behaviour not decoded.
- `usb_video_write/read_completion_contract_unresolved`.
- No UVC function/frame is claimed; a6400 runs still have no video node.
- Host USB enumeration/`SET_CONFIG` gap (E0318) is orthogonal and still open.
