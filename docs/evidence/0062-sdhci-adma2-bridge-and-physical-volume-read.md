# Evidence 0062: SDHCI ADMA2 Bridge and Physical SD Card Sector Execution

## Result and scope

The SD communication contract is now complete end-to-end: the SDHCI host controller emulation bridge connects the kernel driver's MMIO register sequence (base `0xf2a00000`) and ADMA2 descriptor tables directly to read-only SD sector storage (mounted volume `E:\`):

1. **Host controller bridge implementation (`tools.research.sdhci_bridge`)**:
   - Implements the complete SDHCI MMIO register set: block size (`0x04`), count (`0x06`), LBA argument (`0x08`), transfer mode (`0x0c`), command trigger (`0x0e`), present state (`0x2c`), interrupt status (`0x30`), and ADMA2 table pointer (`0x58`).
   - Parses 8-byte ADMA2 descriptors from guest memory, decoding Valid (`0x01`), End (`0x02`), and Action Transfer (`0x20`) attributes and length.
   - Fetches sectors from a `SectorSource` (supporting both direct Windows physical volume `\\.\E:` and deterministic test memory), copies them to destination guest RAM buffers, updates `SDHCI_INT_STATUS` (`0x0003`), and clears `SDHCI_PRESENT_STATE` inhibit bits.
2. **Physical volume read verification (Drive `E:\`)**:
   - Tested against the authentic mounted Sony SDXC card `E:\` (`\\.\E:`, exFAT, **249,966,592 sectors** / 119.19 GB).
   - **CMD17 (Single Block Read)**: transferred LBA 0 (Volume Boot Record) through a single-segment ADMA2 descriptor (`(512 << 16) | 0x23`) into guest physical RAM (`0x00002000`). Verified authentic OEM signature `EXFAT   ` and sector digest SHA-256 `ed765d4031463b2c3ad0d08d02fef20f2d9333843f9dc4080b8264d6b89a7a56`.
   - **CMD18 (Multi-Block Read)**: transferred 4 blocks (2048 bytes) through a 2-segment ADMA2 descriptor chain into distinct memory pages (`0x00003000` and `0x00003400`).
   - Root directory verified at cluster 4 (sector 33,280), identifying authentic Sony camera trees (`PRIVATE`, `AVF_INFO`).
3. **Safety and immutability**:
   - Direct access to `\\.\E:` is opened strictly in read-only mode (`open(..., 'rb')`).
   - `SectorSource` interfaces strictly prohibit write methods. Card `E:\` was never altered or written.
4. **Validation and test suite**:
   - Verified report `artifacts/analysis/sd-bridge-verified` and repeat match deterministically with SHA-256 **afc46ba3fc252a53576fcb359a4a6dd0fc0ac3d4e8dd1fb7248f740462ea21df**.
   - 6 new unit tests in `tests/test_sdhci_bridge.py`.
   - Full test suite: **386 passing tests** (`artifacts/execution/sd-bridge-final-suite.txt`).

## End-to-end SD transfer architecture

```
Guest Driver (mmc_drv.ko / mcmn_drv.ko)
  |
  |-- ioctl 0x10f: takes user buffer, LBA, count
  |-- mcmnd_scatter_makescatterlist: pins user memory pages via get_user_pages()
  |-- mmc_single_scatter_list: wraps buffer in adapter vtable
  |-- mmc_hw_exec_command:
  |     - writes ADMA2 table address to SDHCI_ADMA_ADDRESS (0x58)
  |     - writes block size (512) to SDHCI_BLOCK_SIZE (0x04)
  |     - writes count to SDHCI_BLOCK_COUNT (0x06)
  |     - writes LBA to SDHCI_ARGUMENT (0x08)
  |     - writes transfer mode to SDHCI_TRANSFER_MODE (0x0c)
  |     - triggers transfer via SDHCI_COMMAND (0x0e)
  v
SDHCI ADMA2 Bridge (0xf2a00000)
  |
  |-- Reads 8-byte descriptors from guest memory at SDHCI_ADMA_ADDRESS
  |-- For each transfer descriptor:
  |     - reads count * 512 bytes from SectorSource (Physical \\.\E: or Memory)
  |     - writes bytes directly to guest memory at descriptor.buf_phys
  |     - advances LBA
  |-- Sets SDHCI_INT_STATUS = 0x0003 (Command Complete | Transfer Complete)
  |-- Clears CMD/DAT inhibit in SDHCI_PRESENT_STATE
  v
Guest Buffer Contains Actual SD Card Sectors
```

## Reproduction and validation

```powershell
python -m tools.research.sdhci_bridge --report-dir artifacts/analysis/NEW_BRIDGE
python -m unittest tests/test_sdhci_bridge.py
```

- Verified report `artifacts/analysis/sd-bridge-verified` and repeat match deterministically with SHA-256 **afc46ba3fc252a53576fcb359a4a6dd0fc0ac3d4e8dd1fb7248f740462ea21df**.
- 6 new unit tests in `tests/test_sdhci_bridge.py`.
- Full regression suite passes: **386 passed**, 0 failed, 0 errors (`artifacts/execution/sd-bridge-final-suite.txt`).
