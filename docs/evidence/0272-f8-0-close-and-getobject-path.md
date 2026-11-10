# E0272 — F8-0 probe lifecycle close; F8-1 PC Remote GetObject path

Date: 2026-11-09. Offline + code/tests only; no camera session.

## F8-0 — probe cleanup

- `SonyWpdPTPLiveView.close()` now closes the WPD `PortableDevice` (`driver.device.Close()`) and drops the driver, safely on missing/closed/broken device.
- `run_ptp_liveview_probe.py` wraps the frame attempt in `try/finally`, always calls `client.close()` and writes `closed_utc` to the manifest on every outcome (`ptp_error`, `no_frame`, `captured`).
- Tests: `tests/test_ptp_probe_close.py` (3 cases: close once, no driver, close error swallowed). **653 tests pass.**

This removes one concrete candidate for a lingering WPD/PTP session before teardown, although the F7 stuck teardown had already outlived the probe process.

## F8-1 — camera-side GetObject path

- The PC Remote MTP operation handlers are `MtpRemotePcOperation::GetObject_cmd` (0xf800), `GetObject_dat` (0xf848), `GetObject_res` (0xf8b8) in `libInfraRemote`.
- `GetObject_dat` computes the offset/size and calls `MrpwObjectManager::GetObject(handle, &size, &data, ...)`; `GetObject_res` builds a `0x2001` response and calls `CheckFileTransfered`.
- `MrpwObjectManager::GetObject` (0xe5ec, 788 B) branches on a global byte loaded at `0xe64e`; if nonzero it takes a different path, otherwise it performs a **DMA file transfer** (`FileTransferDMAC330`) with size/offset bookkeeping. This is the general object/file path.
- The liveview-specific buffer source is not yet identified in the object manager; the app-side `GetLiveViewStatus`/event-17 path (E0266–E0270) builds a `GetObject(0x1009)` request, and the stillimage/streaming source that fills the liveview object is the remaining link.

## Next

- Trace the liveview object source: `MrpwObjectManager` liveview handle path, `libInfraStreamingServer`/`sen.elf` shared buffer, and the `MtpRemotePcOperation` dispatch for the liveview handle.
- Continue F8-2 (teardown race) and prepare the F8-4 runbook; no PC Remote session without approval.
