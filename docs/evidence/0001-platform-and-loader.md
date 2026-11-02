# E0001 — Extracted platform and loader findings

Date: 2026-10-18. Scope: the local extracted update, not a running camera. Reproduce with `python -m tools.research.elf_inventory` in the project environment.

## Verified observations in local artifacts

- 474 ELF files were parsed without errors: 85 executables, 276 shared objects, and 113 relocatable objects. All identify as ARM. Full paths, hashes, load segments, interpreters, imports/exports, dependencies, initialization tags, TLS segments, and relocation counts are in `artifacts/inventory/elf-inventory.json`.
- `nflasha7_unpacked/root/chassis` contains `CXD90045`. This supports the platform name; it does not establish the CPU configuration or memory map.
- `nflasha3_unpacked/vmlinux.bin`, byte offset 2,883,624, contains a Linux version string identifying `3.0.27_nl-rt106+`, with SMP/PREEMPT RT build markers and a May 2019 build date. This is kernel image evidence, not a successful boot or measured processor count.
- `im.elf` and `WS_SubProcess.elf` specify interpreter `//lib/ld-linux.so.3`. Both have original initialization tags and runtime-library dependencies.
- `nflasha15_unpacked/bin/network.sh`, line 3, invokes `/usr/bin/WS_SubProcess.elf`. This documents one launch site; the script's own caller and normal camera startup sequence have not been traced.
- `0100_config/mount.conf` describes `/dev/nflasha3` at `/system`, `/dev/nflasha7` at `/rootfs`, and `/dev/nflasha15` at `/usr`. These are update configuration declarations. Runtime mounting and filesystem decoding still require verification. The same configuration contains other product-family paths; their presence is not evidence that those subsystems run on this model.
- `nflasha7_unpacked/sbin/init` contains device-path strings including `/dev/nflasha15` at file offset `0x2670`. Strings alone do not establish control flow.

## C++ runtime blocker

The previously unresolved `_ZTVN10__cxxabiv120__si_class_type_infoE` has candidate definitions in both copies of `libstdc++.so.6.0.14` and four executables, including `WS_SubProcess.elf`. Do not resolve it by loading an arbitrary executable as a library. The actual host executable and dynamic-loader scope must be established.

The two extracted `libstdc++` copies have identical SHA-256 hashes. They have `PT_TLS`, `R_ARM_TLS_DTPMOD32` and `R_ARM_TLS_DTPOFF32` relocations. A strict load experiment stops explicitly at `elf_tls` and leaves no loaded module. Report: `artifacts/execution/libstdcxx-strict.json`.

`WS_SubProcess.elf` also contains `R_ARM_COPY` relocations, which the bounded loader does not implement. Loading only the two UI libraries omits both the runtime dependency graph and possible executable symbol providers. Static provider matching is not proof of symbol binding, version compatibility, or application startup.

## Loader defect and correction

The previous implementation wrote only the resolved symbol address for `R_ARM_ABS32` and `R_ARM_GLOB_DAT`, discarding the implicit REL addend. The inventory found 22,286 ABS32 entries in `libObj.so` and 69,983 in `viewUnified2.so`, so this was material to the current workflow.

The bounded loader now preserves these addends, accounts for Thumb function state, and wraps results to ARM32. REL JUMP_SLOT retains its zero-addend treatment. It also maps the actual page-aligned PT_LOAD virtual span instead of assuming segments start at zero, preserves absolute symbols, rejects incompatible ELF inputs, and rolls back mapped memory/symbol registrations after a loading failure.

Reference for the formulas and REL JUMP_SLOT exception: [Arm ELF ABI, relocation table and dynamic relocations](https://github.com/ARM-software/abi-aa/blob/main/aaelf32/aaelf32.rst). The correction is not a complete dynamic-linker implementation. Tests use independently constructed ELF data and memory assertions; proprietary firmware is not a test fixture dependency.

## Artifact identities

Paths below are relative to `firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/`.

| Artifact | SHA-256 |
| --- | --- |
| `nflasha3_unpacked/vmlinux.bin` | `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707` |
| `nflasha7_unpacked/root/chassis` | `a30d9500a947338359a81af6abe1372ea1c6d6edcbe77c6a0d9a4d8b9821b8b7` |
| `nflasha15_unpacked/bin/network.sh` | `1c4f6e5efa247020e18aac30c373b22e6c43b702ffd35819cb59740e0ede0899` |
| `nflasha15_unpacked/bin/WS_SubProcess.elf` | `1827aa88c1871662609aaaa29bf4b372a5dfcb5ac18f5ef502eb12f287495c0f` |
| `nflasha15_unpacked/lib/libObj.so` | `60ffd2b0f31f4bc139a7c13a4f62c25cdeb6a531ad5ef35df48471e6e36e88b1` |
| `nflasha15_unpacked/lib/viewUnified2.so` | `1e2867b6bff2d4fd4d3b93bacf8c7da0b9a86f266b4ba1763230e33badb6e7f2` |
| `nflasha7_unpacked/lib/libstdc++.so.6.0.14` | `aee778e0f0d6a4dc6031d3e50940ff831a4222d9efa438fcdd28599e07e75918` |

## Next experiments and remaining limits

1. Trace `init` and the caller of `network.sh`; identify the process that loads the UI libraries via direct references or `dlopen` paths. Do not assume the network launcher is the primary UI host.
2. Reconstruct guest loader search paths, symlink aliases and versioned symbol scope. Inventory dependency candidates across rootfs, initrd and `/usr` separately; duplicate SONAMEs are not automatically interchangeable.
3. Choose a bounded original-process startup experiment using the matching guest interpreter, rather than manually invoking factories with synthesized C++ state. Assess a user-mode research experiment separately from full-system emulation.
4. Audit startup requirements for kernel/device interaction, TLS, COPY relocations, initialization order, and IPC. These remain unimplemented in the harness.
5. Continue hardware/platform identification before selecting a full-system backend. Actual CPU model, physical memory map, interrupt controller, and display device contract remain unknown.

No kernel, interpreter, or original UI was booted during this investigation. No camera operations were performed.
