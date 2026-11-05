# Evidence 0078: `Backup_read_multi`, WBI `/dev/stream` Log Area (`0x20030000`), and `/dev/mmca-char` Boundary (88.27M Milestone)

**Date**: 2026-11-04
**Status**: Verified
**Test Suite**: 528 passing unit tests

---

## 1. Executive Summary

Following the `/dev/cec` driver contract (Evidence 0077), execution stopped at 87,946,134 instructions in `TID 1004 (THREAD_INFRA1)` on UIPC queue `0x003e014d` (`Backup` service operation `5`).

In this milestone:
1. **`libbackup.so` / `backup.ko` Multi-Unit and Sync Contracts (`src/a6400/execution/backup_service.py`)**:
   - Reverse-engineered `backup_osal_call_func` (`0x5204` in `backup.ko`) jump table (`0x5248`, 39 entries) and `libbackup.so` wrappers:
     - Operation `1` (`0xd68`): `Backup_get_datasize_multi(units_ptr, sizes_ptr)` — validates a 0-terminated unit array and returns the sum of unit sizes (or `-1` if any unit is missing), optionally writing individual sizes to `sizes_ptr`.
     - Operation `5` (`0x144c`): `Backup_read_multi(units_ptr, dst_ptrs_ptr)` — iterates a 0-terminated unit array, copies each unit's preset bytes to `dst_ptrs[i]`, and returns the count of units read (or `-1` on missing unit).
     - Operation `10` (`0x1940`): `Backup_write_multi(subsystem, units_ptr, src_ptrs_ptr)` — validates subsystem ownership (`(unit >> 16) == subsystem`, else `-4`) and existence (`-1`), mutates each unit in RAM, and returns the count of units written.
     - Operation `14` (`0x1a3c` / `0x5704`) & Operation `15` (`0x1bd8` / `0x575c`): `Backup_sync_subsystem(subsystem)` and `Backup_sync_all()` — store `0` to `msg_ptr + 4`.
     - Operation `31` (`0x1550`): `Backup_nread_multi(units_ptr, dst_ptrs_ptr, capacities_ptr)` — multi-unit capacity-checked read.

2. **`mcmn_mmap_init`, `mcmn_buf_init`, and WBI Section 555 `/dev/stream` Backing (`0x20030000`)**:
   - At 88,128,963 instructions, `THREAD_INFRA1` enters `mcmn_mmap_init` (`0x21ec0` in `libInfraMediaCommon.so`), calling `open64("/dev/stream", O_RDWR | O_DSYNC)` which passes `flags = 0x21002` (`O_RDWR | O_DSYNC | O_LARGEFILE`) and opens `fd = 24`.
   - `mcmn_buf_init` (`0x96c8` in `libInfraMediaCommon.so`) reads BK4 preset units `0x00fa002a` (`0x20030000`) and `0x00fa005f` (`0x00068000` = 425,984 bytes) and maps `/dev/stream` at `PA 0x20030000..0x20098000` (`416 KiB`), matching the live hardware mapping in `reports/a6400_hw_dump.txt` (`L924: 0aeb8000-0af20000 rw-s 20030000 fc:07 287 /dev/stream`).
   - `mcmn_log_init` (`0x1c8c4` in `libInfraMediaCommon.so`) carves out the first `0x8000` bytes (`2 x 0x4000` ring buffer slots) at `PA 0x20030000` and checks the 12-byte header `[0xaa55aa55, 0xc3c3c3c3, 0x00004000]` at `0x1ca12..0x1ca26`.
   - Verified that WBI Section 555 (`nflasha5`, `PA 0x20028000..0x20108000`) contains at offset `0x8000` (`PA 0x20030000`) the exact header `55aa55aa c3c3c3c3 00400000` and `IMCMN`/`IMD`/`IMM`/`IFSYS` version strings.
   - Extended `GuestStream` (`src/a6400/execution/guest_stream.py`) to support `open64` (`0x21002`), multiple disjoint physical mappings (`self.mappings`), and WBI Section 555 backing for `(0x20030000, 0x68000)`.

3. **Execution Milestone (88.27M Instructions — `/dev/mmca-char` Boundary)**:
   - Execution advances from 87,946,134 to **88,268,051 instructions** (+321,917 instructions).
   - Serviced syscalls increase from 2,185 to **2,275** (+90 serviced syscalls).
   - Open file descriptors increase from 74 to **75** (`fd = 24: /dev/stream`).
   - `THREAD_INFRA1` completes `mcmn_mmap_init`, `mcmn_buf_init`, and `mcmn_log_init`, and reaches `open64("/dev/mmca-char", O_RDWR | O_NOATIME | O_LARGEFILE)` (`flags = 0xa0002 = 655362`, major 250, minor 0) to begin SD/MMC media communication!

---

## 2. Boundary Diagnosis at 88.27M Instructions

```text
==============================================================================
=== A6400 EMULATOR BOUNDARY & GROUND-TRUTH DIAGNOSIS ===
==============================================================================
Status              : unsupported_filesystem
Instructions        : 88,268,051
Serviced Syscalls   : 2,275
Active Thread       : TID 1004 (THREAD_INFRA1) [27 total threads]
Syscall (r7=5  )    : sys_open(const char *pathname, int flags, mode_t mode)
------------------------------------------------------------------------------
Raw Boundary        : {"reason": "open_flags_not_read_only_subset", "path": "/dev/mmca-char", "flags": 655362, "pc": 1342755142, "r7": 5, "arguments": [1393785516, 655362, 0]}
------------------------------------------------------------------------------
Ground-Truth Matches in reports/a6400_hw_dump.txt (6 hits):
  [GT] L202: 250 mmca-char
  [GT] L292: crwxrwxrwx    1 0        0         250,   0 Feb 23  2018 /dev/mmca-char
==============================================================================
```

---

## 3. Verification & Test Suite

- Added unit tests in `tests/test_backup_service.py` and `tests/test_guest_stream.py`.
- Full unit test suite passes (**528 tests passing**).
