# E0237 — Offline path-contract execution: 8.3 rejection, not empty letter table

Date: 2026-11-09. Offline only; no camera access and no SD write. This corrects the path diagnosis in E0236.

## Inputs and method

- Original `libInfraFsys.so`, SHA-256 `75f24fd03f4a187563622d6320f0690108fa6e231ac6e84cbda9303b8dc9af2c`.
- New tool `tools/research/probe_uvc_sd_fsys_path.py` executes the original Thumb-2 bodies of `fsys_GetDriveInfoFromPath` (0x16af0) and `fsys_CreatePathInfo` (0x1cff8) under Unicorn, with the library's GOT relocations applied, a synthetic drive record at 0x210000 (`A`, `"/dev/mmca"`, device length 10), fixture letter/device table entries, and explicit service doubles for device-id, mutex, lock/unlock and `memcpy`.
- Run log: `artifacts/uvc-sd-fsys-path-e0237-run.log`; report: `artifacts/analysis/uvc-sd-fsys-path-e0237/manifest.json`.

## Results (13/13 cases as expected)

`fsys_CreatePathInfo` (return 1 accept / 0 reject):

| Path | Result |
| --- | --- |
| `A:/A6400J.DAT` | **1** |
| `A:/a6400_journal_e0235.dat` | **0** |
| `A:/A6400_J.DAT` | 1 |
| `A:/a6400j.dat` | 1 |
| `A:A6400J.DAT` | 1 |
| `/dev/mmca/A6400J.DAT` | **1** |
| `/dev/mmca/a6400_journal_e0235.dat` | **0** |

`fsys_GetDriveInfoFromPath`:

| Case | Result |
| --- | --- |
| letter entry present | 0 (success, drive record written) |
| letter entry empty | **0x80000031** |
| device entry present, id 0 | 0 |
| device entry empty | 0x80000041 |
| device id unknown | 0xffffffff |
| path without `X:` | 0x80000041 |

## Correction to E0236

The physical `Fsys_Open err 0x80000041` for `A:/a6400_journal_e0235.dat` is explained by **`CreatePathInfo` rejecting the filename**, not by an empty PC Remote letter table. An empty letter entry would have returned `0x80000031`, which was not observed. The parses show a name/extension limit consistent with 8.3: an 8+3 name is accepted, while the 21-character stem is rejected, including in the device-path form. Lowercase and an underscore inside an 8.3 name are accepted.

Consequences: a future journal attempt should use an 8.3 letter path such as `A:/A6400J.DAT` (the device path `/dev/mmca/A6400J.DAT` also normalizes, but `IFSYS cmp` treats a leading `/` as a Linux file, so the letter path is the one usable for readback). The existing E0235 build still embeds the old long path and must be rebuilt with the 8.3 name before any future physical attempt.

## Limits

Fixtures, not a live volume; the reboot fault recorded in E0236 still blocks physical sessions, and no live letter/device table was read. This proves the original normalizer/resolver contracts under explicit fixtures, not mount ownership, file creation or durability.
