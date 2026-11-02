# Evidence 0056: Read-only SD inputs and update-path investigation

## Scope and result

The user redirected research from UI startup to determining whether SD-provided inputs could eventually support custom updates, and identified the original camera card mounted at `E:\`. This milestone inventories real inputs and locates original-code research entry points. **No exploitable parser bug, SD boot trigger, accepted custom image, signature bypass, or persistent update path has been established.** Main firmware execution/UI remains E0034; no guest contract was changed.

All research tools opened card files only for reading. No payload was generated, card file modified, camera operation performed, updater/script executed, or device write requested. This is a mounted-filesystem survey, not a raw forensic acquisition or hardware write-protected image. Private photographs and video were neither displayed nor decoded/copied into the project.

## Card observations

The allowlisted camera trees contain **81 files**:

| Extension | Count |
| --- | ---: |
| ARW | 49 |
| JPG | 8 |
| MP4 | 7 |
| XML | 8 |
| BDM | 2 |
| BIN | 2 |
| BNP, INP, INT, IND, BAK | 1 each |

Camera root trees are `DCIM`, `PRIVATE`, and `AVF_INFO`; PRIVATE contains AVCHD, M4ROOT and SONY directories. Windows system directories are excluded. Reparse points/symlinks are not followed. Reports retain relative filenames, sizes and at most64-byte prefixes. Only non-media metadata of at most8MiB receives a full SHA-256; media prefix hashes must **not** be called complete file identities. File size/mtime are checked around acquisition to detect changes. Local reports can contain personal filenames/header metadata and are not public fixtures.

`artifacts/analysis/sd-surface-verified/card-inventory.json` and repeat are byte-identical, SHA-256 **21bb07f3f2d4c4232e43ef1fa6e39519365d13c67c1925ccf40067c2667c769d**. This does not identify unallocated space, deleted files, a complete volume or complete media content.

## Firmware survey and playback leads

The survey checks **374 inventoried .so/.elf/.sh/.src inputs** against preserved baseline hashes before/after scanning. It excludes whole containers and other suffixes, and is therefore not an exhaustive firmware search. Each string lead retains source path/hash/file offset and bounded text; counts precede per-category output caps. First reports are retained; verified/repeat use category-specific retention and stricter SD word matching to avoid misleading `Osd`/`Ssdp` substring hits.

Final `firmware-leads.json` reports are byte-identical, SHA-256 **f9eb130ecd180ae3221cf261631cc7bf129f2a3e7539e684330cbc66922dc9f5**. `libmpr.so` and `libObj.so` contain camera-layout/parser strings. Matches establish candidates, not execution or vulnerabilities. In particular, apparent `ParseExif` command-interface names must not automatically be treated as the low-level media parser.

`sd_firmware_profile` retains six small original Thumb function windows, ELF identities, DT_NEEDED declarations and recognized direct-call labels:

| Library | Original symbol entry | Lead |
| --- | --- | --- |
| libmpr.so | 0x3caf9d | PlayStill::GetRawMakerNote |
| libmpr.so | 0x3a7871 | PlayJpegThum::CopyReadStillStream |
| libmpr.so | 0x8a42d1 | MprIf::UpdateExtDeviceFirmware(unsigned long,unsigned long,unsigned long) |
| libmpr.so | 0x8e8b8d | ExtDeviceFirmUp::CheckCondition |
| libupdaterufp.so | 0x19fd | udtr_ufp_init |
| libupdaterufp.so | 0x1c59 | udtr_copy2dmm |

These coordinates include Thumb low bits and are linked ELF addresses. Unrecognized calls remain unnamed. External-device firmware APIs are **not evidence of camera-body updating**. The playback wrappers still need connection to filesystem reads, lower parsers and process context; no parser was fuzzed or exploited.

## Update source ambiguity resolved in one path

Original common.src files declare `MS_MOUNT_POINT=/mnt`, `DATSRC_SENSER=0`, `DATSRC_MS=1`, `DATSRC_ERROR=2`. `chkfirm.sh` contains `# NOT MSBOOT` above an `/root/IAMLDUDWRT` conditional. `startupdate.sh` labels that marker's branch `UPDATE_TYPE=Serial`. These labels are useful leads, **not proof that retail a6400 boots or updates from an SD file**. No marker was created and none of these scripts was run.

REA/Ghidra through native WSL analyzed the small installed `libupdaterufp.so`, SHA-256 **93ddfa0212f19ad0d204cc41a241ca3dadb0b049725812d48e2df50ba2f16f4f**. The first batch retained one result but failed because `udtr_copy2dmm` matched both PLT/import and implementation; it remains marked failed and was not promoted to a completed batch. The exact-address batch completed all three queries with source hash unchanged:

```
procedure_pseudo_code 0x119fc
procedure_pseudo_code 0x11c58
read_function_instructions 0x119fc
```

Provider coordinates are linked instruction addresses plus synthetic image base0x10000: original0x19fc -> REA0x119fc; original0x1c58 -> REA0x11c58. These are not camera runtime addresses. Planner ET_REL-only analysis does not support these ET_DYN targets, so this investigation uses targeted ELF windows and explicit REA entries rather than an invented dependency graph.

Original instructions and REA agree that `udtr_ufp_init` registers OSAL callback queues0x004b8290,0x004b0233,0x004b024e, then mounts **internal `/dev/nflasha1`** as vfat on `/mnt` and reads `/mnt/dat2` and `/mnt/dat3`. In this path `/mnt` therefore does **not** identify SD media. Actual callback delivery and mount/read results have not been executed or supplied.

REA's `udtr_copy2dmm` reconstruction shows an input filename parameter, `/dev/mem`, mappings and copying. The retained original window confirms open/mmap/memcpy/cleanup imports; caller-controlled source selection, destination ownership and authorization still require tracing. This static observation neither authorizes nor performs a device write and does not connect a photograph to the updater. E0011–13's existing original updater/storage research remains historical evidence, not a demonstrated custom update mechanism.

## Reproduction and next work

```
python -m tools.research.sd_surface_survey --card E:\ --report-dir artifacts/analysis/NEW_SURVEY
python -m tools.research.sd_firmware_profile --report-dir artifacts/analysis/NEW_PROFILE
```

Reports: `sd-surface-first`, `sd-surface-verified`, `sd-surface-repeat`, `sd-firmware-profile`; REA: `sd-update-ufp-first` (failed/retained), `sd-update-ufp-exact` (completed3/3). Preserved firmware hashes are never refreshed to accept changed sources.

Next priorities:

1. Follow original RAW/JPEG playback wrappers to actual byte reads and lower parser entry points, separating thumbnail, EXIF/MakerNote and full-image processing. Establish lengths, bounds and process/privilege context before bounded isolated tests.
2. Find consumers/producers of the MS source selector and updater boot marker; distinguish legacy/shared support, Memory Stick, SD, USB/IPC and internal flash staging. Trace package validation and actual reachability before discussing accepted custom updates.
3. Keep parser execution, privilege escalation, flash writing, boot validation and recovery as distinct evidence requirements. None follows automatically from finding an unchecked-looking expression or a writable device name.

Three constructed-card tests check bounded media acquisition, complete small-metadata identity, exclusion of unknown root directories, unchanged media bytes and the large-metadata cap. Full suite **357 passing tests**, `artifacts/execution/sd-surface-suite.txt`. Status image regenerated without increased compatibility counts.
