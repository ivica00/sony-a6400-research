# E0510 — CXD90045 Sugilite (`grm_gles.ko`) Cross-Generation Parity with CXD90014

- **Date:** 2026-11-14
- **Track:** L2 Full-System (`UnicornMachine`) & L3 Graphics (`GuestGles`, `dmp_p3d`)
- **Primary Inputs:**
  - `firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/grm_gles.ko`
    (**SHA-256:** `a8d1dbe8c66be365d32371b13f35a0e7d598c415c0ff17f2c8f544084ccc6882`)
  - `firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libObj.so`
    (**SHA-256:** `60ffd2b0f31f4bc139a7c13a4f62c25cdeb6a531ad5ef35df48471e6e36e88b1`)
- **Tooling:** `arm-linux-gnueabi-objdump`, `nm` (WSL Ubuntu)
- **Prior Art / Cross-Reference:** [Oein/a5000-emulator](https://github.com/Oein/a5000-emulator) (`docs/RE_DISPLAY_GPU.md` §2, CC BY 4.0, by Park SungHyun / Oein)

## 1. Objective

Verify whether the DMP SMAPH-S30 ("Sugilite") GPU MMIO, clock/reset, and IRQ contract documented by Oein on `ILCE-5000` (`CXD90014`) holds verbatim on `ILCE-6400` (`CXD90045`), and wire the verified kernel/MMIO contract into `UnicornMachine`.

## 2. Direct Observations on `CXD90045` `grm_gles.ko`

Disassembly of `grm_gles.ko` establishes byte-for-byte contract parity with `CXD90014` for the kernel driver boundary:

1. **IRQ & Chdev Registration (`sugilite_chdev_register` `.init.text+0xC8`):**
   - Requests **IRQ `76` (`0x4C`)** with `flags = 0x84` (`IRQF_SHARED | IRQF_TRIGGER_HIGH`).
2. **Interrupt Handler (`sugilite_interrupt` `0x658`):**
   - Reads `BAR + 0x34`; if `0`, calls `__bug_noarg` (must never assert IRQ 76 with `+0x34 == 0`).
   - `bit 31` (`0x80000000`, P3D done): writes `0` to `BAR + 0x1000`.
   - `bit 30` (`0x40000000`, PPF done): writes `0` to `BAR + 0xC18`.
   - `bit 26` (`0x04000000`, PSC0 done): writes `0` to `BAR + 0x1C`.
   - `bits 0..3` (`0x0F`): writes `1` to `BAR + 0x3C` and `BAR + 0x44`.
   - Re-reads `BAR + 0x34` and ORs bits `16..31` into `dev + 0xA8`.
3. **Clock-Up & Divider Sequence (`sugilite_clock_up_internal` `0x248..0x30C`):**
   - Updates clock dividers `0xF28040C4`, `0xF28041A8`, `0xF28050B8`, `0xF280518C` (`(val & ~0xF) | 6`).
   - Writes `0x15` to `0xF3400080`, delays, writes `0x10` to `0xF3400280`, then **reads back `0xF3400080` and calls `__bug_noarg` if `!= 0x15`**.
4. **Register Init (`sugilite_register_init` `0x54`):**
   - Writes `+0x10C0 = 0xFFFFFFFF`, `+0x10C4 = 0xFFFFFFFF`, `+0x1000 = 0`, `+0x1080 = 0x12345678`, `+0x10C0 = 0xFFFFFFF0`, `+0x10D0 = 0`, `+0x1100 = 1`, `+0x1128 = 0`, `+0x1110 = 0`, `+0x1114`, `+0x1118`, `+0x1410 = 0`, and (when `async_fix == 1`) `+0x50`/`+0x54`.
5. **User-Space `rm_*` Submission (`libObj.so` `0x72b404..0x72b5d0`):**
   - `0x72b404`: `cmp.w r0, #0x1800` (tv-mode skip guard on P3D kick).
   - `0x72b458 / 0x72b470 / 0x72b49c`: PPF writes `+0xC00`, `+0xC10`, `+0xC18` (trigger).
   - `0x72b5c6 / 0x72b5d0`: P3D kick writes `+0x1804` (list PA) then `+0x1800` (entry count).

## 3. Implementation & Verification

- `src/a6400/execution/dmp_p3d.py`: clean-room `P3dCommandListDecoder`, `detile_morton_8x8` / `tile_morton_8x8`, `execute_ppf_transfer`, and `SugiliteMmioModel` (`BAR 0xF1000000`).
- `src/a6400/execution/guest_gles.py`: opt-in `p3d_model=False` and `poll_p3d_bar()`.
- `src/a6400/execution/unicorn_machine.py`: wired `SUGILITE_CLK_BASE` (`0xF3400000`, set/clear pairs `+0x080/+0x084` and `+0x280/+0x284`) and `SUGILITE_BASE` (`0xF1000000`, `0x4000`) via `SugiliteMmioModel` with `SUGILITE_IRQ = 76` pending/clear tracking.
- `src/a6400/execution/submicro_link.py`: clean-room 128-byte Slot B CRC-16/CCITT-FALSE + TLV codec and 8-byte command-header codec (verified against the documented `0xA659` snapshot CRC).

## 4. Remaining Boundaries

- `CXD90045` `libObj.so` P3D command-list register numbers and DMP shader ISA parity remain to be verified against captured or replayed `CXD90045` `gl_common` submissions.
- In the sandboxed Windows shell, `unicorn` tests are skipped because `_ctypes.pyd` fails to load (`ImportError: DLL load failed while importing _ctypes`); pure-Python unit tests for `dmp_p3d`, `GuestGles.poll_p3d_bar`, and `submicro_link` pass (`72 passed, 1 skipped`).
