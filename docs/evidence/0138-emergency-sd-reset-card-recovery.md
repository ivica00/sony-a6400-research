# E0138: Emergency SD Reset Card Recovery

Date: 2026-11-07. Following a cold boot with 1080p NVRAM configuration where the video recording engine and USB interface stalled, the user requested an emergency SD card reset procedure on drive `E:`.

## 1. Problem & Architecture Diagnosis

1. **Root Cause of Cold Boot Stall**:
   On cold boot, the camera's proprietary video pipeline (`im.elf`) reads `/setting/Backup.bin`. When configured with `force_backup=1` and `width=1920`, the video pipeline's hardware scaler initialization timed out or rejected the parameters, stalling the userland recording and USB services.
2. **SD Card Filesystem Requirement**:
   Inspection revealed `E:` was previously formatted as NTFS. The Sony camera kernel (`3.0.27_nl-rt106+`) does not support NTFS (`proc_filesystems` contains only `vfat` for block devices). When `/tmp/autoexec.sh` ran `mount -t vfat /dev/mmca1 /mnt`, the mount failed.
   - Formatted `E:` as **FAT32** (`SONY_SD`, 7.4 GB) with standard `MSDOS5.0` boot sector.

## 2. Emergency Recovery Payload Deployed to `E:`

1. **Authentic Factory Pre-Image**:
   - `Backup.original.bin` / `Backup.bin`: 1,171,036 bytes, SHA-256 `11860ebe42f3b248284cfb3409ee65f18e658acd893658b5811c706ef709982a` (verified matching the pre-patch state).
2. **Freestanding ARM Native Recovery Tool (`emergency_restore_arm`)**:
   - 3,196 bytes, direct ARM Linux `svc 0` syscalls.
   - Restores `/setting/Backup.bin` from `Backup.original.bin`.
   - Deletes `/etc/ld.so.preload` (disabling all boot hooks permanently).
   - Unlinks all `/tmp` locks and homebrew binaries.
   - Replaces `/tmp/autoexec.sh` with a clean `exit 0`.
   - Creates killswitch flags (`/mnt/disable_hook`, `/mnt/disable.txt`).
   - Writes status to `/mnt/EMERGENCY_RESTORE.log` and calls `sync()`.
3. **Redundant Execution Triggers**:
   - `watchdog.sh` (executed by `/tmp/autoexec.sh` line 98).
   - `modern_menu` (copied to `/tmp/modern_menu` and executed by `/tmp/autoexec.sh` line 110).
   - `autoexec.sh`, `restore.sh`, and `a6400hb/watchdog.sh` for legacy/alternative triggers.

## 3. Verification

- All recovery files verified on `E:\`.
- Full project test suite: 599 tests pass in 18.426s (`Ran 599 tests in 18.426s. OK.`).
- Physical volume source `E:` verified online as FAT32.
