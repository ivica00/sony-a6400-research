# E0305 — read-only MPR dump, the erased-state ioctl identity, and the first run past the `/dev/nflasha4` boundary

Date: 2026-11-10. **Authorized read-only camera operations only** (explicit user
authorization: "Continue, you may proceed" [translated]). No camera write, no mode switch, no SD access,
no writable internal flash, no GUI frame. The injected UIPC input remains a
labelled experiment.

## 1. Why

E0302–E0304 established that the app's media/DFA initialisation stops at
`ioctl(0x80014123)` on `/dev/nflasha4` (raw MPR partition, block 252:4,
12,582,912 B). No partition image existed in the extracted firmware and the
read-only observation policy correctly refused to fabricate the reply. The next
truthful step required a read-only content dump and the answer semantics.

## 2. Read-only dump (camera)

`tools/camera_debugger.py` (native Sony USB debugger, PID 703, root, feature
0x23, `max_data=4064`) was used only for its read operation. The camera was in
normal MSC mode; the app PID 149 holds `/proc/149/fd/29 -> /dev/nflasha4`
(O_RDWR, untouched).

* Script: `artifacts/analysis/e0305-mpr-dump.py`; 3,097 chunks of 4,064 B.
* Output: `artifacts/hardware/mpr-readonly/nflasha4-12582912.bin`
  **12,582,912 B, SHA-256 `9bb12b379d1344710d1075449b049f05a48a6efdaebc6a9c4cfe587b39c46a14`**,
  3097 chunks, 18.557 s.
* Re-read equality: chunks at offsets 0, 81,920 and 12,578,848 re-read and
  matched the saved bytes (`matches_saved=true`).
* Camera responsiveness: uptime 25,752.89 s → 26,204.81 s across the whole
  operation, fd 29 unchanged, no reboot, no mode switch.
* Manifest: `artifacts/hardware/mpr-readonly/manifest.json` (camera identity,
  chunk log, hashes, re-read results, pre/post receipts). Receipts:
  `precheck.txt`, `postcheck-dump.txt`, `analysis.log`, `dump.log`.
* Content shape (not a format decode): 12,288 × 1 KiB pages; 633 pages start
  with the `CMMeX` header and contain a `PBG8DSHP'` marker; 11,642 pages are
  zero-filled. Byte counts: 12,098,358 zero, 393,506 `0xFF`, 91,048 other.

## 3. The first flash ioctl is EXT_CSD byte 0xB5 (static identity)

The a6400 `emmc.ko` (nflasha3 initrd, SHA-256
`d60683420d1ef7af57571d4281def19254c88e47c9047da9d5098e49de848671`) was
disassembled read-only with capstone/pyelftools:

* `emmc_blk_ioctl` @ `.text 0x9e8c` (ARM, size 2072). The branch whose command
  literal is `0x80014123` (`0x9eec`/`0x9ef0`) enters handler `0xa4ac`.
* Handler `0xa4ac`: `bl emmc_seq_get_erased_mem_cont` (reloc `0xa4bc`),
  then `bl __put_user_1` (reloc `0xa4d0`), copying one byte to the user
  pointer; error path uses `bdevname`/`printk`.
* `emmc_seq_get_erased_mem_cont` @ `0x14da4` (60 B): locks its context
  (`0xe4b0`), loads `[ctx+0x98]` (the parsed EXT_CSD buffer), calls the byte
  accessor `0xd294` (`ldr r3,[r0]; ldrb r0,[r3,#0xb5]`) and unlocks
  (`0xe530`). So the returned byte is **EXT_CSD[0xB5] = ERASED_MEM_CONT**.
* For the app, `libmpr` converts the byte at `0x33f2f6..0x33f31e`: a zero byte
  stores 0; any non-zero byte stores `-1` into the DFA field.

Disassembly and relocations: `e0305-emmc-erased-ioctl.py/.txt`,
`e0305-emmc-relocations.py/.txt`.

## 4. Direct read-only observation: `B=00`

To avoid guessing, a minimal probe was built against the preserved Sony libc
(`tools/native_camera/mpr_erased_state_probe.c`; `-nostdlib`, camera
`libc.so`, `/lib/ld-linux.so.3`, entry `snapshot_start.S`).
ELF SHA-256 `eac87e1eaf9ac8ab852f9036d3eba2ae17c722e1e87f955965065453485e7304`,
6,020 B. It opens `/dev/nflasha4` **O_RDONLY**, issues exactly one
`ioctl(fd, 0x80014123, &byte)`, closes the fd and writes `B=<hex>`.

* Pushed with `tools/camera_debugger.py push`; read-back verified by the tool.
* Run receipt: **`B=00`** (raw output in
  `artifacts/hardware/mpr-readonly/erased-probe-run.txt`).
* Removal receipt: helper and the earlier failed static probes removed from
  `/tmp_bt`; camera still responsive; fd 29 unchanged.
* Only the fixed read-only query was executed. No partition write, no ioctl
  other than the observed read query, no mode switch.

Manifest section `erased_state_ioctl_observation` records command, probe hashes,
push/run/cleanup receipts and `read_only: true`.

## 5. Emulator policy: `--nflasha4-device observed-dump`

`src/a6400/execution/guest_nflasha4.py` adds a hash-checked dump policy
(`Nflasha4Dump`) and `interpreter_probe` serves, under an explicit opt-in:

* open `/dev/nflasha4` O_RDWR accepted (observed flags 2, fd 31);
* `lseek` with correct `SEEK_END` (`size + offset`) and `SEEK_SET`/`CUR`
  handling; served `lseek(SEEK_END)=12,582,912`;
* `read` served from the dump with bounds checks and EOF semantics;
* ioctl `0x80014123` answered with the **observed `0x00`** and recorded;
* `fsync`/`fdatasync` return 0 **only while the model has served no write on
  that fd** (`flush_result(dirty=False)`); any dirty state is an explicit
  boundary (`nflasha4_write_flush_not_supplied`);
* `write`/`writev`/`pwrite`/`fstat`/other ioctls/`mmap` stop with explicit
  `unsupported_nflasha4_contract` boundaries; no partition bytes are fabricated.
* Image identity is checked against the manifest hash; a mismatched or partial
  dump is refused before execution.

Reports record `nflasha4_dump_policy` (image SHA-256, size, observed byte,
evidence paths). Default (`stop`) and `open-only` behaviour are unchanged;
focused tests `tests/test_guest_nflasha4.py` (5) pass.

## 6. Bounded runs past the old boundary

Both resume `boot-e0301-live-receiver.ckpt` (214,289,958) with the E0303-G5
Path-1 policies, the verified VBUS body on queue `0x012002DA`, and the new
`--nflasha4-device observed-dump`. The VBUS delivery/completion is again
observed (handle 4106; callback frees its message; completion
`message_touched=false`).

| run | instructions | threads | result |
| --- | --- | --- | --- |
| `e0306-live-dump.json` | 233,281,147 | 55 | 131 `/dev/nflasha4` operations; stops at `fdatasync(fd=31)` |
| `e0307-live-dump2.json` | **235,778,358** | **61** | 240 `/dev/nflasha4` operations; stops at `mount("/dev/nflasha1","/mnt","vfat",...,"posix_attr")` |

Served operations include the observed `lseek(SEEK_END)=12,582,912`, the
`0x80014123` ioctl (`erased_state_byte=0`), and descending 1 KiB reads
(1,047,552 → 1,024 …), i.e. the original DFA/FlashLib scan. No write was
requested through the served path; the clean flush answers only the empty
modelled page state.

**Still no USB FSM transition**: `UsbControl` (1018), `UsbBusPower` (1016) and
`BusPower` (1022) remain `blocked_futex`; `usb_otgcore.config` is `None`;
`viewUnified2` is not loaded; OSD A/B are unmapped; **no GUI frame**.

## 7. Boundary and next

The next side path is a **read-only `/dev/nflasha1` (vfat, mounted at `/mnt`)**
contract: the app issues `mount("/dev/nflasha1","/mnt","vfat",...,"posix_attr")`
after the MPR scan. That needs (a) a read-only content dump of nflasha1 (or a
preserved image if one exists) and (b) a bounded read-only vfat mount/file
contract — neither exists yet. Do not serve mount by fabricating success.

Other open contracts remain the UVC/PTP-relevant ones from E0303/E0304:
UsbControl's runtime receive id and the inbound SETCONFIG message, the
`0x008F013A` relayed-notification consumer, the buspwr port-type reply, and the
otgcore PTP/UVC descriptor templates. The physical UVC/PTP lane remains paused.

## 8. Artifacts

* Dump: `artifacts/hardware/mpr-readonly/` (image, manifest, receipts, analysis).
* Camera probe: `tools/native_camera/mpr_erased_state_probe.c`,
  `artifacts/native/mpr-ioctl-probe/` (ELF, build script/manifest, failed
  static-control binaries retained).
* Analysis: `artifacts/analysis/e0305-mpr-dump.py`, `e0305-mpr-analyze.py`,
  `e0305-emmc-erased-ioctl.py`, `e0305-emmc-relocations.py`,
  `e0307-mpr-structure.py`.
* Runs: `artifacts/analysis/e0306-run-live-dump.py`,
  `e0307-run-live-dump2.py`; reports `artifacts/execution/e0306-live-dump.json`,
  `e0307-live-dump2.json`; checkpoints `boot-e0306-live-dump.ckpt`,
  `boot-e0307-live-dump2.ckpt`.

## 9. Checks

Full suite **862 tests OK** (18.559 s) after the policy and tests were added;
focused nflasha4/wiring tests pass. This note is offline evidence plus the
authorized read-only camera dump/query; it establishes no UVC/PTP function and
no GUI frame.
