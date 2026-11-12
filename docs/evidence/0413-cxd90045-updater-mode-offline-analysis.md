# E0413 — CXD90045 / CE Linux 8: updater-mode entry, CautionConfig crash and non-UI recovery (offline analysis)

Date: 2026-11-12. **Scope: strictly offline.** No camera was touched, no USB command was issued and no
partition was written. Inputs are the local ILCE-6400 (a6400, FW 2.00, CXD90045) firmware extraction,
the preserved read-only `/dev/nflasha1` and `/dev/nflasha2` dumps, and the local Sony-PMCA-RE checkout.
The external camera is an ILCE-6100 Ver.1.00 (JP). Both are CXD90045 / Sony CE Linux 8.2.x bodies, but
they are **not identical firmware**: a6400 and ILCE-6100 file sizes/offsets (including
`CautionConfig.so`) differ. Statements below are labelled **[C]** (confirmed from our artifacts) or
**[I]** (inference).

## 0. Short answer

1. **Updater boot is selected before Linux, by the loader, from the updater partition — [I] for the
   selection mechanism, [C] for the dual boot contract.**
   The a6400's updater partition `/dev/nflasha1` ("SYSTEM (Updater)", 7.9 MB vfat) contains a complete
   second boot set: `boot/vmlinux.bin` (1,697,068 B, ARM zImage), `boot/initrd.img` (4,354,048 B,
   **cramfs** updater userspace), `boot/kemco.txt` (its kernel cmdline), `boot/loadaddr.txt` (load
   addresses), `p1chksum` (MD5s of both images), `dat2`/`dat3` (model/region). The main boot set is in
   `/dev/nflasha3` (raw `vmlinux.bin` + ext2 `initrd.img`). **[C]** The code that chooses between them
   is the loader, which is not in the firmware update package or in any local dump; **[I]** that the
   loader reads the `/setting/updater/mode` marker. The preserved camera exposes `/dev/nflashaB0/B1`
   nodes and a `[kalnflashaB0]` kernel thread, but no loader image was preserved.
2. **The app writes the updater request on the internal setting partition, not on SD.**
   The running app contains the `UDTR0604` updater-control strings: `rm -f /setting/updater/mode*`,
   create `/setting/updater/mode` (+`mode1`/`mode3`/`mode6`), run `ud_send_lsi.elf %d`, then
   `ud_reboot.elf`. The updater initramfs later reads `/setting/updater/mode1/2/3/5/6` to choose the
   update action, and the physical `/setting` dump shows the post-update cleanup state (`updater/comp`
   present, no `mode*`). **No `\updater\mode`-on-SD trigger exists anywhere in our a6400 dump.**
3. **The loader→Linux boot-mode contract is a backup-memory record, 0x51000F.** `upm.ko` reads it with
   `Backup_read()` and exposes `/proc/udm/upm_bootmode`; its enum contains
   `LDR_BOOT_MODE_UPDATER` (3), `ADJUST` (5), `USB_CHARGE` (6), `BIS` (0x0C), etc. `bootin.elf`
   independently reads the same record and maps 5→`app_argv=adj`, 6→`app_argv=usbj`. This is the
   confirmed NVRAM/boot-flag interface; the *writer* (loader condition/key state) is missing.
4. **`CautionConfig.so` is a hard dynamic dependency of the UI view, not a lazy optional module.**
   `viewUnified2.so` has `DT_NEEDED = CautionConfig.so`. The a6400 local copy is 12,070,800 B; the
   reported 6100 truncation to 1,280,848 B (0x138B50) cuts it inside `.dynsym`, before `.dynstr`,
   `.text`, `.rodata` and `.data`, while its first `PT_LOAD` declares 10,871,440 B of file data.
   `dlopen("viewUnified2.so")` therefore cannot succeed at UI start. **[C]** for the local layout;
   the equivalent 6100 failure is **[I]** but the ELF arithmetic is unambiguous.
5. **`CautionConfig.so` is loaded at UI/view start, not at a specific key.** MENU-hold stopping the loop
   is best explained by the loader selecting a non-NORMAL boot mode (ADJUST/USB_CHARGE/BIS family) or by
   the UI event path being held before the unified view is constructed; both are **[I]** — our dump has
   no loader key map. **No secondary key combination in the preserved code brings up the USB gadget
   from a dead/halted app.** The updater/MSC/PTP gadget is a separate boot (updater ramfs) or an
   app-managed service that is not running in the crash state.
6. **Recovery through the updater ramfs is technically feasible but needs an updater boot trigger that
   we cannot prove from this dump.** The updater ramfs contains busybox, `mount`, `/dev/mmca1` (250:11),
   `/dev/nflasha15` (252:15) and a password-less `/bin/ash --login` loop unless `/root/IAMLDUDWRT`
   exists. vfat is proven by use; ext2 for `/usr` is not exercised by updater scripts **[I]**.
7. **Serial: 115200 8N1 is confirmed by both kernel cmdlines.** Normal boot uses `console=ttynull`
   (silent); updater boot uses `console=ttyAM0,115200n8` (serial console active). UART0/UART3 are at
   `0xf2000000`/`0xf2003000`. **No 1.8 V logic-level or boot-mode pad measurement exists in the local
   artifacts**; 1.8 V is common for this SoC but remains **[I]**.

## 1. Inputs, identities and boundaries

| input | identity | use |
| --- | --- | --- |
| a6400 firmware package | `firmware/extracted_a6400/` (FW 2.00, model 0x81030011, crypter `CXD90045`) | app/updater userspace, partition images |
| physical `/dev/nflasha1` dump | 8,323,072 B, SHA-256 `b264e1e61bde1808dbe4b14df834933040af6a48f90e89bb08338ca07515451f` | updater boot contract + updater cramfs |
| physical `/dev/nflasha2` dump | 20,971,520 B, SHA-256 `4d3269e51af1e48ac8af11775cf59ce111ff2cdd7cd9601911ac4f2f82c7f6fa` | runtime `/setting` marker state, `/setting/kemco.txt` |
| `firmware.tar_unpacked/.../nflasha3_unpacked/` | main `vmlinux.bin` SHA-256 `12eeec82…963707`, `initrd.img` `15803c2d…3a13e83` | normal boot set, `sbin/init` |
| `nflasha15_unpacked/` (app `/usr`) | `libObj.so`, `viewUnified2.so`, `CautionConfig.so`, `bootin.elf`, `launch_shell.elf`, `kmod/upm.ko` | UI, boot orchestration, loader-mode consumer |
| `updater.img` (a.k.a. `udtrbody.bin`) | 143,360 B cramfs, SHA-256 `09ee888c…c96f81` | updater "body" delivered into the updater ramfs |
| physical boot telemetry | `reports/a6400_hw_dump.txt` | `/proc/cmdline`, mounts, processes, UART devices |

Boundaries kept: no updater execution, no mount, no device write, no SD access, no host-side replay of
the loader. Derived listings are in
[`0413-updater-initramfs-tree.txt`](../../artifacts/analysis/0413-updater-initramfs-tree.txt),
[`0413-nflasha1-updater-boot-files.txt`](../../artifacts/analysis/0413-nflasha1-updater-boot-files.txt)
and [`0413-setting-updater-markers.txt`](../../artifacts/analysis/0413-setting-updater-markers.txt).

## 2. Boot layout and boot sets — [C]

Partition table (`0300_partconf/partinf.conf`; mount table `0100_config/mount.conf`):

| node | size | role |
| --- | --- | --- |
| `/dev/nflasha1` | 0x7F0000 (7.9 MB) | **SYSTEM (Updater)** — vfat; second boot set |
| `/dev/nflasha2` | 20 MB | **Setting** — `/setting` vfat; updater mode markers, `kemco.txt`, `Backup.bin` |
| `/dev/nflasha3` | 48 MB | **SYSTEM (Main)** — main `vmlinux.bin` + ext2 `initrd.img`, `sabin/`, `av-cam.bin` |
| `/dev/nflasha4` | 12 MB | MPR backup (raw) |
| `/dev/nflasha5` | 60 MB | Warm boot image (`wbi`) |
| `/dev/nflasha7` | 8 MB | Rootfs (ext2, static rootfs) |
| `/dev/nflasha15` | 300 MB | `/usr` (raw ext2) — contains `CautionConfig.so` |
| `/dev/nflashaB0/B1` | — | loader area (device nodes exist; **image not preserved**) |

Updater boot set on the physical `/dev/nflasha1` (`artifacts/hardware/nflasha1-readonly/`):

| file | value |
| --- | --- |
| `boot/vmlinux.bin` | 1,697,068 B, SHA-256 `7d61feae…079311f`, MD5 `dca40b71…`; zImage magic `0x016f2818` at +0x24 |
| `boot/initrd.img` | 4,354,048 B, SHA-256 `e6315bf0…a4f1845`, MD5 `bdceae53…`; **cramfs** (`45 3d cd 28`) |
| `boot/kemco.txt` | 816 B, SHA-256 `abcd32dc…e634210`; cmdline starts `kemco`; `console=ttyAM0,115200n8`, `xrstreq=0`, `wdt.mode=0` |
| `boot/loadaddr.txt` | 33 B, `0x00108000,0x00700000,0x00103000` |
| `p1chksum` | 105 B: MD5s of `./boot/vmlinux.bin` and `./boot/initrd.img` — both match actual file MD5s (covers only those two images, **not** `kemco.txt`/`loadaddr.txt`/`dat2`/`dat3`) |
| `dat2` / `dat3` | `11 00 03 81` / `00 00 00 00` (model / region) |

The updater cramfs holds 562 entries, including `/sbin/init` (shell script), `/bin/busybox`,
`/bin/ash`, `/bin/mount`, `/sbin/dosfsck`, `/sbin/mkdosfs`, all `ud_*` helpers, 154 device nodes
(`/dev/mmca1` 250:11, `/dev/nflasha15` 252:15, `/dev/nflasha1` 252:1, `/dev/nflasha2` 252:2,
`/dev/nflasha7` 252:7, `/dev/nflasha13` 252:13, `/dev/nflashaB0` 252:126), kernel modules under
`/usr/kmod`, `/root/IAMUPDATER`, `/version.txt` = `100.101.011`, `/root/chassis` = `CXD90045`.

Updater `/sbin/init` — [C]:

```
mount -t proc proc /proc
mount -t sysfs none /sys
mount -o rw,noatime,remount -t rootfs rootfs /
mkramdsk.sh            # tmpfs, 32 MiB, on /ramdsk
insmod.sh              # devno,dmac,ldec,emmc tbl=0x80000000,osal_utm,osal_uipc,
                       # utimer,stream,stream2,sio; mounts /dev/nflasha2 /setting vfat;
                       # backup.ko; osal_ulogio; dmm.ko; i2c; optional ca.ko
UdtrMain.sh &
while true; do
  if [ -f /root/IAMLDUDWRT ]; then read -p LOGIN: x; [ "$x" = xylitol5 ] && /bin/ash --login
  else /bin/ash --login; fi
  sleep 1
done
```

Because the physical updater image contains `/root/IAMUPDATER` but **not** `/root/IAMLDUDWRT`, this
image drops into a password-less root shell on the console. This is the most valuable recovery
property of the updater boot, and it is why the external user's "stock file on SD" plan only needs a
shell + mount capability, not a working UI.

Normal boot — [C]: `nflasha3/initrd.img_unpacked/sbin/init` (SHA-256 `0af5724e…`, unstripped) is a
single binary; there are **no `/etc/init.d`/`rcS` scripts** in the static images. It mounts `/proc`,
`/sys`, rootfs (`dnflasha7`→`nflasha7`), pivots, mounts `/usr`, `/system`, `/setting`, `/log` etc.,
checks mode files (section 3), then launches `/usr/bin/bootin.elf` and finally
`/usr/bin/launch_shell.elf`. Physical boot telemetry (`reports/a6400_hw_dump.txt`):

```
1  launch_shell.elf 0 1          <- init's execl args: ctrl-c=0, pvtroot_done=1
142 bootin.elf
149 im.elf debug s g r u l i a lazy-global
mount /dev/nflasha10 /etc vfat rw,sync,dirsync,noatime,...
```

`launch_shell.elf` is a supervisor: it opens `/dev/console` (or `/dev/ttycons` when ctrl-c is enabled),
disables echo, then `fork`/`setsid`/`execv("/bin/ash","--login")` and on child exit `wait4` →
`sleep 2` → respawn. `bootin.elf` is the multi-phase launcher that runs the `im.elf` phases
`s g r u`, `s g r u l` or `s g r u l i a` and finally the app.

## 3. Updater-mode / non-UI trigger inventory

### 3.1 Confirmed writer and consumers — [C]

Physical `/setting` (`nflasha2`) markers:

| path | meaning | evidence |
| --- | --- | --- |
| **`/setting/updater/mode`** | **"next boot = updater" flag** | created by app UDTR0604 code / `up.sh`; absent from the physical normal-boot `/setting` dump |
| `/setting/updater/mode1` | production updater action | `UdtrMain.sh getCurrentMode()` → `MODE_PROD` |
| `/setting/updater/mode2` | service action | `getCurrentMode()` → `MODE_SERVICE` |
| `/setting/updater/mode3` | minor action | `getCurrentMode()` → `MODE_MINOR` |
| `/setting/updater/mode5` | MS-crypt action | `getCurrentMode()` → `MODE_MSCRYPT` |
| `/setting/updater/mode6` | version-skip action | `getCurrentMode()` → `MODE_VERSKIP` |
| `/setting/updater/comp` | "update completed" marker; `execute_ufp.sh` deletes `mode*` when present | updater script; physical dump has `comp` present and **no** `mode*` |
| `/setting/updater/uincomp` | "updater incomplete" marker → abort with `ERROR_UINCOMP=54` | `UdtrMain.sh` |
| `/setting/updater/dat4` | current firmware version data (2 B `00 02`) | updater script, physical dump |

App-side writer (`/usr/bin/up.sh`, plus `UDTR0604` strings embedded in `libObj.so`) — [C]:

- `up.sh`: `rm -f /setting/updater/mode*`; `touch /setting/updater/mode` (+`mode1`/`mode3`/`mode4`/
  `mode5`/`mode6` depending on action); `sync`; `ud_send_lsi.elf $mode_num`.
- `libObj.so` contains the same control strings: `rm -f /setting/updater/mode*`,
  `/setting/updater/mode1|mode3|mode6|mode`, `[UDTR0604] …`, `ud_send_lsi.elf %d`, `ud_reboot.elf`,
  `mount -t cramfs -o loop /mnt/boot/initrd.img /tmp_updater`, `/mnt/dat2`, `/mnt/dat3`,
  `/setting/updater/dat4`, `UD_GET_LOADER_VER` (NAND `NAND_IOC_GET_SAFE_PHYS_BLOCKS` /
  `NAND_IOC_PREAD_SAFE` on `/dev/nflasha`), `UD_SET_MD`, `UD_REBOOT`, etc. So the app has a complete
  "set mode marker → signal → reboot" updater-request engine.
- `ud_send_lsi.elf`: `Backup_read(0x4B0000, &byte)`; only when that byte is 1 or 2 it allocates a
  4-byte OSAL message with the integer argv (`atoi(argv[1])`), sends it to queue **0x804B0376**,
  waits 3000 ms on queue **0x004B0379**, frees the message. The actual consumer/target was not traced.

Updater-side consumer — [C]: `UdtrMain.sh getCurrentMode()` tests `mode3`, `mode2`, `mode6`,
`mode1`, `mode5` and defaults to `MODE_USER`; `execute_ufp.sh` copies `dat2`/`dat3` from `/mnt`
(nflasha1) and `dat4` from `/setting`, then runs `sauu`/`crypter.elf` under a UFP update; the payload
bodyfs is mounted from `/usr/bin/udtrbody.bin` (cramfs) by `sauu`/`mf`/`crypter.elf`.

### 3.2 Loader-side selection — the missing link

The loader binary is **not present** in any local artifact:

- the update package's `0700_part_image/dev/` carries only `nflasha3`, `nflasha5`, `nflasha7`,
  `nflasha15` — no `nflasha1`/`nflashaB0` image;
- no loader image (for example the `loader_mpt.tar` that `loader_writer.sh` unpacks into
  `/dev/nflashaB0`), and no dump of the `/dev/nflashaB0/B1` loader area, exists in the workspace;
- the preserved camera exposes `/dev/nflashaB0` (252:126) / `nflashaB1` (252:127) and a
  `[kalnflashaB0]` kernel thread, but the device was not dumped;
- the only loader-relevant data we do hold is the content of the two boot partitions and the
  `p1chksum`/`loadaddr.txt`/`kemco.txt` contract.

Strong **[I]** (consistent with all data): the loader reads `/setting/kemco.txt` for the normal kernel
cmdline (the physical `/setting/kemco.txt`, SHA-256 `5f957314…d50ca`, is byte-identical to
`0800_appli/setting/kemco.txt` from the update package and its text equals the observed
`/proc/cmdline`); for an updater request it reads `/setting/updater/mode`, loads
`/dev/nflasha1/boot/vmlinux.bin` to `0x00108000` + `boot/initrd.img` to `0x00700000` per
`loadaddr.txt`, and uses `/dev/nflasha1/boot/kemco.txt` as the updater cmdline. Which hardware/key/
backup state sets `/setting/updater/mode` *before Linux exists* is not in our data.

### 3.3 Confirmed loader boot-mode/NVRAM interface — [C]

`upm.ko` (`/usr/kmod/upm.ko`) defines `LDR_BOOT_MODE_*` and reads the loader mode from backup memory:

| loader mode | name (upm.ko string) | `/proc/udm/upm_bootmode` output | observed consumer |
| ---: | --- | --- | --- |
| 1 | `LDR_BOOT_MODE_COLD` | NORM | — |
| 2 | `LDR_BOOT_MODE_HOT` | NORM | — |
| **3** | **`LDR_BOOT_MODE_UPDATER`** | NORM (not mapped to a proc string) | loader boot selection (before Linux, [I]); value itself is [C] |
| 4 | `LDR_BOOT_MODE_CIPA` | NORM | — |
| **5** | **`LDR_BOOT_MODE_ADJUST`** | `ADJUST` | `bootin.elf` → `app_argv=adj`; init sets `is_cho` (no consumer found in `main`) |
| **6** | **`LDR_BOOT_MODE_USB_CHARGE`** | `USB_CHARGE` | `bootin.elf` → `app_argv=usbj`; init sets `is_usbj` (no consumer found in `main`) |
| 10 | `LDR_BOOT_MODE_WARM` | NORM | warm restore |
| 11 | `LDR_BOOT_MODE_SS` | NORM | — |
| 12 | `LDR_BOOT_MODE_BIS` | `BIS` | init `is_bis` (skips `/log` prep and mounts `/sys` in the shell path); `im.elf` `smode`/`BIS` helper |

`k_upm_get_ldr_mode` returns a `.bss` global at offset 0x860; `k_upm_setup_boot_factor` fills it with
`Backup_read(record 0x51000F, &mode)` (`R_ARM_ABS32` to `.bss+0x860` in `.rel.text`).
`/proc/udm/upm_bootmode` (`upm_bootmode_read_proc`, 0xE480) maps 6→`USB_CHARGE`, 5→`ADJUST`,
0xC→`BIS`, everything else→`NORM`.

`bootin.elf` has the same contract independently: functions at 0x9614 and 0x964C call
`Backup_read(0x51000F)` and return `value==5` / `value==6`; its help lists
`<app_argv>: adj -- adjust mode / usbj -- USB charge mode / normal default`, and its command lines
contain ` app_argv=adj ` / ` app_argv=usbj `. This is the confirmed loader→Linux boot-mode flag; the
loader's own rule for setting it (key state, boot factor, charger, update request) is not in the dump.

### 3.4 Other non-UI modes in the normal init — [C]

`nflasha3/initrd.img_unpacked/sbin/init` (0x90A8 `check_mode_file`, 0x92CC `check_bootmode`,
0x9038 `check_forced_senser`) reads:

- `/setting/mode/dmode` (created by `/usr/bin/change_mode.sh`): characters `0`,`k`,`g`,`d`,`e` set
  `is_kernel_only`, `is_kmcenv`, `is_gdb`, `is_duma`, `is_efence`; if the file opens at all,
  `is_oreore_env=1` (a debug hook that later mmaps a path from `/setting/env.txt`).
- `/proc/udm/upm_bootmode`: `USB_CHARGE`→`is_usbj`, `ADJUST`→`is_cho`, `BIS`→`is_bis`.
- `/setting/sen/smode`: first two bytes `UU` → `is_forced_senser` (unless `is_bis`).

Behaviour found in `main`: if `/setting/mode/dmode` contains `0` (`is_kernel_only`), the app/bootin/UI
sequence is skipped and init goes to the console-shell fallback (mount `/sys`, clear `LD_PRELOAD`,
`/usr/bin/launch_shell.elf`, then `/bin/ash --login` error fallback). On a normal camera the kernel
cmdline has `console=ttynull`, so this shell is **not** reachable over UART unless the cmdline/console
is changed; the updater cmdline (`console=ttyAM0,115200n8`) is the one that gives a serial shell.
`im.elf` has its own helper at 0x9434 that reads `/setting/sen/smode` + `/proc/udm/upm_bootmode`: it
returns 1 only when `smode` starts `UU` and the upm mode is not `BIS` (or `/proc/udm/upm_bootmode`
cannot be read), otherwise 0. Its caller/boot decision was not traced.

`change_mode.sh` values (0 = kernel only/console; 1/2/3 = global infra/LIRO/app; letter suffixes for
KMC/gdb/DUMA/eFence/… ) are debug modes, not updater modes. The physical `/setting/mode/` directory on
our camera is empty (no `dmode`), and `/setting` has no `updater/mode*` files — i.e. our camera is in
normal boot with a completed-update marker (`updater/comp`).

### 3.5 Things that are **not** present

- **No SD `\updater\mode` check.** All updater marker paths are `/setting/...` on `nflasha2`. The
  updater ramfs has `/dev/mmca1` and busybox, but its initramfs scripts never mount the SD card;
  `is_valid_boot.sh` references a missing `ud_get_boot_device.elf` and its call is commented out in
  `/sbin/init`, so the "MS boot"/SD-validity path is dead code in this image.
- **No key-combo updater trigger in userspace.** The only key enumeration we see is upm's
  `BF_KEY_*` boot-factor list (`BF_KEY_POWER`, `BF_KEY_PLAY`, `BF_KEY_USB_CONNECT`, `BF_KEY_EVF`,
  `BF_KEY_MENU_APO`, …) and the loader boot-mode enum. There is no handler that turns a key into
  `/setting/updater/mode`.
- **No bootloader.** See 3.2.

## 4. `CautionConfig.so` crash and the MENU symptom

### 4.1 Why the truncated file is fatal — [C] for a6400 layout, [I] for 6100

Local a6400 `CautionConfig.so` = 12,070,800 B. ELF layout (offsets = vaddrs; one big first segment):

| range | content |
| --- | --- |
| 0x0000D4–0x076F18 | `.gnu.hash` |
| 0x076F18–0x192918 | `.dynsym` (all dynamic symbol names live in `.dynstr`) |
| 0x192918–0x5F3A36 | `.dynstr` |
| 0x617218–0x7A8028 | `.rel.dyn` |
| 0x7BF588–0x940954 | `.text` |
| 0x94095C–0xA7793C | `.rodata` |
| vaddr 0xAA62B0–0xB8AA00 | `.data.rel.ro`/`.dynamic`/`.got`/`.data`; `.bss` 0xB8AA00–0xC53720 |
| PT_LOAD[0] | file size **0xA9E290 (10,871,440 B)** |

The reported truncation size 1,280,848 B = **0x138B50** falls **inside `.dynsym`**: the dynamic symbol
names (`.dynstr`) and every relocation, `.text`, `.rodata` and `.data` byte are absent, and the first
`PT_LOAD` extends ~9.6 MB past end-of-file. `ld.so` cannot build this object (truncated dynsym/strtab;
segment beyond EOF → read/mmap failure or SIGBUS). Because `viewUnified2.so` declares
`DT_NEEDED = CautionConfig.so`, this is **link-time**, not optional lazy loading — every attempt to
load the unified UI view fails. The exact 6100 file is not held locally, so its offsets differ and the
same arithmetic is [I], but the reported 6100 sizes (12,078,652 → 1,280,848) make the same conclusion
unavoidable.

Companion files: `ModelCautionConfig.so` (6,764 B) and `CautionRsrcConfig.so` (125,712 B) are loaded by
`libObj.so` (`dlopen`/`dlsym`) for the Caution engine; `CautionConfig.so` itself is the 12 MB
UI/menu/caution data+model library (`CmnViewSettingNode`, `CmnViewMenuData`, `ViewCautionToInstance`
and `CautionRsrcMgr` symbols are in it). It is the menu model resource, not a small plugin.

### 4.2 What MENU-hold most plausibly does — [I]

We cannot prove the external MENU behaviour offline; the loader key handling is absent. The evidence
that constrains the explanation is:

- the app/UI path is: init → bootin.elf (phases `s g r u l i a`) → `im.elf debug s g r u l i a
  lazy-global` → `libObj.so` loads `viewUnified2.so` → its `DT_NEEDED CautionConfig.so` must load;
- `bootin.elf` already distinguishes loader modes: `ADJUST (5)` → `app_argv=adj`, `USB_CHARGE (6)` →
  `app_argv=usbj`; its help also lists `dmode=0 kernel only` and `amode=normal/adj/usbj`;
- `upm.ko` exposes `BIS (0x0C)` and the init code has a BIS branch; a key held at power-on is exactly
  the kind of input the loader boot-factor list (`BF_KEY_*`) exists for;
- a partially booted app in `adj`/`usbj`/kernel-only mode would not construct the unified view, so
  `viewUnified2.so`/`CautionConfig.so` would never be reached, leaving a frozen/partial UI while
  lower-level MCU functions (shutter, AF illuminator) continue.

So the consistent hypothesis is: **holding/spamming MENU changes the loader boot mode (ADJUST/BIS
family) or the early input path so the unified view is never built; the crash is skipped, not fixed,
and the UI is stuck.** This is a hypothesis, not a demonstrated key map: we do not have the loader, and
no local code maps MENU to `LDR_BOOT_MODE_*`.

### 4.3 Is any service/USB path reachable from the halted state? — [I]

No. In normal boot the USB gadget is an app-driven service: `libObj`/`libUsbControl`/`usbg_*` are
loaded and configured by the application (previous E0309/E0310/E0318 work shows the USB FSM threads
blocked in `RcvMsg`/futex until the app/upper layers issue the configuration request). If the UI is
dead/partial, MTP/MSC are not published. The charging-only descriptor the external user sees
(`054C:0994`) is not any of the descriptors declared for a6400 in `config.yaml` (normal
`054C:0448/047D/0BFE/0BFF/0CA7/0CA8`; updater `054C:03E2`), so **[I]** it belongs to the
loader/charging firmware, not to the updater or normal Linux USB stack. The updater USB identity only
comes up after a real updater boot (the updater ramfs loads `usb_portMonitor`, `usbg_sen`,
`usb_extcmd`, `usbg_storage`). We found no secondary key combination in the preserved code that starts
those services from a crashed UI.

## 5. Updater ramfs mount/recovery capabilities — [C] except where noted

The updater cramfs (`/dev/nflasha1/boot/initrd.img`) is a complete userspace with:

- `/bin/busybox` + `/bin/sh`, `/bin/ash`, `/bin/mount`, `/bin/umount`, `/bin/cp`, `/bin/sync`,
  `/bin/dd`, `/bin/tar`, `/sbin/dosfsck`, `/sbin/mkdosfs`;
- block nodes `/dev/mmca1` (250:11, SD), `/dev/nflasha1` (252:1), `/dev/nflasha2` (252:2),
  `/dev/nflasha7` (252:7), `/dev/nflasha13` (252:13, updater work), `/dev/nflasha15` (252:15, `/usr`),
  `/dev/dnflasha15` (252:143), `/dev/ram0`, `/dev/mem`, etc.;
- `/sbin/init` mounts proc/sys/rootfs, 32 MiB tmpfs `/ramdsk`, `/dev/nflasha2`→`/setting` (vfat), and
  auto-starts `/bin/ash --login` unless `/root/IAMLDUDWRT` is present.

Open detail: the update-engine binaries (`sauu`, `mf`, `crypter.elf`) expect
`/usr/bin/udtrbody.bin` (cramfs body), but that file is **not** inside the preserved nflasha1 cramfs.
So the full updater flow must obtain it from another mount (e.g. `/usr` from nflasha15) or receive it
over the UFP protocol; the exact source is unresolved. This does not affect a manual file-copy
recovery, only the automatic update engine.

Commands the updater itself runs (proven capability): `mount -t vfat /dev/nflasha1 /mnt`,
`mount -t vfat /dev/nflasha2 /setting`, `mount -t vfat /dev/nflasha13 …`, tmpfs mounts,
`umount`, `mkdosfs`, `dosfsck -Y`, `cp`, `sync`, `md5sum -c`. It does **not** mount `/usr`; ext2
support in the updater kernel is therefore not exercised by its own scripts **[I]**. If ext2 is built
into the updater kernel, the repair sequence from the updater shell is:

```sh
# from the password-less /bin/ash --login on the updater console
mkdir -p /mnt /mntusr
mount -t vfat /dev/mmca1 /mnt                    # SD card (FAT), stock CautionConfig.so
mount -t ext2 -o rw /dev/nflasha15 /mntusr       # /usr raw ext2; may fail if no ext2 in this kernel
cp /mnt/CautionConfig.so /mntusr/lib/CautionConfig.so.new
sync
ls -l /mntusr/lib/CautionConfig.so.new           # must be 12070800 B (a6400) / 12078652 B (6100)
mv /mntusr/lib/CautionConfig.so.new /mntusr/lib/CautionConfig.so
sync
umount /mntusr
umount /mnt
mount -t vfat /dev/nflasha2 /setting 2>/dev/null
rm -f /setting/updater/mode*                     # do not re-enter updater accidentally
sync
```

Safety warning: the updater `init` immediately starts `UdtrMain.sh`, which is the **update engine**
(`sauu`/`crypter.elf`/`mf`, partition formatting and firmware writes). If a valid update payload and
`mode1/2/3/5/6` action marker are staged, it may begin a destructive update before/while the shell is
used. For a file-copy-only session, confirm no update payload or action marker is present, and never
interrupt an update that has already started.

Caveats:
- This is **not risk-free**: the original incident was caused by an in-place truncation while `/usr`
  was rw. `cp` + `sync` + `mv` and size/SHA verification reduce (not eliminate) the risk; never
  overwrite the only good copy in place.
- ILCE-6100 partition numbering is assumed to match (same CXD90045 family); verify `/proc/mounts` and
  `mount.conf`-equivalent on the actual camera before any write.
- If the updater kernel lacks ext2, an alternative is to repair via the main-boot init (normal rootfs
  mounts `/usr` before the UI starts) only if a shell can be obtained before the app starts — our
  analysis shows init gives no shell in normal boot (it pivots and execs `launch_shell.elf`; the
  console shell fallback exists only when `/proc` mount fails, when `/setting/mode/dmode` contains `0`
  i.e. `is_kernel_only != 0`, or when the `launch_shell.elf` exec fails). **The updater boot is the
  intended recovery route; whether the external camera can be forced into it is the open question
  (section 3.2).**
- The updater USB identity (`054C:03E2` on a6400) and UFP protocol are for firmware delivery; they do
  not expose a file-copy interface to an arbitrary host.

## 6. UART and boot-mode hardware

Confirmed from cmdlines and the physical boot dump:

- **115200 8N1** — `exception.console_option=115200n8` in both the normal md/cmd (`/setting/kemco.txt`)
  and the updater `boot/kemco.txt`; the updater cmdline additionally sets
  `console=ttyAM0,115200n8`; the normal cmdline sets `console=ttynull` (kernel console silent).
- UART MMIO: `uart0 0xf2000000-0xf2000fff` (`cxd900x0-uart`), `uart3 0xf2003000-0xf2003fff`;
  character major 204 = `ttyAM`, major 241 = `ttynull`; `/dev/tty` 5:0, `/dev/console` 5:1 exist on
  the physical camera.
- `cfg.uart=9` (normal) / `cfg.uart=15` (updater) — currently undecoded board/pinmux selector, not a
  baud setting.
- **1.8 V logic level is not evidenced in any local artifact.** It must be measured before connecting a
  UART adapter; treat 1.8 V as **[I]**.
- No boot-mode/test-pad data exists in the dumps. The only boot-mode interface we can name is the
  loader→Linux backup record 0x51000F (section 3.3) plus the loader boot-factor key list; the loader
  image/board straps are not available. The `/dev/nflashaB0/B1` loader area cannot be reconstructed
  from the update package.

## 7. Confirmed vs inferred

| claim | status | evidence |
| --- | --- | --- |
| `/dev/nflasha1` is the updater boot set (zImage + cramfs initramfs, loadaddr, kemco, p1chksum) | **C** | dump files/hashes, zImage magic, p1chksum MD5 match |
| `/dev/nflasha3` is the main boot set; normal cmdline is `/setting/kemco.txt`-shaped | **C** (file equality) / **I** (loader consumes it) | file SHA equality, physical `/proc/cmdline` |
| app writes `/setting/updater/mode*` and runs `ud_send_lsi.elf` / `ud_reboot.elf` | **C** | `up.sh`, libObj `UDTR0604` strings |
| updater initramfs consumes `mode1/2/3/5/6`, aborts on `uincomp`, cleans on `comp` | **C** | `UdtrMain.sh`, `execute_ufp.sh`, physical `/setting` state |
| loader boots updater when the marker is present | **I** | marker + dual boot set + update lifecycle; loader absent |
| loader boot mode is backup record 0x51000F with UPDATER=3, ADJUST=5, USB_CHARGE=6, BIS=0x0C | **C** (consumer side) | `upm.ko`, `bootin.elf`, `/proc/udm/upm_bootmode` |
| SD `\updater\mode` trigger exists | **not found** | all marker paths are `/setting/...`; MS path dead |
| key combo triggers updater boot | **not found / I** | only BF_KEY enum + ADJUST/USB_CHARGE mapping |
| `viewUnified2.so` hard-depends on `CautionConfig.so` | **C** | ELF `DT_NEEDED` |
| truncation 1,280,848 makes `CautionConfig.so` unloadable | **C** (a6400 layout) / **I** (6100 offsets) | ELF section/segment arithmetic |
| MENU-hold stops the crash by selecting a non-NORMAL boot/early-input state | **I** | bootin app_argv modes, loader-mode consumers; no key map |
| USB gadget reachable from halted UI | **no evidence; I: no** | app-driven USB; updater USB is a separate boot |
| updater shell gives SD+mount+shell for file restore | **C** | updater cramfs nodes/busybox/init |
| updater kernel can mount ext2 `/usr` | **I** | ext2 not exercised by updater scripts |
| serial 115200 8N1 | **C** | cmdlines |
| serial 1.8 V / boot pads | **I / unknown** | no local measurement |

## 8. What would close the gaps (offline or authorized)

1. Dump `/dev/nflashaB0`/`B1` (loader) read-only, if a shell/debugger route is authorized again; that
   is the only way to see the actual updater-boot selection logic and key mapping.
2. Capture `/proc/cmdline` and `/proc/udm/upm_bootmode` on a camera that is known to be in each boot
   mode (normal, USB charge, ADJUST) if any read-only opportunity exists — confirms bootin's `adj`
   selection mapping from the outside.
3. Dump `/etc` (`nflasha10`) read-only to see whether `/etc/profile`/init scripts start `im.elf` (and
   therefore what the crash-loop supervisor actually is); our rootfs images contain no scripts, so the
   startup scripts live only in the runtime `/etc` vfat partition.
4. A trace of `ld.so` on an emulated/authorized image with a deliberately truncated
   `CautionConfig.so` to confirm the exact failure mode (`dlopen` error vs SIGBUS) — pure offline test.
5. For the external camera: the only proven-free route is to obtain an updater boot, then use the
   updater initramfs shell to restore the file from SD as in section 5. There is no confirmed SD-file
   or key-combo updater trigger in the CXD90045 artifacts we hold, so the request should not be
   promised beyond "if you can get it into updater mode".

## 9. Reproduction / artifacts

All read-only derivations used here:

```text
# read-only extraction paths used (derived, no execution)
src/a6400/execution/guest_vfat.py  VfatImage(...).walk() -> entry -> read_file(entry)
fwtool.py/fwtool/archive/cramfs.py  readCramfs(BytesIO(initrd)) -> 562 entries, 154 device nodes
pyelftools + capstone 5.0.7 (Thumb/ARM)  -> init, bootin, launch_shell, im.elf, upm.ko, libObj
```

Derived outputs:
- [updater initramfs tree + device rdev decode](../../artifacts/analysis/0413-updater-initramfs-tree.txt)
- [nflasha1 updater boot contract files](../../artifacts/analysis/0413-nflasha1-updater-boot-files.txt)
- [physical /setting updater markers](../../artifacts/analysis/0413-setting-updater-markers.txt)

No camera or USB interaction was performed for this record.
