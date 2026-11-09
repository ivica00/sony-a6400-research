# E0235 — Bounded SD-journal collector (offline build)

Date: 2026-11-09. No camera access in this step: build, static command contracts and host fixtures only. No SD write.

## Inputs

- Original `libInfraFsys.so`, SHA-256 `75f24fd03f4a187563622d6320f0690108fa6e231ac6e84cbda9303b8dc9af2c`, exact Ghidra 12.1.4 reconstructions in `artifacts/tools/rea/fsys-command-journal-e0223`, `artifacts/tools/rea/fsys-path-exact-e0220`, `artifacts/tools/rea/fsys-createpath-e0235` and `artifacts/tools/rea/fsys-drive-query-e0228`.
- New build `artifacts/native/monitor-sd-journal-e0235`: `native_monitor_collector.elf` 24,652 bytes, SHA-256 `e9e1e9b6abb068a7be3fa789b8ca3c084294c95915b39b585e18f75cfaf48089`; sources are the collector, the output/ack helper and the snapshot header, compiled against the preserved Sony libc.
- The compile was run through `wsl.exe --cd <project> --exec arm-linux-gnueabi-gcc` because the Windows-Python nested WSL launch returned `Wsl/E_ACCESSDENIED`; the compiler arguments are identical to `tools.research.build_native_monitor_collector` and are recorded in the manifest.

## Command contracts used

- `IFSYS writeandflash path size ival` allocates 1 MiB and fills consecutive 64-bit words `ival, ival+1, …`; opens with flags `6` (create + write; an existing file is reopened, not O_EXCL), calls `Fsys_WriteAndFlush` per chunk, closes. It prints `Write To …` and `Fsys_Open err 0x…`/`write err 0x…`, but no readback. Command return `1` is not write proof.
- `IFSYS cmp infile outfile` treats a leading `/` as a Linux file and a `x:` name as PrFile, compares both contents, and prints `File Contents Differ`, `File Size Differ`, `Can't open file …` or `illegal file name`; identical content prints nothing before the prompt.
- `IFSYS dump path [offset] [cnt]` opens PrFile read-only (flags `1`) and prints a hex dump through `printf`; open errors print a numeric `Fsys_Open err`.
- `IFSYS flush path` opens flags `6`, calls `Fsys_Flush`, closes and prints `Fsys_Flush OK`; `IFSYS ls path` lists names through `printf`.
- `fsys_CreatePathInfo` normalizes letter paths and a separate device-path form; `fsys_GetDriveInfoFromPath` returns `0x80000041` when the letter table entry or device lookup is absent.

## Collector design

Fixed target `A:/a6400_journal_e0235.dat`, 64 bytes, initial value `0xE0235000`; a run-owned `/tmp_bt/mon_sd_<stamp>.expected` holds the exact expected bytes (eight little-endian u64 words). The write session runs fixed steps: `getdriveinfo A`, `cmp expected expected` (proves the app can read the expected RAM file), `cmp journal journal` (absence gate), `writeandflash`, `cmp expected journal` (byte readback), `flush`, `cmp expected journal` again. A restart-verify session runs only `getdriveinfo A` and `cmp expected journal`. A probe session runs `ls /dev/mmca/`, `dump /dev/mmca/<target>` and `dump A:/<target>` after the first command passes SD identity, then reads the live Fsys letter/device tables. No arbitrary command text: all command strings are compile-time constants; only the validated expected path is passed in.

## Checks

- 21 compiled ARM admission cases pass (`artifacts/native/monitor-journal-admission-e0235`), unchanged ack/probe/prefix policies.
- 15 mocked collector cases pass (`artifacts/native/monitor-sd-journal-e0235/collector-check.log`): 11 pre-existing passive/query cases plus journal success, pre-existing-target abort, write-error abort and one probe case.
- 624 tests pass in 17.933 s (`artifacts/monitor-sd-journal-e0235-tests.log`), run with `TMP`/`TEMP` redirected to `artifacts/tmp` because the sandbox denies child-process writes to the system Temp directory; the earlier interpreter probe result remains valid.
- Manifest records exact hashes, the launcher workaround and the limitations.

## Later rebuilds and limits

Later offline iterations added a 30 s settle sleep and an `--sd-idle` mode; the current manifest in `artifacts/native/monitor-sd-journal-e0235` records the final ELF SHA-256 `0a11b40ed751218bf08af94d85638f6f94050f9d6cc3df6ca8805fbafa8112e7`. E0237 subsequently proved that the embedded target name `A:/a6400_journal_e0235.dat` is rejected by the original 8.3 normalizer; the collector must be rebuilt with an 8.3 name such as `A:/A6400J.DAT` before any future physical attempt.

## Limits

Creation is not O_EXCL; the absence gate is not atomic against another writer. `cmp` cannot express device paths, so readback is limited to letter paths or `dump`'s `printf` output, whose capture by the monitor ring is unverified. The device-path form is statically supported but unproven. No physical deployment or SD write occurred in this step; the physical attempt is recorded in E0236.
