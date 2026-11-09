# E0208 — 90-second Windows test: composite parent Code 10

Date: 2026-11-09. User manually switched MSC → PC Remote → MSC during this test. All camera filesystem writes were confined to `/tmp_bt`.

## Physical outcome

The longer session **did not create usable UVC/PTP children**. Windows bound the parent to `usbccgp` (`usb.inf`) but reported **ProblemCode10**, Status Error. Neither MI_00 nor MI_01 was observed. Therefore E0207's explanation that the parent error was simply installation interrupted by a 30-second window remains an unproven hypothesis; extending the session to90 seconds did not resolve it.

The camera-side lifecycle succeeded:

- Native PC Remote identity detected after24s;181 threads attached/resumed in1436ms for hook publication.
- `IOCTL_UVC_INIT` returned0; composite held90 seconds.
- STOP succeeded;181 threads attached/resumed in1495ms for retirement; original opcode0xe1a0c00d restored.
- Runner reported complete/result0, TracerPid0 afterward.
- Module unloaded with status0; its node/module/runner/log/receipt files removed; `/proc/modules` byte-equal to baseline. Debugger703 responsive in restored MSC.

Exact physical module: E0206 `7adc42e6e981270860e4c383368d2df87a3851aa775f150792610d320aa49a6e`,70996bytes. New runner: `faaa4c2641e962e04a0ed1acef461f6ceafbf2fc5654b4ff193de7fc859191e0`,11800bytes. New runner defaults90 seconds and copies its final stdout receipt through `/proc/self/fd/1` into a fresh RAM pathname after teardown, avoiding `/setting`. Both original log and complete1025-byte receipt were recovered; this test did not establish that the original RAM pathname had been unlinked.

## Host evidence

Read-only PnP capture during the active session:

```text
USB\VID_054C&PID_0CAA\CF93603BE631
FriendlyName: USB Composite Device
Service: usbccgp
DriverInf: usb.inf
Status: Error
ProblemCode: 10
MI_00: absent
MI_01: absent
```

One full hub descriptor read succeeded at08:46:10 UTC: device descriptor `12010002ef0201404c05aa0c000201020301`; configuration173bytes, declared3 interfaces. PTP interface0 has81/02/83; IAD groups UVC VC1+VS2; video Bulk IN82. This confirms bytes returned in that read, not Windows acceptance or a working streaming interface. A later independent read failed with WinError31 at08:47:21 UTC. No driver was installed, replaced or removed by our tools.

Artifacts:

- `artifacts/hardware/uvc-ptp-windows-90s-e0208/manifest.json` — host samples and recovered lifecycle result; final status `session_restored_children_failed_code10`.
- Its `composite-hub-descriptors.json`, `receipt-recovered.log`, `kernel-log-recovered.txt`, `modules-after-recovered.txt` and final status/debugger files.
- `artifacts/hardware/uvc-ptp-windows-active-e0208/manifest.json` — explicit live driver/problem properties.
- Its `hub-descriptors.json` — later read failure.
- `artifacts/hardware/uvc-ptp-host-preflight-e0208` — filtered Sony SetupAPI baseline; no active0CAA node at that earlier sample.

SetupAPI slices were archived, but historical successful native WPD install blocks do not explain the composite parent's runtime Code10. Next capture must include ProblemStatus and control-request/configuration results. Do not force-bind WPD to the composite parent or assume longer waiting alone fixes this.

## Tool changes and recovery

Added `uvc_ptp_windows_host.py`: strict identity/interface classification; parent is not counted as PTP; unrelated webcams are ignored. Ready requires Status OK, ProblemCode0 and expected inbox service/INF. It records parent, MI_00, MI_01, other interfaces, driver properties/query errors and Sony SetupAPI blocks. IAD1+2 is one expected UVC function, not two cameras.

Session controller now defaults90s, distinguishes child binding from session completion, captures hub/SetupAPI observations and requires runner completion/retirement evidence before unload. A host USB reconnect bug initially stopped automatic collection: the controller opened a successful connection and then opened another instead of reusing it. No camera-side lifecycle failure occurred. A separate fresh connection recovered both complete logs, checked TracerPid0, unloaded the module and verified exact restoration. The manifest preserves `automatic_cleanup_error` and marks `cleanup_recovered=true`. Controller now reuses one reconnect context; that fix is syntax/unit/regression checked, not physically rerun in this record.

Seven new host-classification tests pass. Final suite: **612 tests pass in18.428s**. Log: `artifacts/uvc-ptp-host-e0208-final-tests.log`.

## Sensor feeder boundary and preparation

The current shared module remains enumeration-only: video START is suppressed and registration/WAIT/UPDATE/ENABLE streaming ioctls are rejected. Existing `uvc_sensor_feeder_30fps.c` cannot simply run beside this session: it opens/initializes another UVC owner, resets SET_PATH, changes DMM Rule5 and restores Rule0, can emit a static fallback, and copies JPEG bytes into the same owned DMA destination passed to Update. E0143 already established the12-byte-header source/destination alias hazard.

Added source-span validation to `uvc_composite_shim.c`: reject zero frame/source,32-bit wrap and overlap with either owned destination slot. Extended ARM audit covers both slot aliases, overlap from below and valid disjoint boundary. New **offline-only** candidate E0208:71092bytes,SHA-256 `47e486874a3f208259573d5e639b6c8ca5a85f03ce5cf8ee7edce167415a0923`,55imports,**112 ARM audit checks pass**. It was not uploaded or used for the physical90s test.

Feeder integration still needs one session/FD owner, source storage disjoint from both driver destinations, frame/metadata and decoded-dimension validation, correct DMM lifetime through completion, WAIT before reuse, per-slot frame lengths, matched unmapping/freeing and preservation of the active shooting pipeline. A test pattern must not count toward sensor frames. No sensor feeder or Scalar/DMM change was executed in this test.

## Next experiment

Diagnose composite parent startup/control requests and SET_CONFIGURATION before enabling video. Trace native callback results and whether the native exclusion gate blocks a required acknowledgement; these are investigation candidates, not established causes. Once parent and both children start, verify a PTP transaction and then connect the bounded sensor producer to endpoint82 with correct lifetime/ownership. Camera is restored MSC; no further switch requested in this record.

References: [Microsoft composite interfaces](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/descriptors-on-composite-usb-devices), [IAD](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/usb-interface-association-descriptor), [SetupAPI log](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/setupapi-device-installation-log-entries). The inbox architecture describes expected binding; only the recorded host observations establish our actual result.
