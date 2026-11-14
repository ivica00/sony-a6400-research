# E0505 — `av-cam.bin` `CC:` 3D LUT and `EC_Gamma` Pre-8-Bit Pipeline Analysis

- **Date:** 2026-11-14
- **Target:** `firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/av-cam.bin`
  - **SHA-256:** `90d515cfec8b936f1ba9a69dcac462816b880297752a652474d67c4bba39125e`
  - **Size:** `16,674,456` bytes (`0x635C6000`–`0x645ACE98`)
  - **Format / Base:** `ORIL` v4 raw ARM/Thumb-2 PIC, `ORIL_BASE = 0x635C6000`
- **Tools:**
  - Ghidra `12.1.4` via REA (`rea.mjs --mcp` in WSL Ubuntu, `format=raw-binary`, `architecture=arm`, `entry_point=0x635C6000`, `REA_GHIDRA_DISABLED_ANALYZERS="Decompiler Parameter ID"`)
  - Capstone `5.0.7` (Thumb-2 disassembly verification)
- **Preserved REA artifacts:**
  - `artifacts/tools/rea/cc-3dlut-rea-2/` (`FUN_63ad04dc`, `FUN_63ad0520`, `FUN_63ad08c8`, `FUN_63ad0930`, `FUN_63ad0fc8`, `FUN_63d8fec6`, `FUN_63d8f6dc`)
  - `artifacts/tools/rea/cc-3dlut-rea-3/` (`FUN_63acec0c`, `FUN_63ad136c`, `FUN_63ad2178`, `FUN_63ad2e3c`, `FUN_63ad4300`, `FUN_63d8edb4`, `FUN_63d8f044`, `FUN_63d90122`)
  - `artifacts/tools/rea/cc-3dlut-rea-4/` (`FUN_63b1f614`, `FUN_63ba8158`, `FUN_63dba69e`, `FUN_63ba8cf6`)
- **Scope & constraints:** Strictly read-only static analysis. No physical camera access and no firmware modifications.

---

## 1. Located Functions and String Cross-References

| String VA | String | Referencing Function |
|---|---|---|
| `0x63f6b63a` | `CC: LutMode Change SA %02X <- %02X` | `FUN_63ad0520` (`0x63ad06a4`..`0x63ad06aa`) |
| `0x63f6b65d` | `CC: LutMode Change CAP %02X <- %02X` | `FUN_63ad0520` (`0x63ad06aa`..`0x63ad06b0`) |
| `0x63f6b681` | `CC: LutMode Change MOV/MON %02X <- %02X` | `FUN_63ad0520` (`0x63ad06b0`..`0x63ad06b6`) |
| `0x63f6b77c` | `CC: Create3DLUT 0x%X > 0x%X Level:%d ConvSD:%d` | `FUN_63ad0930` (`0x63ad0ae2`..`0x63ad0aee`) |
| `0x63f6b7ab` | `CC: Create3DLUT uc_SRAM=[%d], SRAM addr=0x[%X] ` | `FUN_63ad0930` (`0x63ad0af6`..`0x63ad0b08`) |
| `0x63f6b80e` | `CC: Copy3DLUT 0x%X > 0x%X ` | `FUN_63ad0930` (`0x63ad0e20`..`0x63ad0e2a`) |
| `0x63f6b887` | `CC: Copy2DLUT 0x%X > 0x%X ` | `FUN_63ad0930` (`0x63ad0ee8`..`0x63ad0ef2`) |
| `0x63f6b900` | `CC: LUT Write Cnt:%d ` | `FUN_63ad0fc8` (`0x63ad12b2`..`0x63ad12b8`) |
| `0x63f732cf` | `SetGammaTable Error GammaSize :%d` | `FUN_63b1f614` (`0x63b1f622`) |
| `0x63f7a1e1` | `Gamma/EC_Gamma.cpp` | `FUN_63ba8158` (`0x63ba81c6`), `FUN_63dba69e` (`0x63ba8474`), `0x63ba8cf6` |

---

## 2. Verified `CC:` 3D LUT Findings

### 2.1 ISP Pipeline Position & Color Domain
- `FUN_63d8fec6` (called by `MOV/MON` handlers `FUN_63acec0c`, `FUN_63d8edb4` and `SA/CAP` handler `FUN_63d8f044`) executes in sequence:
  1. `FUN_63ad4418()` — selects `LutMode` (`cc_out + 4`) via `FUN_63ad396c` from CC tuning table (`+0x150..+0x15d`).
  2. `FUN_63ad2178()` — computes 8-channel / 4-quadrant gain & phase color adjustments (`local_44[8]`).
  3. `FUN_63ad2e3c()` — computes the **3×3 color matrix** (`local_48[9]`, 16-bit `short` coefficients written to `cc_out + 0x50` / `*param_2 + 0xae`).
  4. `FUN_63ad0fc8()` — 3D/2D LUT controller (calls `FUN_63ad0520` and `FUN_63ad0930`).
  5. `FUN_63ad136c()`, `FUN_63d90122()`.
- **Color space of the 3D LUT:** **YCbCr**, not linear RGB or post-gamma RGB.
  - `FUN_63ad0930` (`ConvSD == 1`) reads the grid axis tables at `0x63e69562` and `0x63e6956c`:
    - Luma `Y` (5 points): `[0, 64, 128, 192, 256]`
    - Chroma `Cb` (9 points): `[-128, -96, -64, -32, 0, 32, 64, 96, 128]`
    - Chroma `Cr` (9 points): `[-128, -96, -64, -32, 0, 32, 64, 96, 128]`
  - `ConvSD == 1` applies a Q14 fixed-point YCbCr matrix (`0x4000`, `0xd17`, `0x6eb`, `0x3f45`, `-0x71e`, `-0x4b1`, `0x3ef2`) with non-linearization tables `0x63ad049c` and `0x63ad0460` (BT.601 ↔ BT.709 conversion).

### 2.2 `MOV` + Picture Profile / S-Log3 Activity (`FUN_63ad0fc8`)
- `FUN_63ad0fc8` reads `LutMode = *(byte *)(cc_out + 4)`:
  - `0xFF`: `cc_out + 0x68 = 0`, `RefAdr = 0` (disabled).
  - `(LutMode >> 5) & 3 == 0` and `(LutMode & 0xF) <= 2`: **3D LUT** (`cc_out + 0x68 = 1`).
  - `(LutMode >> 5) & 3 == 1` and `(LutMode & 0xF) <= 2`: **2D LUT** (`cc_out + 0x68 = 2`).
- `cc_out + 0x0c` (`1` = enabled, `0` = bypassed) is cleared to `0` if:
  1. `*(short *)(cc_out + 0x68) == 0 && *(char *)(*param_1 + 0x30) != 1`,
  2. `*(byte *)(*param_1 + 0x28) < 0x1c` matches bitmasks `0x3400000` / `0xc000000` with tuning flags `*(iVar4 + 0x11)` bits 6/7,
  3. On `MOV/MON` (`*(char *)(param_1[1] + 6) != 1`), the SRAM bank flag `*(param_2 + 0x18)[uc_SRAM] == 0`,
  4. `*(char *)(*param_1 + 0x190) != 0`.
- `LutMode` values come from runtime-populated CC tuning tables (`+0x150..+0x15d`), not hardcoded constants in `.text`.

### 2.3 SRAM Table Format, Grid Size, and Address
- **Grid size:** **`5 × 9 × 9 = 405` (`0x195`) entries** (5 `Y` × 9 `Cb` × 9 `Cr`), `405 × 4 = 1620 = 0x654` bytes per bank. (Not `17³` or `33³`.)
- **Permutation:** `FUN_63ad04dc` maps `(y, cb, cr)` via `uint16_t[405]` at `0x63e69238` (`min=0`, `max=404`, `405` unique indices).
- **Entry format (`FUN_63ad04dc` & `FUN_63ad0930`):** Each 32-bit word packs **three signed 7-bit deltas** clamped to `[-64, +63]` (`0xffffffc0..0x3f`):
  - `word32 = ((ΔY & 0x7F) << 16) | ((ΔCb & 0x7F) << 8) | (ΔCr & 0x7F)`
- **Parameters:**
  - `Level:%d` = `*(byte *)(*param_1 + 0x29)`: `1..7` scales deltas by `(Level * delta) >> 3`; `>= 8` copies unscaled (when `ConvSD == 0` and `*param_1 + 0x30 != 1`).
  - `ConvSD:%d` = `*(byte *)(cc_out + 0x69)` (`0` or `1` from `FUN_63ad08c8`): enables BT.601 ↔ BT.709 YCbCr conversion in `Create3DLUT`.
  - `uc_SRAM=[%d]` = `*(byte *)(*param_1 + 0x222)`: ping-pong bank index (`0` or `1`) in `MOV/MON`.
- **SRAM address:** Dynamically allocated in `FUN_63ad0808` via `0x63940be4` (`0x39d` units) and mapped via `0x63c01d7c`, stored in `*(param_2 + 0x10) + 0x6b8` (`MOV/MON`, indexed by `uc_SRAM * 0x654`), or `*(param_2 + 0x10) + 0x64` (`CAP`).

### 2.4 `RefAdr` / `BufAdr` Sources and Overwriting
- **`RefAdr` pointers (GOT base `0x645a21e4`, pointing into `.bss` `0x6449xxxx`, zero-filled in the static `.bin`):**
  - 3D LUT (`cc_out + 0x68 == 1`): `0x645a4d64 -> 0x64490025` (`0`), `0x645a9cd8 -> 0x64490659` (`1`), `0x645a6ba8 -> 0x64490cf9` (`2`).
  - 2D LUT (`cc_out + 0x68 == 2`): `0x645a8fa4 -> 0x64491461` + `(LutMode & 0xf) * 0xa2` (`9×9×2 = 162` bytes).
- **Overwriting:** `FUN_63ad0fc8` invokes `FUN_63ad0930` whenever `FUN_63ad0520` detects a parameter/mode/sync change (`LutMode`, `Level`, `ConvSD`, 6-axis `+0x30..+0x37`, `uc_sync`/`IsSplit`) or during `MOV/MON` state transitions (`cVar7 == 1`), rewriting the `0x654`-byte buffer.

---

## 3. Verified `EC_Gamma` Pre-8-Bit Findings (`FUN_63b1f614`, `FUN_63dba69e`, `FUN_63ba8158`)

- **`SetGammaTable` (`FUN_63b1f614`):**
  - Enforces exact table size **`0x60` = 96 entries**, **`uint16_t` each** (`0xc0 = 192` bytes).
  - Copies the 192-byte table to a staging buffer (`DAT_63b1f674 + 0x63b1f642`), translates both addresses via `FUN_63c01d7c(..., 0x12, 0)`, and programs hardware via `FUN_63b1ac74(0xd, ...)`.
- **`Gamma/EC_Gamma.cpp` (`FUN_63dba69e`, `FUN_63ba8158`):**
  - Selects among up to `0x24` (`36`) gamma curves (`param_3 + 0x639` clamped `<= 0x23`) depending on shooting mode, Picture Profile, Creative Style, and S-Log2/3 flags (`*param_1 + 0x13c`, `+0x634`, `+0x640`, `+0x648`, `+0x83c`, `+0x1bd`).

---

## 4. Technical Conclusion on Feasibility

1. **Direct `SLog3 -> custom 3D LUT (33³/17³ RGB) -> 8-bit MOV` via `CC: 3D LUT` is NOT feasible:** the `CC:` 3D LUT hardware block operates in post-gamma/post-matrix **YCbCr** on a coarse **`5 × 9 × 9`** grid with **7-bit signed deltas `[-64, +63]`**, which cannot represent a Log-to-Rec.709 tone curve or gamut transform.
2. **LUT Decomposition before 8-bit encoding IS architecturally feasible in principle:** a `.cube` LUT can be decomposed into:
   - **1D Gamma (`EC_Gamma` / `SetGammaTable`, `96 × uint16_t`)** + **`YKNEE`** for the tone/contrast curve before 8-bit quantization,
   - **3×3 Matrix (`FUN_63ad2e3c`, `9 × int16_t`)** for gamut/primary color conversion,
   - **`5 × 9 × 9` YCbCr delta 3D LUT (`FUN_63ad0930`)** for smooth secondary look/split-tone residual adjustments within `[-64, +63]`.
   - Sharp, localized color discontinuities in an arbitrary `.cube` LUT cannot be reproduced due to the `5 × 9 × 9` grid resolution and `±63` delta clamp.
