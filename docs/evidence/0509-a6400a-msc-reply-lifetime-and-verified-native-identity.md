# E0509 - a6400A MSC reply lifetime and verified native identity

Date: 2026-11-13. **Offline original-instruction controls followed by one
owner-run, normal-mode, read-only identity transaction.** No driver replacement,
service/updater mode, helper upload, startup change, arbitrary camera file
access, storage-sector command or flash/SD write.

## 0. Result

PR integration note (2026-11-14): the a6400A records were renumbered after
upstream allocated their original IDs. Local receipt directories and the
original observations below are unchanged.

**Normal Sony model information now works on the a6400A through the unchanged
Windows USBSTOR driver.** One corrected, uninterrupted request/response
transaction returned:

- Model **`ILCE-6400A`**.
- Opaque five-byte product code **`0032858730`**.
- Reply command **1**, direction **1**, 8,192 transfer bytes.
- Model transaction duration **0.002727 s**; request acknowledgement at
  **0.001933 s**. Exactly one request and one response read; **no BUSY**.

This supersedes the unresolved normal-model-query boundary in
[E0508](0508-a6400a-native-readonly-transport-and-model-info-busy.md).
It does **not** establish root/debugger access, live kernel/module identity,
`/proc`, `/setting`, physical partition dumps or a booted emulator. The target
remains **reference**, not verified execution.

The earlier client procedure had a lifetime flaw: it returned after the first
BUSY, then attempted completion in another process several minutes later.
Original packaged code prepares a finite reply timeout. Those late reads did
not test an uninterrupted reply window and could not establish permanent
incompatibility. The exact live cause of the first BUSY is not proven; warm
service state and the actual live binary were not independently captured.

## 1. Inputs and tooling

All firmware comes from E0506's signed 1.01 package, preserved locally:

| Component | SHA-256 |
| --- | --- |
| `usb_extcmd.ko` | `d47d05ec891d18c8582baf19e413967c5d3fd5c36438d76f6d2e8a7f112428e3` |
| `usbg_storage.ko` | `3c79156a3f3e9fc1a1bff733d33647a1121a5688aed87271647a14d8b9c346b2` |
| `libusbcmd.so` | `23b94deb094d31f160cfe1d46330f2425e94d4801dfccb66720c4cf4b81cfb7e` |
| `libInfraDevInfoSender.so` | `db4a0c97ccbd5fad6acec2354dbfeea12c50b2e93e7d346d02e280d7f70d896e` |

Targeted ARM/Thumb disassembly reuses `storage_trace`, `startup_trace` and ELF
relocation helpers. WSL/REA is unavailable on this host as recorded in E0506;
no toolchain installation or global setup was attempted.

New [`msc_extcmd_trace`](../../tools/research/msc_extcmd_trace.py) executes
closed original instruction windows with declared fixture memory, relocations
and unsupported-PC stops. It is not a kernel loader:

- Command-node lookup is an **explicit callee fixture**, not original list
  traversal or a captured live registration.
- Only the closed executed call graph is relocated; no whole-module linkage
  is claimed.
- Integer division helpers are explicit mathematical ABI fixtures.
- Ready paths stop **before** cancellation or transfer; no USB or IPC response
  is invented.
- The model-info builder and its backup/file reads are **not** executed offline.

## 2. What the original driver means by BUSY

In the packaged `usb_extcmd.ko`:

- `get_inquiry_state`, `.text+0x50C`, asks for an opcode/16-bit-feature match.
- Missing lookup returns **0**.
- A present node with no requested bit in `node+0x14` returns **1**.
- A present node with that bit set returns **2**.

Original status-ioctl logic (`0xC018EB05`, decision window starting at
`.text+0x1624`) maps these to:

| Constructed node/key state | Direction | Original result |
| --- | --- | --- |
| Missing or different command key | IN or OUT | illegal command **`05/20/00`** |
| Present, requested direction not armed | IN or OUT | **`09/81/81`** |
| Present, requested direction armed | IN or OUT | ready branch, bounded stop before transfer |

Twelve original-code status controls cover missing/present nodes, all low two-bit
masks, both directions, and different opcode/feature fixtures. BUSY status
polling does **not** modify the constructed node's readiness field.

Original arming/clearing helpers execute the sequence **`0 -> 2 -> 3 -> 1 -> 0`**:
bit 1 (mask 2) arms host OUT/receiver readiness; bit 0 (mask 1) arms host
IN/sender readiness. A separate original TEST UNIT READY **normal-ready media
fixture** leaves that field unchanged and returns ordinary zero sense.
That is not a proof of every media/state path or a cold USB session.

These are exact matching branches in the **package**. They were not promoted
to direct observations of the live kernel or to a unique diagnosis of E0508.

## 3. Registration and finite reply lifetime

The original userspace chain is explicit:

1. `DevInfoSender::InitCmd` prepares registration for feature **1**, with
   8,192-byte send/receive bounds.
2. `UsbCmd_ExtCmdSvcWrap::Init` passes opcode **`0x7A`** and that feature to
   `usbcmd_Create`.
3. `usbcmd_t::Create` packs the registration and calls ioctl **`0xC00CEB00`**.
   Presence of this code does not prove a live successful registration.
4. On a successful received request, the original
   `DevInfoSender::ReqTranserCmp` window prepares reply direction **`0x80`**
   and timeout **10,000**.
5. Original `transInit` copies that timeout into the public data parameter;
   original `PackParamDriver` preserves **10,000** in the driver timeout field.
6. Original finite-wait arithmetic converts that value to **1,000 ticks** using
   the compiled 100-Hz factor, i.e. **10 seconds under that kernel contract**.
   No scheduler or wall-clock passage was emulated.
7. Original callback windows for successful send completion or a declared
   non-cancel error fixture prepare RECEIVE again, direction **0**, timeout
   **0**. Original readiness clearing removes the send-ready bit.

Consequently, a later host READ cannot be assumed to resurrect an expired reply.
The receive/reply/rearm windows, pure parameter-copy functions and finite-wait
conversion were executed from the original ARM/Thumb bytes. They do not prove
which stages actually occurred in the first physical session.

Retained host file metadata shows:

- First E0508 elevated receipt: **20:01:26.214691 UTC**.
- Completion-helper source became available **218.625 s later**.
- Completion-only receipt: **20:06:17.546377 UTC**, **291.332 s later**.

These are host file times, not camera timestamps. They show why the delayed
manual procedure had no demonstrated relationship to a finite reply window.
They do **not** identify the camera's precise arm/expiry time.

## 4. Client correction

[`a6400a_native_readonly`](../../tools/research/a6400a_native_readonly.py) now:

- Keeps request and all allowed response polling in **one process/transaction**.
- Starts one monotonic **8-second scheduling budget before the request**;
  a slow request does not receive a fresh response budget afterwards.
- Retains the exact inquiry/model-info command and payload allowlist, one
  request, at most **40** response reads, no OUT replay, and existing I/O timeouts.
- Records UTC start/end plus monotonic acknowledgement and elapsed timing.
- Rejects another reply command or request-direction header instead of parsing
  it as a valid model response; the observed reply is command 1/direction 1.
- Refuses legacy `--finish-model-info` **before discovery or device I/O**.
  The old prototype source and receipts remain preserved; no stale request is
  resumed.

Default invocation is still host metadata only. No new SCSI opcode, TEST UNIT
READY, service operation, updater initialization or sector/file operation is
admitted. The previous logical-volume/physical-handle difference was not
silently treated as qualified: this physical result establishes only the
parent-verified LUN 0 route actually used.

## 5. One physical verification

After original-code controls and 50 focused checks passed, the owner explicitly
ran one fresh Administrator query, keeping Mass Storage and the existing driver.
Fresh PnP admission again selected the camera's exact parent-verified LUN 0;
no drive number was guessed.

| Operation | Requested / actual bytes | SCSI status |
| --- | --- | --- |
| Inquiry | 36 / 36 | success |
| One feature-1/subcommand-1 request | 8,192 / 8,192 | success |
| One immediate response read | 8,192 / 8,192 | success |

The model transaction ran from **20:58:54.784682 UTC** to
**20:58:54.787394 UTC**. The reply identifies `ILCE-6400A`; serial and raw
property-list data were not retained.

**Identifier correction:** the observed wire product code is opaque
**`0032858730`**, not updater `fdat.model` **`0x81030017`**. Those are different
namespaces. The target profile's `product_code` now records the observed Sony
wire code with this source; the updater ID remains in its package evidence and
explicit boundary. This corrects the earlier provisional field interpretation,
not the signed updater's identity.

Inquiry revision **`1.00`** is a SCSI inquiry revision, **not** the camera's
reported system-software version 1.01. No firmware-version updater command was
used to verify the latter.

The final host-only postcheck still shows `054C:0F0F`, USBSTOR, status OK/error
0. The successful model reply demonstrates application responsiveness for this
query; no uptime, no-reboot interval, kernel/module hash, cold-boot repeatability
or broader camera behavior is claimed.

## 6. Reproduction and validation

Offline only, against the preserved private inputs, choose a **new** directory:

```powershell
.\venv\Scripts\python.exe -m tools.research.msc_extcmd_trace `
  --output-dir .\artifacts\analysis\e0486-a6400a-msc-dispatch\NEW-CONTROLS

.\venv\Scripts\python.exe -m unittest `
  tests.test_msc_extcmd_trace tests.test_a6400a_native_readonly `
  tests.test_usb_debug_abi_trace tests.test_target_profiles -q
```

The real transaction was explicitly supervised and is preserved as
`native-fresh-1/receipt.json`; it is not part of ordinary tests. Do not replay
physical commands merely to reproduce an offline report.

Receipts under `artifacts/analysis/e0486-a6400a-msc-dispatch/` include input
symbols/hashes, targeted original instruction reports, original controls,
`reply-lifetime-controls/report.json`, exact exercised client source/hash,
the fresh transaction and postcheck. Earlier failed/stale receipts are retained
under E0508. No proprietary image or generated disassembly is committed.

Validation before the physical query: **50 focused tests OK**; twelve original
status decisions, four arming/clearing transitions, one TUR fixture, finite-wait
conversion, three callback windows and both pure packing functions completed
within their declared bounds.

Final focused source/profile checks: **51 tests OK**.
Documentation/dashboard/layout checks: **52 tests OK**.
The final full suite runs **1,587 checks**, with **2 failures / 13 errors /
71 skips** from the same unavailable historical captures/build receipts as
E0508. It is not green; no new failing case was introduced or hidden, and the
failure-stack sources match the initial Git HEAD. E0482's historical passing
count is not a new full-suite result.

The physically exercised client source is preserved separately from final
offline hardening. The later command/direction rejection was fixture-tested and
agrees with the captured reply's recorded 1/1 header; it was not rerun on the
camera. No additional camera protocol command followed the successful query.

## 7. Remaining boundary

The normal identity path is now **physically verified**. This does not identify
an installed debugger or create file/partition access. Keep the a6400A profile
at **reference**.

The next access work is a separately reviewed **temporary privileged read-only
bootstrap or existing-debugger discovery contract**, before live `/proc`,
`/setting` metadata and clean partition dumps can be captured. Mode switches,
uploads, persistent startup changes and driver replacement are not authorized
by the successful identity query. No such step was attempted here.

## 8. PR integration validation (2026-11-14)

The contribution was reconciled with upstream commit
`16d8c1b9fc611ac684af3659162f6434e4d65daa`. The a6400A records now use
**E0506-E0509** to avoid upstream's independently allocated evidence IDs.
Existing local receipt directories retain their original names. Upstream's
platform findings and E0490's historical 1,720-test passing record are preserved;
that count is not presented as this host's result.

- Contribution and PR-check selection: **113 tests OK**.
- Changed Python modules and tests: byte-compilation passed.
- Original ARM/Thumb reply-lifetime controls and both a6400/a6400A USB packing
  replays: passed offline against the preserved inputs.
- Full offline suite: **1,712 run, 2 failures, 13 errors, 84 skipped** in
  26.835 seconds. It is **not green**.
- The same 15 failing cases were reproduced by running the five affected test
  modules in an unmodified detached worktree at that upstream commit. No
  proprietary input was copied or substituted. This is a targeted baseline
  comparison, not a second full-suite run.
- The failures still require unavailable original-a6400/ZV-E10 captures,
  compiled UVC bridge/selector artifacts and tree/descriptor/overlay receipts.
  No guard was weakened or missing input fabricated.

Current receipts are local under `artifacts/analysis/e0494-pr-preparation/`,
including `full-suite.log`, `full-suite-summary.json`,
`upstream-baseline-failing-modules.log`, `upstream-baseline-summary.json` and
the original-code replay reports. The temporary baseline worktree was removed.
No camera command, driver change or certificate operation was performed during
PR preparation.
