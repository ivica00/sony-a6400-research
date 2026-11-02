# Experiment 0006: Read-only inode metadata

Question: can original libc finish metadata conversion using identified image fields and an explicitly selected read-only mount state?

Run the original kernel windows and the `im.elf l` commands in [E0028](../evidence/0028-readonly-inode-metadata-and-module-request.md), using separate report paths. Preserve E0027's reports. Limits remain three million instructions and 45 seconds. No camera, updater, host module loader or device write is used.

Controls: with both new options disabled, stop on `st_rdev` at 2,222,528 instructions; with regular-inode rdev only, stop on `st_atime`; with both selected, record the first subsequent unsupported request. Never clear guards for writable, unknown, mismatched or non-ext2 mounts. Preserve guards on special-node rdev. Keep default and metadata-only interpreter baselines.

Evidence required: hash-checked original inode initialization/attribute/atime instructions, explicit constructed-window inputs, hash-checked original mount candidates, image inode offsets/times and matching source identities. Record module-buffer identity and parameters if original code requests `init_module`, but do not service it or treat the request as initialization success.

Reject fabricated seconds, host timestamps, generic zero metadata, silent mount selection, kernel-load success stubs and host syscall forwarding. Selected read-only image state is an experiment assumption; successful camera mounts and physical metadata equivalence remain unvalidated. Display output remains absent until original code submits verified pixels through a supported display contract.
