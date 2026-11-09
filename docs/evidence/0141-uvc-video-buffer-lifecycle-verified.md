# E0141: UVC video and DMA buffer registration lifecycle verified

Follow-up correction: [E0144](0144-native-jpeg-receiver-ownership-and-dma-allocation.md) proves original argument `0x50e` is a DMM UnitType, not a KB size. The lifecycle below used the explicit fixed-window shim; it did not establish native allocation or ownership of that window.

Date: 2026-11-07. Work resolved context reuse across sessions in the callback bridge and verified complete live userspace registration, DMA buffer configuration, buffer unregistration, driver unregistration, and clean release of physical memory directly against the physical a6400 camera kernel.

## Bridge context lifecycle and multi-session reuse

In initial testing, unregistering the UVC bridge left `b->magic` set to `MAGIC` (0x55425643) to prevent dangling ABA references in a multi-client model. However, on an embedded system where the kernel module holds a static singleton bridge instance (`g_uvc_bridge`), retaining the magic value caused subsequent userspace initialization calls (`open("/tmp_bt/video")` followed by `ioctl(0x4038e000)`) to fail with `-EBUSY` (`-16`).

Fix applied:
1. `tools/native_camera/uvc_callback_bridge.c`: in `a6400_uvc_bridge_retire()`, explicitly reset `b->magic = 0` once all shadow descriptors are unregistered and in-flight operations are quiescent.
2. `tools/native_camera/uvc_composite_shim.c`: in `a6400_uvc_gadgetcore_unregister_hook()`, clear `g_uvc_bridge.magic = 0` upon successful unregistration.
3. Rebuilt composite module `artifacts/native/uvc-composite-checked-e0139/usbg_video_a6400.ko` (28,420 bytes, SHA-256 `c34777b3aa813ecdcb919919c2a0a46a4e8e47b525b524208e3d9c8d0c2810f7`).
4. Verified multi-session cycling directly on the physical camera: executed two consecutive full init/stop/close cycles in userspace; both returned result `0` (`CYCLE1_DONE`, `CYCLE2_DONE`) without kernel errors.

## Complete DMA buffer registration lifecycle

Disassembly of `usbg_video_core_ioctl` in `usbg_video.ko` proved the buffer registration IOCTL commands:
- `0x4008f000`: `RegVideoDataBufInfo` (copies 8 bytes `{ uint32_t size; uint32_t phys_addr; }` from userspace, stores physical address and computes noncached virtual address `phys + 0x60000000`).
- `0x0000f001`: `UnregVideoDataBufInfo` (zeroes buffer pointers).
- `0x4008f003`: `UpdateVideoBufEvt` (submits frame to DMA transfer engine when `is_streaming` is active; returns `-ENOBUFS` / `-105` when idle).
- `0x0000f002`: `WaitVideoReadCmp` (blocks on transfer completion).

Built freestanding native ARM test binary `tools/native_camera/uvc_probe_init.c` (`artifacts/native/uvc_probe_init_arm`, 4,872 bytes, SHA-256 `c4e703cb8ed34990cd140705ee61a962cb1ed2b2c208b68a06938fe69cc8e990`). Executed against `/tmp_bt/video` on physical camera:
- `OPEN_FD=3`
- `IOCTL_INIT_RESULT=0` (`0x4038e000`)
- `IOCTL_REG_BUF_RESULT=0` (`0x4008f000`: size 1,325,056 bytes, phys `0x20000000`)
- `IOCTL_UNREG_BUF_RESULT=0` (`0x0000f001`)
- `IOCTL_STOP_RESULT=0` (`0x0000e001`)
- `CLOSE_RESULT=0`

Kernel `dmesg` confirms clean lifecycle:
```text
[ 5246.173664] [a6400_uvc] alloc_phys called: task=730 size_kb=1294
[ 5246.173795] [a6400_uvc] alloc_phys SUCCESS: phys=0x20000000 size=1325056 noncache=80000000
[ 5246.174374] [a6400_uvc] gadgetcore_register_hook: name=USB Gadget Video Device config=1 ifaces=2
[ 5246.174525] [a6400_uvc] bridge_prepare SUCCESS, calling bridge_register...
[ 5246.174782] [a6400_uvc] cleared bit 2 (flags: 0x6 -> 0x2)
[ 5246.174890] [a6400_uvc] restored flags: 0x6
[ 5246.174962] [a6400_uvc] bridge_register result=0
[ 5246.176202] [a6400_uvc] gadgetcore_unregister_hook called
[ 5246.176300] [a6400_uvc] unreg: cleared bit 2 (flags: 0x6 -> 0x2)
[ 5246.176456] [a6400_uvc] unreg: restored flags: 0x6
[ 5246.176547] [a6400_uvc] bridge_unregister result=0
[ 5246.177030] [a6400_uvc] free_phys called
```

## Gadgetcore Commit and Descriptor Assembly Contract

Analysis of `vmlinux.bin` gadgetcore routines (`usb_gadgetcore_ioctl` at `0x602b8844` and `0x602bc550`):
- `0x401ce201`: stores configuration record (28 bytes).
- `0x400ce203`: sets bit 2 of `gadgetcore->flags (+0x68)`, executes `0x602bc550` to construct combined USB descriptors across all registered drivers in `gadgetcore->drivers_list`, and asserts D+ pull-up (`0x602bd7f8`).
- `0x0000e204`: disconnects D+ (`0x602bd834`) and clears bit 2 via `_test_and_clear_bit(2)`.

All 599 emulator tests pass in 18.67s. Root debugger PID 704 intact in Mass Storage mode.
