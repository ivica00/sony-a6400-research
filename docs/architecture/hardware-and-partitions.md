# Hardware, Flash Partitions & Peripheral Contracts

Consolidated hardware reference from `E0222`, `E0298`, `E0305–E0314`, `E0414–E0415`, and `E0468–E0476`.

## 1. Flash & Storage Partition Map (`a6400`)

| Device | Size | Mount / Role | Access / Evidence |
| --- | --- | --- | --- |
| `/dev/nflashaB0` | 4 MiB | Boot area: `EXBL` container + `DGU5` loader (`V85.00.03`) | Readable `O_RDONLY` (`E0414`, `E0415`) |
| `/dev/nflashaB1` | 4 MiB | Secondary boot area (all 4 MiB zero on observed unit) | Readable `O_RDONLY` (`E0414`) |
| `/dev/nflasha1` | 8,323,072 B | Updater FAT12 (`boot/{kemco.txt,loadaddr.txt,initrd.img,vmlinux.bin}`) | Readable `O_RDONLY` (`E0306`, `E0414`) |
| `/dev/nflasha2` | 20,971,520 B | `/setting` (rw FAT12: `Backup.bin`, `DmmConfig.bin`, `psd.bin`, `updater/dat4`) | Readable `O_RDONLY` (`E0307`) |
| `/dev/nflasha3` | 50,331,648 B | `/system` (rw FAT12: live `vmlinux.bin` 8.2.6.0, `initrd`, payloads) | Readable `O_RDONLY` (`E0414`, `E0415`) |
| `/dev/nflasha4` | 12,582,912 B | Raw MPR partition (`emmc.ko` ioctl `0x80014123` → `0x00`) | Readable `O_RDONLY` (`E0305`) |
| `/dev/nflasha7` | — | `/` rootfs (ro) | Firmware / `E0486` |
| `/dev/nflasha15` | — | `/usr` application libraries (ro) | Firmware / `E0486` |
| `/dev/nflasha16` | — | `/android/system` (ro) | Firmware / `E0486` |
| `/dev/nflasha23` (`B:`) | — | Internal flash (`B:` drive) — **excluded from journal writes** | `E0222` |
| `/dev/mmca` (`A:`) | — | Physical SD card (`A:` drive) | `E0222` |

**Runtime writable mounts (`E0486`)**: `/setting`, `/system`, `/tmp`, `/log`, `/android/data`, `/lens`.

## 2. Display & GPU (`E0298`, `E0313–E0314`)

- **Verified Display**: OSD A/B `640×480` RGBA4444 (captured safely via `im.elf` ptrace in `E0298`). `gl_common+0x1000` (`960×540`) is an internal buffer, not the screen.
- **GPU**: DMP **SMAPH-S30** (not PICA200); private ISA blocks full rasterization.
- **GPES BAR (`0xF1000000`, 128 KiB)**:
  - Word `0x00 = 0x000b0000` (identity); IRQ status at `+0x34` (`0x40000000`, `0x80000000`); acks at `+0x1000`/`+0xC18`, `+0x1C`, `+0x3C`/`+0x44`; command block `+0xE8..+0x170`.
  - `grm_gles.ko` ioctls: `0x8004820A` (suspend/status), `0xC004820D` (wait-completion, blocks thread until `0x820E`), `0xC004820E` (signal), `0xC0048203` (event-wait), `0x8209` (consume), `0x820F` (kick latch).

## 3. USB Gadget (`DWC3` / `gadgetcore`, `E0468–E0476`)

- **Host-bindable composite (`054C:0322`)**: Parent + PTP (`MI_00`) + UVC (`MI_01`).
- **EP0 Status-OUT Forensics (`E0468`, `E0471`)**: Camera arms EP0 OUT status TRB (`ep0state=3`, `next=1`) within `16.388 ms`, but the host's single Status OUT arrives during the `NRDY→arm` window, gets NAK'd, and the Windows 5.000 s control timeout aborts `GET_CUR` (`0xA1 0x81`).
- **Status Pre-Arm Fix (`E0476`)**: `a6400_uvc_status_prearm` in `uvc_callback_bridge.c` sets `dwc->ep0state=3` and calls `__dwc3_ep0_do_control_status(dwc, dwc->eps[0])` (`0x602b253c`) at class data-stage completion, preventing the missed Status OUT window (offline Unicorn-verified `8/8 PASS`, `117/8/0` audit, awaiting explicit GO for Run B26).
