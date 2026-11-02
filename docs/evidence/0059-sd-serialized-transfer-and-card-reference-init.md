# Evidence 0059: SD Serialized Transfer Pipeline and Original Card Reference Initialization

## Result and scope

The SD read contract is now fully traced from ioctl `0x10f` through the serialized transfer layer to card operations, resolving the origin of `state[0]` and the synchronization mechanisms:

1. **Complete serialized transfer chain**: ioctl `0x10f` dispatches through `mmcd_blk_ioctl` (.text `0x3fa0`) to range validator `0x343c` (`FUN_00013500`), transfer chunker `0x31d4` (`FUN_00013298`), `serialized_transfer` (`0x2760`), `real_card_transfer` (`0x53ac`), and card operations table entry 0 (`mmc_mmcp_read` at `0x17070`).
2. **Card-state object identity and producer**: `mmc_mmcp_detect_each` (.text `0x14794`) allocates `struct mmcp_card` (**0x508 bytes** / 1288 bytes) from cache `_DAT_000381c4`. It initializes `state[0]` (`card[0]`) to `param_1`, which is the pointer to the host controller hardware context structure (`host_hw`).
3. **Synchronization and lock dispatch**: at `.text+0x16338`, `ldr r0, [r0]` consumes `state[0]` to obtain `host_hw`, then calls `mmc_hw_wrapper_lock_sem(host_hw)` at `0x1633c`. The lock helper extracts `hw_id` from `*host_hw` (byte 0, must be `< 4`) and invokes `ip_func_ops[hw_id]->lock_sem(host_hw)` at offset `+0x2c`.
4. **Card selection bypass**: upon lock return 0, preparation compares card RCA at `+0x278` with active selected RCA pointed to by `card[0xa4]` at `+0x290`. When matching, bus width and clock reconfiguration are skipped and preparation returns 0 with the hardware lock retained for the transfer. The transfer terminates with `mmc_hw_wrapper_unlock_sem`.
5. **Bounded execution advance**: `sd_read_bounds --card-reference-prefix` executes past `ldr r0, [r0]` at `0x16338` to the relocation at `0x1633c`, reaching **24 instruction events** before stopping at `unresolved_relocation`. Existing invalid and default controls remain byte-identical.

Card `E:\` was not modified or accessed. No hardware register response, synthetic DMA, clock reply or main/UI advance was invented.

## Original serialized transfer topology

REA/Ghidra decompilation and ARM ELF relocation analysis verify the following eight-stage call pipeline for ioctl `0x10f`:

```
ioctl(fd, 0x10f, request)
  -> mmcd_blk_ioctl (.text 0x3fa0)
     -> FUN_00013500 (.text 0x343c)
        -> FUN_00013298 (.text 0x31d4)
           -> FUN_00013008 (.text 0x2f44)
              -> serialized_transfer (.text 0x2760)
                 -> real_card_transfer (.text 0x53ac)
                    -> mmc_mmcp_read (.text 0x17070)
                       -> FUN_00026f58 (.text 0x16e94)
                          -> FUN_000263ec (.text 0x16328) [preparation]
```

| Pipeline stage | Function | Offset | Role |
| --- | --- | --- | --- |
| 1. ioctl dispatch | `mmcd_blk_ioctl` | `.text+0x3fa0` | Takes driver mutex, verifies descriptor `[0x10f, 16, 0]`, dispatches read (direction 0) to `0x343c`. |
| 2. Extent range check | `unnamed_0x343c` | `.text+0x343c` | Compares LBA (`request+8`) and sector count (`request+12`) against summed partition extents; on error writes `-3` (`0xfffffffd`) and returns 0; on valid range calls `0x31d4`. |
| 3. Scatterlist chunking | `unnamed_0x31d4` | `.text+0x31d4` | Queries max transfer limit (`local_34`), chunks requests > `0x8000` sectors (32,768 sectors = 16 MiB), prepares scatterlist with `mcmnd_api_makescatterlist`, calls `0x2f44`. |
| 4. Serialized routing | `serialized_transfer` | `.text+0x2760` | Walks device extent array `*(param_1 + uVar5*4 + 0xc)` and invokes selected device transfer handler `*puVar1`. |
| 5. Card ops dispatch | `real_card_transfer` | `.text+0x53ac` | For read (`param_7 == 0`), logs trace API `0x81`, invokes card operations table entry 0 (`**(card+0xc)` = `mmc_mmcp_read`) passing card context `piVar5[1]`. |
| 6. MMCP entry | `mmc_mmcp_read` | `.text+0x17070` | Passes selector 3 (read), starting sector, count, and scatterlist callbacks to helper `0x16e94`. |
| 7. Command helper | `unnamed_0x16e94` | `.text+0x16e94` | Verifies capacity (`card[0xb7]`, offset `+0x2dc`), calls preparation helper `0x16328`, issues CMD17 (single) or CMD18 (multi), commands 512-byte blocks, calls unlock sem wrapper `0x12acc` before return. |
| 8. Preparation & lock | `unnamed_0x16328` | `.text+0x16328` | Reads `state[0]` (`host_hw`), calls `mmc_hw_wrapper_lock_sem`, compares card RCA with active selected RCA, returns 0 with lock held. |

## Card reference producer and structure layout

In `mmc_card_open` (.text `0x9f70`), the driver initializes a `struct mmc_card` (size `0x4c`), associates it with the host controller context `param_1`, and calls `mmc_mmcp_detect_each(param_1, ...)`:

`mmc_mmcp_detect_each` (.text `0x14794`) allocates the authentic `struct mmcp_card` (**0x508 bytes** / 1288 bytes) and establishes its fields:

| Offset | Name | Type | Initial value / Producer |
| --- | --- | --- | --- |
| `+0x000` | `host_hw` | `void*` | Pointer to host controller hardware context structure (`param_1`); this is `state[0]`. |
| `+0x004` | `host_hw_plus_4` | `void*` | Secondary host context reference (`param_1 + 4`). |
| `+0x00c` | `cid` | `uint32_t[4]` | Card identification register words (CMD2 response). |
| `+0x21c` | `csd` | `uint32_t[4]` | Card specific data register words (CMD9 response). |
| `+0x278` | `rca` | `uint16_t` | Relative Card Address extracted from CMD3 response (`local_9c._2_2_`). |
| `+0x280` | `bus_width` | `uint32_t` | Initial bus width mode (`1` = 1-bit). |
| `+0x284` | `clk_freq_khz` | `uint32_t` | Initial clock frequency (`25000` = 25 MHz). |
| `+0x28c` | `selected_rca_val` | `uint16_t` | Active selected RCA value on bus (`local_9c._2_2_`). |
| `+0x290` | `selected_rca_ptr` | `uint16_t*` | Pointer to active selected RCA storage (initialized to point to `+0x28c`). |
| `+0x2dc` | `capacity_sectors` | `uint32_t` | Card capacity in 512-byte sectors (`card[0xb7]`), derived from CSD v1/v2 bit extraction. |

## Synchronization and locking contract

At `.text+0x16328`:

1. `0x16334: mov r4, r0` preserves card pointer.
2. `0x16338: ldr r0, [r0]` dereferences `state[0]`, loading the `host_hw` pointer.
3. `0x1633c: bl mmc_hw_wrapper_lock_sem` calls the lock helper at `.text+0x18dfc`.
4. `mmc_hw_wrapper_lock_sem` loads `ldrb r1, [r0]` to read `hw_id` (must be `< 4`), looks up `ip_func_ops[hw_id]`, and invokes `ops->lock_sem(host_hw)` at offset `+0x2c`.
5. `0x16340: subs r6, r0, #0`: checks lock status. Non-zero error immediately branches to exit (`0x163cc`) without unlocking.
6. `0x16348: ldr r3, [r4, #0x290]`: loads pointer to active selected RCA.
7. `0x1634c: mov r5, #0x278`: loads card RCA offset.
8. `0x16350: ldrh r2, [r4, r5]`: loads card RCA.
9. `0x16354: ldrh r3, [r3]`: loads currently selected RCA value.
10. `0x16358: cmp r2, r3`: compares card RCA with active selected RCA.
11. `0x1635c: beq #0x163cc`: if matching (card already selected), branches directly to exit, skips `mmc_hw_wrapper_set_trans_width`, clock setting and CMD7 selection, and returns `0` with the semaphore held!
12. At transfer completion in `0x16e94`, `FUN_00022b90(*param_1)` (.text `0x12acc`) calls `mmc_hw_wrapper_unlock_sem(host_hw)` (.text `0x18e70`), releasing the lock via `ops->unlock_sem(host_hw)` at offset `+0x30`.

## Bounded card reference execution bounds

`sd_read_bounds --card-reference-prefix` maps constructed host hardware context `0x08400000`, writes this pointer to `STATE` (`state[0]`), and writes `hw_id = 0` to `0x08400000`:

- Invalid controls (0, 0, 1024), (0xffffffff, 2, 1024), (1023, 2, 1024) still stop at isolated return `-1` after 14, 17, and 21 original events (unchanged).
- Valid control (0, 1, 1024) executes past `0x16338: ldr r0, [r0]` and reaches `0x1633c: bl mmc_hw_wrapper_lock_sem`.
- Because `0x1633c` is an unresolved relocation in `mmc_drv.ko`, execution halts cleanly on `unresolved_relocation` at **PC 0x1633c** after **24 original instruction events** (23 recorded trace offsets).
- Default mode without flags retains E0057 regression hash `1e21c411c21cb8a1131c0f7e535534d6a53b0ecf02ffdd55517c97f5cb75432f`.
- Preparation-only mode `--preparation-prefix` retains E0058 regression hash `5be6a98c4d74ff937e321567229a4e312f0444f133fdfc8c8d2a2721048d4d34`.
- Card-reference mode `--card-reference-prefix` produces byte-identical hash **f124b8e65883d0269a0c205a747970e22bcd6a9ffaa7912536996d9ae6898805**.

## Reproduction and validation

```powershell
python -m tools.research.sd_transfer_profile --report-dir artifacts/analysis/NEW_TRANSFER_PROFILE
python -m tools.research.sd_read_bounds --card-reference-prefix --report-dir artifacts/execution/NEW_CARDREF
```

- Transfer profile `artifacts/analysis/sd-transfer-profile-verified` / repeat are byte-identical, SHA-256 **2f7a2a235ee5ae2c2682a3bef9f01f3ab56a7aa24ad3e38a3303f987ba055cf8**.
- Bounded card reference execution reports `artifacts/execution/sd-read-bounds-cardref-verified` / repeat are byte-identical, SHA-256 **f124b8e65883d0269a0c205a747970e22bcd6a9ffaa7912536996d9ae6898805**.
- 8 new native WSL REA procedure queries completed across `sd-serialized-transfer` (5 queries) and `sd-card-open-init` (3 queries).
- 5 new tests in `tests/test_sd_transfer_profile.py` and `tests/test_sd_read_bounds.py`. Full test suite: **367 passing tests**, `artifacts/execution/sd-transfer-final-suite.txt`.
- Status visualization `status_a6400.png` regenerated.

Next for emulation: trace `ip_func_ops` initialization and host controller semaphore implementation, resolve MWF device-path responder, and connect the verified DMA/block buffer path.
