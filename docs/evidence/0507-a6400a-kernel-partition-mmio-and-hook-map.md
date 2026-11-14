# E0507 - a6400A kernel, partition, MMIO and emulator-hook map

Date: 2026-11-13. **Offline preserved Sony packages only. No camera access.**
Continues [E0506](0506-a6400a-offline-qualification-and-debugger-boundary.md).
The a6400A is the subject; the existing original-a6400 package is a comparison
input, not a requirement to own or operate an original camera.

## Result and provenance boundary

PR integration note (2026-11-14): the a6400A records were renumbered after
upstream allocated their original IDs. Local receipt directories and the
original observations below are unchanged.

The package-side machine map is now reproducible with
[`bionzx_machine_map`](../../tools/research/bionzx_machine_map.py).
It separates main and updater kernels, records complete local symbol tables,
compares partition/mount configuration and instruction-backed MMIO mappings,
identifies userspace versions, and replays a bounded updater prefix without old
kernel hooks. It never mounts an image or contacts a camera.

**Still not available:** live `/proc/version`, `/proc/partitions`,
`/proc/kallsyms`, `/proc/cmdline`, `/proc/iomem`, actual ATAGS/DTB bytes,
the owner's `/setting` inventory, or physical a6400A partition dumps.
Package configuration is not presented as any of those observations. No
first-class runnable-machine or full-boot claim is made.

## 1. Exact kernel identities

Input package identity is E0506's signed Sony 1.01 download:
`fd6ae50755a9202a8b506b6b77aa27ab41ae717e96f05a0d4e2ad699b40d9ad1`.

| Image | Kernel release / build | Raw kernel SHA-256 |
| --- | --- | --- |
| Original a6400 package main | `3.0.27_nl-rt106+`, Sony CE Linux `8.2.5.7`, `#1 SMP PREEMPT RT`, 2019-05-27 14:09:40 JST | `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707` |
| a6400A 1.01 main | `3.0.27_nl-rt106+`, Sony CE Linux `8.2.7.6`, `#1 SMP PREEMPT RT`, 2026-04-10 15:09:44 JST | `9d51ab60df8246f10cb2afb12fb504d7f148fae437ee404f5b9837cc3b8f85ca` |
| a6400A 1.01 updater, decompressed | `3.0.27_nl-rt106` (**no `+`**), Sony CE Linux `8.2.6.0`, `#2 SMP PREEMPT RT`, 2025-12-25 17:17:03 JST | `0616ca7036567c9e6c1869fe47ece2debeebaecacad550aabbb3055d308cacd8` |

The complete banner strings, compiler tags and decoded symbols are retained
locally. Symbol **records** and unique symbol **names** are separate counts:
the main a6400A has 24,514 records / 24,351 unique names; the original main image
has 24,600 records / 24,421 unique names. These do not identify the live body.
The original updater capture is absent here and is not substituted with a
different image.

All three machine descriptors identify `ARM-CXD900X0`, machine ID `0xDA9`.
Kernel linear-layout verification uses physical `0x00108000`, virtual
`0x60108000`, and page offset `0x60000000`; the actual banner pointer and text
range are checked against each image, not copied from the original profile.

## 2. Partition layout: package configuration, not /proc

The two packages' **30** `partinf.conf` rows and **30** `mount.conf` rows are
equal. Representative configured extents:

| Device | Configured start | Configured bytes | Role / configured mount |
| --- | --- | --- | --- |
| `nflasha1` | `0x00010000` | 8,323,072 | updater, no ordinary mount |
| `nflasha2` | `0x00800000` | 20,971,520 | `/setting`, vfat |
| `nflasha3` | `0x01C00000` | 50,331,648 | `/system`, vfat |
| `nflasha4` | `0x04C00000` | 12,582,912 | MPR/raw, no ordinary mount |
| `nflasha5` | `0x05800000` | 62,914,560 | `/wbi` |
| `nflasha7` | `0x0A400000` | 8,388,608 | `/rootfs` |
| `nflasha10` | `0x0AC00000` | 12,582,912 | `/tmp`, vfat |
| `nflasha11` | `0x0B800000` | 524,288,000 | `/log`, vfat |
| `nflasha15` | `0x2D800000` | 314,572,800 | `/usr` |
| `nflasha23` | `0x50800000` | 2,097,152 | `/PMBP` |

The full machine-map JSON contains every row, including reserved zero-size
slots. It checks matching configuration sizes, unique labels and nonoverlapping
occupied extents. It does **not** infer runtime device nodes, major/minor
assignments, boot-area exposure, free space or mount success.

**Do not mistake update payloads for full partition dumps.** The a6400A package's
`nflasha3`, `nflasha7`, `nflasha15` files are respectively **29,492,224**,
**5,103,616**, **217,424,896** bytes, smaller than the configured partition
capacities. No omitted bytes are padded or invented. The latter two contain ext2
images; the tool leaves an unrecognized header explicitly unknown rather than
guessing the former image's filesystem.

Configuration hashes:

- `mount.conf`: `0ef2d463b13cb23995f83080e6189da9e1287566d0645f5b41d5c8da14fd8acd`.
- `partinf.conf`: `fc23dc2edb8e378e7985fb5da4d09a0e4c5f2445d679a730fd1d544dde831f78`.

## 3. Boot parameters and userspace

The packaged main `setting/kemco.txt` is byte-identical across the two packages:
1,655 bytes, SHA-256
`5f9573148e6dc71d9ddf8f64de1311e6241a411eaba110288ae83f5cc02d50ca`.
Its declared banks are **1 GiB at 0** and **256 MiB at `0x80000000`**, with
the same reservation records, `rootfstype=ext2`, `init=/sbin/init`,
`console=ttynull` and main klog base `0x035A5000`.

The **a6400A updater** instead declares 1 GiB at 0 plus **1016 MiB** at
`0x80000000`, `console=ttyAM0,115200n8`, klog base `0x034A0000`, and a cramfs
initrd. Its own `loadaddr.txt` supplies kernel/initrd/boot-parameter addresses
`0x00108000`, `0x00700000`, `0x00103000`.
Do not mix main and updater bank declarations or log addresses.

ATAGS in the report are **reconstructed** standard tags, not captured loader
bytes. The prefix uses the existing Sony `kemco` text reconstruction; the run
does not reach and verify `setup_arch` parsing. No `.dtb` file was found in the
supplied a6400A package; that is not proof of no DTB in a live boot.
No embedded `IKCFG_ST` configuration anchor was found in the analyzed kernels.

| Rootfs | BusyBox banner | libc / loader |
| --- | --- | --- |
| Original package main | `1.13.4`, built 2017-04-15 | glibc `2.11.2`, `ld-2.11.2.so` |
| a6400A package main | **`1.34.1`**, built 2024-03-18 | glibc **`2.11.2`**, different binary hashes |
| a6400A package updater | **`1.29.3`**, built 2018-12-07 | glibc **`2.11.2`**, its own binary hashes |

The component files are ELF32 little-endian ARM EABI5. Exact sizes, hashes,
entry points and version strings are in the report; no guest executable was
invoked as a host process.

Only the **packaged** setting names were inventoried: `appfw_infra/`,
`DmmConfig.bin`, `facedmy.bin`, `kemco.txt`, `ulogio.bin`. This is not a dump of
the owner's settings, calibration, backup data or personal files.

## 4. MMIO: recovered subset agrees, not a blanket hardware claim

Original ARM instructions in `cxd900x0_map_io` supply the table pointer and count
to `iotable_init`; all **eight** descriptors match across original main,
a6400A main and a6400A updater:

| Kernel virtual | Physical | Length |
| --- | --- | --- |
| `0xF0000000` | `0xF0000000` | `0x05000000` |
| `0xF5000000` | `0xF5000000` | `0x00100000` |
| `0xF6000000` | `0xF6000000` | `0x00100000` |
| `0xF8000000` | `0xF8000000` | `0x00100000` |
| `0xF9000000` | `0xF9000000` | `0x00100000` |
| `0xFA000000` | `0xFA000000` | `0x04000000` |
| **`0xF8800000`** | **`0xBF800000`** | `0x00100000` |
| **`0xF8C00000`** | **`0xBFC00000`** | `0x00100000` |

The final two are **not identity mappings**. The map code overwrites the stored
type fields before the call, so zero-valued on-disk type words are not reported
as final memory attributes.

The `gic_init` argument setup independently resolves distributor
**`0xF8001000`**, CPU interface **`0xF8000100`**, and IRQ base **29** on all
three images. A PC-relative load in `ext_timer_setup` resolves a context whose
base field at `+8` is **`0xF2403000`** on all three.
The a6400A updater prefix directly accesses UART **`0xF2000000`**.
Other blocks/register semantics remain unqualified; no broad MMIO scan or
zero-success reply is used.

## 5. Concrete per-build hook hazards

| Site | Original package main | a6400A main | a6400A updater |
| --- | --- | --- | --- |
| `ret_to_user` | `0x6010DF34` | same | same |
| SPSR restore / final return | `0x6010DF50` / `0x6010DF64` | same opcodes | same opcodes |
| DFSR read | `0x60119C44` | **`0x60119DE4`** | **`0x60119DE4`** |
| DFAR read | `0x60119C48` | **`0x60119DE8`** | **`0x60119DE8`** |
| IFAR read | `0x60119C60` | **`0x60119E00`** | **`0x60119E00`** |
| IFSR read | `0x60119C64` | **`0x60119E04`** | **`0x60119E04`** |
| `cpu_v7_switch_mm` | `0x6011A36C` | **`0x6011A50C`** | **`0x6011A50C`** |
| `do_page_fault` | `0x60116D94` | **`0x60116D24`** | `0x60116D94` |
| return after `handle_mm_fault` call | `0x60116E9C` | **`0x60116E2C`** | `0x60116E9C` |

The existing machine's **old updater** literals are yet another baseline:
DFSR/DFAR `0x60119B44/48`, IFAR/IFSR `0x60119B60/64`, switch-mm fallback
`0x6011A26C`. They must not be used on the a6400A. Equal Linux release text
is not an address/layout contract.

The 13-word main `ret_to_user` window differs only in its first BL's target
encoding; the SPSR and final-return opcodes match. That does not establish
correct banked-state, frame, scheduler or TLB behavior on this kernel.

The existing TTBR0 scanner also produces an apparent Thumb candidate two bytes
before an ARM MCR in each analyzed kernel. These are therefore recorded as
**opcode candidates**, not all promoted to executable sites. A runtime profile
must verify instruction mode and context before installing hooks.
`swapper_pg_dir` is not present by that name in these decoded symbol tables;
the walker cannot rely on its name or treat missing translations as success.

No old hooks were installed and no shared walker or legacy baseline was changed
in this step. Guest TTBR state, TTBCR split and `task_struct`/`mm_struct` offsets
still need per-image validation and real execution.

## 6. Offline execution and validation

The shared mapper replays the hash-identified a6400A updater using a Cortex-A9
**CPU fixture**, 32 MiB of explicitly zero-initialized RAM inside its declared
first bank, original kernel/initrd, and reconstructed entry registers.

- **Strict baseline:** 3,001 instructions, stop at the first unmapped UART write
  `0xF2000038`, matching E0506.
- **Explicit PL011 fixture:** only listed architected registers are serviced;
  unknown reads/writes stop, rather than returning zero. After including the
  architected error-clear write at `+4`, **3,017 instructions** execute, then an
  unsupported timer read at **`0xF2403100`**, PC **`0x0011FFDC`**, stops execution.
- **No code patch, inherited kernel hook, timer response, high-level camera
  behavior or host filesystem response. Zero serial bytes. No boot or shell.**
- Exit **2** denotes the preserved prefix boundary, not a passed boot test.
- Ten constructed-fixture tests cover geometry, nonlinear-call refusal, input
  identity/path boundaries, nonidentity MMIO, and strict UART behavior.
- Focused mapper/profile/boot-contract/virtual-TLB checks: **81 run, 4 skipped,
  no failures/errors**.

Earlier strict, UART-only and ECR-boundary receipts remain preserved; no failed
or shorter run was overwritten.

Final combined mapper/profile/boot-contract/TLB/documentation validation:
**133 run, 4 skipped, no failures or errors**. Eleven explicit real-input
assertions also verify the claimed table equalities, exact moved sites,
release-flavor distinction, unknown live fields and measured prefix boundary.

Full offline suite: **1,566 run, 2 failures, 13 errors, 71 skipped**. It is
not green: the failure cases exactly match E0506's unavailable historical
a6400/ZV-E10 dumps, compiled bridge/selector artifacts and tree/descriptor/overlay
receipts. Failure-stack source files still match the initial Git HEAD.
No new failure case was introduced or hidden; no identity guard or missing-input
test was weakened. The dashboard retains E0482's historical passing count, not
a new successful full-suite or a6400A compatibility claim.

## 7. Reproduce / receipts

From the repository root, against the preserved private inputs, choose a **new**
output directory:

```powershell
.\venv\Scripts\python.exe -m tools.research.bionzx_machine_map `
  --package-root .\firmware\extracted_a6400a_v101 `
  --kernel-sha256 9d51ab60df8246f10cb2afb12fb504d7f148fae437ee404f5b9837cc3b8f85ca `
  --reference-root .\firmware\extracted_a6400 `
  --reference-kernel-sha256 12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707 `
  --updater-sha256 c9040270ad886214c5656894b90fb1e839a3ab942cb65726633d8f1f1221c093 `
  --replay-prefix --pl011-base 0xF2000000 `
  --output-dir .\artifacts\analysis\e0484-a6400a-machine-map\NEW
```

Omit `--pl011-base` to get the strict unmapped-MMIO baseline; omit
`--replay-prefix` for static mapping only (exit 0). Expected hashes are required,
existing output directories are refused, and no camera imports are used.

Local receipts: `artifacts/analysis/e0484-a6400a-machine-map/`, including
`verified-final/machine-map.json`, complete per-image symbol JSON, source/tool hashes,
focused/full test logs and earlier bounded runs. Firmware and large raw outputs
stay ignored; no proprietary image is committed.

## 8. What would unblock captured-dump work

First qualify native read-only access on **this a6400A**, without bypassing the
E0506 driver guard or assuming a persistent installation is required. Service
mode, uploads, startup changes, driver replacement and any camera writes still
need separate reviewed scope; none is authorized or attempted by this report.

With qualified access, preserve bounded pre/post uptime and:

1. `/proc/version`, `/proc/cpuinfo`, `/proc/partitions`, `/proc/cmdline`,
   `/proc/iomem`, `/proc/modules`, `/proc/mounts`, `/proc/kallsyms`.
2. Read-only partition-node identities and exact sizes before selecting dumps.
3. Host-streamed `O_RDONLY`/`pread` dumps of the required boot/system partitions,
   initially `nflasha1`, `nflasha3`, `nflasha7`, `nflasha15`; full lengths, hashes
   and small sample rereads, with no silent padding and no SD destination.
4. Names/metadata for `/setting` first, not bulk calibration/settings contents.
   The updater package does not preserve the owner's `nflasha2`.

Do not sweep `/dev/mem`, force a mode change, fabricate `/proc` files from
configuration, or relabel package images as clean physical dumps.
Only identity-matched captures can promote this reference map to a live-backed
machine profile. That work does not require an original a6400 on the desk.
