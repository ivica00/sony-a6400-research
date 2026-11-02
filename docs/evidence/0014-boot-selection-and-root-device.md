# E0014 — Boot mount selection, device node resolution, and runtime mount state

Date: 2026-10-18. Scope: static analysis of `initrd` boot scripts, `sbin/init`, kernel module `devno.ko` (`udif_devnodes`), and `0100_config/mount.conf`. No camera write, updater execution, or simulated hardware service is invoked.

## Findings

1. **Device Major/Minor Allocations (`devno.ko`)**:
   `kmod/devno.ko` provides the exported kernel symbol `udif_devnodes` containing 88 device node descriptor entries:
   - `nflasha`: `type=1` (block device), `major=252` (`0xfc`), `base_minor=0`, `count=32`.
   - `dnflasha`: `type=1` (block device), `major=252` (`0xfc`), `base_minor=128` (`0x80`), `count=32`.
   - Both compressed (`dnflasha`) and uncompressed (`nflasha`) flash partitions share **major number 252**. Partition numbering maps directly to `base_minor + partition_index`.

2. **Boot Mount Sequence (`sbin/init`)**:
   `initrd` and `rootfs` share an identical unstripped ELF binary `sbin/init` (SHA-256 `0af5724e...`). The binary mounts partitions using an internal table `mnts` (22 entries at `.data + 0x13308`):
   - **Phase 1 Modules**: `drivers1` (4 modules) are loaded: `/kmod/devno.ko`, `/kmod/dmac.ko`, `/kmod/ldec.ko`, and `/kmod/emmc.ko tbl=0x80000000`.
   - **Rootfs Mounting**: `init` first attempts to mount `/dev/dnflasha7` -> `/rootfs` as `ext2` with flags `0xc0ed0001` (`MS_MGC_VAL | MS_RDONLY`). If this fails, it executes the fallback mount of `/dev/nflasha7` -> `/rootfs` as `ext2`.
   - **Pivot Root**: Upon mounting `/rootfs`, `init` executes `chdir("/rootfs")`, `pivot_root(".", "initrd")` (`syscall 218` / `0xda`), `chroot(".")`, and sets `pvtroot_done = 1`.
   - **Usr Mounting**: Inside the pivoted rootfs, `init` attempts to mount `/dev/dnflasha15` -> `/usr` as `ext2`. If `dnflasha15` fails, it falls back to `/dev/nflasha15` as `ext2` ("trying no-compress"), followed by cramfs and vfat fallbacks.
   - **Runtime Partitions**: `init` mounts `/dev/nflasha10` to `/tmp` (vfat, `0xc0ed0490`), `/dev/nflasha10` to `/etc` (vfat, `0xc0ed0490`, read-write), `/dev/dnflasha3` to `/system` (vfat, fallback `/dev/nflasha3`), `/dev/nflasha2` to `/setting`, `/dev/nflasha11` to `/log`, `/dev/nflasha18` to `/lens`, and `/dev/nflasha12` to `/cert`.
   - **Phase 2 Modules**: `init` writes `"set"` to `/proc/udm/drivers` and loads `drivers2` (31 modules from `/usr/kmod/`).
   - **Userland Milestone**: Runs `/usr/bin/swap_prepare.sh`, then launches `/usr/bin/bootin.elf`.

3. **Resolved `st_dev` Values for Linux Kernel Contracts**:
   Linux kernel ARM EABI `stat64` encodes device IDs via `new_encode_dev(makedev(major, minor))`:
   - `/lib` (in partition 7, `/rootfs`):
     - **Compressed (`/dev/dnflasha7`)**: `major=252`, `minor=128 + 7 = 135` (`0x87`) -> `st_dev = 0x0000fc87` (**64647**).
     - **Uncompressed (`/dev/nflasha7`)**: `major=252`, `minor=0 + 7 = 7` (`0x07`) -> `st_dev = 0x0000fc07` (**64519**).
     - Note: `nflasha7` in firmware update payloads contains an uncompressed ext2 superblock (`magic 0xef53` at offset 1024), so direct mounts consume `0xfc07`, whereas compressed eMMC partitions consume `0xfc87`.
   - `/usr` (partition 15):
     - **Compressed (`/dev/dnflasha15`)**: `major=252`, `minor=128 + 15 = 143` (`0x8f`) -> `st_dev = 0x0000fc8f` (**64655**).
     - **Uncompressed (`/dev/nflasha15`)**: `major=252`, `minor=0 + 15 = 15` (`0x0f`) -> `st_dev = 0x0000fc0f` (**64527**).
   - `/etc` (partition 10):
     - **`/dev/nflasha10`**: `major=252`, `minor=0 + 10 = 10` (`0x0a`) -> `st_dev = 0x0000fc0a` (**64522**).

4. **Resolution of the `/etc` Overlay Boundary**:
   - `rootfs/etc` is completely empty in static firmware images (`0` files).
   - At runtime, `sbin/init` mounts `/dev/nflasha10` over `/etc` as a writable `vfat` filesystem (`flags=0xc0ed0490`: `MS_NOATIME | MS_DIRSYNC | MS_SYNCHRONOUS`).
   - Consequently, `/etc/ld.so.preload` and `/etc/ld.so.cache` do not exist in static firmware images; they require camera runtime state from `/dev/nflasha10`.
   - The `--respect-runtime-mounts` execution guard correctly stops at unsupplied `/etc` (3,091 instructions) because `/dev/nflasha10` is an unsupplied writable runtime partition.

## Inputs and reproduction

Artifacts verified against local baseline hashes:

| Input artifact | SHA-256 |
| --- | --- |
| `0700_part_image/dev/nflasha3_unpacked/initrd.img_unpacked/kmod/devno.ko` | `3b36fcea8687d7f29112a7008ce61fde9229679ebc24c65ec2d21cf3af632f56` |
| `0700_part_image/dev/nflasha3_unpacked/initrd.img_unpacked/sbin/init` | `0af5724ece7f60db2831b7a4e61829be369868027877cca0f921f981ae8dc7ad` |
| `0100_config/mount.conf` | `0ef2d463b13cb23995f83080e6189da9e1287566d0645f5b41d5c8da14fd8acd` |
| `0700_part_image/dev/nflasha7` | `305e289ecc1d768544af71c83d58ce23ec4d232be1e7572d9d4f68f0f12188cc` |
| `0700_part_image/dev/nflasha7_unpacked/sbin/init` | `0af5724ece7f60db2831b7a4e61829be369868027877cca0f921f981ae8dc7ad` |

Reproduction commands:
```powershell
.\venv\Scripts\python.exe -m tools.research.boot_mount_trace
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Output is recorded in `artifacts/inventory/boot-mount-trace.json`. The full test suite has **147 passing tests**.

## Limitations and boundaries

- Resolving `st_dev` (`0xfc07` uncompressed / `0xfc87` compressed) provides primary contract evidence for `stat64` on `/lib`.
- Inode timestamps (`st_atime`, `st_mtime`, `st_ctime`) remain runtime-variable; providing `st_dev` without timestamps maintains the guarded boundary unless explicitly allowed by policy.
- Runtime contents of `/dev/nflasha10` (the writable `/etc` and `/tmp` partition) are not present in firmware update packages and require either preserved physical camera partition dumps or explicit synthetic test mocks.
