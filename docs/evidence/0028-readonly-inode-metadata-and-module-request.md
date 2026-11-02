# Evidence 0028: Read-only inode metadata and the original module request

Follow-up scope correction: [E0029](0029-backup-service-guard-and-liro-entry.md) identifies unverified backup-service acknowledgements before this module request. The recorded run remains reproducible with the explicit historical `--backup-service unverified-ack` option. The UI runner now stops at the earlier unsupplied backup-service reply by default; `adr=0x0` is not established camera state.

## Result

An explicit read-only ext2 image policy advances `im.elf l` beyond libc's metadata conversion to the original **`init_module` syscall 128**. At **2,226,764 instructions**, after **197 supplied responses**, it requests loading **65,276 bytes** that match `/usr/kmod/liro.ko` exactly, with parameter string ` adr=0x0  `. The syscall is not serviced. No kernel module, camera device operation, framebuffer transaction or UI is executed by this milestone.

Two separate options supply only newly established metadata: `--regular-inode-rdev` and `--readonly-image-times`. Disabled runs retain E0027's boundary. These are bounded process experiments under a selected static, read-only image state, not observations of which mount succeeded on a camera.

## Original kernel evidence

The hash-checked kernel is unchanged: `vmlinux.bin`, SHA-256 `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`. Its export-table function/name-pointer pairs identify these routines directly:

| Name | Export record file offset | Linked function address |
| --- | --- | --- |
| `generic_fillattr` | `0x36c7f0` | `0x601c3070` |
| `inode_init_always` | `0x36ce48` | `0x601d635c` |
| `init_special_inode` | `0x36ce10` | `0x601d5648` |
| `touch_atime` | `0x36f6d8` | `0x601d6664` |

`tools.research.inode_attribute_trace` checks each original pointer and terminated name, disassembles the routines and executes isolated original ARM windows. Constructed inode, superblock, dentry and stack inputs are explicitly recorded. No filesystem traversal or complete inode allocation is claimed.

- **35 original instructions** in the `inode_init_always` prefix set inode offset `0x88` to zero, stopping before its first external call.
- **51 original instructions** in `generic_fillattr` return normally and copy that inode field to kstat offset `0x1c`.
- Character and block controls execute **12** and **15** original `init_special_inode` instructions, respectively. Their supplied internal device numbers are copied by `generic_fillattr`, demonstrating why a regular-file zero must not be supplied indiscriminately to special nodes.
- **17 original `touch_atime` instructions** return without changing the constructed timestamp bytes when the superblock's read-only bit is set. Original code tests superblock flags with mask `0x401` before any clock call or timestamp update.

The mapping uses the same linked kernel-image base relation as E0024; it does not establish physical machine addresses. [Linux inode initialization](https://raw.githubusercontent.com/torvalds/linux/master/fs/inode.c) and [ext2 inode loading](https://codebrowser.dev/linux/linux/fs/ext2/inode.c.html) provide primary contract references. The current upstream sources are explanatory references, not assertions that Sony's kernel equals current Linux. Local original instructions establish the reported initialization, copying and read-only-atime behavior. Ext2's on-disk seconds and zero nanoseconds are distinct from a running writable inode's timestamp history.

## Selected read-only image state

The runner independently reads the hash-checked original `sbin/init`, SHA-256 `0af5724ece7f60db2831b7a4e61829be369868027877cca0f921f981ae8dc7ad`, through the existing mount-table decoder. It requires matching ext2 mount candidates for each declared image and verifies that all matching candidates carry `MS_RDONLY`. It retains the actual candidate records and init/image identities in the report.

The `/rootfs` partition-7 and `/usr` partition-15 ext2 candidates carry `0xc0ed0001`; both compressed and direct candidates are read-only. This selection does not resolve compressed versus direct physical storage, verify a successful mount, or supply writable `/etc`. Existing direct-device-number assumptions remain those of the process experiment.

`GuestStat64` receives the optional per-image mount selection. Only matching image identity, ext2 type and the read-only flag permit image timestamps. Writable, unselected, mismatched or other-filesystem metadata remains guarded. Malformed supplied timestamps fail before copying any bytes. Original image seconds are preserved bit-for-bit; ext2 nanoseconds are zero. The fixture includes `0xffffffff` to check signed-time bit preservation rather than host-date conversion.

For `/usr/kmod/liro.ko`, the verified partition-15 image hash is `0e9b19144b021d8b1b1908554a7ac9cdc6f8b9599eeeb1d53118b8832a296e56`, inode **10083**, inode file offset **42210560**. Its image timestamps are atime **1558936647**, mtime **1558936569**, ctime **1558936647**. These values describe the preserved read-only image selection, not a physical camera capture.

The regular-file device-number option is independent. It supplies zero only for regular inode metadata, recording the initialization basis. It leaves directories, symlinks, character/block nodes and all unrelated buffers guarded. Per-buffer verified ranges do not globally disable field guards; unlabeled known ranges are omitted from provenance tracking, including reads spanning a named field and a verified range.

## Execution observations and reproduction

| Selected options beyond E0027 | Boundary | Instructions | Responses |
| --- | --- | ---: | ---: |
| Neither new option | `st_rdev` read | 2,222,528 | 196 |
| Regular-inode device number only | `st_atime` read | 2,222,551 | 196 |
| Both options | `init_module` syscall, before response | 2,226,764 | 197 |

```powershell
.\venv\Scripts\python.exe -m tools.research.inode_attribute_trace
.\venv\Scripts\python.exe -u -m tools.research.experiment_ui_boot --argument l --stimulus none --urandom-open --madvise-dontneed --regular-inode-rdev --readonly-image-times --trace-library-activation --instructions 3000000 --timeout-us 45000000 --report artifacts/execution/package-h-readonly-times-l-final.json
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

The final boundary is ARM syscall 128 at PC `0x5029dd50`. The post-stop diagnostic checks readable bounds and provenance before hashing the requested buffer. Its SHA-256 is `72cb5700d34ecac6f8a9475f05268e55c94bf972183884bdb0e6d95edc40d9f7`, matching the verified module file. Hashing is observation only, not a successful kernel-load response. The original parameter string is retained, not selected by the host.

The original module's static `.modinfo` declares dependencies `osal_uipc,backup,osal_utm,dma330` and kernel version magic `3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7 `. Its unresolved symbols include Sony backup, IPC, DMA, cache/address translation, timer and thread services. The reproducible static inventory is included in `package-h-inode-attributes.json`; imports do not establish that all are reached during initialization.

## Verification and limits

All **243 tests pass**, including the previous 237, in `artifacts/tests/package-h-inode-attributes-suite-final.txt`. New checks cover actual ARM reads of supplied metadata, source bit preservation, option defaults, special-node exclusion, mismatched/writable mount guards, destination reuse, cross-range reads, per-buffer isolation and atomic failure for invalid source times.

`package-h-inode-comparisons.json` records report hashes and exact comparisons of status, instruction count, response count, boundary and final instructions. The final read-only run matches its first run on all those fields. Disabled `l` matches E0027; the no-response baseline remains **1,183** instructions and the metadata-only baseline remains **6,493**, still stopping on unknown `st_dev`.

E0014's timestamp limitation remains correct for unselected or writable runtime state; this record establishes a narrower explicit read-only image experiment. No physical timestamp replay, runtime remount, entropy output, kernel module loader, IRQ/DMA execution or camera timing is supplied. The `i` path's guarded entropy read remains unresolved. The next module boundary requires real kernel/module contracts, not a success stub. See [Experiment 0006](../experiments/0006-readonly-inode-metadata.md). The regenerated status chart remains research status, not camera pixels.
