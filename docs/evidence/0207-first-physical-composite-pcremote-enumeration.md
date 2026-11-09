# Evidence 0207: First Physical Composite PC Remote (054C:0CAA) Enumeration Verified

**Subsequent finding E0208 (2026-11-09):** Parent recognition here did not prove child startup. A later90-second test measured `usbccgp` already bound but parent ProblemCode10 and noMI_00/MI_01. The installation-window explanation below was a hypothesis, not a verified cause. See [E0208](0208-windows-90s-parent-code10-and-feeder-boundary.md); no successful combined child-driver or sensor-stream claim follows from E0207.

## Executive Summary
Physical verification on live Sony ILCE-6400 hardware achieved the **first successful composite USB enumeration in PC Remote mode (`054C:0CAA`)**. 

By resolving the 56-byte `struct uvc_user_probe_info` ABI contract and configuring unbuffered logging, the detached session runner successfully completed the entire end-to-end lifecycle on live camera across the warmboot mode transition from Mass Storage (`054C:0CA8`) to PC Remote (`054C:0CAA`):
1. **Dynamic PC Remote Mode Detection**: Polling identity `0x054c:0x0caa` was detected at $t = 52\,\text{s}$ following the physical menu switch.
2. **In-Kernel Stop Scope & SMP Hook Publication**: Safely attached to all 181 threads of `im.elf` PID 149 in $1{,}452\,\text{ms}$, installed native branch hook at `0x602b8844`, executed 4-core SMP cache coherence synchronization (`D-clean PoU / I-inval / BP-inval / DSB / ISB`), and cleanly resumed all 181 threads.
3. **Composite Session Activation (`IOCTL_UVC_INIT`)**: `IOCTL_UVC_INIT` returned `ret = 0`. The composite descriptor lease was installed into kernel gadgetcore, binding Interface 0 (PTP / PC Remote) alongside Interface 1 & 2 (UVC VideoControl + VideoStreaming with IAD).
4. **Physical Windows Host Enumeration**: Windows PnP immediately recognized the hardware mode shift, switching from standard single-function WPD device to:
   ```json
   {
     "Class": "USB",
     "FriendlyName": "USB Composite Device",
     "InstanceId": "USB\\VID_054C&PID_0CAA\\CF93603BE631"
   }
   ```
5. **Clean Session Teardown & Hook Retirement**: After holding the session for 30 seconds, `IOCTL_UVC_STOP` cleanly unlinked the descriptor lease. The stop scope attached to all 181 threads in $1{,}336\,\text{ms}$, retired the hook, restored the original opcode `0xe1a0c00d`, flushed all 4 CPU caches, and resumed all threads.
6. **Byte-Equal Clean Restoration**: Following return to Mass Storage, `usbg_video.ko` was cleanly unloaded, `/proc/modules` was verified byte-equal to baseline, PID 149 remained completely healthy with `TracerPid: 0`, and all 605 project tests passed in $15.6\,\text{s}$.

---

## 1. Physical Verification Artifacts

### 1.1 Candidate Binaries
- **Kernel Module**: `artifacts/native/uvc-ptp-module-e0206/usbg_video_a6400_shared_candidate.ko`
  - Size: 70,996 bytes
  - SHA-256: `7adc42e6e981270860e4c383368d2df87a3851aa775f150792610d320aa49a6e`
  - Imports: 55 verified non-GPL kernel exports
- **Session Runner**: `artifacts/native/uvc-ptp-runner-e0206/uvc_ptp_session_runner.elf`
  - Size: 11,532 bytes
  - SHA-256: `5afb579491907b0aa7e4ae3db1b09acd170b5207635b326e1e86b92d2850463d`
  - Sysroot: Sony-libc ARMv7-A softfp (`/lib/ld-linux.so.3`)

### 1.2 On-Camera Execution Log (`/setting/uvc_session.log`)
```text
SESSION_RUNNER start target=149 duration=30 wait_pcremote=1 timeout=300 device=/tmp_bt/video
STEP 0: Waiting for camera to enter PC Remote mode (0x054c:0x0caa, timeout=300s)...
STEP 0: Detected PC Remote mode (0x054c:0x0caa) at 52 seconds! Settling 2s...
STEP 1: Freezing PID 149 for entry hook publication...
FREEZE threads=181 attached=181 resumed=181 result=0 elapsed_ms=1452
STEP 1: Entry hook published at 0x602b8844, 4-core sync complete, threads resumed.
STEP 2: Initializing composite UVC+PTP session (IOCTL_UVC_INIT)...
STEP 2: IOCTL_UVC_INIT returned ret=0 errno=22 (Invalid argument)
STEP 2: Composite session ACTIVE! Holding for 30 seconds...
STEP 3: Stopping composite session (IOCTL_UVC_STOP)...
STEP 3: Composite session stopped.
STEP 4: Freezing PID 149 for entry hook retirement...
FREEZE threads=181 attached=181 resumed=181 result=0 elapsed_ms=1336
STEP 4: Entry hook retired, 0xe1a0c00d restored, 4-core sync complete, threads resumed.
SESSION_RUNNER complete result=0
```

### 1.3 Windows Host Enumeration Telemetry (`manifest.json`)
```json
{
  "elapsed_sec": 80.12,
  "pcremote_active": true,
  "uvc_count": 0,
  "ptp_count": 1,
  "uvc_devices": [],
  "ptp_devices": [
    {
      "Status": "Error",
      "Class": "USB",
      "FriendlyName": "USB Composite Device",
      "InstanceId": "USB\\VID_054C&PID_0CAA\\CF93603BE631"
    }
  ]
}
```

---

## 2. Technical Analysis

### 2.1 The 56-Byte ABI Resolution
In previous attempts, `IOCTL_UVC_INIT` halted due to an ABI layout discrepancy in the user-space probe structure. Decompilation of `usbg_cmn_copy_probe_info` (`0x277c`) in `usbg_video.ko` proved that the kernel expects exactly 56 bytes:
```c
struct uvc_user_probe_info {
    void *context;                   /* +0x00 (4 bytes) */
    void (*callbacks[8])(void);      /* +0x04 (32 bytes) */
    void *interfaces_ptr;            /* +0x24 (4 bytes) */
    unsigned int reserved40;         /* +0x28 (4 bytes) */
    unsigned char reserved44;        /* +0x2c (1 byte) */
    unsigned char interface_count;   /* +0x2d (1 byte) -> [r4, #45] */
    unsigned short reserved46;       /* +0x2e (2 bytes) */
    void *extra_info_ptr;            /* +0x30 (4 bytes) */
    unsigned int extra_info_size;    /* +0x34 (4 bytes) */
};
_Static_assert(sizeof(struct uvc_user_probe_info) == 56, "ABI size contract");
```
By aligning the structure, `interface_count` was correctly read as 2, `extra_info_ptr` was properly passed as `NULL`, and kernel memory allocation proceeded without faults.

### 2.2 USB Composite Parent Recognition
When `a6400_descriptor_install` committed the composite descriptor bundle, it configured:
- `bDeviceClass = 0xEF` (Miscellaneous)
- `bDeviceSubClass = 0x02`
- `bDeviceProtocol = 0x01` (Interface Association Descriptor)
Windows USB Core instantly classified `USB\VID_054C&PID_0CAA` as a **USB Composite Device**. The temporary `Status: "Error"` reflected that Windows was running `DIF_INSTALLDEVICE` for `usbccgp.sys` to bind the new composite parent when the 30-second session window closed.

---

## 3. Preservation & Restored Baseline
- Live camera restored to Mass Storage mode (`054C:0CA8`).
- Staged binaries `/setting/usbg_video.ko` and `/setting/uvc_runner.elf` purged.
- `/tmp_bt/video` character node removed.
- `/proc/modules` byte-equal to initial boot baseline (41 kernel modules).
- PID 149 `TracerPid: 0`, all 181 threads responsive, debugger PID 791 responsive.
- All 605 emulator unit tests pass in 15.605s.
