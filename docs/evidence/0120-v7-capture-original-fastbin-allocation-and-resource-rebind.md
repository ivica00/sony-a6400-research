# E0120 — V7 capture, original allocation and resource rebind

Date:2026-11-06. Main-menu touch remains incomplete.

## Complete physical capture

Both PID4015 outputs preserved before further work: `artifacts/hardware/native-layout-resource-snapshot-pid4015.{log,bin,json}`. Exact252040-byte binary,1875 records,229524 raw bytes; SHA256 `8036a15cc11cfc79f71b06749a89d779b6893a3f1e7ed9cd45f9a9cf9c9a750f`. MENU attempt154/object1a28f940; active resource1a2cace0/ref1/owner6c880. Unused-resource list492/nonzero0/activeabsent. Three arenas166 fastbin chunks, prefix-only. All176 CPU threads attached/resumed1353ms. SNAPSHOT/BINARY/END0, first attempt successful. Helper completed; no observer armed.

## Verified original allocator progression

Replay without row-entry control uses actual selected first row. Original activation now reaches the allocation path, beyond the resource blob-header boundary from E0119.

At PC431a320 original malloc pops head slot1a200018: captured chunk1a2c3240, size16, next1a2fd7f8. Guard verifies arena came from actual TLS, slot is one of ten original fastbin heads, head points to chunk, class agrees with size, original next value matches captured chunk+8. Only that exact store is admitted. At original return PC431c4dc, malloc returns1a2c3248/request12. Payload bytes were already captured. glibc non-mmap chunk capacity includes next chunk's prev_size word;12 requested bytes are valid for16-byte chunk. Emulator permits writes only within the original returned/requested allocation. This permission is removed if original free later receives the same payload.

Original constructor64bac06 writes resource to new node+8. Original list insertion stores64c82a6/82a8/8460/8462 into already captured bytes, only while inserting an actually allocated node. This is not blanket permission for heap writes.

Resource1a2cace0 decrements1->0. Resource36fe30 is captured with count0, then ORIGINAL acquisition PC64bdfe0 performs0->1->2; original release64be08c performs2->1. Release guard admits only a positive observed count, original two-byte decrement PC, captured bytes; zero-count underflow still stops. No count is forced. Accounting233472+768=234240, peak323968.

## New auxiliary dependency, with provenance limits

Original code at5e16c10 fetched from camera and checked byte-equal against actual camera libObj ELF. Later bounded16-byte USB windows at70836d0/7087c70/708c240/708a520 provide module indirection data. They are EXPLICIT later/non-atomic inputs; no whole-application coherence claim. No later USB heap bytes are silently merged.

Replay now stops after24638 instructions: original getter64b6ac8 reads object69f00+3c, uncaptured address69f3c. Function identity is not established; do not label it a proven notification service. A separate CPU-frozen USB256-byte capture of69f00 was archived ONLY for analysis as `native-notification-owner-usb-e0120.{log,bin,json}` (artifact name is provisional).175 attached/resumed1117ms/result0, binary284 bytes, SHAdd76c3bef391df5a42ee39daac85bc7665a19c7be482827f21dc4289c597f69c. It contains vtable706c418, owner6c880 at+c, and pointer69edc at+3c. These bytes are NOT merged into active-MENU replay. Next establish the original auxiliary object's contract and necessary same-phase dependencies before another physical capture.

Report: `artifacts/analysis/menu-activation-v7-resource-replay.json`. Source preparation tags new datasets by PID, preserving E0115/E0115b controls. Reproduction:

```powershell
python -m tools.research.menu_activation_snapshot_probe --main-thread-control --active-state artifacts/hardware/native-layout-resource-snapshot-pid4015.json
```

## Validation and limitations

Repeated V7 replay reaches same24638-instruction boundary. V5 negative control still returns0 after8186 instructions. Full unittest suite566 passed with required normal host temp-directory access; restricted initial run had the same four temp-permission errors. No physical input mapping, originating UI thread, full activation or popup rendering proven. No camera application calls, application RAM patches or SD writes performed. No new physical test requested or observer armed.
