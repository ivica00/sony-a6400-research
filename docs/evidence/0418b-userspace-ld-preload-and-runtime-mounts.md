# E0418b — Userspace startup prerequisites: `ld.so` preload config, `LD_*` environment, and runtime mounts

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no Senser
mode, no SD or flash write. Inputs are the E0414 read-only dumps and receipts, the
preserved a6400 v2.00 firmware extraction, and retained read-only camera artifacts
already on disk. Labels: **[C]** confirmed from the listed artifacts/traces,
**[I]** inference from the same evidence. This note contains no proprietary binary
payloads — names, paths, hashes, environment strings and mount records only.

## 0. Short answer

1. **No `ld.so.preload` configuration ships in either image.** The live `nflasha3`
   `initrd.img` (CE Linux 8.2.6.0) and the preserved v2.00 `initrd.img` contain
   **no `/etc` directory at all**: no `/etc/ld.so.preload`, no `/etc/ld.so.conf*`,
   no `/etc/init.d/*`, and no `rcS` script. The initramfs is a purpose-built C
   `/sbin/init` plus six kernel modules, the dynamic loader/libs, ~380 static
   device nodes, empty `/proc` and `/rootfs` mount points, and `version.txt`. **[C]**
2. **The preserved `/usr` image** (a6400 v2.00 `nflasha15` ext2) also has **no
   `/etc` directory**, no `ld.so.preload`/`ld.so.conf*`, no `init.d`, no `rcS` and
   no `inittab`. Its only `LD_LIBRARY_PATH` assignment is inside
   `bin/WebApiLauncher.sh` for `orb-server`; it does not apply to `im.elf`. **[C]**
3. **Factory default preload list is empty.** All preload code paths are debug
   mechanisms gated by `/setting/mode/dmode` / `/setting/mode/preload`
   (`bin/change_mode.sh`). Both files are absent from the retained E0307
   `/setting` dump, and the three `.so` targets hard-coded in `/sbin/init`
   (`libkmcsup.so.2.0.0`, `libsonyefence.so`, `libduma.so`) are **not present in
   the preserved `/usr` image**. **[C]**
4. **The running environment observed for `im.elf` contains no `LD_PRELOAD` and no
   `LD_LIBRARY_PATH`.** `/proc/149/environ` (im.elf, argv
   `im.elf debug s g r u l i a lazy-global`) holds only `LT_ABORTREASON=0`,
   `HOME=/`, `MALLOC_MMAP_THRESHOLD_=32768`, `TERM=linux`, `TOPRC=/etc/toprc`,
   `PATH=/sbin:/bin:/usr/sbin:/usr/bin:/devel/usr/bin`,
   `MALLOC_OPTIONS=gfffffffff`, `MALLOC_TRIM_THRESHOLD_=32768`, `PWD=/`.
   PID 1 is `/usr/bin/launch_shell.elf 0 1` and carries the same init-provided
   variables plus an **empty** `LD_PRELOAD=` and no `LD_LIBRARY_PATH`. **[C]**
5. **Runtime `/etc`** is a writable vfat mount of `/dev/nflasha10` (never part of
   the static images). In the retained read-only camera snapshot: `/etc/ld.so.preload`
   lists only the **two project-installed diagnostics**
   (`/setting/touch_native_guarded_v1.so`, `/setting/usb_debug_launcher.so`);
   `/etc/ld.so.conf` returns **ENOENT (-2)** and `/etc/ld.so.conf.d` does not
   exist. These are **not** factory preloads. **[C]**
6. **Exact runtime mount state and sequence** are recovered below: the 13-line
   `/proc/mounts` from the E0414 probe and postcheck receipts (identical before and
   after), the init's 22-record internal mount table (identical in the live
   8.2.6.0 and preserved v2.00 `/sbin/init`), and the mount call order recovered
   from the disassembly. `/dev/pts` is mounted by `bootin.elf`, not by init;
   `/tmp/lt` (tmpfs) exists only in the LeakTracer debug mode. **[C]**

## 1. Inputs and identity

| input | bytes | SHA-256 (prefix…suffix) | role |
| --- | --- | --- | --- |
| `artifacts/dumps/a6400-nflasha-readonly/nflasha3-50331648.bin` | 50,331,648 | `cd4178d4…0719a6` | E0414 read-only dump, FAT12 `/system` |
| live `initrd.img` inside that dump | 2,184,192 | `db95861f…254673` | ext2 initramfs, CE Linux 8.2.6.0 (authoritative) |
| `firmware/extracted_a6400/…/nflasha3_unpacked/initrd.img` | 3,963,904 | `15803c2d…a13e83` | preserved package v2.00 initramfs |
| `firmware/extracted_a6400/…/dev/nflasha15` (preserved `/usr`) | 214,664,192 | `0e9b1914…296e56` | ext2 image mounted at `/usr` |
| `firmware/extracted_a6400/…/dev/nflasha7_unpacked` | — | — | preserved rootfs (cross-check: `/etc` directory is empty) |
| `/sbin/init`, preserved v2.00 | 26,101 | `0af5724e…8dc7ad` | initrd copy and rootfs copy are byte-identical |
| `/sbin/init`, live 8.2.6.0 initrd | 26,994 | `1dbe18fe…251b21` | live build (different size, same contract) |

The E0414 receipts are `receipts/probe-20261112T155552.json` (`probes.proc_mounts`)
and `receipts/postcheck-20261112T160042.json` (`commands.proc_mounts`); the two
`/proc/mounts` outputs are identical. Camera uptime across the session was
1,557.57 s → 1,846.30 s (monotone, no reboot), PID 149 fd 29 unchanged, `/tmp_bt`
empty (E0414 README).

The live `/usr` (`nflasha15`) was **not dumped** in E0414. All `/usr` statements
below are therefore pinned to the **preserved v2.00 image**; the running camera is
8.2.6.0 and E0302 already showed that its `/usr/lib/libObj.so` differs from the
extracted image, so live `/usr` content is not identity-matched here. **[C]/[I]**

## 2. `ld.so.preload`, `ld.so.conf*`, `init.d`, `rcS` inventory

| container | `/etc` dir | `ld.so.preload` | `ld.so.conf*` | `/etc/init.d` | `rcS` / `inittab` |
| --- | --- | --- | --- | --- | --- |
| live `initrd.img` (8.2.6.0) | **absent** | absent | absent | absent | absent |
| preserved `initrd.img` (v2.00) | **absent** | absent | absent | absent | absent |
| preserved `/usr` image (`nflasha15`) | **absent** | absent | absent | absent | absent |
| preserved rootfs (`nflasha7`) | present, **empty** | absent | absent | absent | absent |

* Both initrd trees were fully walked (live: 408 entries — 15 directories,
  12 regular files, 381 device nodes; preserved: 418 / 17 / 386). Only regular
  files are `/sbin/init`, `/sbin/dosfsck`, `/version.txt`, six `kmod/*.ko`, and
  loader/lib files. There is **no shell init script anywhere in the initramfs**;
  the mount/driver/launch logic lives in the compiled `/sbin/init` (`main`,
  `mount_partition`, `insmod_drivers`, `set_oreore_env`, `launch_shell` symbols). **[C]**
* The preserved `/usr` image (827 walked entries — 34 directories, 758 regular
  files) has no `etc/` directory. Its script-like files under `bin/`, `wifi-scripts/`
  and `tool/LeakCheck` are application/updater helpers, not SysV init scripts.
  Byte hits for the literal `rcS` inside shared libraries / `tcpdump` /
  certificate data are coincidental substrings (e.g. `srcS…`, `RsrcS…`), not
  scripts; no file named `rcS` exists. **[C]**
* The loader used at boot, `lib/ld-2.11.2.so`, is a stock glibc 2.11.2 loader and
  contains the generic `LD_PRELOAD`, `LD_LIBRARY_PATH` and `ld.so.preload` strings
  (i.e. it *supports* those mechanisms). The static images simply supply no
  config file. **[C]**

### 2.1 Runtime `/etc` (not a static image)

`/etc` is mounted read-write from `/dev/nflasha10` vfat by the init's mount table
(record 21, see §4). From the retained **read-only** camera snapshot
(`artifacts/analysis/e0302-camera-scope/`):

| path | result |
| --- | --- |
| `/etc/ld.so.preload` | 67 B, sha256 `89f5145b…e341c4`; contents = `/setting/touch_native_guarded_v1.so` + `/setting/usb_debug_launcher.so` |
| `/etc/ld.so.conf` | read error **-2 (ENOENT)** |
| `/etc/ld.so.conf.d` | `ls: No such file or directory`; glob loop empty |

The two preload entries are this project's diagnostics, not Sony factory data;
E0410/E0411 record them as the only entries and unchanged on 2026-11-12. E0411
also showed by `/proc/149/maps` grep that the touch preload was genuinely absent
from `im.elf` after the P4a test, consistent with `im.elf` being
hibernation-restored rather than re-exec'd (E0084). **No raw binary is reproduced
here; paths and hashes only.**

## 3. Every preload `.so` and `LD_*` environment assignment found in the images

### 3.1 `/sbin/init` (identical contract in both builds)

Default environment installed with `putenv` before userland starts (live 8.2.6.0
strings, contiguous literal-pool references in `main`):

```
HOME=/                                   PATH=/sbin:/bin:/usr/sbin:/usr/bin:/devel/usr/bin
TOPRC=/etc/toprc                         MALLOC_OPTIONS=gfffffffff
MALLOC_MMAP_THRESHOLD_=32768             MALLOC_TRIM_THRESHOLD_=32768      (live only)
LT_ABORTREASON=0
```

The preserved v2.00 build installs the same list except
`MALLOC_MMAP_THRESHOLD_=131072` and no `MALLOC_TRIM_THRESHOLD_`. In both builds the
end of `main` falls through to `putenv("LD_PRELOAD=")` (empty value) immediately
before `launch_shell()`; that is the source of the empty `LD_PRELOAD=` visible in
`/proc/1/environ`. No `LD_LIBRARY_PATH` is ever installed by init. **[C]**

Conditional debug preload branches in `main` (all gated by the `/setting/mode/dmode`
letters parsed by `check_mode_file`; the flags are zero when that file is absent).
The letter values are directly visible in `bin/change_mode.sh` (§3.3):

| gate | preload / environment | applied to |
| --- | --- | --- |
| dmode contains `k` | `LD_PRELOAD=/usr/tool/libkmcsup.so.2.0.0` | `bootin.elf` child |
| dmode contains `e` | `LD_PRELOAD=/usr/tool/libsonyefence.so` | `bootin.elf` child |
| dmode contains `d` | `LD_PRELOAD=/usr/tool/libduma.so`, `DUMA_MALLOC_0_STRATEGY=1`, `DUMA_PROTECT_FREE=1`, `DUMA_ALIGNMENT=4`, `DUMA_OUTPUT_FILE=/root/dumaLog.txt`, plus `system("echo 1000000 > /proc/sys/vm/max_map_count")` | `bootin.elf` child |
| dmode contains `0` (or `/proc/udm/upm_bootmode` = `ADJUST`) | no preload; init goes straight to `launch_shell` (no app boot) | — |
| dmode contains `g` | GDB mode: `system("GDB")` then `system("/usr/bin/bootin.elf")` | interactive |
| `/setting/env.txt` exists | line parser `parse_and_set_env`: a line containing `=` is `putenv`-ed, otherwise `unsetenv`-ed (arbitrary variables possible, incl. `LD_*`) | init's own environment |
| `/setting/sen/smode` begins `UU` | forced Senser: `run_bg_process("/usr/bin/sen.elf")` | — |

`/sbin/init` also opens `/proc/snsc_boot_time`, reads `/proc/cmdline`
(only `console=ttyAM0` is matched), `/proc/version` (qemu), `/proc/mounts` (nfs),
`/proc/udm/upm_bootmode` (`USB_CHARGE`/`ADJUST`/`BIS`) and
`/setting/mode/dmode`; when `dmode` was opened successfully it calls
`set_oreore_env()` which opens `/setting/env.txt`, `mmap`s it and calls the line
parser above. **[C]**

### 3.2 `bootin.elf` (preserved `/usr/bin/bootin.elf`)

`bootin.elf` is the launcher that builds `im.elf`'s argv
(`im.elf debug s g r u l i a lazy-global`) and starts it. Recovered behaviour from
its literal pools and disassembly:

| item | finding |
| --- | --- |
| preload file | reads `/setting/mode/preload` (≤0x200 B) and builds `LD_PRELOAD="<file contents>"` |
| normal launch | shell command `im.elf debug … lazy-global &` executed via `system()`; the resulting argv matches the observed `/proc/149/cmdline` exactly |
| debug preload | when the debug option bit is set, the `LD_PRELOAD="…"` string is prefixed to that shell command (inline assignment); the same bit-gated block clears the inherited `LD_PRELOAD` in its own environment via glibc `putenv("LD_PRELOAD")` (a name without `=` removes the variable) |
| normal-mode environment | with all debug option bits clear (the observed boot, no `dmode` file), no preload string is generated and no variable is added; `im.elf` inherits the environment from init (which has no `LD_*` at that point) |
| LeakTracer (`lt`) | mounts tmpfs on `/tmp/lt`, creates `leaktracer.in/out` fifos and links, then `putenv`s `LT_CHECK_PROCESS=1`, `LT_INT_DIR=/tmp/lt`, `LT_MISC_DIR=/tmp/lt` |
| device nodes | mounts `none /dev/pts devpts` (flags `0xc0ed0000`) — this is the source of the `/dev/pts` line in `/proc/mounts` |
| wfree | `putenv("MALLOC_OPTIONS=2W")` when the sslibc free-check mode is selected |
| gdb/system | prefixes the command with `gdb --args ` and/or uses `system()` instead of the background path |

The preserved `/usr/tool/` contains `LeakCheck`, `LeakTracer.so`, `libefence.so`,
`libjemalloc_tsh.so.1`, `libmcheckb.so`. The three hard-coded init preloads above
are **not present**; `libefence.so` is present but no init/bootin/script path
references it (the script variable `LIB_EFENCE` is defined but never used). The
`libjemalloc_tsh.so` name written by `change_mode.sh` differs from the shipped
`libjemalloc_tsh.so.1`. **[C]**

### 3.3 `bin/change_mode.sh` (factory debug-mode writer, `/usr` image)

```
MODE_FILE=/setting/mode/dmode
PRELOAD_FILE=/setting/mode/preload
LIB_LT=/usr/tool/LeakTracer.so          LIB_JEMALLOC=/usr/tool/libjemalloc_tsh.so
LIB_EFENCE=/usr/tool/libefence.so       LIB_MCHECKB=/usr/tool/libmcheckb.so
```

| mode argument | dmode written | preload file written |
| --- | --- | --- |
| `0`–`6` | `0`/`1`/`2`/`3`/`1n`/`2n`/`3n` | empty |
| `7` | `3L` | `LeakTracer.so` path |
| `8` | `3w` | empty (sslibc Wfree) |
| `9` | `3k` | empty (init `k` → `libkmcsup.so.2.0.0`) |
| `a` | `3g` | empty (GDB mode) |
| `b` | `3s` | empty (gdbserver mode) |
| `d` | `3d` | empty (init `d` → DUMA branch) |
| `e` | `3e` | empty (init `e` → `libsonyefence.so`) |
| `f` | `3p` | `libjemalloc_tsh.so` |
| `10` | `3p` | `libmcheckb.so` |
| `p <path>` | `3p` | arbitrary `<path>` |

All of this is a factory debug path. In the retained E0307 `/setting` dump
(image sha `4d3269e5…c7f6fa`): the `mode/` directory exists but is **empty** —
no `mode/dmode`, no `mode/preload`, and no `/setting/env.txt`. Hence the debug
preload gates are all clear and both preload files are absent. **[C]**

### 3.4 `/usr/bin/WebApiLauncher.sh` (only `LD_LIBRARY_PATH` in `/usr`)

```sh
LD_LIBRARY_PATH=/usr/glib orb-server -f /usr/share/network/remotecontrol -p 10000 -D -1 &
```

This variable is scoped to the `orb-server` command only; it is not exported to
init, `bootin.elf` or `im.elf`. `tool/LeakCheck` is a manual wrapper
(`LD_PRELOAD=$SHLIB_PATH/$SHLIB exec $@`), and `lib/libosal_ulogio.so` merely
contains an `LD_PRELOAD` lookup string. Neither sets an environment for
`im.elf`. **[C]**

### 3.5 Observed runtime environment (retained read-only `/proc` artifacts)

| process | argv | environment |
| --- | --- | --- |
| PID 1 | `/usr/bin/launch_shell.elf 0 1` | `HOME=/`, `TERM=linux`, `PATH=/sbin:/bin:/usr/sbin:/usr/bin:/devel/usr/bin`, `TOPRC=/etc/toprc`, `MALLOC_OPTIONS=gfffffffff`, `MALLOC_MMAP_THRESHOLD_=32768`, `MALLOC_TRIM_THRESHOLD_=32768`, `LT_ABORTREASON=0`, `LD_PRELOAD=` |
| PID 149 (`im.elf`) | `im.elf debug s g r u l i a lazy-global` | `LT_ABORTREASON=0`, `HOME=/`, `MALLOC_MMAP_THRESHOLD_=32768`, `TERM=linux`, `TOPRC=/etc/toprc`, `PATH=/sbin:/bin:/usr/sbin:/usr/bin:/devel/usr/bin`, `MALLOC_OPTIONS=gfffffffff`, `MALLOC_TRIM_THRESHOLD_=32768`, `PWD=/` |

Provenance: the kernel starts `/sbin/init` with its built-in `HOME=/` and
`TERM=linux` environment (kernel `envp_init`; not emitted by init itself, so the
`TERM=linux` entry comes from this kernel default) **[I]**; init adds its own
defaults, optionally merges `/setting/env.txt`, mounts `/sys`, sets
`LD_PRELOAD=` empty and `exec`s `/usr/bin/launch_shell.elf` (this is why PID 1 is
the shell and not init itself). Before that it had already spawned
`/usr/bin/bootin.elf`; `bootin.elf` mounts `/dev/pts`, prepares the `im.elf`
command line and — with no debug mode set — passes on the environment as it
received it (no `LD_PRELOAD`, no `LD_LIBRARY_PATH`). That chain matches both
observed environments and the observed argv exactly. **[C]; the fork/system
detail is [I]**.

`im.elf` itself is hibernation-restored (E0084) and is therefore not re-exec'd on
a warm resume; the loader-level `/etc/ld.so.preload` is not re-applied to it, and
its `/proc/149/maps` did not contain the project touch preload (E0411). **[C]**

## 4. Runtime `/proc/mounts` and the mount sequence

### 4.1 Exact `/proc/mounts` (E0414 receipts, probe and postcheck identical)

```
rootfs / rootfs rw 0 0
proc /proc proc rw,relatime 0 0
/dev/nflasha7 / ext2 ro,relatime,errors=continue 0 0
/dev/nflasha15 /usr ext2 ro,relatime,errors=continue 0 0
/dev/nflasha10 /tmp vfat rw,sync,dirsync,noatime,fmask=0022,dmask=0022,codepage=cp437,iocharset=ascii,shortname=mixed,posix_attr,avoid_dlink,errors=remount-ro 0 0
/dev/nflasha10 /etc vfat rw,sync,dirsync,noatime,fmask=0022,dmask=0022,codepage=cp437,iocharset=ascii,shortname=mixed,posix_attr,avoid_dlink,errors=remount-ro 0 0
/dev/nflasha3 /system vfat rw,sync,dirsync,noatime,fmask=0022,dmask=0022,codepage=cp437,iocharset=ascii,shortname=mixed,posix_attr,avoid_dlink,errors=remount-ro 0 0
/dev/nflasha2 /setting vfat rw,sync,dirsync,noatime,fmask=0022,dmask=0022,codepage=cp437,iocharset=ascii,shortname=mixed,posix_attr,avoid_dlink,errors=remount-ro 0 0
/dev/nflasha18 /lens vfat rw,sync,dirsync,noatime,fmask=0022,dmask=0022,codepage=cp437,iocharset=ascii,shortname=mixed,posix_attr,avoid_dlink,errors=remount-ro 0 0
/dev/nflasha12 /cert vfat rw,dirsync,noatime,fmask=0022,dmask=0022,codepage=cp437,iocharset=ascii,shortname=mixed,batch_sync,posix_attr,avoid_dlink,errors=remount-ro 0 0
/dev/nflasha11 /log vfat rw,dirsync,noatime,fmask=0022,dmask=0022,codepage=cp437,iocharset=ascii,shortname=mixed,batch_sync,posix_attr,avoid_dlink,errors=remount-ro 0 0
none /sys sysfs rw,relatime 0 0
none /dev/pts devpts rw,relatime,mode=600 0 0
```

The retained E0302 capture (`artifacts/analysis/e0302-camera-scope/proc-mounts.txt`)
is identical except for one extra project helper mount, `none /tmp_bt tmpfs …
size=1024k`, which E0414 removed (`/tmp_bt` empty in the postcheck). The E0414
state is the clean baseline.

### 4.2 Init's internal mount table (22 records; identical in both init builds)

| # | device | target | fstype | flags | data |
| --- | --- | --- | --- | --- | --- |
| 0 | `proc` | `/proc` | proc | 0x0 | — |
| 1 | `none` | `/sys` | sysfs | 0x0 | — |
| 2 | `/dev/nflasha2` | `/setting` | vfat | 0xc0ed0490 | `posix_attr` |
| 3 | `/dev/dnflasha3` | `/system` | vfat | 0xc0ed0001 | `posix_attr` |
| 4 | `/dev/nflasha3` | `/system` | vfat | 0xc0ed0490 | `posix_attr` |
| 5 | `/dev/nflasha10` | `/tmp` | vfat | 0xc0ed0490 | `posix_attr` |
| 6 | `/dev/nflasha15` | `/usr` | cramfs | 0xc0ed0001 | — |
| 7 | `/dev/dnflasha15` | `/usr` | ext2 | 0xc0ed0001 | — |
| 8 | `/dev/nflasha15` | `/usr` | vfat | 0xc0ed0490 | `posix_attr` |
| 9 | `/dev/nflasha9` | `/usr/upgrade` | vfat | 0xc0ed0490 | `posix_attr` |
| 10 | `/dev/nflasha23` | `/log` | vfat | 0xc0ed0490 | `posix_attr` |
| 11 | `/dev/nflasha24` | `/log` | vfat | 0xc0ed0490 | `posix_attr` |
| 12 | `/dev/nflasha25` | `/log` | vfat | 0xc0ed0490 | `posix_attr` |
| 13 | `/dev/ms1` | `/log` | vfat | 0xc0ed0490 | `posix_attr` |
| 14 | `/dev/nflasha10` | `/log` | vfat | 0xc0ed0490 | `posix_attr` |
| 15 | `/dev/nflasha18` | `/lens` | vfat | 0xc0ed0490 | `posix_attr` |
| 16 | `/dev/nflasha15` | `/usr` | ext2 | 0xc0ed0001 | — |
| 17 | `/dev/nflasha11` | `/log` | vfat | 0xc0ed0490 | `batch_sync,posix_attr` |
| 18 | `/dev/dnflasha7` | `/rootfs` | ext2 | 0xc0ed0001 | — |
| 19 | `/dev/nflasha7` | `/rootfs` | ext2 | 0xc0ed0001 | — |
| 20 | `/dev/nflasha12` | `/cert` | vfat | 0xc0ed0490 | `batch_sync,posix_attr` |
| 21 | `/dev/nflasha10` | `/etc` | vfat | 0xc0ed0490 | `posix_attr` |

The records are at the tail of `.data` in both builds; only the table base address
differs (`0x13308` preserved, `0x132e0` live). `/etc` is the **last table record**
(it is mounted after `/tmp` in the call order); because no static image carries an
`/etc` directory, any `/etc/ld.so.preload` can only come from the writable
`nflasha10` vfat. **[C]**

### 4.3 Mount call order recovered from `main` (identical in both builds)

```
mount_partition(mnts[0])                     # /proc            (first call in main)
mount_partition(mnts[18])                    # /dev/dnflasha7 -> /rootfs
mount_partition(mnts[19])                    # /dev/nflasha7  -> /rootfs (fallback)
chdir("/rootfs"); pivot_root(".", "initrd")  # syscall 218; old root is put under /initrd
mount_partition(mnts[7])                     # /usr ext2 (dnflasha15)
mount_partition(mnts[16])                    # /usr ext2 no-compress  (fallback)
mount_partition(mnts[6])                     # /usr cramfs            (fallback)
mount_partition(mnts[8])                     # /usr vfat              (fallback)
mount_partition(mnts[5])                     # /tmp    /dev/nflasha10
mount_partition(mnts[21])                    # /etc    /dev/nflasha10
mount_partition(mnts[3])                     # /system dnflasha3
mount_partition(mnts[4])                     # /system nflasha3 vfat (fallback)
mount_partition(mnts[2])                     # /setting /dev/nflasha2
mount_partition(mnts[17])                    # /log    /dev/nflasha11 (batch_sync)
mount_partition(mnts[15])                    # /lens   /dev/nflasha18
mount_partition(mnts[20])                    # /cert   /dev/nflasha12 (batch_sync)
set_oreore_env()                             # optional /setting/env.txt merge
insmod_drivers(drivers2, 31)                 # second driver phase
... start /usr/bin/bootin.elf (run_bg_process) ...
mount_partition(mnts[1])                     # /sys    sysfs (after userland start)
putenv("LD_PRELOAD="); launch_shell()        # -> /usr/bin/launch_shell.elf (PID 1)
```

After `pivot_root`, the early `/proc` mount (made on the old root) is relocated
into the new root with a `MS_MOVE` (0x2000) mount from `/initrd/<target>` to
`/<target>`; this is the `move_partition` path whose failure string is in the
binary. `/dev/pts` (devpts) is **not** in the init table: `bootin.elf` mounts it
after it runs (`mount("none", "/dev/pts", "devpts", 0xc0ed0000, …)`, §3.2).
`/tmp/lt` tmpfs is created by `bootin.elf` only in the LeakTracer debug mode. **[C]**

### 4.4 Final device per target, as observed in `/proc/mounts`

| target | table candidates | observed device / fstype | result |
| --- | --- | --- | --- |
| `/` | 18, 19 | `/dev/nflasha7` ext2 ro | dnflasha7 unavailable → uncompressed fallback |
| `/usr` | 7, 16, 6, 8 | `/dev/nflasha15` ext2 ro | ext2 no-compress fallback used |
| `/tmp`, `/etc` | 5, 21 | `/dev/nflasha10` vfat rw | both on the same vfat partition |
| `/system` | 3, 4 | `/dev/nflasha3` vfat rw | dnflasha3 fallback |
| `/setting` | 2 | `/dev/nflasha2` vfat rw | — |
| `/lens` | 15 | `/dev/nflasha18` vfat rw | — |
| `/cert` | 20 | `/dev/nflasha12` vfat rw | `batch_sync` |
| `/log` | 10–14, 17 | `/dev/nflasha11` vfat rw | `batch_sync`; init only calls record 17 |
| `/sys` | 1 | sysfs | mounted late, after `bootin.elf` was launched |
| `/dev/pts` | — (not in table) | devpts | mounted by `bootin.elf` |
| `/usr/upgrade` | 9 | not mounted | no SD/upgrade state observed |

The vfat targets above are mounted read-write by the init when they are mounted
during boot; this note only records the resulting mount entries. E0414 itself
performed no camera-side write, and the device/mount state was unchanged
before/after. **[C]**

> **Ordering caveat:** `/proc/mounts` lists `/system`, `/setting`, `/lens`, `/cert`,
> `/log` while the init calls `/log` before `/lens`/`/cert`. The enumeration order
> of `/proc/mounts` is therefore **not** a reliable record of `mount()` call order
> on this kernel; §4.3 is the disassembly-derived call order. **[C]/[I]**

## 5. What actually starts, and the capture boundaries

The startup chain implied by the binaries and the retained `/proc` snapshot:

```
kernel env {HOME=/, TERM=linux}
  -> /sbin/init (initrd -> pivot_root -> same binary in rootfs)
       mounts per §4.3, default env per §3.1, optional /setting/env.txt
       -> run_bg_process(/usr/bin/bootin.elf)
            -> mount devpts /dev/pts; no LD_* added (normal mode, no dmode file)
            -> system("im.elf debug s g r u l i a lazy-global &")
                 -> im.elf (PID 149; env per §3.5; no LD_PRELOAD / LD_LIBRARY_PATH)
       -> mount /sys; putenv("LD_PRELOAD="); launch_shell()
            -> /usr/bin/launch_shell.elf 0 1 (PID 1)
```

Boundaries and non-claims:

1. The live `/usr` (`nflasha15`) image was never dumped; `/usr` conclusions are
   pinned to the preserved v2.00 image. The live camera's `/usr/lib/libObj.so`
   already differs from the extracted one (E0302 header check), so the live
   `/usr/tool` contents and change_mode behaviour are not identity-matched here.
2. The runtime `/etc` was only partially captured read-only (preload file, conf and
   conf.d existence). A complete `/etc` listing (e.g. shell rc files, if any) was
   never taken; no `rcS`/`inittab` on `nflasha10` is therefore *not proven absent*,
   only not observed. This does not change the init path: the init is a compiled C
   program that never opens an rc script (its only shell invocations are fixed
   `system()` commands such as `dosfsck`/`swap_prepare.sh` and the `/bin/ash
   --login` fallback loop).
3. `/setting/mode/dmode`, `/setting/mode/preload` and `/setting/env.txt` were
   absent in the E0307 read-only `/setting` dump; if they exist on another boot
   they enable arbitrary debug preloads/environment. They are factory debug
   mechanisms, not factory defaults, and creating them would be a persistent flash
   write outside this project's read-only scope.
4. The two `/etc/ld.so.preload` entries are project-installed diagnostics
   (touch probe and USB debug launcher). They are not Sony factory content; they
   apply to newly `exec`'d processes and not to hibernation-restored `im.elf`.
5. The environment snapshot is a single retained observation (E0302, 2026-11-10);
   later `/setting` changes by the owner could change a future boot.
6. No camera access, no USB, no mode switch, no flash/SD write, no source or test
   change occurred for this note. The suite was not rerun here: this round only
   added files under `artifacts/` plus this document, and the current repository
   checkpoint already records the suite baseline (E0418: 1,462 tests OK). A local
   attempt to run the suite was stopped by a sandbox denial on a system temporary
   path, not by a test failure; no test result is claimed here.

## 6. Reproduction

All offline, from the repository root, with the project venv:

```powershell
python artifacts\analysis\e0418b-userspace\scan_userspace_startup.py
python artifacts\analysis\e0418b-userspace\disasm_init.py `
  artifacts\analysis\e0418b-userspace\live-initrd-sbin-init.elf `
  artifacts\analysis\e0418b-userspace\init-live-8260.disasm.txt
```

Artifacts (all under the git-ignored `artifacts/`):

| path | content |
| --- | --- |
| `artifacts/analysis/e0418b-userspace/report.json` | machine-readable result of every check above |
| `artifacts/analysis/e0418b-userspace/extract_ext2.py` | read-only ext2 reader (validated: the parsed preserved initrd equals the existing `initrd.img_unpacked` tree byte-for-byte) |
| `artifacts/analysis/e0418b-userspace/scan_userspace_startup.py` | reproducible scanner (hashes verified before use) |
| `artifacts/analysis/e0418b-userspace/disasm_init.py` | ARM/Thumb disassembler with PLT and literal-pool resolution |
| `artifacts/analysis/e0418b-userspace/live-initrd-sbin-init.elf` | extracted live init (hash `1dbe18fe…`) |
| `artifacts/analysis/e0418b-userspace/init-live-8260.disasm.txt`, `init-preserved-v200.disasm.txt` | annotated disassembly used for §3–§4 |
| `artifacts/analysis/e0418b-userspace/initrd-live/` | materialised live initramfs tree (audit only) |

No product source, test, CI or status-card file was changed by this round.
