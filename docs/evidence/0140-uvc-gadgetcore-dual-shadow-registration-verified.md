# E0140: Live UVC Gadgetcore Dual-Shadow Registration & Quiescence Verified

Date: 2026-11-07. Successfully verified live userspace initialization, dual-interface shadow registration, and safe unregistration of the composite UVC module (`usbg_video_a6400.ko`) directly against Sony BIONZ X kernel gadgetcore on physical ILCE-6400.

## 1. Executive Summary

- **Live IOCTL 0x4038e000 Result**: Exit code `0` (Success).
- **Live IOCTL 0xe001 (Stop) Result**: Exit code `0` (Success).
- **Character Device Lifecycle**: `/tmp_bt/video` (major 248, minor 33) cleanly handles open, DMA buffer allocation (1294 KB at physical `0x20000000` $\rightarrow$ noncache `0x80000000`), registration, unregistration, buffer free, and close.
- **Kernel Gadgetcore Registration**: Transactional dual shadow registration (`shadow[0]` VideoControl interface 1, `shadow[1]` VideoStreaming interface 2) completed into `usb_gadgetcore` driver list.
- **USB Root Debugger State**: PID 704 intact, responsive, and unaffected throughout.
- **Regression Tests**: All 599 emulator tests pass in 17.674s.

---

## 2. Kernel Gadgetcore State & Atomic Bypass Contract

### 2.1 The Registration Gate (`+0x68` bit 2)
Disassembly of `usb_gadgetcore_register_driver` (`0x602b8610`) revealed an internal guard:
```arm
0x602b8628:  ldr      r7, [r5, #0x68]
0x602b862c:  ubfx     r7, r7, #2, #1
0x602b8630:  cmp      r7, #0
0x602b8634:  mvnne    r0, #0xf  ; returns -16 (-EBUSY) if bit 2 is set
```
When the camera connects via USB in Mass Storage mode, Appframework (PID 149) issues IOCTL `0x400ce203` to `/dev/usb/gadgetcore` (fd 86), invoking `_test_and_set_bit(2, gadgetcore+0x68)` to lock the gadget descriptor table. Any subsequent driver registration or unregistration without clearing bit 2 is rejected with `-EBUSY` (-16).

### 2.2 Atomic Bypass in Bridge Shim (`uvc_composite_shim.c`)
To register the UVC shadow drivers without disrupting the active Mass Storage connection or USB root debugger:
1. Retrieve `gadgetcore` manager instance from pointer `0x6051b17c`.
2. Temporarily clear bit 2 of `gadgetcore->flags` (`*p_flags &= ~4u`).
3. Call `usb_gadgetcore_register_driver` for `shadow[0]` and `shadow[1]`.
4. Restore original flags (`*p_flags = orig_flags`).

Live kernel `dmesg` confirms execution:
```text
[ 3567.197911] [a6400_uvc] gadgetcore_register_hook: name=USB Gadget Video Device config=1 ifaces=2
[ 3567.198061] [a6400_uvc] bridge_prepare SUCCESS, calling bridge_register...
[ 3567.198176] [a6400_uvc] cleared bit 2 (flags: 0x6 -> 0x2)
[ 3567.198332] [a6400_uvc] restored flags: 0x6
[ 3567.198406] [a6400_uvc] bridge_register result=0
[ 3567.198901] [a6400_uvc] gadgetcore_unregister_hook called
[ 3567.199000] [a6400_uvc] unreg: cleared bit 2 (flags: 0x6 -> 0x2)
[ 3567.199251] [a6400_uvc] unreg: restored flags: 0x6
[ 3567.199374] [a6400_uvc] bridge_unregister result=0
```

---

## 3. Userspace Probe Utility (`uvc_probe_init_arm`)

Freestanding native ARM test binary `tools/native_camera/uvc_probe_init.c` (1956 bytes, direct syscalls `svc 0`, no libc dependency):
1. `sys_open("/tmp_bt/video", O_RDWR)` $\rightarrow$ fd 3.
2. Constructs `struct uvc_user_probe_info` (56 bytes) with `g_interfaces = {0, 1, 1, 2}` (VideoControl = 1, config = 1, VideoStreaming = 2).
3. `sys_ioctl(3, 0x4038e000, &info)` $\rightarrow$ returned `0`.
4. `sys_ioctl(3, 0x0000e001, 0)` $\rightarrow$ returned `0`.
5. `sys_close(3)` $\rightarrow$ returned `0`.

---

## 4. Verification & Status

| Step | Contract | Result |
| :--- | :--- | :--- |
| `insmod` | Load `usbg_video_a6400.ko` into volatile RAM | `SUCCESS` |
| `/tmp_bt/video` open | Major 248, Minor 33, DMA 1294 KB mapped | `fd = 3` |
| `ioctl(0x4038e000)` | Dual shadow registration in `usb_gadgetcore` | `result = 0` |
| `ioctl(0xe001)` | Proactive DMA quiescence & driver unregister | `result = 0` |
| `/tmp_bt/video` close | Buffer freed, character device released | `result = 0` |
| Debugger state | PID 704 on `FEATURE=0x23` | `INTACT` |
| Regression suite | 599 unit/integration/hardware contract tests | `599 / 599 PASS` (17.674s) |
