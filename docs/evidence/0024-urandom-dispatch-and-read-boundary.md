# Evidence Record 0024: Original urandom Dispatch and Guarded Entropy Read

## Result

Package H's optional `--urandom-open` contract opens the verified image node `/dev/urandom` and reaches `read(4, 0x546a9188, 4)` at **41,955,226 instructions**. Execution stops with `unsupported_filesystem`, reason `entropy_state_not_supplied`, PC `0x5008b1c4`, syscall 3. Exactly **zero entropy bytes** are supplied. The 601 serviced syscall responses include the successful open, not the blocked read. No framebuffer transaction or camera UI is produced.

The default Package H policy retains E0023's namespace stop; the optional contract is a declared static-image experiment. Compiled driver registration and continued availability of the image device node are assumptions, not a boot observation. Boot-event ordering/payloads and the writable runtime `/etc` remain unverified as in E0023.

## Input identities and commands

All firmware inputs are unchanged from E0023. In particular:

- `vmlinux.bin`: SHA-256 `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`.
- rootfs `nflasha7`: SHA-256 `305e289ecc1d768544af71c83d58ce23ec4d232be1e7572d9d4f68f0f12188cc`.
- `im.elf`: SHA-256 `866729eb0bc1e6f5aba04d8bf8e45491985afe89a078ccb106a1ce2476865225`.
- `ld-linux.so.3`: SHA-256 `7c215cee6c4175079d69cb1433c6be90189e793f6e44f068ed6ac97621dd7a2c`.

```powershell
.\venv\Scripts\python.exe -m tools.research.entropy_trace
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --urandom-open --instructions 45000000 --timeout-us 240000000 --report artifacts/execution/package-h-urandom-read.json
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --urandom-open --instructions 45000000 --timeout-us 240000000 --report artifacts/execution/package-h-urandom-read-repeat.json
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --instructions 45000000 --timeout-us 240000000 --report artifacts/execution/package-h-urandom-disabled-regression.json
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

The process runner preserves input mappings/hashes, policy assumptions, message deliveries, final registers/instructions, syscall arguments and boundary. Reports are separate from prior baselines. The static tool never executes an updater or touches a camera.

## Observed identity and kernel contract

The hash-checked rootfs inode 110 at file offset `0xa280` is a character node with mode `020444`, UID/GID 0. Its first `i_block` word is `0x109` (old device encoding): major **1**, minor **9**. This is the special device's `rdev`, not the filesystem's `st_dev`; no invented inode, timestamp or containing-filesystem identity is supplied to the guest.

The kernel contains a 12-entry memory-device table at file offset `0x2d6bf0`. Interpreting its pointers with linked-image base `0x60108000` resolves every nonempty name consistently: `mem`, `null`, `port`, `zero`, `full`, `random`, `urandom`, `kmsg`. This base is an image-address relation, not a newly validated physical machine map.

Minor 9's row contains name pointer `0x604604a8`, mode `0666`, file-operations pointer `0x603df048`, and zero backing-info pointer. The operations table contains read pointer `0x60296f20` and a zero open callback at offset `0x2c`. Routine names below are inferences from these table relationships and matching upstream source, not recovered Sony symbols.

Two isolated original-code windows establish the dispatch:

| Window | Original result | Limitations |
| --- | --- | --- |
| `memory_open` at `0x60295c40` | 22 original ARM instructions, normal return with `r0=0`; constructed file's operations pointer becomes `0x603df048` | Constructed inode/file/stack, minor 9; no VFS traversal, registration or boot |
| `urandom_read` at `0x60296f20` | Five original ARM instructions reach `0x60296e0c` with `r0=0x604e3c50`, unchanged destination pointer and count 4 | Stops before entropy extraction; no pool data is consumed |

The second window loads a pointer to the nonblocking-pool candidate. Knowing that pointer does not establish its runtime contents. The downstream original extraction routine mixes/transfers pool state, extracts bytes, and copies them to userspace. A preserved kernel initializer is insufficient to identify that state after boot.

Primary references: Linux [3.0 memory-device dispatch](https://raw.githubusercontent.com/torvalds/linux/v3.0/drivers/char/mem.c) and [3.0 urandom implementation](https://raw.githubusercontent.com/torvalds/linux/v3.0/drivers/char/random.c). Upstream explains the contract shape; the local kernel table and executed windows establish the reported Sony-binary observations. The general old/new device encodings are defined in the kernel's [device-number helpers](https://raw.githubusercontent.com/torvalds/linux/master/include/linux/kdev_t.h); the ext2 special-inode selection is visible in [ext2 inode source](https://codebrowser.dev/linux/linux/fs/ext2/inode.c.html). These source references do not establish that Sony's full kernel equals upstream.

## Implementation and verification

- `Ext2Metadata` decodes old/new special-device major/minor fields from original inode bytes. Constructed fixtures check both encodings.
- `GuestFilesystem` accepts an explicit `urandom_open` option. Only the exact read-only `/dev/urandom` open may use this exception. It checks special-character mode, 1:9 identity and image provenance, enforces directory/file permissions, and uses the existing bounded guest descriptor table. Other runtime paths and symlink aliases retain their guards.
- Read stops before any host copy or return value; it records the requested buffer, byte count, source hash and zero supplied bytes. Close is supported. Other operations stop without fabricated metadata or device content. No host randomness or host device path is used.
- An ARM fixture executes open followed by read and verifies the unsupported boundary, exactly one syscall response and unchanged destination bytes. Negative cases cover default policy, wrong identity, missing provenance, wrong type, write flags, unknown paths, descriptor exhaustion, metadata operations and path provenance.
- **215 tests pass**, including all original 204. The captured suite is `artifacts/tests/package-h-urandom-suite.txt`.
- The default no-response probe still stops after **1,183 instructions**, in `package-h-urandom-default-regression.json`.

The independent opted-in repeat matches status, instruction count, syscall count, boundary and final 32 instructions exactly. The disabled-option regression matches E0023 on the same fields (41,953,485 instructions, 600 responses). Comparisons are preserved in `artifacts/execution/package-h-entropy-comparisons.json`. The bounded protocol is [Experiment 0002](../experiments/0002-guarded-urandom.md).

## Remaining boundary

No identified runtime entropy pool or read transcript is available. Advancing the successful read would require a declared, justified entropy-state model or a provenance-checked replay input; arbitrary bytes, host randomness or a forced open failure would change this experiment's assumptions. None is supplied here. Authentic boot-event producers/payloads, display geometry/format, framebuffer submission and a guest-rendered camera UI remain open. `status_a6400.png` records this research state and is not camera output.
