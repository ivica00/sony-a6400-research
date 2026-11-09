# E0134: ZV-E10 2.03 reference UVC stack and JPEG path

Date: 2026-11-07. User supplied `firmware/Update_ZVE10V203.exe` to investigate
the actual UVC implementation as a reference for a6400. This is reference
analysis, not an a6400 deployment or compatibility result.

## Input identity and local extraction

Original EXE:376353248 bytes, SHA256
`386970919b758b59de849cd954efd31de00e5f9e435056ce99a7c212a4aca584`.
Sony lists the same filename and size at:
https://www.sony.com/electronics/support/software/00272347
Matching name/size is not cryptographic authenticity verification.

The EXE was never executed. No camera/debugger access, upload, module loading,
USB mode change, RAM/backup/SD write or installed mod occurred in this step.

Installed fwtool cannot parse this newer Packman EXE wrapper directly. Initial
failure is retained at `artifacts/analysis/zve10-v203-extraction-e0134`.
Inspection found an invertedMSCF signature at file offset0x71a24/465444.
Bytewise XORff yields a bounded CAB of375877134 bytes, SHA256
`5b73eb2e4b7c5b30efef027fad87c88aeabbf4cdffd051aaf63e5a8c3dfa4b7a`.
7-Zip24.09 lists/extracts it successfully:45 files,381381404 expanded bytes,
including `FirmwareData_ZVE10V203.dat`. No embedded program was launched.

`tools.research.extract_reference_firmware` records hashes, rejects path escape,
bounds output bytes/file count and uses the existing fwtool decoder. The first
recursive unpack hit Windows' case-insensitive filename collision between Linux
xtables names; that failed report and its partial output are preserved at
`zve10-v203-packman-extraction-e0134`. It is not labeled complete.

The corrected fresh extraction is:

`firmware/extracted_zve10_v203_linuxnames/`

Manifest: `artifacts/analysis/zve10-v203-linuxnames-extraction-e0134/manifest.json`.
It reports completed, input unchanged,1428 regular archive files and1016229515
extracted archive bytes. Ten case collisions retain both payloads under explicit
alternate host names recorded in the manifest;1360 symlink/device/special
entries are recorded and not materialized. This is an analysis tree, not a
bootable Linux filesystem or a repacked image. All regular output files are
hashed. Original EXE and intermediate DAT were unchanged.

Decoded FDAT metadata: crypterCXD90045, model01030010, region0, version2.03,
non-accessory/non-lens. Crypter family does not prove identical silicon revisions.

## Direct UVC component comparison

Complete comparison:
`artifacts/analysis/zve10-uvc-bound-e0134/comparison.json`.
Earlier partial/provisional comparisons are retained under
`zve10-uvc-comparison-e0134`; the bound comparison uses the completed tree.

| Component in primary filesystem | ZV-E10 reference | a6400 preserved same path |
| --- | --- | --- |
| kmod/usbg_video.ko | Present,20668 bytes | Absent |
| kmod/usbg_audio.ko | Present,20456 bytes | Absent |
| lib/libInfraStreamingUsb.so | Present,52524 bytes | Absent |
| lib/libInfraUsbCmn.so | CUsbGadgetStreaming, registration and UVC descriptor tables | Library present; streaming definitions absent |

The video module contains `uvc_ep0_comp`, `uvc_transfer_dmac_cb`, original
write/ioctl paths, DMA330 transfer dependencies and an isochronous-in video
stream label. It registers through Sony `usb_gadgetcore_register_driver`,
the same API family identified in E0133. The source path names Sony
`Usb-RsrcCommon_171H/driver/usbg_video/usbg_video_core.c`.

`libInfraStreamingUsb.so` contains state machines for host start/stop,
PROBE/COMMIT, a VideoEsManager and a matching audio manager. This is concrete
UVC control/producer integration, not a name-only inference from ModelUsbLiveView.

Both reference kernel modules advertise vermagic
`3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7`, matching a6400's version string.
This is not loadability proof. Device-node tables, structure layouts, kernel
exports, callback ABI, DMA/cache rules, resources and module lifetime still need
exact cross-camera validation. No reference module was copied onto a6400.

## Original descriptors: 720p25/30

In reference libInfraUsbCmn, actual UVC VS_FRAME_MJPEG descriptor bytes decode:

| Raw frame descriptor file offset | Width x height | Default interval,100ns | Nominal rate |
| --- | --- | --- | --- |
| 0x12550 |1280x720|400000|25 |
| 0x1263e |1280x720|333333|approximately30 |

The parser joins these bytes through exported PAL/NTSC interface tables, not
just a binary signature scan. PAL table1cb4c references node1caac, whose blob
pointer12537/length3d contains frame12550. NTSC table1cc60 references node1cda4,
whose blob pointer12625/length3d contains frame1263e. Additional speed variants
reference the same respective blobs.

Descriptor max-frame-buffer field raw00e10000=14745600 and advertised bitrates
are recorded as descriptor values, NOT observed JPEG lengths, allocated
capacity or proof of achievable throughput. These two descriptor blobs advertise
720p only; they are not evidence of a1080p profile.

## Reference application-to-encoder-to-UVC chain

Separate hash inventories avoid altering the established a6400 inventory.
`rea_wsl_batch --inventory <artifacts/.../reference-inventory.json>` now supports
an explicitly selected reference inventory; existing default behavior and
firmware identity guards remain. Inputs still must be under firmware, inventory
under artifacts. The reference was not supplied as an a6400 module replacement.

Completed immutable-input REA/Ghidra12.1.4 batches:

- `artifacts/tools/rea/zve10-uvc-source-e0134`: six functions plus original
  set_path_sync instructions.
- `artifacts/tools/rea/zve10-uvc-register-e0134`: registration/unregistration
  and original registration instructions.

Ghidra synthetic addresses are linked ELF values+10000 for these libraries.
They are not physical camera addresses. Decompiler prototypes remain inferred.

Reference `VideoEsManager::video_stream_start` linked903e performs original
state/mutex checks and invokes:

```
set_path_sync(this, 1,    0,  0, 0,    0)
set_path_sync(this, 0x20, 30, 5, 1280, 300)
```

Original instructions verify these argument constants. Raw300 size parameter
units are not established. set_path_sync linked8e14 accepts path1/20, encodes
rate by shifting8, constructs header2009/0100/0044/0001, places width at+14,
and sends to **01670464**. This is a material difference from the network JPEG
configuration destination0167046a investigated on a6400.

Reference get_video_image linked90c0 builds the familiar JPEG-fetch request
2009/0100/0014/0001 and sends to **0167046a**. Response processing yields a
handle, size shifted7 and additional handle fields.

set_video_data_to_driver linked9618 then uses:

1. get_video_image;
2. open_dmm_unit;
3. WaitVideoReadCmp;
4. UpdateVideoBufEvt with the size and memory information;
5. close_dmm_unit and free both returned ownership handles.

These are statically reconstructed original calls, not exercised DMA or a live
frame capture. They establish why raw JPEG-pointer copying or skipping release
is not an equivalent producer integration.

StreamingGadget_init linked6bec calls usb_streaming_register_gadget.
Reference libInfraUsbCmn defines that function at11f8c; its original call to
usbif_register_gadget selects gadget type **0x12**. This is a runtime API enum,
not an identified backup property to write. a6400's inspected same library lacks
the CUsbGadgetStreaming definitions and streaming descriptor exports.

The retained actual a6400 libInfraUsbCmn file captured in E0133 also has none
of these four markers: CUsbGadgetStreaming, usb_streaming_register_gadget,
streaming_ntsc_interface_desc, streaming_pal_interface_desc. The negative
check and actual-file hash are retained in the bound comparison directory.

## Consequence and next work

We now have a concrete native Sony UVC reference. The main observed delta is
missing driver, userland state machine and gadget registration/descriptors in
a6400's inspected primary filesystem. It is not established as a single hidden
flag. Matching kernel API family and JPEG message headers makes targeted
compatibility investigation worthwhile, but does not prove drop-in modules or
1080p encoder support.

Next audit reference usbg_video creation/ioctl/endpoint contract against actual
a6400 kernel/devno and libInfraUsbCmn, then trace receiver01670464 and compare
it to the earlier0167046a service on a6400. Verify original source parameters,
completion and DMM ownership before constructing any installable port. A first
native UVC target would reproduce reference720p, followed by a separate
source/descriptor/buffer/throughput investigation for1080p. No mod is armed and
no physical camera interaction is required by this checkpoint.

Reproduce comparison:

```powershell
python -m tools.research.compare_uvc_reference --reference-root firmware/extracted_zve10_v203_linuxnames/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked --report-dir artifacts/analysis/NEW-uvc-reference
```

Extraction and comparison modules compile. All599 project tests pass in17.448s
after the new launcher inventory option; none of these checks prove camera UVC
execution. Generated status metrics are not increased for static reference data.
