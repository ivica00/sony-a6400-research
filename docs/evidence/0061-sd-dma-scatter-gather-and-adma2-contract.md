# Evidence 0061: SD DMA Scatter-Gather Buffer Transfer Pipeline and ADMA2 Contract

## Result and scope

The SD data transfer pipeline from user memory pinning through kernel scatter-gather management and hardware ADMA2 descriptor execution is now fully resolved across `mcmn_drv.ko` and `mmc_drv.ko`:

1. **User buffer memory pinning (`mcmn_drv.ko`)**: `mcmnd_scatter_makescatterlist` (.text `0xd5cc`) receives the user virtual address from ioctl `0x10f`. It acquires `compat_down_read(&current->mm->mmap_sem)`, invokes `get_user_pages` to pin the backing physical pages into RAM, releases `compat_up_read`, and establishes DMA bus addresses via `dma_map_sg`.
2. **Scatterlist adapter vtables (`mmc_drv.ko`)**:
   - **Single-segment adapter** constructed by `mmc_single_scatter_list` (.text `0x2090`): wraps a 3-word private state `[phys_addr, length, index]` into a 4-pointer vtable object:
     - `+0x00`: `state` pointer
     - `+0x04`: `list_count` (.text `0x1e8c`) -> returns constant 1
     - `+0x08`: `get_next` (.text `0x1ea0`) -> fills segment address and length into output struct, increments index, returns 1 then 0
     - `+0x0c`: `reset_list_ptr` (.text `0x1ed8`) -> rewinds index to 0
   - **Multi-segment adapter** (.text `0x25cc`, `0x25e0`, `0x2688`): walks standard Linux 16-byte `struct scatterlist` arrays, extracting `sg->dma_address` at `+0x0c` and `sg->length` at `+0x08`.
3. **ADMA2 descriptor table generation (`mmc_hw_exec_command`)**:
   - The descriptor table is allocated at `host_hw + 0xa8`.
   - `mmc_hw_exec_command` (.text `0xd754`) queries segment count via `list_count`, rewinds via `reset_list_ptr`, and loops with `get_next`.
   - Each ADMA2 entry is **8 bytes**:
     - Word 0 (`+0x00`): attribute and length. Lower 16 bits encode attributes: bit 0 Valid (`0x01`), bit 5 Action Transfer (`0x20`), giving attribute `0x21`. Upper 16 bits encode length (0 represents 64 KiB).
     - Word 1 (`+0x04`): 32-bit physical DMA buffer address.
   - Loop termination: at `.text+0xd910`, `orr r2, r2, #2` sets bit 1 (`ADMA2_END`), making the final entry attribute `0x23`.
   - Table translation: `.text+0xd920` calls `mmc_os_virt_to_phys` on `host_hw + 0xa8`.
   - Register programming: `.text+0xd930` writes the physical address to `SDHCI_ADMA_ADDRESS` (register offset **0x58**).
4. **SDHCI hardware register transfer programming**:
   - `0x04` (`SDHCI_BLOCK_SIZE`): sets block size **512** (`0x200`).
   - `0x06` (`SDHCI_BLOCK_COUNT`): sets sector count.
   - `0x08` (`SDHCI_ARGUMENT`): sets starting sector LBA.
   - `0x0c` (`SDHCI_TRANSFER_MODE`): sets DMA enable, read direction, and multi-block flags.
   - `0x0e` (`SDHCI_COMMAND`): writes command index (CMD17 / CMD18) to trigger hardware transaction.
   - `0x2c` (`SDHCI_PRESENT_STATE`): polled before launch for DATA/CMD inhibit bits.
   - `0x2e` (`SDHCI_TIMEOUT_CONTROL`): sets timeout (0x0b).
5. **Transfer completion and buffer release**:
   - Command completion signals `mmc_os_wait_eventflag(host_hw + 0x08)`.
   - `mcmnd_scatter_releasescatterlist` (.text `0xd7ac`) invokes `dma_unmap_sg` and `put_page` to unpin the user pages.

Card `E:\` was not written or altered. No fabricated DMA data or synthetic responses were invented.

## Memory pipeline architecture

```
ioctl 0x10f(fd, [status, user_buf, lba, count])
  |
  v [mcmn_drv.ko: mcmnd_scatter_makescatterlist (0xd5cc)]
  |-- compat_down_read(&mm->mmap_sem)
  |-- get_user_pages(user_buf, count * 512) -> pin physical pages
  |-- compat_up_read(&mm->mmap_sem)
  |-- dma_map_sg() -> obtain bus DMA addresses
  |
  v [mmc_drv.ko: real_card_transfer (0x53ac) & mmc_single_scatter_list (0x2090)]
  |-- wraps scatterlist in 4-pointer adapter vtable:
  |     adapter[0] = state [phys_addr, length, 0]
  |     adapter[1] = list_count (0x1e8c)
  |     adapter[2] = get_next (0x1ea0)
  |     adapter[3] = reset_list_ptr (0x1ed8)
  |-- passes adapter to mmc_mmcp_read -> unnamed_0x16e94 -> cmd[0x88]
  |
  v [mmc_drv.ko: mmc_hw_exec_command (0xd754)]
  |-- iterates adapter with list_count, reset_list_ptr, get_next
  |-- builds 8-byte ADMA2 descriptors at host_hw + 0xa8:
  |     [desc+0] = (len << 16) | 0x21 (Valid | Transfer)
  |     [desc+4] = phys_addr
  |-- sets ADMA2_END (0x02) on final descriptor: [desc+0] |= 2 (0x23)
  |-- writes mmc_os_virt_to_phys(table) to SDHCI_ADMA_ADDRESS (0x58)
  |-- sets SDHCI_BLOCK_SIZE (0x04) = 512, SDHCI_BLOCK_COUNT (0x06) = count
  |-- sets SDHCI_ARGUMENT (0x08) = LBA, SDHCI_TRANSFER_MODE (0x0c)
  |-- writes CMD17/18 to SDHCI_COMMAND (0x0e) -> hardware transfer executes
  |
  v [mcmn_drv.ko: mcmnd_scatter_releasescatterlist (0xd7ac)]
  |-- dma_unmap_sg()
  |-- put_page() -> unpin user pages
```

## ADMA2 descriptor format

Each ADMA2 descriptor is **8 bytes** (64-bit alignment):

| Offset | Field | Bits | Value / Encoding |
| --- | --- | --- | --- |
| `+0x00` | Attributes & Length | 0..0 | Valid (`0x01` = entry valid) |
| | | 1..1 | End (`0x02` = final entry in descriptor chain) |
| | | 2..2 | Int (`0x04` = generate interrupt on completion) |
| | | 4..5 | Action (`0x20` = Transfer data) |
| | | 16..31 | Transfer length in bytes (`0` = 65,536 bytes) |
| `+0x04` | Physical Address | 0..31 | 32-bit physical DMA buffer address |

## Native WSL REA verification

Completed 7 procedures across two batches:
- `artifacts/tools/rea/sd-dma-scatter/`:
  - `00-procedure_pseudo_code.json`: `mmc_single_scatter_list`
  - `01-procedure_pseudo_code.json`: `0x11f64` (`get_next`)
  - `02-procedure_pseudo_code.json`: `0x11f50` (`list_count`)
  - `03-procedure_pseudo_code.json`: `0x11f9c` (`reset_list_ptr`)
- `artifacts/tools/rea/sd-mcmn-scatter/`:
  - `00-procedure_pseudo_code.json`: `mcmnd_api_makescatterlist`
  - `01-procedure_pseudo_code.json`: `mcmnd_scatter_makescatterlist`
  - `02-procedure_pseudo_code.json`: `mcmnd_api_releasescatterlist`

## Reproduction and validation

```powershell
python -m tools.research.sd_dma_profile --report-dir artifacts/analysis/NEW_DMA_PROFILE
python -m unittest tests/test_sd_dma_profile.py
```

- Verified report `artifacts/analysis/sd-dma-profile-verified` and repeat match deterministically with SHA-256 **b831d0e1afcef21210a8b52ab932a6e9e154d02bf86bf27cbff1f4650c4d17d5**.
- 6 new unit tests in `tests/test_sd_dma_profile.py`.
- Full test suite: **380 passing tests** (`artifacts/execution/sd-dma-final-suite.txt`).
- Updated status visualizations: `status_a6400.png` and `artifacts/reports/status_a6400.png` (with `sdhci_dma` at 10/10).
