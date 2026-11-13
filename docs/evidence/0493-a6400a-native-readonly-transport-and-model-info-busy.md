# E0493 - a6400A native read-only transport and unresolved model-info BUSY

Date: 2026-11-13. **Read-only host metadata and narrowly allowlisted normal-mode
SCSI traffic.** No service/updater mode, driver replacement, helper upload,
filesystem/sector access, startup change, SD write or flash write.
Continues [E0491](0491-a6400a-offline-qualification-and-debugger-boundary.md)
and [E0492](0492-a6400a-kernel-partition-mmio-and-hook-map.md).

**Subsequent result:** [E0494](0494-a6400a-msc-reply-lifetime-and-verified-native-identity.md)
finds a finite packaged reply lifetime and verifies one uninterrupted normal
model query successfully. The BUSY observations below remain valid historical
receipts, not a permanent compatibility diagnosis. The prototype delayed
`--finish-model-info` mode is now refused before I/O; root/dump access is still
unverified.

## 0. Result

PR integration note (2026-11-14): the a6400A records were renumbered after
upstream allocated their original IDs. Local receipt directories and the
original observations below are unchanged.

**Windows USBSTOR SCSI inquiry works with a user-run Administrator probe.
Sony model information does not yet complete. Root/debugger access and physical
partition dumps remain unverified.**

One 8,192-byte normal model-info request completed at the SCSI transport level.
Its immediate READ and **40** later completion-only READs all returned Sony
device-busy, sense **`09/81/81`**, with zero transferred bytes. SCSI acceptance
is **not** an application acknowledgement or evidence that the callback ran.

The bounded probe stopped. No model request was resubmitted, no poll budget was
increased after exhaustion, and no reset/reconnect/mode change was attempted.
The owner reported a normal USB/Mass Storage screen with no visible error;
the host still reports `054C:0F0F`, USBSTOR, status OK/error 0.
Camera uptime and application quiescence were not measurable.

## 1. Identity and host-device admission

Initially the camera was absent. The only Sony device was HID `054C:0994`;
it was **not probed**. The owner then connected the a6400A in unchanged Mass
Storage mode.

Fresh Windows PnP/CIM observations identify exactly one healthy
`054C:0F0F` USBSTOR camera. Disk candidates are accepted only when their actual
PnP parent chain reaches that exact camera instance. Instance serials are used
only by Windows association in memory and are not retained.

Observed children:

| Disk index in this session | PnP LUN suffix | Model |
| --- | --- | --- |
| 1 | 0 | Sony DSC USB Device |
| 2 | 1 | Sony DSC USB Device |

These are session observations, **not hardcoded disk numbers**. The probe selects
the unique parent-verified LUN 0, verifies its Windows storage number after
opening, and refuses ambiguity, another Sony PID, or a changed driver/status.
No drive letter is guessed. LUN 0 has no associated logical volume, so the
upstream logical-volume path was unavailable; no card mount or drive-letter
assignment was attempted.

An ordinary-permission physical-device open failed with **WinError 5, Access
denied**, before any SCSI command (`operations=[]`). The owner explicitly ran the
narrow probe from a standalone Administrator PowerShell. No automatic elevation
or global development-environment change was used.

Windows pass-through requires a handle opened with read/write access rights.
That is distinct from sending a storage write: the probe does not call
ReadFile/WriteFile or admit sector commands. Only the exact transactions below
can reach its SCSI exchange method.

## 2. Bounded probe and reviewed command surface

New tool: [`a6400a_native_readonly`](../../tools/research/a6400a_native_readonly.py).
Its default is **metadata only**, with no device handle or SCSI command.
It uses the existing Microsoft USBSTOR binding and Python ctypes, not a new
libusb filter, driver, native binary or installed PMCA checkout.

Allowed commands:

1. Standard **INQUIRY** `12 00 00 00 24 00`, IN, exactly 36 bytes.
2. Sony **GetModelInfo**: CDB `7a0100000000000000000000`,
   feature 1/subcommand 1; one exact, zero-padded 8,192-byte request.
3. The same CDB, IN, exactly 8,192 bytes, to retrieve that model response.

The data-OUT transaction in item 2 delivers a logical **read query**, not a
file, sector or firmware write. The payload cannot be replaced with another
subcommand or arbitrary bytes. Storage READ/WRITE, TEST UNIT READY, native
debugger feature `0x23`, updater initialization, and mode commands are not
admitted.

The initial helper version did not retry any SCSI error. After observing the
specific Sony BUSY sense, the follow-up added:

- A distinct `SonyBusy` error for **only** status 2 / sense `09/81/81`.
- **READ-only** retry handling, at most 40 attempts in an 8-second scheduling
  window; each Windows I/O requests a 5-second timeout.
- No retry of the request/OUT transaction and no retry of other failures.
- `--finish-model-info <receipt>`: validates the earlier acknowledged command
  sequence and disk admission, then sends only completion READs, not an inquiry
  or a new request.
- Partial-result preservation and explicit rejection of malformed receipts.

If a model reply is obtained in future qualified work, the parser retains model
and product code, not serial numbers, raw property lists or entire responses.
No model reply was obtained here.

## 3. Physical receipts

| Stage | Authored SCSI operations | Actual observation |
| --- | --- | --- |
| Ordinary-permission attempt | none | raw-device open denied |
| Owner-run Administrator probe | 1 inquiry + 1 model request + 1 response read | inquiry: success/36 B; request: success/8,192 B; read: BUSY/0 B |
| Owner-run completion-only probe | 40 model response reads | all BUSY/0 B; bounded timeout; **zero new requests** |

Total authored SCSI traffic: **43 operations**, comprising one inquiry, one
logical read-query OUT packet and 41 IN response attempts. This does not count
or characterize unrelated automatic Windows USB traffic.

No response payload was fabricated and the BUSY result is not described as an
unsupported camera, missing debugger, rejected firmware ABI, or confirmed
application hang. Those conclusions are not established.

All helper host handles were closed through its checked context manager.
There was no deployed camera helper/module to remove. A postcheck found the
same normal host binding; the owner independently reported a normal USB screen.
The model query's application state remains unknown: **do not claim a clean
completed application transaction or a measured no-reboot interval**.

## 4. Offline source and wire verification

Public upstream reference:
[Sony-PMCA-RE, commit a82f5baa](https://github.com/ma1co/Sony-PMCA-RE/tree/a82f5baaa8e9c3d9f28f94699e860fb2e48cc8e0).
The protocol, Windows pass-through path and service-mode boundaries were read;
no upstream camera-facing script was executed.

**Important exclusion:** upstream `infoCommand()` calls both `getCameraInfo()`
and `SonyUpdaterCamera.init()`. It is not the read-only identity procedure used
here. The old project installer and service-mode wrappers were not run either.

The a6400A packaged `libInfraDevInfoSender.so` is strictly equivalent to the
original packaged library except allowed `.comment` metadata:
candidate SHA-256
`db4a0c97ccbd5fad6acec2354dbfeea12c50b2e93e7d346d02e280d7f70d896e`.
That is packaged-code evidence, not proof of live registration or execution.

An independent offline control executed only the pinned upstream packing
methods, with a constructed transport:

- `pmca/usb/sony.py`: Git blob `9e597375eb645cc498645fbf5c483a9f1c1d77a1`,
  SHA-256 `53ffb4d9d49cb5146623fda2b66ecb137681a6fc9ab0c98d23a51e75128af97e`.
- `pmca/util/__init__.py`: Git blob `b2ee7d939661150ebb4c0c15f2b8a6eb0d96847e`,
  SHA-256 `1bf318b75faf450011123ce430becc87aec8a7a161765afe38c498cdd20cbacf`.
- CDB, complete request and response size match exactly. Request SHA-256:
  `f7d7aea26b80ca97661fa8293d5edee22ee86766e2c2b9fde637b44b4cd2f3c3`.

This rules out a difference in those checked per-command bytes, **not** a
full-session mismatch. The upstream MscDevice constructor also sends TEST UNIT
READY; that step was not sent here. The new probe uses a parent-verified physical
disk handle, rather than upstream's logical-volume path. Their significance,
the live application's command registration, and LUN/session behavior remain
unresolved; no speculative fix was applied to the camera.

## 5. Validation and retained evidence

Sixteen focused constructed-fixture cases cover target/parent/LUN admission,
exact command allowlisting, malformed or wrong-model replies, serial omission,
read-only BUSY retries, no OUT replay, partial results, finite attempt count,
deadline behavior, partial-BUSY-data refusal and pending-receipt admission.
Native probe + existing ABI/profile checks: **46 tests OK**.

The initial full offline suite (before the BUSY cases) ran **1,575** checks,
with the same **2 failures / 13 errors / 71 skips** from missing historical
artifacts as E0492. The final source runs **1,582 checks**, with those same
**2 failures / 13 errors / 71 skips**; no new failure case was introduced.
The relevant failure-stack sources remain unchanged from the initial Git HEAD.
Documentation/dashboard/layout checks: **52 tests OK**. The full suite is not
green on this host, and E0482's historical passing count is not a new pass.

Local receipt root:
`artifacts/analysis/e0485-a6400a-readonly-access/`.
It retains:

- Host identity/parent/LUN/volume association and postchecks, without serials.
- `native-attempt-1/receipt.json`: ordinary-permission refusal, zero commands.
- `native-elevated-1/receipt.json`: owner's acknowledged request and first BUSY.
- `native-elevated-read-1/receipt.json`: owner's 40 completion-only BUSY reads.
- Exact source copies for the physically exercised probe versions.
- The pending receipt hash, full attempt summary, source-identified upstream
  wire control, final source/safety ledger and test logs.

The physical probes used preserved earlier versions. Final hardening additionally
refuses BUSY with partial data and malformed handoff input; those cases were
fixture-tested, not rerun on the camera. No further camera protocol traffic was
sent after the 40-read limit.

The first elevated receipt hash is
`940b53610cebd0fd7b77051edaace013888b646407b6b54bb736aa344a617d0e`;
the completion tool verified it before issuing reads. Failed receipts were
preserved, not overwritten with a success-shaped fallback.

Safe offline checks:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_a6400a_native_readonly -q
```

Default host-metadata-only invocation, with a **new** output directory:

```powershell
.\venv\Scripts\python.exe -m tools.research.a6400a_native_readonly `
  --output-dir .\artifacts\analysis\e0485-a6400a-readonly-access\NEW-METADATA
```

**Do not rerun the model request or completion loop on this session based on
these reproduction notes.** The actual executed commands are preserved in the
conversation and receipts. No root filesystem or partition dumping command was
attempted.

## 6. Next boundary

Keep the a6400A as a **reference** profile. Before any new physical attempt,
review the normal MSC session sequence and response/registration behavior
against exact firmware instructions. A longer BUSY loop is not a solution.

Native debugger presence, `/proc`, `/setting` and clean physical dumps remain
unknown. If an alternative needs service mode, a helper upload, startup changes
or a driver replacement, it requires a separately reviewed plan and explicit
scope; the owner's Administrator identity-probe action does **not** authorize
those changes. No persistent install is assumed necessary.
