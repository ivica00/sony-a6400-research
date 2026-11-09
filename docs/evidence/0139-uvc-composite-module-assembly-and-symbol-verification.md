# E0139: UVC Composite Kernel Module Assembly and Symbol Verification

Date: 2026-11-07. Successfully assembled and verified the complete composite kernel module `usbg_video_a6400.ko` integrating reference ZV-E10 UVC logic with the a6400 E0135/E0136 bridge.

## 1. Module Composition

1. **Reference Core**:
   - `usbg_video.ko` (from ZV-E10 v2.03, SHA-256 `d385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb`).
   - Original executable sections (`.text`, `.init.text`, `.exit.text`) verified binary-intact via prefix matching.
2. **Device Node Bridge (E0135)**:
   - Redirected `udif_devnodes` import to private module table `a6400_uvc_devnodes`.
   - Binds character device to `usb/video` (major 248, minor 33, count 1), avoiding the conflict with a6400's `jet/pclc_msg` (248:18).
3. **Gadgetcore & Quiescence Bridge (E0136)**:
   - Redirected `usb_gadgetcore_register_driver` to `a6400_uvc_gadgetcore_register_hook`.
   - Redirected `usb_gadgetcore_unregister_driver` to `a6400_uvc_gadgetcore_unregister_hook`.
   - Maps 2-interface reference compound descriptor to two 1-interface shadow descriptors (`shadow[0]` and `shadow[1]`).
   - Handles callbacks at `+0x10` (START) / `+0x14` (STOP), drains pending in-flight requests, and provides safe dual-registration rollback and proactive DMA quiescence.

## 2. Kernel Symbol Resolution

All 41 undefined symbols in `usbg_video_a6400.ko` were cross-referenced against a6400's live `/proc/kallsyms` (retained and live-queried via debugger PID 704):
- Hardware DMA: `dma330_mem_transfer_async` (exported by `dma330.ko` at `0x5f49d768`).
- IPC & OSAL: `osal_rcv_msg_tmo`, `osal_snd_msg`, `osal_free_msg`, `osal_valloc_msg_wait`, `osal_dynamic_id`, `osal_snd_sync_direct`, `osal_snd_sync_msg` (exported by `osal_uipc.ko` at `0x5f049000`).
- Memory & Core: `__udif_kmalloc`, `__udif_kfree`, `kmalloc_add_trace`, `malloc_sizes`, `udif_km_debug`.
- Character device: `register_chrdev_region`, `unregister_chrdev_region`, `cdev_init`, `cdev_add`, `cdev_del`.
- Gadgetcore: `usb_gadgetcore_register_driver` (`0x602b8610`), `usb_gadgetcore_unregister_driver` (`0x602b8560`), `usb_event_add_queue`.

Result: **41 / 41 (100%)** undefined symbols are verified satisfied by the a6400 kernel and active modules. Zero unresolved externals.

## 3. Artifact Details

- Output: `artifacts/native/uvc-composite-checked-e0139/usbg_video_a6400.ko`
- Size: 26,396 bytes
- SHA-256: `2e927b1fd99893dceedbd6897745635e97676e2e56a9cb112c6c43998cd3c114`
- Vermagic: `3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7 ` (exact match with camera kernel)
- Test suite: All 599 tests pass in 17.347s.
