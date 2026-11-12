# E0415 — nflashaB0 EXBL loader decode, nflasha3 boot-set unpack and full-emulation roadmap

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch
and no write to any firmware image. Inputs are the E0414 read-only dumps
(`artifacts/dumps/a6400-nflasha-readonly/`), the preserved a6400 firmware extraction and
the local legacy tools. Labels: **[C]** = confirmed from our artifacts, **[I]** = inference.

## 0. Short answer

1. **`nflashaB0` is the missing a6400 first-stage loader.** The partition begins with a
   0x200-byte **EXBL container** (magic `0x4C425845` = `EXBL`, seven 0x40-byte segment
   records). pformat.elf from the updater writes exactly this block; the decoded field
   table (from pformat's `.data` key table at vaddr `0x118d8`) maps `start/size/verstr/
   load/entry/awake_*/bp_*` into the record. The live image has six used records whose
   `load` is uniformly `0xFE040000 + start*512`, a total extent of `0x2C000` bytes, and
   entry `0xFE047000` (ARM reset vector). **[C]**
2. **The loader payload is a Sony "DGU5" boot loader** (`V85.00.03`,
   `(C)2016 Sony Corp. DIG/PD/SD-2`, `Astra LPDDR3 Initialize Ver.40.00.01`) with DRAM
   training, eMMC/FAT access, `INS:awake_cmd0`, `LBK` backup load, boot-mode evaluation
   (`0x0051000F` literal, `BOM:<<BootMode:`, `\updater\mode`) and `LDR` app-boot strings
   (`\ldr_drv.bin`, `\dfe_app.bin`, `\dfe_dat.bin`, `\lif_app.bin`). **[C]** for presence
   and strings, **[I]** for the exact boot flow. E0413's "loader not preserved" is now
   closed read-only.
3. **`nflasha3` is the main boot set**: FAT12 with raw ARM kernel `vmlinux.bin`
   (4,085,888 B) + ext2 `initrd.img` (2,184,192 B) plus 11 camera payloads. Ten of the
   thirteen files are byte-identical to the preserved package extraction; kernel, initrd
   and `av-cam.bin` are **not** (live build is Sony CE Linux **8.2.6.0**/2021, the package
   is **8.2.5.7**/2017). Use the live dump for current-state emulation. **[C]**
4. **Kernel layout is pinned**: physical load `0x00108000`, page offset
   `0x60000000` → virtual base `0x60108000`; live kallsyms decode gives `_stext =
   0x60108160`, `linux_banner = 0x603C8028` (= base + file `0x2C0028`), `_etext =
   0x6048D024` (matches `/proc/iomem` `Kernel text` end `0x0048D023`). **[C]**
5. New read-only tooling: `exbl_image.py` (EXBL parser), `nflasha_boot_set.py` (boot-set
   unpack), `kernel_backing.py` (live-kernel Unicorn backing + kallsyms), and
   `exbl_boot_harness.py` (bounded Unicorn run with MMIO/boot-param tracing). The loader
   executes in Unicorn: strict policy stops at its first MMIO write
   (`0xFE04733C → 0xF800000C = 0xFFFF`); opt-in `observe-zero` collects the register map
   (1 M instructions: 126,326 reads / 4,323 writes / 4,303 distinct addresses), including
   PL011 UART0 programming at `0xF2000024/0x28/0x2C/0x30`. The boot-parameter block at
   `0x00103000` is **not** written in the observed prefix. **[C]** for the trace, no boot
   claim.
6. The QEMU/Unicorn full-emulation plan is in section 7. The immediate next physical-free
   gates are: recover the machine ID/ATAGS contract used by the loader, then boot the
   **nflasha1 updater set** (`zImage` + cramfs + `console=ttyAM0`) in a minimal machine to
   reach a real `/bin/ash` before touching the main boot set.

## 1. Inputs and identities

| input | identity |
| --- | --- |
| `nflashaB0-4194304.bin` | 4,194,304 B, SHA-256 `3db81064…f4d260` (E0414) |
| `nflasha1-8323072.bin` | 8,323,072 B, SHA-256 `b264e1e6…15451f` (E0414/E0306) |
| `nflasha3-50331648.bin` | 50,331,648 B, SHA-256 `cd4178d4…0719a6` (E0414) |
| `nflasha3_unpacked/` (package) | main kernel SHA-256 `12eeec82…963707`, initrd `15803c2d…3a13e83` (E0413) — **not** the live build |
| `updater.img_unpacked/bin/pformat.elf` | 8,072 B, updater partition-format tool |
| live kernel symbols | decoded from the live `vmlinux.bin` (24,600 symbols) |

`pformat.elf` is an ARM EABI dynamic executable (entry `0x884D`, `.text`
`0x884C..0x90F8`). Its `.data` vaddr `0x118d8` is a 16-byte-entry key table that the
config parser (`0x8B1C`) walks: the writer `0x8D48` memsets a **0x200-byte block**, stores
the magic, opens `pformat_config.txt`, parses up to **seven 0x40-byte records**
(`(section+1)<<6`) plus a **7 × 0x24-byte** `file_param` array. [C]

## 2. EXBL container decode (nflashaB0 offset 0)

### 2.1 Block and record layout

| offset | size | content |
| --- | --- | --- |
| `0x000` | 4 | magic `45 58 42 4C` (`EXBL`, LE word `0x4C425845`) |
| `0x004..0x03F` | 60 | zero |
| `0x040 + n*0x40` | 7 × `0x40` | segment records (`n = 0..6`; record 6 is empty on this image) |

Record fields, decoded from pformat's key table (key → record offset):

| key | offset | key | offset |
| --- | --- | --- | --- |
| `start` | `0x00` | `awake_start` | `0x28` |
| `size` | `0x04` | `awake_memaddr` | `0x2C` |
| `verstr` | `0x0C` | `awake_entry` | `0x30` |
| `load` | `0x10` | `awake_loadsize` | `0x34` |
| `entry` | `0x14` | `bp_entry` | `0x38` |
| `awake_cmd0disable` | `0x24` | `bp_loadsize` | `0x3C` |

### 2.2 Live records (all integers as observed) [C]

| n | start (sector) | size (sectors) | load | entry | awake_cmd0disable | awake_memaddr | awake_loadsize | bp_entry | bp_loadsize |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | `0x038` | `0x100` | `0xFE047000` | `0xFE047000` | 1 | `0xFE040000` | `0x27800` | `0xFE047000` | `0x27800` |
| 1 | `0x004` | `0x014` | `0xFE040800` | `0xFE040800` | 0 | 0 | 0 | 0 | 0 |
| 2 | `0x018` | `0x020` | `0xFE043000` | 0 | 0 | 0 | 0 | 0 | 0 |
| 3 | `0x13C` | `0x004` | `0xFE067800` | `0xFE067800` | 0 | 0 | 0 | 0 | 0 |
| 4 | `0x140` | `0x020` | `0xFE068000` | 0 | 0 | 0 | 0 | 0 | 0 |
| 5 | `0x138` | `0x004` | `0xFE067000` | 0 | 0 | 0 | 0 | 0 | 0 |
| 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

* `start`/`size` are in 512-byte sectors: `load = 0xFE040000 + start*512` holds for
  **6/6** records (`mapping_consistent = true`).
* Total extent `max((start+size))*512 = 0x2C000` (180,224 B); payload sum 178,176 B; the
  image's non-zero data ends at `0x272EB`, the rest is zero padding. [C]
* Entry `0xFE047000` is the ARM reset vector table: `b 0xFE047058`; at `0xFE047058`
  `ldr r0,[pc,#0x54]` loads the stack literal, `mov sp,r0`, then calls into the image.
  The literal is `0xFE0F0000`, i.e. the stack top is inside the inferred SRAM window. [C]

### 2.3 Loader identity and boot-contract strings [C]

| image offset | load address | string |
| --- | --- | --- |
| `0x15530` | `0xFE055530` | `(C)2016 Sony Corp. DIG/PD/SD-2` |
| `0x15550` | `0xFE055550` | `V85.00.03` |
| `0x1555C` | `0xFE05555C` | `Astra` (`DGU5 for …`, `Astra LPDDR3 Initialize Ver.40.00.01`) |
| `0x8E28` | `0xFE048E28` | u32 literal `0x0051000F` (backup boot-mode record, E0413) |
| `0x8E34` | `0xFE048E34` | `BOM:<<BootMode: %u: %s>>` |
| `0x8E60` | `0xFE048E60` | `fat_mount` |
| `0x8E7C` | `0xFE048E7C` | `\updater\mode` (updater marker path, backslash form) |
| `0xCE18` | `0xFE04CE18` | `INS:awake_cmd0:%s(%d)` / `INS_E:awake_cmd0:Unknown` |
| `0xD2D0` | `0xFE04D2D0` | `LBK:[START]load Backup.bin/.bak ROM` (+ `\Backup.bak`, `\Backup.bin`) |
| `0xD724` | `0xFE04D724` | `LDR:Copy MIS param @0x%08X -> @0x%08X` |
| `0xD800` | `0xFE04D800` | `LDR:MODEREAD :0x%08X` |
| `0xDCF8` | `0xFE04DCF8` | `\ldr_drv.bin`, `\wole_app.bin`, `\bt_firm.hcd`, `\dfe_app.bin`, `\dfe_dat.bin`, `\lif_app.bin` |

The seven `awake_*`/`bp_*` names are **not** literal strings inside the B0 payload: they
are pformat.elf config keys that address EXBL record fields (§2.1). The payload contains
the `INS:awake_cmd0` handler strings instead. [C]

**Correction to E0414:** E0414 described the `EXBL` bytes at image offset `0xCDE0` as "a
second EXBL record". With the pformat decode that reading is superseded: the container has
exactly one 0x200-byte block at offset 0, and `0xCDE0` lies inside loader segment 0
(`0x38..0x138` sectors, load `0xFE047000..`), where it is part of the loader's signature/
string data (`EXBL` literal at `0xFE04CDE0`, followed by `ins` strings). It is not a
second container header.

## 3. nflasha3 (main boot set) unpack

FAT12 tree (13 files, 2 directories; directory entries 15):

| file | bytes | SHA-256 (prefix) | vs package |
| --- | --- | --- | --- |
| `vmlinux.bin` | 4,085,888 | `d7a9ae09…618` | **differs** (live build) |
| `initrd.img` | 2,184,192 | `db95861f…673` | **differs** (package 3,963,904 B) |
| `av-cam.bin` | 16,803,048 | `dd8f8d0c…4b7` | **differs** (package 16,674,456 B) |
| `bonobo.bin` | 172,144 | `a9e739bc…431` | identical |
| `dfe_app.bin` | 1,956 | `8f9a8d3f…d95` | identical |
| `dfe_dat.bin` | 65,536 | `703f457a…e74` | identical |
| `ldr_drv.bin` | 6,796 | `d5cec378…f49` | identical |
| `lif_app.bin` | 6,716 | `5e1ebaa1…e32` | identical |
| `lensbin_lensproperty/LensAberrationData.bin` | 161,766 | `40d17dbb…031` | identical |
| `sabin/idt_cam.bin` | 176,528 | `d21e2c0b…f9f` | identical |
| `sabin/sa_dfdet.bin` | 156,292 | `356d7483…a08` | identical |
| `sabin/ssboot.bin` | 11,280 | `a707c285…684` | identical |
| `sabin/ssboot_any.bin` | 9,648 | `a018e887…ce7` | identical |

Identity notes: the live kernel contains
`Linux version 3.0.27_nl-rt106+ … (gcc version 4.5.1 (20181205 (Sony CE Linux 8.2.6.0)) ) …
Tue Aug 10 13:03:39 JST 2021` at file offset `0x2C0028`; the package kernel banner is
`… 20170415 (Sony CE Linux 8.2.5.7) …`. Both are 4,085,888 B with the banner at the same
offset and 121/998 4 KiB chunks byte-identical (117 of them non-zero), consistent with an
in-place rebuild of the same layout rather than a different kernel family. The live dump
is therefore the authoritative input for the current camera; the package extraction stays
as a cross-check only. [C] for hashes, [I] for the rebuild explanation.

Formats: `vmlinux.bin` is a **raw ARM kernel image** (`msr cpsr_c, #0xd3` at offset 0,
`Linux version` at `0x2C0028`); `initrd.img` is **ext2** (magic `53 EF` at `0x438`).
nflasha1: `boot/vmlinux.bin` (1,697,068 B) is an **ARM zImage** (`0x016F2818` at `+0x24`,
gzip at `0x3F8F`), `boot/initrd.img` (4,354,048 B) is **cramfs**, and
`boot/loadaddr.txt` parses to `{kernel_load: 0x00108000, initrd_load: 0x00700000,
boot_params: 0x00103000}`. [C]

## 4. Kernel layout and symbol backing [C]

| fact | value | source |
| --- | --- | --- |
| physical load | `0x00108000` | `loadaddr.txt`, `/proc/iomem` `Kernel text 0x00108000-0x0048D023` |
| page offset | `0x60000000` | live kallsyms addresses `0x60xxxxxx` |
| virtual base | `0x60108000` | `_stext - 0x160 = 0x60108000` === base + file 0 |
| `_stext` | `0x60108160` | live kallsyms |
| `_etext` | `0x6048D024` | live kallsyms (matches `0x0048D023` phys end) |
| `linux_banner` | `0x603C8028` | live kallsyms; equals base + file offset `0x2C0028` |
| initrd load | `0x00700000` | `initrd=0x700000,8M` (live cmdline) |
| boot params | `0x00103000` | `loadaddr.txt` third field |
| symbols | 24,600 | kallsyms decode of the live image |
| `usb_gadgetcore_register_driver` | `0x602B8610` | live kallsyms |
| E0405ab `make_device_desc` `0x602BB988` | resolves exactly to symbol `make_device_desc` | live kallsyms |

`KernelBacking` maps the live image at `0x60108000` (text `R+X` up to `_etext`, data
`R+W`), resolves symbols, verifies `linux_banner` against the file offset, and is ready to
back E0405ab/E0407b-1 kernel-module tests with the real kernel text/data layout instead of
a placeholder. [C] for the mapping; using it as a booted kernel is **not** claimed.

## 5. Unicorn early-boot harness (nflashaB0)

`ExblBootHarness` loads the six EXBL segments from the hash-checked dump at their load
addresses, maps the inferred SRAM window `0xFE000000..0xFE100000` and the low-RAM window
`0x00000000..0x01000000`, and runs from `0xFE047000`. MMIO windows
(`0xF0000000..0xFDFFFFFF`, `0xFE100000..0xFFFFFFFF`) are always mapped zero-backed so
accesses reach logging hooks; the policy decides whether the first access stops the run
(`stop`, fail-closed) or is observed and execution continues (`observe-zero`, explicitly
labelled unmodelled observation). The boot-parameter window `0x00103000..0x00104000` is
hooked read/write. [C]

| run | result |
| --- | --- |
| strict `stop` | stops at first MMIO write: PC `0xFE04733C` → `0xF800000C = 0xFFFF`; then a read of `0xF8000000` would follow; UART untouched before that |
| `observe-zero`, 1 M instructions | 126,326 MMIO reads / 4,323 writes / 4,303 distinct addresses; stop = instruction limit in a polling loop; 0 boot-parameter accesses |
| UART0 register programming | `0xF2000024 = 0x1A` (IBRD), `0xF2000028 = 3` (FBRD), `0xF200002C = 0x70` (LCR_H, 8N1/FIFO), `0xF2000030 = 0x701` (CR: UARTEN, TXE, RXE); polling reads on `0xF2000000` (DR, 21,045) and `0xF2000018` (FR, 42,090) |
| clock/reset + PHY writes | `0xF8000000/0xC`, `0xF2403100/0x104`, `0xF2910004/0x28/0x44`, `0xF2910238`, `0xF2912204` (PLL/PHY/DDR related) |
| boot contract | static references: `0x0051000F` @ `0x8E28`, `BOM:<<BootMode:` @ `0x8E34`, `\updater\mode` @ `0x8E7C`, `fat_mount` @ `0x8E60` |

Boundaries: MMIO reads are zero-filled by policy (no hardware state modelled), the SRAM
window is inferred from the stack literal/image end, the loader does not reach the kernel
handoff or the `0x00103000` parameter block in the observed prefix, and no boot is claimed.

## 6. Full-emulation architecture

Observed hardware facts used by the architecture (all [C] unless noted):

| component | evidence |
| --- | --- |
| kernel | Linux 3.0.27 `3.0.27_nl-rt106+`, ARMv7, SMP 4 CPUs, PREEMPT RT |
| RAM | `/proc/iomem` `System RAM 0x00000000-0x3FFFFFFF` (1 GiB) and `0x80000000-0x8FFFFFFF`; cmdline `mem=1G@0 … mem=256M@0x80000000@1` plus reserved regions |
| interrupt controller | `/proc/interrupts` `GIC`, 4 CPUs; kernel `arch/arm/common/gic.c` |
| UART | `AMBA/PL011`, `pl011_init`, `cxd900x0-uart`, `ttyAM`; UART0 `0xf2000000`, UART3 `0xf2003000`; `console=ttyAM0,115200n8` (updater) |
| timer | `arch/arm/mach-cxd900x0/hwtimer.c`, `cxd4115_clocksource_init`, `cxd4105-freerun-timer`, watchdog `wdt.c` |
| board | machine name string `ARM-CXD900X0`, `arch/arm/mach-cxd900x0/{mmap,cpuid,wdt,pcie,pcie_ctl,hwtimer,bam}.c`, `cxd900x0_init` registers `amba_device` UARTs and the BAM platform device |
| eMMC/flash | `emmc.ko` (HS200), partitions `nflasha*` 252:0; MPR `nflasha4`; boot area `nflashaB0/B1` |
| SD | `mmc_drv`/`mcmn_drv`/`ms_drv`, SDH30/MMCP, `mmca10` 250:10 |
| USB | dwc3 `0xf0200000`, gadget modules usbg_*; MSC = 054C:0CA8 |
| CPU core model | kernel's proc_info table contains `0x410FC050` (A5), `0x410FC090` (A9), `0x410FC0F0` (A15); which one CXD90045 uses is **not directly measured** [I] — recover from the machine/loader before fixing a QEMU `-cpu` |
| machine ID | not yet recovered [I]: needed as ATAGS `r1`; recover from the `machine_desc` table (name reference found at file offset `0x3A85F8`, near the kernel ATAGS tag table) or from the loader's ATAGS builder |

### 6.1 Layered plan

| layer | scope | status |
| --- | --- | --- |
| L0 static inputs | EXBL loader, live kernel+symbols, initrd, boot sets, identities | **done (this record)** |
| L1 loader harness | Unicorn EXBL execution with MMIO/boot-contract tracing | **done (bounded, zero-backed MMIO)** |
| L2 updater boot | QEMU boot of nflasha1 `zImage` + cramfs initrd → `/bin/ash` on PL011 | next; needs machine model |
| L3 main boot | nflasha3 raw kernel at `0x00108000` + ext2 initrd at `0x00700000`, ATAGS at `0x00103000`; custom driver stubs; `/sbin/init` | after L2 |
| L4 full system | eMMC/SD/USB/DMA/display contracts, `/usr` modules, `im.elf` application | after L3 |

### 6.2 QEMU bring-up plan (L2)

1. **Recover the machine contract** [I→C]: find the `machine_desc` entry for
   `ARM-CXD900X0` (`.nr`) and the `struct tag` ATAGS layout the loader produces at
   `0x00103000`; the loader's `LDR:Copy MIS param`/ATAGS builder code is in the EXBL
   image. This gives QEMU's `-machine` id and the exact `r1`/`r2` boot register contract.
2. **Minimal machine model** (`hw/arm/cxd900x0.c` or a Unicorn equivalent):
   1 GiB RAM at `0x00000000` + 256 MiB at `0x80000000` with the reserved-memory holes from
   `/proc/iomem`; GIC (base recovered from `mach-cxd900x0` init code, not guessed);
   PL011 at `0xF2000000` (and `0xF2003000`) with `console=ttyAM0,115200n8`; one simple
   periodic clocksource stub instead of modelling the custom `hwtimer` first; a watchdog
   stub that never fires.
3. **Boot the updater set** (`-kernel nflasha1 boot/vmlinux.bin` is a zImage; pass the
   cramfs initramfs; cmdline from `boot/kemco.txt`). Validate: kernel banner on PL011,
   `sbin/init` reaches the busybox shell (`/bin/ash --login` loop unless
   `/root/IAMLDUDWRT`), no unmodelled register touch without a label.
4. **Then main boot set**: boot the raw kernel with our ATAGS builder + ext2 initrd; add
   the custom modules in dependency order: `devno` → `dmac`/`ldec`/`emmc` (flash) →
   `mmc_drv`/`ms_drv` → `osal_uipc`/`osal_utm` → display/USB services; stub `upm` (boot
   mode consumer), `grm_gles`/`dmm` (graphics), `dfe`/`lif`/`ldr_drv` (camera assist
   blobs loaded by the loader strings above) with explicit "unmodelled device" markers.
5. **Fidelity gates**: original code owns behaviour; each served MMIO/register must be
   labelled observed/stub; stop on unmodelled register instead of returning zeros; no host
   navigation/rendering decisions; keep the read-only dumps as the byte source.

### 6.3 Open inputs / risks

* machine ID + ATAGS layout (must be recovered before any QEMU boot attempt);
* GIC base and the custom timer/watchdog register maps (static decode from
  `mach-cxd900x0` code);
* eMMC protocol (custom `emmc.ko`), `ldec`/`dmac`/`dma330` DMA, BAM — sequential modelling;
* efuse/MIS/ASV reads (`LDR:ASV val`, `LDR:read MISCREG`, `LDR:EFUSE_*`) that the loader
  expects before it can hand off;
* the live `/system` differs from the preserved package for three files: use live dump,
  keep package only as cross-reference.

## 7. Artifacts and checks

* Dumps: `artifacts/dumps/a6400-nflasha-readonly/` (E0414).
* Analysis: `artifacts/analysis/e0415-nflasha-boot/` (`b0-probe.txt`,
  `boot-set-unpack.json`, `pformat-annotated.txt`, `b0-shape`, `live-vmlinux.bin`,
  `live-kallsyms.json`, `exbl-boot-stop.json`, `exbl-boot-observe-zero.json`,
  `full-suite.log`).
* Code: `src/a6400/execution/{exbl_image,nflasha_boot_set,kernel_backing,exbl_boot_harness}.py`;
  runner `tools/research/run_exbl_boot_trace.py`.
* Tests: `tests/test_exbl_image.py`, `tests/test_nflasha_boot_set.py`,
  `tests/test_kernel_backing.py`, `tests/emulator/test_exbl_b0_boot.py` (30 tests total;
  dump-dependent cases skip when the E0414 dumps are absent).
* Full suite: **1436 tests OK** (23.4 s, `python -m unittest discover -s tests -q`),
  log `artifacts/analysis/e0415-nflasha-boot/full-suite.log`. The documented status card
  (`docs/images/research-status.svg`, README status snapshot) was regenerated and pinned
  to E0415 / 1436 tests.

## 8. Next

1. Recover the machine ID + ATAGS contract from the EXBL loader (static, offline).
2. Build the minimal machine model and boot the updater set (L2) to a real shell.
3. Only then attempt the main boot set (L3); keep the loader harness as the L1 oracle and
   the live kernel backing for module-level tests.
