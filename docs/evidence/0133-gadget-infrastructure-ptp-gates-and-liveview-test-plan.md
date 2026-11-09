# E0133: Gadget infrastructure, PTP gates and Live View test plan

Date: 2026-11-07. User requested actual inspection of backup flags, USB gadget
infrastructure and scaler configuration, plus concrete reversible tests.

## Reference-model premise

Sony's model-specific guides document ZV-1 and original ZV-E10 USB streaming as
MJPEG1280x720 at30/25fps. They do not establish native1080p on those models or
identical CPU/front-end silicon revisions on a6400. Shared hardware capability
remains a research lead; no1080p encoder limit or single unlock flag is assumed.

- https://helpguide.sony.net/dc/1910/v1/en/contents/TP1000201632.html
- https://helpguide.sony.net/ilc/2070/v1/ja/contents/TP1000071026.html
- https://www.sony.jp/ichigan/products/ZV-E10/spec.html

## Camera operations and retained evidence

Existing normal MSC root debugger feature0x23/PID1793 was used. No camera file,
SD, backup property or RAM write; no module insertion, mount, UDC rebind, mode
switch, application function invocation, upload, observer or hook. Three bounded
individual ptrace reads verified the USB status getter/code/GOT/byte; this was
not a simultaneous snapshot or original function call.

Reports:

- `artifacts/hardware/usb-streaming-platform-e0133`: initial read-only audit;
  `/kmod` enumeration returned no files, NOT proof that modules are absent.
- `artifacts/hardware/usb-streaming-platform-pathfix-e0133`: corrected
  `/usr/kmod` enumeration, complete976469-byte kallsyms, maps, filesystems,
  loaded modules and UDC attributes. `proc_config.gz` failedENOENT; no kernel
  configuration options were invented from this missing file.
- `artifacts/hardware/usb-liveview-status-e0133`: actual verified memory reads.
- `artifacts/hardware/usb-remote-libraries-e0133`: bounded complete reads of
  five actual camera libraries, hashes, symbols and original disassembly.
- `artifacts/analysis/usb-liveview-presets-e0133`: package preset values,
  module ABI audit and original packet/PTP gate controls.

## USB infrastructure: more than a profile flag

Camera kernel: `3.0.27_nl-rt106+`, SMP PREEMPT RT, build2021-08-10.
UDC `dwc3.0` reports DRIVER/USB_UDC_DRIVER=`usb_gadgetcore`, current high-speed,
maximum super-speed, configured. Maximum remains a controller attribute.

No `/sys/kernel/config`, `/config`, `/sys/class/android_usb` or
`/sys/class/video4linux` exists in this observation. `configfs` is absent from
registered filesystems. No active configfs USB gadget tree was found.
Actual disk enumeration found `configfs.ko`, `libcomposite.ko`,
`usbg_cmn.ko`, `usbg_sen.ko`, `usbg_stillimage.ko`, `usbg_storage.ko`,
`usbg_buspower.ko`, `usb_f_mass_storage.ko`. The enumerated patterns found no
UVC/video function module. No UVC symbol occurs in complete current kallsyms.
This supports 'no demonstrated UVC function/profile', not a proof that no
unobserved module or stripped implementation could exist anywhere.

Native interfaces include `/dev/usb/gadgetcore`, `otgcore`, `sicd_core`,
`sicd_data`, `sicd_event`, `massstorage`, `usb_extcmd`, `vspe`, and `ter`.
Names ofvspe/ter are not capability proof; these nodes were not opened/read.
The boot script on the camera matches the known Sony gadgetcore module list.

Kallsyms identifies actual built-in entry points:

| Symbol | Observed kernel address |
| --- | --- |
| usb_gadget_probe_driver | 0x602b4ba8 |
| usb_gadget_unregister_driver | 0x602b4a6c |
| usb_gadgetcore_register_driver | 0x602b8610 |
| usb_gadgetcore_unregister_driver | 0x602b8560 |
| usb_gadgetcore_stop_other_driver | 0x602b8744 |
| usb_gadgetcore_ioctl | 0x602b8844 |

These are inspection targets, NOT authorized function-call or patch recipes.
Unregister/stop would threaten the sole active debugger transport.

Local inventory-checked `.symtab`/`.modinfo` audit shows libcomposite depends on
configfs and imports usb_gadget_probe_driver/unregister_driver; Sony
usbg_stillimage imports Sony gadgetcore registration helpers. Vermagic matches
the kernel version string. This does not prove module loadability or endpoint
compatibility. Missing DATA names in kallsyms cannot establish unresolved
symbols: the captured kallsyms may omit non-function data. Dynamic loading is
not justified by matching vermagic alone. No module was inserted.

## Configuration, exact gate and encoded packet

E0132's source-equal network JPEG path is retained. It is NOT yet proved to be
the PTP frame producer. Its normal gate is linked113cc function,
width comparisons11420/11426/1142c, fallback11504. 1920 goes to fallback;
force-backup branch11460 obtains defaults instead.

Hash-verified package BK4 `CX62600_UC2.bin` (SHA256
241c8521035bc9ff1edbe66cf3d42d81879a4bef8ff9e21cbfb84530a1446154) contains:

| Backup ID | Bytes | Package value | Interpretation at this consumer |
| --- | --- | --- | --- |
| 01710000 | 1 | 00 | select configuration-derived settings |
| 01710001 | 1 | 0b | compression parameter11 |
| 01710002 | 2 | 8002 | width640, little-endian |
| 01710003 | 2 | 001e | encoded rate0x1e00 |
| 01710004 | 4 | 32000000 | raw JPEG size-limit parameter50 |

These are PACKAGE values, not current camera backup values. Attribute0 in the
preset is not a UVC enable bit. No property was read from live backup or written.
The current flag is a network JPEG configuration selector, not established
global USB-streaming enablement. Size-limit parameter units are unresolved.

Source-equal `pvtSfrSetPath` linked111a0 constructs header2009/0100/0044/0001.
Original instructions executed up to first external memset call111fa preserve
width640/1024/1280/1920 from explicit argument fixtures. Packet fields established:

| Offset from original packet | Type | Written value/source |
| --- | --- | --- |
| +10 | u16 | encoded rate argument |
| +13 | u8 | compression argument |
| +14 | u16 | width argument |
| +16 | u16 | literal0, meaning unresolved; NOT a proven height field |
| +18 | u32 | raw size-limit argument |
| +40 | u8 | JPEG-path selector boolean, later store after memset |

Offsets are hexadecimal. Prefix controls stop BEFORE memset and do not prove a
complete initialized packet, IPC success or encoder acceptance. No fake helper
return was installed. Four packet-prefix controls pass.

New REA batches `usb-liveview-receiver-e0133` and
`usb-liveview-dataflow-e0133` show pvtScalarInfraIFSetPath sends to0167046a,
with an idle-path transition if required, and caches the requested settings only
after its success branch. Source-equal DataflowInfraSender::SendASync executes
OSAL allocation/copy/send in its original implementation. The actual receiver,
its dimension checks and front-end/encoder buffers remain unresolved. The OSAL
destination is not an application PC or arbitrary callable address.

## Actual USB status and separate PTP filters

Actual libInfraRemote load bias10a28000. Bounded GNU-hash resolution, exact
24-byte live getter/file comparison and instruction-shape checks derive:

| Item | Observed runtime address/value |
| --- | --- |
| GetLiveViewStatus getter | 10a34d68 |
| Original GOT slot | 10a418fc |
| Status byte target | 10a48528 |
| Raw status | 0 |

The byte is not a frame-size field or UVC mode selector. It must not be set1
to fabricate producer readiness. All addresses are session-specific and must
be re-derived; the read tool rejects wrong mapping, bytes and owner range.

Original actual-camera GetObjectInfo_cmd at linkedf760 has a special
handleffffc002 branch: call getter atf78e, then status0 returns2009 and nonzero
returns local0. Actual GetObject_cmd linkedf81c checks handleffffc001 and
returns local0 for it; ffffc002 returns2009 in the isolated post-header filter.
Four original-code slice controls prove these results with explicit prior-call
fixtures; no PTP request/session was issued. This distinguishes metadata
readiness from a complete live-frame transfer route.

GetObjectInfoEe at actual linkede238 writes constant4b000 at instructione252
to object-info+8:307200 bytes of advertised object metadata. This is NOT yet
proved allocated buffer capacity or an exact JPEG truncation threshold.
Original GetObject transfers existing buffers via DMA330/memcpy and has
ownership/state transitions. Editing only advertised size cannot allocate a
larger frame buffer.

Whole libInfraRemote camera bytes differ from local firmware. REA results are
static leads: actual camera disassembly independently verifies the above gates
and constant. GetObjectInfoEe differs at two literal-pool bytes; GetObject at29
literal-pool bytes. Those address differences were retained, not normalized
away into a whole-function equality claim. dataflow sender bytes DO match.

## Concrete next reads and experiments

1. Complete the receiver trace for0167046a and identify its owning task/queue,
   width-to-height/aspect calculation, allocation sizing, encode completion,
   cache/DMA ownership and release. Inspect the custom gadget registration/ioctl
   tables and PTP callbacks independently. Do not treat network/USB consumers
   as the same object because both mention LiveView.
2. Read current five backup properties through a verified original bounded
   read-only Backup_get_datasize/Backup_read helper and record exact sizes and
   return codes. The existing camera_link read-backup wrapper uses a different
   session workflow and must not silently switch modes. Do not use a persistent
   backup write as the first experiment.
3. When the original JPEG service is legitimately loaded, derive its current
   load bias B and re-resolve all symbols from the actual library, then capture
   the following together with original queue state and owner thread identity:

   | Candidate linked address | Length | Symbol |
   | --- | --- | --- |
   | B+23868 | 1 | m_default_compressrate |
   | B+2394e | 2 | m_default_framerate |
   | B+23958 | 1 | m_eevalue_force_backup |
   | B+2395c | 4 | m_default_jpegSizeMax |
   | B+2396c | 2 | m_default_width |
   | B+23978 | 44 hex | s_currentScalarInfraIf |

   These linked values come from preserved server symbols and require
   same-version revalidation. The service is absent from current maps, so
   there is NO valid currentB and no meaningful current RAM patch address.
4. Establish a stock640 baseline: one complete JPEG, SOF-derived actual
   width/height, payload length, timestamps/sequence, decode success and proper
   release. Then test supported1024. Test1280 and1920 only after the receiver
   bounds and full frame-buffer capacity are verified. Width1920 alone does not
   establish height1080; +16 must not be blindly changed to1080.
5. If a RAM-only configuration experiment is supported by that evidence,
   perform it at an original quiescent reconfiguration boundary, on its owner
   thread, with exact preimage check, complete saved old settings, original
   allocation/reconfiguration calls and deterministic rollback. A width/rate
   store into active producer or DMA buffers is not an acceptable substitute.
   Test one frame first; restore after rejection, timeout or size mismatch.
6. Only after continuous original production works, test USB delivery separately:
   measured complete-frame FPS, dropped frames, payload sizes, bounded queue,
   latency, error/timeout counters and disconnect/reconnect recovery. A useful
   initial run is30 seconds followed by300 seconds. 30*mean JPEG bytes/second
   determines payload demand; measure transport headroom rather than assuming
   nominal high-speed capacity guarantees30fps.
7. UVC needs an actual function implementation, descriptors, endpoint allocation,
   host PROBE/COMMIT and stream start/stop/alternate-setting handling. If absent,
   adding a matching function and producer integration is new development, not
   enabling a profile. Do not unbind the sole MSC/debugger connection until
   independent recovery and exact rollback are verified. A custom extcmd/bulk
   receiver is a separate Android transport option; neither implies UVC support.

No crash-free1080p/30 test can be promised before these ownership/allocation
contracts are established. No physical action or active mod is pending.

## Reproduction and checks

```powershell
python -m tools.research.usb_streaming_platform_audit --report-dir artifacts/hardware/NEW-platform-audit
python -m tools.research.usb_liveview_status_read --report-dir artifacts/hardware/NEW-status-read
python -m tools.research.liveview_packet_prefix_probe --source artifacts/hardware/usb-liveview-path-source-e0132/000111a0.bin --output artifacts/analysis/NEW-packet-prefix.json
python -m tools.research.ptp_liveview_gate_probe --source artifacts/hardware/usb-remote-libraries-e0133/libInfraRemote.so --output artifacts/analysis/NEW-ptp-gates.json
```

New modules compile, four original packet-prefix controls and four actual-file
PTP controls pass;10 debugger/locking/remoteELF tests pass. Initial full599-test
run had four temporary-directory permission errors; the normal-host-access rerun
passed all599 tests in16.574s. These are bounded
contracts and explicit fixtures, not a physical encode or PTP streaming test.
