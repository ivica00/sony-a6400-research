# E0006 — Read-only guest filesystem and original library search

Date: 2026-10-18. Scope: original interpreter research over declared image snapshots. No camera or full-system fidelity is claimed.

## Observed result

The new optional `files` policy executes **5,078 original interpreter instructions**. The linker checks `/etc/ld.so.preload`, attempts `/etc/ld.so.cache`, and searches ARM/TLS-specific library directories. Those absent paths receive guest `ENOENT` results based on the complete static image namespace.

Execution stops at **`stat64` of the existing `/lib` directory** with `unsupported_filesystem` / `stat64_success_structure_not_implemented`. No successful metadata structure is fabricated. This experiment supplies negative `stat64` path results only; successful stat/fstat structures remain unsupported.

Two fresh runs produce identical reports. The observed firmware run has not successfully opened or read a library yet. File open/read/seek/close behavior is covered by constructed fixtures, including an ARM execution fixture that opens a verified file and stops at its next unsupported `fstat64` request.

## Namespace and backing data

The guest namespace uses the previously recovered original-image paths and links, with `nflasha7` provisionally mounted at `/` and `nflasha15` at `/usr`. Complete static directories can establish absence in this snapshot. That is not proof that a live camera never overlays or changes a path.

Known runtime/unsupplied mount roots (including `/dev`, `/proc`, `/setting`, `/tmp`, `/system`, storage and update mount points) stop explicitly. They do not become ordinary missing files. Relative paths stop pending a verified working-directory policy. There is no Windows-path fallback.

Successful regular-file opens require an allowlisted extracted content path confined to the firmware directory, a matching baseline SHA-256, and matching original metadata size. The content is read into an immutable snapshot with independent guest descriptor offsets. A changed, unavailable or unverified local backing file is an unsupported-input stop, not guest `ENOENT`.

The rootfs and `/usr` images are hash-checked before the run. Namespace metadata remains a generated local research artifact; it is not a signed camera filesystem attestation. Runtime overlays and namespace changes are outside this policy.

## Implemented bounded contracts

- `access`: existence/read checks from guest metadata, with directory traversal checks. Write/execute modes remain unsupported.
- `open`: regular files, O_RDONLY and declared ARM large-file/close-on-exec flags only. Writes, creation, unsupported flags, devices and directory descriptors stop.
- `read`: immutable verified bytes, guest write-permission/bounds checks, independent offsets and EOF. A failed copy preflight does not advance the descriptor. Successful copies clear stale uname provenance.
- `lseek` and `close`: guest offset/descriptor behavior; no host descriptor is exposed. Large-file seeks requiring a different ABI stop.
- `stat64`: verified missing-path errors only. Existing-path success stops for the next ABI milestone.

Credentials are explicitly UID/GID zero with no supplementary groups. Basic metadata permission checks are used; a denied root operation requiring a capability decision stops rather than guessing. Inherited stdio is unsupplied. Experimental ceilings are 256 descriptors and 1 MiB per read. These are declared resource policies, not measured camera limits.

Path traversal respects guest symlinks and `..` ordering. A trailing slash on a regular file returns ENOTDIR. The shared resolver moved to `src/a6400/images/guest_paths.py`; research-tool imports remain compatible.

Kernel-contract reads cannot consume uname bytes whose runtime identity is unknown. The existing identity guard is checked during pathname copying as well as CPU reads. This prevents passing a guarded buffer directly to a syscall from bypassing the guard.

Read-copy failure uses an atomic preflight policy rather than Linux's possible partial-copy side effects. ACLs, extended security modules, concurrent filesystem changes, arbitrary credentials/capabilities and writable mount behavior remain unimplemented.

## Commands and reports

```powershell
.\venv\Scripts\python.exe -m tools.research.probe_interpreter --syscalls files
.\venv\Scripts\python.exe -m tools.research.probe_interpreter --syscalls files --report artifacts/execution/interpreter-files-repeat.json
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Reports: `artifacts/execution/interpreter-files.json` and `interpreter-files-repeat.json`. This run intentionally returns exit code 2 because an existing-path metadata contract is unsupported. The JSON retains every completed request and the exact stopping reason. Earlier `stop`, `brk`, and `brk-uname` policies remain selectable.

Implementation: `guest_filesystem.py`, `guest_paths.py`, and `verified_content.py`. Tests cover path absence versus unknown runtime state, symlink traversal, permissions, content identity/confinement, immutable snapshots, offsets/EOF/seeks/closes, invalid pointers, copy permissions, provenance, unsupported operations and execution integration.

Primary contract references: [Linux v3.0 file/access operations](https://github.com/torvalds/linux/blob/v3.0/fs/open.c), [read/seek behavior](https://github.com/torvalds/linux/blob/v3.0/fs/read_write.c), and [ARM open flags](https://github.com/torvalds/linux/blob/v3.0/arch/arm/include/asm/fcntl.h). These guide the bounded contracts; live Sony kernel behavior is still unverified.

## Next milestone

Verify the ARM EABI `stat64`/`fstat64` layout and recover the original filesystem metadata needed by the linker. Do not invent inode/device/timestamp values. Unknown fields must remain explicit if their source or boot-time values cannot be established. After successful metadata handling, target the first original library header read and guest file-backed mapping.
