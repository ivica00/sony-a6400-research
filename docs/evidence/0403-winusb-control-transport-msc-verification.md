# E0403 — WinUSB control transport: B1c bounded 18-byte patch verified in Mass Storage (B2/B3 not reached)

Date: 2026-11-12. Physical work in **Mass Storage only** (`054C:0CA8`), strictly
within the approved Phase B bounds. No PC Remote switch, no persistent flash
write, no boot/auto-load hook, no kernel-text write, no UVC/`VS_PROBE`/`ffmpeg`
change. The camera was not rebooted and the battery was never touched.

The full B1a–B3 milestone is **not complete**. This record covers the delivered
and physically verified portion: the B1c 18-byte kernel-data patch with mandatory
save/CRC/readback/restore, proven over two load/unload cycles. B2/B3 (vendor
interface, `/dev/a6400_dbg`, WinUSB binding, `camera_debugger.py --transport
winusb`) were **not** deployed; see §6 for the exact remaining work.

## 1. Reversibility invariant compliance

- The module exists only as
  `artifacts/native/a6400-dbg-patch-e0403/final/a6400_dbg_patch.ko` on the host.
  On the camera it was staged at `/tmp_bt/a6400_dbg_patch.ko` (volatile RAM),
  loaded with manual `/sbin/insmod`, and deleted after the test
  (`rm -f`; a later `read` returns `-ENOENT`).
- No file was written to `/setting`, `/tmp` persistent paths or any flash
  partition; no preload/launcher/auto-load entry was added.
- The only memory mutation is the 18 bytes at VA `0x604E5130` (physical
  `0x4E5130`, `/proc/iomem` *Kernel data*). The module saves the original bytes
  in RAM, verifies their CRC32, patches, verifies the read-back CRC32, and on
  `rmmod` restores and re-verifies the stock CRC32. A battery pull would still
  reset the volatile DRAM to stock.
- Every failure path in `init_module` attempts to restore before returning an
  error; the first (license) load failure recorded in §3 never patched.

## 2. Module construction and static audit

The helper is built from the pinned ZV-E10 `usbg_video.ko` carrier
(SHA-256 `d385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb`),
which contributes only its exact `.modinfo` vermagic and
`.gnu.linkonce.this_module` struct. Carrier code is linked but unreachable:
`__this_module`'s init/exit relocations (offsets `0xbc`/`0x134`) are retargeted
to the helper's `init_module`/`cleanup_module`, the carrier entry points are
renamed, and the embedded module name becomes `a6400_dbg_patch`.

Two build facts were discovered and fixed:

1. the carrier imports `udif_devnodes`, but this a6400 kernel exports
   `__udif_devnodes` (ksymtab/kstrtab evidence); the build aliases the import;
2. `probe_kernel_write` is `EXPORT_SYMBOL_GPL`, so the helper adds
   `license=GPL`. The first insmod without it failed closed with
   `a6400_dbg_patch: Unknown symbol probe_kernel_write (err 0)`; nothing was
   patched and no state changed.

Built module: **23,560 bytes**, SHA-256
`0aa37edcfe742cbf5ffc09b86f06c59e78cd6ecda97590f909dfe0e1ce552608`,
vermagic `3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7`. Static audit
(`tools/research/build_debug_patch_module.py --audit-only`) verifies ARM `ET_REL`,
this_module size/name, exact carrier vermagic, defined `init_module`/
`cleanup_module`, and that every undefined symbol is exported by the live kernel
(via the kallsyms ksymtab aliases). Artifacts:
`artifacts/native/a6400-dbg-patch-e0403/` (`manifest.json`,
`carrier-manifest.json`).

## 3. Hardware verification — two load/unload cycles, Mass Storage

Receipt: `artifacts/hardware/e0403-b1c-patch/manifest.json` plus per-cycle dmesg
captures. Module SHA read-back verified on the camera. Kernel log:

```
[ 4412.272004] A6400DBG init begin va=604e5130 len=18
[ 4412.272110] A6400DBG PRECHECK_OK crc=6e795789
[ 4412.272194] A6400DBG PATCH_OK crc_before=6e795789 crc_after=fdadfcba
[ 4412.842911] A6400DBG RESTORE_OK crc=6e795789 attempts=1
[ 4413.425338] A6400DBG init begin va=604e5130 len=18
[ 4413.425526] A6400DBG PRECHECK_OK crc=6e795789
[ 4413.425611] A6400DBG PATCH_OK crc_before=6e795789 crc_after=fdadfcba
[ 4413.974339] A6400DBG RESTORE_OK crc=6e795789 attempts=1
```

- `6e795789` is the CRC32 of the stock 18-byte `MSFT100`/`0x30` descriptor;
  `fdadfcba` is the CRC32 of the `MSFT20`/`0x02` replacement.
- Cycle 2's `PRECHECK_OK crc=6e795789` is independent proof that cycle 1
  restored the stock bytes; cycle 2 then patched and restored again.
- `/proc/modules` no longer lists `a6400_dbg_patch`; `/tmp_bt` file removed.
- Camera uptime continued (4153 s → 4430 s), no reboot; debugger pid 1056 still
  answers `ping`, `usb_state` (`klog.addr=0x035a5000`, ring valid) and
  `dump-ring` after the tests. Windows saw no re-enumeration; the OS-string
  descriptor is only re-read on the next PnP descriptor query.

## 4. B1a / B1b status (pre-flight, not hardware-validated)

- **B1a (EP0 vendor control-transfer chunking):** not validated. The decoded
  EP0 request layout (`buf +0`, `len +4`, `dma +8`, `complete +0x1c`, status
  `+0x2c`, actual `+0x30`) and the bridge's proven class-IN reply path give the
  implementation shape, but 4096-byte vendor IN/OUT transfers, data-phase
  completion and the daemon bridge have not been exercised. The B2 design will
  start with ≤64-byte control chunks and grow only after measurement.
- **B1b (`bcdUSB >= 0x0210`):** not measured. The MS OS 2.0 requirement still
  needs the live device descriptor (or gadgetcore device-tree fields) read and,
  if it is `0x0200`, a descriptor-tree fix in the B2 module. No descriptor was
  modified in this step.

## 5. What was not done (explicit)

- No vendor interface (`0xFF/0xDB/0x01`) was injected; no `/dev/a6400_dbg` node
  exists; no gadget driver was registered.
- No MS OS 2.0 descriptor set was served (the 18-byte patch only makes Windows
  *ask*; the answer path is B2).
- Windows did **not** bind `WinUSB.sys`, and
  `tools/camera_debugger.py --transport winusb ping` still fails closed with
  `no Sony vendor debugger interface (0xff/0xdb/0x01)`.
- PC Remote was not entered; no in-band recover test was run.

## 6. Remaining work to finish B2/B3

1. Acquire the gadgetcore context at module load (verified offsets from
   E0377/E0398: root `gc+0x6c`, registered-driver list `gc+0x78`, mode byte
   `gc+0x84`) and read the live MSC config/device descriptor tree read-only.
2. Implement the zero-endpoint vendor interface on the wire config
   (`make_config_desc` output append, `bNumInterfaces`/`wTotalLength` update) and
   register an `old_descriptor` for it with START/STOP/VENDOR callbacks; verify
   `gc+0x84`/`bcdUSB` gates before relying on MS OS descriptors.
3. Implement EP0 vendor IN/OUT request queueing (using the decoded request ABI)
   and an in-RAM request/response ring bridged to a new `/dev/a6400_dbg`
   character device; keep the daemon's existing 4096-byte protocol with chunking
   if EP0 limits require it.
4. Serve the MS OS 2.0 `WINUSB` descriptor set for `wIndex=0x0007` from the
   vendor callback (offline bytes already tested:
   `src/a6400/usb_debug_descriptors.py`), then load in MSC, verify WinUSB binds
   and `--transport winusb` passes `ping`/`usb_state`/`dmesg`/`ring_dump`, then
   `rmmod` and CRC-verify the OS-string restore again.
5. Only after that, PC Remote always-on and in-band recover (B4), then the
   runtime hook wiring (B5).

## 7. Commands / receipts

```
.\venv\Scripts\python.exe -m tools.research.build_debug_patch_module --audit-only
.\venv\Scripts\python.exe -m tools.research.run_debug_patch_b1c
artifacts/hardware/e0403-b1c-patch/manifest.json
artifacts/native/a6400-dbg-patch-e0403/final/a6400_dbg_patch.ko
```

Full suite after the static-audit tests: **1,371 tests OK**.
