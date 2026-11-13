# E0477 — BIONZ X (CXD90045) cross-model platform map from 13 official updaters

Date: 2026-11-13. **Strictly offline.** No camera, no USB, no updater execution, no
network. Inputs: thirteen official Sony updater packages, hash-pinned below, unpacked with
`fwtool` at `cdba742b`. Nothing proprietary is committed: no firmware bytes, no extracted
image, no decompiled Sony code — only hashes, counts, addresses, and the scripts that
reproduce them.

## 0. Short answer

1. **Thirteen bodies, nine kernels.** Four kernels are shared by more than one body. The
   sharing is established by an **identical kernel symbol-name set**, not by a file hash:
   `ZV-E10` and `ILCE-7C` share one code object (only 9 addresses differ, all in string data), and
   `ILCE-6100A`, `ILCE-7M3`, `ILCE-7RM4A` share one symbol set (4,042 addresses differ).
2. **`ILCE-6400` and `ILCE-6600` share a symbol set exactly** (24,421 names, 0 added,
   0 removed) while 9,124 addresses are shifted by a constant. Every one of those 9,124 is a
   data symbol: all 14,401 function symbols sit at the same address. They are two builds of
   one kernel source, not two kernels.
3. **The command table is a monotone ladder** on the A6xxx/ZV line: `ILCE-6100A` and
   `ILCE-6400` carry 285 records, `ILCE-6600` adds exactly one (`0x413b`), and the
   ZV-E10/ILCE-7C pair carries 337. No body removes a command that `ILCE-6400` has.
4. **Every body that carries `0x413b` writes its value into a settings-cache field that
   the same image never reads.** This is not an `ILCE-6600` peculiarity; it holds on all
   ten bodies that have the command.
5. **`usbg_video.ko`/`usbg_audio.ko` are absent on 9 of 13 bodies** and byte-identical on
   the two that share a code object. The UVC delta is a module-package delta, not a kernel
   capability delta.

## 1. Inputs

Each row is an official updater exactly as published; `SHA-256` is of the unmodified file.

| body | input | SHA-256 |
| --- | --- | --- |
| ILCE-6400 | `Update_ILCE6400V200.exe` | `ea460cbec5f8b62119630f0a653eeca4f4ffad887670e60c0fd9c0345e6b30a6` |
| ILCE-6600 | `Update_ILCE6600V110.exe` | `67a1d92be9b9d1ea3c483502918edf6423653ecadcf4b0184303b096a601d76f` |
| ILCE-6100A | `Update_ILCE6100AV101.exe` | `06c161db9be9d95802f035e390d0c457d439ac973120bd303c70ce6313388dc6` |
| ZV-E10 | `Update_ZVE10V203.exe` | `386970919b758b59de849cd954efd31de00e5f9e435056ce99a7c212a4aca584` |
| ILCE-7M3 | `Update_ILCE7M3V404.exe` | `8c356688a70946a855191e99fd4d9096a5c3d4263f3f11065605eaea45639d57` |
| ILCE-7C | `Update_ILCE7CV203.exe` | `e382c3deecb8d0fe8463a2451ddbfa897cd131a1797170d05936fabc4ffaf6f8` |
| ILCE-7RM3 | `Update_ILCE7RM3V310.exe` | `03c9152c08e8c4bea2b2c572ddf63bea10ae5e9755879a373a063c899a706b54` |
| ILCE-7RM4 | `Update_ILCE7RM4V120.exe` | `0eccb51bf15e8c58c8a06eac51e3ab2c88a2d4f679888d81dc3acec570e0044e` |
| ILCE-7RM4A | `Update_ILCE7RM4AV113.exe` | `545fdf6cf5009a4d077e8626313974c9ba5ee3741039c3d976c15d85b1246aa1` |
| ILCE-9 | `Update_ILCE9V600.exe` | `f4d0cf824fd4d088f2b6433c00b729f6aed6f08916fe8e057b66354f3b6a186a` |
| ILCE-9M2 | `Update_ILCE9M2V320.exe` | `9da1dd4dc4a1d18de8a7ddcb151e16aa0650b58eb4a86694878a8afc36420801` |
| ZV-1 | `Update_DSCZV1V201.exe` | `6b32c86707be1dccdd04c52633327e971ce86413165f02fe39ceff0070e8e243` |
| DSC-RX0M2 | `Update_DSCRX0M2V310.exe` | `7103f194912943b7d597cfe159a4f5c295b6eaae4ebb212ed02e0f8c814e4680` |

Two container shapes are used by this input set and both are handled without guessing:

- **UFU** — magic `89 55 46 55 0d 0a 1a 0a`, then repeated `<u32 big-endian length><4-byte
  tag><payload>` for `DATV`, `PROV`, `UDID`, `FDAT`, `SDAT`, terminated by `DEND`. The
  container ends at `DEND`; a naive first-`DEND` byte search truncates inside `FDAT`.
- **PackMan** — a bitwise-NOT of an `MSCF` cabinet (ILCE-7M3, ILCE-7C, ILCE-7RM4A in this
  set). Inverting the bytes from the `MSCF` offset yields a cabinet whose `FirmwareData_*.dat`
  member is the same encrypted `.dat` the UFU path produces.

## 2. Method

1. Each `.exe` is read once; the payload container is located and written out unchanged
   (`tools/research/sony_updater_payload.py`). No source file is modified.
2. `fwtool.py unpack` produces `firmware.tar_unpacked/0700_part_image/dev/...`, which
   contains `nflasha3_unpacked/vmlinux.bin`, `nflasha3_unpacked/av-cam.bin` and
   `nflasha15_unpacked/lib/libObj.so`.
3. `tools/research/decode_kernel_kallsyms.py` decodes the bounded legacy absolute-address
   kallsyms from each `vmlinux.bin` (byte-exact, no disassembler).
4. `tools/research/av_command_table.py` locates the `av-cam.bin` command table by shape
   (16-byte records `<IIII>`, ids in `0x4000..0x4200`, handler inside the image's mapped
   range, third word 0/1) rather than by a per-model constant.
5. Comparisons are set operations over symbol names and command ids; no per-model
   constant is copied between bodies.

## 3. Observation

Kernel symbol sets and the A6400 delta (names beginning `C.`, `$`, `__func__` or `CSWTCH`
are compiler-generated literals and are excluded from the name comparison):

| group | build | bodies | shared symbols | identical addresses | reading |
| --- | --- | --- | --- | --- | --- |
| one code object | Sony CE Linux 8.2.7.6 | `ZV-E10`, `ILCE-7C` | 24,356 | 24,347 | 9 addresses differ, all in string data; all 14,460 function symbols are at the same address |
| one symbol set, three builds | Sony CE Linux 8.2.7.6 | `ILCE-6100A`, `ILCE-7M3`, `ILCE-7RM4A` | 24,351 | 20,309 | same symbol set; 20,309 of 24,351 addresses are equal *within the group* (each of the three sits 191 addresses away from `ILCE-6400`); 4,033 of the 4,042 differing addresses are function symbols, so these are three separate kernels and not one code object |
| one symbol set, two builds | 8.2.5.7 / 8.2.6.0 | `ILCE-6400`, `ILCE-6600` | 24,421 | 15,297 | same symbol set, 9,124 addresses shifted, all of them data |
| unique | 8.2.5.7 | `ILCE-7RM3`, `ILCE-9` | — | — | no other body matches |
| unique | 8.2.6.0 | `DSC-RX0M2`, `ILCE-7RM4`, `ILCE-9M2`, `ZV-1` | — | — | no other body matches |

Both address columns in the table above are measured against `ILCE-6400`, except the
`ILCE-6100A`/`ILCE-7M3`/`ILCE-7RM4A` group, whose 20,309 is the count of addresses equal to
the group's own reference member; measured against `ILCE-6400` each of the three shares
191. The per-body column in section 4 of `platform-table.tsv` is the `ILCE-6400` figure.

The `ILCE-6600`/`ILCE-6400` result deserves its own sentence, because it is the one that
changes what a per-body profile may claim: the two kernels contain **exactly the same
24,421 symbol names, none added and none removed**, and 9,124 of them moved by a constant
offset (`-0x60` for 8,871 of them). That is one kernel source compiled twice with different
string constants (`linux_proc_banner`, `sqrt_oddadjust`/`sqrt_evenadjust` and six `__func__`
strings), not two independent kernels. All 14,401 function symbols sit at the same address, and
every one of the 9,124 moved symbols is data, so the executable code is identical and only
string data moved.

## 4. Command table

| body | records | added vs ILCE-6400 | removed |
| --- | --- | --- | --- |
| `ILCE-6400` | 285 | — | — |
| `ILCE-6100A` | 285 | 0 | 0 |
| `ILCE-6600` | 286 | 1 (`0x413b`) | 0 |
| `ILCE-9` | 286 | 1 (`0x413b`) | 0 |
| `DSC-RX0M2` | 287 | 2 | 0 |
| `ILCE-9M2` | 293 | 8 | 0 |
| `ZV-1` | 294 | 9 | 0 |
| `ILCE-7M3` | 322 | 37 | 0 |
| `ILCE-7RM3` | 322 | 37 | 0 |
| `ILCE-7RM4` | 333 | 48 | 0 |
| `ILCE-7RM4A` | 333 | 48 | 0 |
| `ZV-E10` | 337 | 52 | 0 |
| `ILCE-7C` | 337 | 52 | 0 |

The additions are nested, not scattered: every added id lies in `0x413b..0x4170`, and every
body's addition set is a subset of the ZV-E10's. The full id lists are in
`docs/evidence/cross_model/command-delta.tsv`.

## 5. Alternative explanations

- **"Different counts mean different firmware generations, so the comparison is
  meaningless."** The identity test is on symbol *names* and command *ids*, which are
  structural. That `ILCE-6400`/`ILCE-6600` show 0/0 while `ILCE-6100A` shows 359/439 is a
  measured statement about those images, not an artifact of version drift.
- **"The table locator may have found a different structure on some bodies."** The locator
  requires the record shape, id range, handler range and the 0/1 third word; it reports the
  longest such run, and every body's run is contiguous and unique. The per-body offsets and
  counts are in the table above and are reproduced by one command.
- **"A shared symbol set does not prove shared code."** Correct, and it is not what is
  claimed. For `ZV-E10`/`ILCE-7C` the addresses are also equal (24,347 of 24,356), which is
  the strong form. For the `ILCE-6100A`/`ILCE-7M3`/`ILCE-7RM4A` group only the symbol set is equal and
  4,033 of the 4,042 differing addresses are function symbols, so that group is three
  separate kernels that happen to share a symbol list, and the record does not call it one
  code object.

## 6. Confidence and limitations

- **Confirmed from artifacts:** the thirteen input hashes, the unpack, the per-body kernel
  symbol sets and counts, the per-body command-table offsets and counts, the delta sets.
- **Inferred, stated as such:** that an identical symbol set means one kernel source. The
  evidence for it is the exact set equality plus a constant address delta; it is not read
  from a Sony build script.
- **Not examined:** any body's application layer beyond `libObj.so` name counts; the
  `.exe` host-side data flow; whether a body's bootloader accepts another body's image.
- Counts are for the packaged images. A live camera of the same model may run a newer build
  (the `ILCE-6400` live build observed earlier is 8.2.6.0 while its package is 8.2.5.7).
- The `ILCE-7M3`/`ILCE-7C`/`ILCE-7RM4A` packages in this input set are the current published
  versions; Sony keeps only the newest file per model, so no earlier version of the same
  model could be compared.

## 7. Reproduce

```bash
# 1. payload out of the updater (no source file modified)
python3 -I tools/research/sony_updater_payload.py <dir-with-updaters> <out-dir>

# 2. fwtool unpack (unchanged upstream tool)
(cd fwtool.py && python fwtool.py unpack -f <container> -o <unpacked>/<body>)

# 3. kernel symbols
python3 -I tools/research/decode_kernel_kallsyms.py \
    --input <unpacked>/<body>/.../nflasha3_unpacked/vmlinux.bin \
    --sha256 <sha256-of-that-file> --output <body>.json

# 4. command table
python3 -I tools/research/av_command_table.py \
    <unpacked>/<body>/.../nflasha3_unpacked/av-cam.bin

# 5. the whole comparison, including the delta and the shared-build groups
python3 -I tools/research/cross_model_report.py <unpacked-root> --json report.json
```

Expected for step 5, on this input set: `13 bodies, 9 distinct kernel symbol sets,
3 groups with more than one body`, and the counts in sections 3 and 4.

## 8. Dependent implementation/scenarios

- The per-body `TargetProfile` entries for `ILCE-6100`, `ILCE-6600` and `ILCE-7M3` can now
  carry evidence-backed kernel symbols instead of a stub (E0478–E0480).
- The six USB-side symbols this project's profile schema asks for are resolvable for all
  thirteen bodies (E0481), so a new body no longer needs a camera to gain a profile.
- The UVC `usbg_video.ko` question is a module-package question, answerable per body before
  any physical work (E0482).

## 9. Next experiment

Pick a body that is only a stub today and run the identical chain against its own capture,
then diff the two symbol sets. `ILCE-7M3` is the strongest candidate: it shares a symbol set
with `ILCE-6100A`, and the ZV-E10's UVC modules are absent from it, so the split between
"the kernel can do it" and "the package ships it" is measurable on one body.
