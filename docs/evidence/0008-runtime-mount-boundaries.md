# E0008 — Runtime mount evidence and an earlier fidelity boundary

Date: 2026-10-18. Scope: static original boot evidence and a conservative process experiment. No camera operations.

## Findings

The original `init` contains 22 mount records. In addition to the provisional root and `/usr` filesystems, these include an attempted **`/dev/nflasha10` → `/etc`** vfat mount. Consequently, absence of `/etc/ld.so.preload` in the preserved root image does not establish absence on a booted camera.

E0006 and E0007 remain reproducible experiments under their declared static snapshot assumptions. Their missing-file responses are not validated runtime-camera responses. The new opt-in `--respect-runtime-mounts` check makes this distinction executable: the original interpreter stops at its first access to `/etc`, after **3,091 instructions**, with `unsupported_filesystem` / `runtime_namespace_not_supplied`. It does not supply ENOENT for that path.

This earlier stop is a stronger boundary on the fidelity claim, not loss of the snapshot experiment. The unchanged `metadata` experiment still reads 512 library bytes and reaches 6,493 instructions. Its fresh report is identical to E0007. Two fresh mount-aware reports are also identical.

## Mount selection evidence

`init`'s `mnts` symbol is at `0x13308`, 440 bytes, with 20-byte records. The helper at `0x8eac` loads source, target, filesystem and flags from the first four words, puts the fifth word on the stack, and calls `mount` at `0x8ece`. This supports interpreting the fifth word as mount data/options. These are static instructions; mount outcomes remain unobserved.

Observed `/usr` sequence in `main`:

| Call instruction | Record address | Source | Filesystem | Branch condition |
| --- | --- | --- | --- | --- |
| `0x97fc` | `0x13394` | `/dev/dnflasha15` | ext2 | first attempt on this branch |
| `0x980e` | `0x13448` | `/dev/nflasha15` | ext2 | first attempt failed |
| `0x9820` | `0x13380` | `/dev/nflasha15` | cramfs | prior attempt failed |
| `0x9832` | `0x133a8` | `/dev/nflasha15` | vfat | prior attempt failed |

At `0x983c`, `main` loads record `0x134ac` and calls the helper at `0x983e`: `/dev/nflasha10` → `/etc`, vfat, flags `0xc0ed0490`, data `posix_attr`. Earlier root handling tries `/dev/dnflasha7` and then `/dev/nflasha7` at `0x9786` and `0x9790`, before the pivot sequence. Other branches depend on boot-mode state such as NFS and QEMU checks. None is silently selected as measured normal camera boot.

The two extracted copies of `init` (root image and initial ramdisk) are byte-identical. The updater's `mount.conf` lists `/dev/nflasha15` for `/usr`, but does not express these compressed-device fallbacks or the `/etc` overlay. The executable's behavior is therefore necessary evidence beyond the configuration file.

## Device table evidence

The `udif_devnodes` symbol in `devno.ko` spans 1,056 bytes, interpreted as 88 records of 12 bytes. Name pointers use section-backed ARM ABS32 relocations. Each record contains one relocated pointer followed by four halfwords. The following meanings are **inferred from the table pattern**, pending validation against the registering driver/kernel consumer:

| Name | Raw halfwords | Inferred kind, major, first minor, count |
| --- | --- | --- |
| `nflasha` | `1, 252, 0, 32` | block, 252, 0, 32 |
| `nflashaB0` | `1, 252, 126, 1` | block, 252, 126, 1 |
| `nflashaB1` | `1, 252, 127, 1` | block, 252, 127, 1 |
| `dnflasha` | `1, 252, 128, 32` | block, 252, 128, 32 |

The ranges differ. A partition filename alone does not select the mounted device or establish the suffix-to-minor rule. The report deliberately supplies neither a selected runtime identity nor a `st_dev` value. Device-number and timestamp guards from E0007 remain unchanged. Kernel strings and the eMMC module suggest compressed-device handling, but strings alone are not used to select a runtime path.

## Implementation

`tools/research/mount_evidence.py` checks source paths and existing baseline hashes before reading them. It resolves table relocations, decodes mount records and bounded original instruction blocks, and writes `artifacts/inventory/mount-evidence.json`. The report separates raw fields from inferred meanings, retains source hashes and states `runtime_device_identity_selected: false`.

`--respect-runtime-mounts`, available with `files` or `metadata`, derives possible runtime mount targets from the hash-checked original `init`. It adds unsupplied targets to the existing unknown namespace roots. Conditional targets are treated conservatively; this does not assert that every attempted mount succeeds. `/usr` and `/rootfs` remain the explicitly supplied image assumptions of the existing experiment. No runtime contents are imported from Windows or invented.

Generated mount-aware reports include the init identity and the unsupplied target list. Reports receive a separate default filename, preserving snapshot baseline outputs. Default no-response and earlier syscall policies remain unchanged.

## Input identities

| Artifact | SHA-256 |
| --- | --- |
| Both extracted `sbin/init` copies | `0af5724ece7f60db2831b7a4e61829be369868027877cca0f921f981ae8dc7ad` |
| Initial ramdisk `kmod/devno.ko` | `3b36fcea8687d7f29112a7008ce61fde9229679ebc24c65ec2d21cf3af632f56` |
| Updater `0100_config/mount.conf` | `0ef2d463b13cb23995f83080e6189da9e1287566d0645f5b41d5c8da14fd8acd` |

Original application, interpreter, kernel and filesystem identities remain as recorded in E0003–E0007. The analysis uses only preserved local firmware; no external Sony source tree was assumed to match it.

## Reproduce and validate

```powershell
.\venv\Scripts\python.exe -m tools.research.mount_evidence
.\venv\Scripts\python.exe -m tools.research.probe_interpreter --syscalls metadata --respect-runtime-mounts
.\venv\Scripts\python.exe -m tools.research.probe_interpreter --syscalls metadata --respect-runtime-mounts --report artifacts/execution/interpreter-metadata-mount-aware-repeat.json
.\venv\Scripts\python.exe -m unittest discover -s tests
```

Both bounded firmware runs intentionally exit 2 at unsupplied `/etc`. Constructed tests cover mount options, malformed records/targets, distinct device ranges, missing relocations, invalid ranges, bounded strings, source identity/confinement, and actual Thumb execution that stops at an unsupplied overlay before returning missing-path errors. The complete suite has 120 passing tests.

## Next work

1. Trace the device table's registering consumer to establish field meanings and partition numbering, and trace compressed-device registration conditions.
2. Establish boot mode and successful mount selection before assigning `st_dev`.
3. Establish the contents or verified relevant absence under the `/etc` overlay from an identified state snapshot or authorized read-only observations. Define how that state is supplied and hashed.
4. Continue file-backed mappings only under a declared namespace/device-state profile. Preserve snapshot experiments as scoped research; do not report their deeper progress as validated camera startup.
