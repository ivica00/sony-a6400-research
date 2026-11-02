# E0007 — Original library header read with guarded inode metadata

Date: 2026-10-18. Scope: bounded original-interpreter execution; no camera validation.

## Result

The explicit `metadata` policy reaches **6,493 original interpreter instructions**. The linker opens `/usr/lib/libjemalloc_ds.so.1` as descriptor 3 and reads its first **512 bytes**. It calls `fstat64`, reads sourced inode fields, and stops at the first attempted consumption of unknown `st_dev`, at PC `0x40004b9e`. Status is `unverified_metadata_read`; this is an intentional unsupported-data boundary.

This is the first observed original firmware library read in this probe. It is not completed linking, application entry, library execution, UI startup, a booted kernel or proof of camera equivalence. No file-backed mapping has been reached. Two fresh reports are identical. The earlier `files` policy retains its 5,078-instruction boundary, completed syscall history and stopping arguments.

## Inputs and metadata evidence

Original filesystem images are ext2 with 1,024-byte blocks and 128-byte inodes:

| Source | SHA-256 | Indexed nodes |
| --- | --- | --- |
| `nflasha7`, provisional `/` | `305e289ecc1d768544af71c83d58ce23ec4d232be1e7572d9d4f68f0f12188cc` | 614 |
| `nflasha15`, provisional `/usr` | `0e9b19144b021d8b1b1908554a7ac9cdc6f8b9599eeeb1d53118b8832a296e56` | 827 |

`Ext2Metadata` verifies each entire source image against its existing manifest hash, follows original directory blocks, and obtains inode numbers, inode offsets, mode, ownership, size, link count, allocation counts and image timestamps. Directory sizes come from inodes; the earlier extraction metadata normalized directories to size zero. Namespace ownership/mode and regular-file sizes are cross-checked before attaching the metadata.

The opened library is 2,984 bytes, SHA-256 `c22384a7b19929eaa0b2cfc71b950071488eac0af631e815de26c1df47ea3e01`. Its source inode is 14216 at image byte offset 59000704 in `nflasha15`. Content still comes through the confined, allowlisted, hash-verified snapshot provider described in E0006.

Application `im.elf` hash remains `866729eb0bc1e6f5aba04d8bf8e45491985afe89a078ccb106a1ce2476865225`; interpreter `ld-2.11.2.so` remains `7c215cee6c4175079d69cb1433c6be90189e793f6e44f068ed6ac97621dd7a2c`. Existing CPU, stack, credentials, UTS and namespace assumptions remain experimental as documented in E0003–E0006.

## Partial metadata contract

`GuestStat64` implements a deliberately partial ARM EABI layout, 104 bytes. The 64-bit size starts at offset 48, allocation count at 64 and final inode number at 96. This ABI must not use the packed x86 layout.

The handler writes sourced inode fields and zero padding after checking that the whole destination is writable. It records the image hash and inode offset in every successful partial response. `stat64` and descriptor-based `fstat64` share this contract. A failed copy preflight returns guest EFAULT without mutation.

Device numbers depend on the actual mount/device setup. Image timestamps do not prove runtime timestamps after boot and reads. Both device-number fields and all timestamp fields remain guarded. Their bytes retain prior guest contents; they are not supplied as guessed zeros. A zero syscall return here explicitly means **the declared partial research contract was serviced**, not that a complete Linux stat structure was reproduced. Reports retain `partial_contract: true`, the written-field list and guarded-field list.

Shared provenance guards stop CPU reads of unknown fields and reject kernel-contract reads that would otherwise bypass the CPU hook. Guest writes clear only overwritten provenance; file copies and overlapping uname/stat copies clear stale provenance across both domains. A stopped probe cannot be resumed through this boundary. The current run reads `st_mode` once and `st_ino` twice before attempting `st_dev`.

Primary references: [ARM stat64 structure](https://cos.googlesource.com/third_party/kernel/+/d40ce1708000fcf19c597e88c9074f442a557113/arch/arm/include/asm/stat.h), [ext2 inode definition](https://github.com/torvalds/linux/blob/master/fs/ext2/ext2.h), [ext2 inode loading](https://code.googlesource.com/linux/torvalds/linux/+/b8c60e8fc6f755c2cdf7164931afdbfa670c6646/fs/ext2/inode.c), and [Linux attribute filling](https://android.googlesource.com/kernel/common.git/+/4a61f17378c2cdd9bd8f34ef8bd7422861d0c1f1/fs/stat.c). These ground the research contract; they do not establish the exact Sony kernel's runtime state or changes.

## Reproduction and checks

```powershell
.\venv\Scripts\python.exe -m tools.research.probe_interpreter --syscalls metadata
.\venv\Scripts\python.exe -m tools.research.probe_interpreter --syscalls metadata --report artifacts/execution/interpreter-metadata-repeat.json
.\venv\Scripts\python.exe -m tools.research.probe_interpreter --syscalls files --report artifacts/execution/interpreter-files-metadata-regression.json
.\venv\Scripts\python.exe -m unittest discover -s tests
```

Metadata runs intentionally exit 2 at the unknown-data boundary. Generated reports remain under `artifacts/execution/`. No original input is modified and no camera operation is performed.

Constructed fixtures cover image identity, inode high UID/GID bits, hard links, source offsets, directory sizes, malformed entries, directory cycles, invalid blocks, unsupported features, truncation, 64-bit ABI placement, unchanged unknown bytes, CPU and host-read guards, partial overwrite, atomic failed copies, stat/fstat consistency and actual ARM syscall-to-guard execution. The complete suite has 113 passing tests.

## Next work

Recover the mount/device identity required by `st_dev` from original boot configuration, device-driver evidence or explicitly authorized read-only camera observations. Preserve this stop until its source is established. Then target the first file-backed mapping with correct ARM mmap ABI, guest protections and verified content. Timestamp handling and runtime mount overlays remain independent unresolved contracts.
