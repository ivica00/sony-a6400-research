# Experiment 0009: Stream device and DDS allocation

Question: is implementing the original stream character-device ABI sufficient for the selected `im.elf i` experiment to reach fb0?

Use [E0034](../evidence/0034-stream-device-and-graphics-allocator-boundary.md) for exact inputs, policy and commands. Preserve the old disabled-stream boundary and all selected upstream assumptions. Enable the new device explicitly with `--stream-device image-driver`; do not relabel the preset-backed state, deterministic entropy or invented empty `/tmp` as observed camera state.

Verify 249:7 in both original devno data and the image inode. Reproduce the ioctl and mmap ARM windows. Do not replace the physical PFN argument with anonymous zero-filled state: unsupplied bytes must remain guarded until valid writes replace them. Reject aliases, unsupported mappings, inaccessible host copies and unsupported operations without fabricated success.

The actual continuation opens stream but reaches the original DMP allocator assertion before any stream ioctl/mmap or fb0 request. Preserve the requested SIGABRT and its PC/arguments; do not implement it as a no-op. Trace original GRM-MA recipient `0x014c0424`, its request/reply fields and DMM queue `0x0061003c` next. Resolve the required allocation state before returning physical addresses, handles or pool contents.

Keep the full-library REA timeout as a failed analysis record; use the successful small-driver sessions and targeted original consumer instructions. Original hardware mapping, DMA, framebuffer geometry and real UI pixels remain separate validation gates.
