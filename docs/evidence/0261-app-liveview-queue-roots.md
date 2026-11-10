# E0261 — App-side map and static roots for the liveview queue

Date: 2026-11-09. Offline + read-only MSC debugging. No PC Remote, no module, no camera writes.

## App context (MSC, read-only)

- `/proc/149/cmdline`: `im.elf debug s gru l i a lazy-global`; `/proc/149/status`: 175 threads, `TracerPid: 0`.
- `/proc/149/maps` (saved to `artifacts/analysis/app-maps-e0261/maps.txt`): 344 mapped files.
- Relevant mappings: `libInfraPtpControl.so` at `0x10f70000`, `libInfraPtpExtCmd.so` at `0x1146f000`, `libptp.so` at `0x11416000`, plus `libInfraRemote`, `libInfraRemoteControlNet`, `libInfraStreamingServer`, `libInfraUsbCmn`, `libUsbControl`, `libInfraMtpServer`, `libInfraMscServer`, `libMWF`, `libBizFw`.
- The liveview queue global in `libInfraPtpControl` is at library vaddr `0xf450` (base + `0x10f7f450`). In MSC it reads **0** (the callback/queue is not registered outside PC Remote); the adjacent word at `+0xf454` is `0x3ef`, unidentified.

## Static symbol/string scan (rootfs)

- Only `libInfraPtpControl.so` **defines** `PTPT_register_callback_usb`, `PTPT_open_usb` and `PTPT_register_callback`; no other rootfs ELF imports the USB registration symbol.
- `libInfraRemote.so` contains the string `PTPT_register_callback` and `LiveView`, and defines `InfraRemoteUsb::actionParsePtpCd2RemoteAppId(MWF::ObjMsg*)` — a PTP CD parser for remote app IDs.
- `LiveView` strings also appear in `libInfraRemoteControlNet.so`, `libInfraStreamingServer.so`, `libNetCommon.so`, `viewUnified4/7.so`, `orb-server`, and the DLNA description.
- `libInfraRemote`, `libInfraRemoteControlNet` and `libInfraStreamingServer` all use `osal_rcv_msg_tmo`/`osal_snd_msg`, so they are potential queue producers/consumers.

## Interpretation

The liveview request is dispatched by `libInfraPtpControl` to a queue whose id is stored by `PTPT_register_callback_usb`; that registration is not a static import of any rootfs library, so it is either resolved dynamically (the `PTPT_register_callback` string in `libInfraRemote`) or done inside the PC Remote/remote stack at runtime. The qid is only non-zero in PC Remote. The next offline step is to trace the `libInfraRemote` string references (disassembly around the string/`dlsym`) and locate the queue creation/consumer, which will identify the app mode gate.

## Limits

Read-only MSC; the qid cannot be observed in PC Remote under this plan. Static scans cover rootfs ELFs; on-demand-loaded code and dlsym resolution are not executed.
