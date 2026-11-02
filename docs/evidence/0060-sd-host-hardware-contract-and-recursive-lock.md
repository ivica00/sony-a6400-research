# Evidence 0060: SD Host Hardware Context Contract and Recursive Mutex Synchronization

## Result and scope

The SD host controller interface and kernel driver synchronization contracts are now fully resolved from module initialization through hardware register dispatch:

1. **Host controller context structure (`struct host_hw`)**: allocated with size **208 bytes** (`0xd0`) by `kmem_cache_alloc` in `mmc_hw_init` (.text `0xc8f0`) and `mmc_hw_open` (.text `0xdff4`). Byte `+0x00` is `hw_id` (0..3). Up to 4 controller slots are tracked.
2. **Hardware operations table (`ip_func_ops`)**: located in `.bss` at offset `0xfa8` (**48 bytes**, 4 entries * 12 bytes). Populated at runtime by `mmc_hw_wrapper_get_ops` (.text `0x18840`), which routes legacy SD/eMMC slots to `mmc_hw_get_ops_info` (.text `0xe2f4`) and UHS-II slots to `mmc_hw_uhs2_get_ops_info` (.text `0x1dfdc`).
3. **Dispatch table registration**: `mmc_hw_get_ops_info` registers the static operations table at `.bss + 0xd34`, populated by `mmc_hw_init`:
   - `+0x00`: `mmc_hw_open`
   - `+0x24`: `mmc_hw_exec_command`
   - `+0x2c`: `mmc_hw_lock_sem`
   - `+0x30`: `mmc_hw_unlock_sem`
4. **Recursive mutex locking contract**: `mmc_hw_lock_sem` (.text `0xc404`) and `mmc_hw_unlock_sem` (.text `0xc3ec`) add `#0x4c` to `host_hw` and invoke `mmc_os_lock_sem_long` (.text `0x121c`) / `mmc_os_unlock_sem_long` (.text `0x1278`).
   - `mmc_os_lock_sem_long` extracts `current_thread_info()` via `sp & ~0x1fff` (`0xffffe000`) and reads `task->pid` at `task + 0x104`.
   - If `current->pid` matches `sem->owner_pid` at `sem + 0x18` (offset `+0x64` in `host_hw`), it increments recursion depth `sem->nest_count` at `sem + 0x1c` (offset `+0x68`) and returns `0` without blocking.
   - If not owned, it invokes `_mutex_lock`, records `owner_pid = current->pid`, sets `nest_count = 1`, and returns `0`.
   - `mmc_os_unlock_sem_long` decrements `nest_count`; when zero, it clears `owner_pid` and invokes `_mutex_unlock`.
5. **Physical MMIO base and SDHCI registers**:
   - `mmc_hw_init` maps physical address **0xf2a00000** via `udif_ioremap` and stores the virtual pointer at `host_hw + 0x8c`.
   - `mmc_hw_exec_command` (.text `0xd754`) polls `SDHCI_PRESENT_STATE` at register offset **0x2c** via `mmc_os_read16`, checking bit 2 (`SDHCI_DATA_INHIBIT`) and bit 0 (`SDHCI_CMD_INHIBIT`).
   - Activity LED GPIO is signaled via `mmc_hwconf_led_on(*host_hw)` on command start and `mmc_hwconf_led_off()` on completion or error.
6. **Command construction & dispatch**:
   - `set_r1_cmd` (.text `0x12b0c`): sets opcode (CMD17 for single block, CMD18 for multi block), response type 1 (R1), and starting LBA at `cmd + 0x14`.
   - Data helper `0x12658`: sets selector 3 (read) at `cmd + 0x10`, block size 512 (`0x200`) at `cmd + 0x84`, sector count at `cmd + 0x86`, and scatterlist at `cmd + 0x88`.
   - Transfer helper `0x15588`: calls `mmc_hw_wrapper_exec_command(host_hw, cmd)`, then transfer completion calls `0x12acc` (`mmc_hw_wrapper_unlock_sem(host_hw)`).

Card `E:\` was not modified or written. No synthetic register values, fake DMA transfers, or main/UI advances were invented.

## Hardware controller context layout (`struct host_hw`)

`struct host_hw` is allocated with size **208 bytes** (`0xd0`):

| Offset | Field | Type | Function / Description |
| --- | --- | --- | --- |
| `+0x00` | `hw_id` | `uint8_t` | Host controller index (`0..3`), checked with `cmp r1, #3` in all wrappers. |
| `+0x08` | `eventflag` | `struct eventflag` | Command completion waitqueue, initialized by `mmc_os_init_eventflag` in `mmc_hw_open`. |
| `+0x4c` | `lock_sem` | `struct sem_long` | Host recursive mutex, initialized by `mmc_os_init_sem_long` (`_mutex_do_init`). |
| `+0x64` | `lock_owner_pid` | `int32_t` | PID of active lock holder (`lock_sem + 0x18`). |
| `+0x68` | `lock_nest_count`| `int32_t` | Recursion counter (`lock_sem + 0x1c`). |
| `+0x6c` | `card_int_sem` | `struct sem_short`| Interrupt spinlock, initialized by `mmc_os_init_sem_short`. |
| `+0x8c` | `mmio_base` | `void*` | Kernel virtual address of mapped SDHCI registers (physical `0xf2a00000`). |

## Operations table structure (`ip_func_ops`)

Located in `.bss` at offset `0xfa8`:

```
ip_func_ops[4]:
  [0]: { void *ops = 0xd34, uint32_t flags = 0, void *vendor_ops = 0xdc4 }
  [1]: { void *ops = ...,   uint32_t flags = ..., void *vendor_ops = ... }
  [2]: { void *ops = ...,   uint32_t flags = ..., void *vendor_ops = ... }
  [3]: { void *ops = ...,   uint32_t flags = ..., void *vendor_ops = ... }
```

Slot operations table (`.bss + 0xd34`) offsets:

| Offset | Function | Implementation | Role |
| --- | --- | --- | --- |
| `+0x00` | `open` | `mmc_hw_open` (0xdff4) | Allocates `host_hw`, sets up IRQ, eventflag, mutexes. |
| `+0x04` | `release` | `mmc_hw_release` | Shuts down controller and frees context. |
| `+0x08` | `init_host_ctrl` | `mmc_hw_init_host_ctrl` | Configures SDHCI host controller registers. |
| `+0x0c` | `sw_reset` | `mmc_hw_sw_reset` | Issues software reset to SDHCI core. |
| `+0x24` | `exec_command` | `mmc_hw_exec_command` (0xd754) | Turns on LED, checks present state `0x2c`, launches transfer. |
| `+0x2c` | `lock_sem` | `mmc_hw_lock_sem` (0xc404) | Calls `mmc_os_lock_sem_long(host_hw + 0x4c)`. |
| `+0x30` | `unlock_sem` | `mmc_hw_unlock_sem` (0xc3ec) | Calls `mmc_os_unlock_sem_long(host_hw + 0x4c)`. |

## Hardware register map

| Register / Physical Address | Offset | Access width | Role |
| --- | --- | --- | --- |
| `0xf2a00000` | `0x00` | - | Physical MMIO base for SDHCI host controller (mapped via `udif_ioremap`). |
| `SDHCI_PRESENT_STATE` | `0x2c` | 16-bit | Polled via `mmc_os_read16(mmio_base, 0x2c)`: bit 2 = DATA inhibit, bit 0 = CMD inhibit. |
| Activity LED | GPIO | - | Controlled via `mmc_hwconf_led_on` and `mmc_hwconf_led_off`. |

## Native WSL REA verification

Five procedure queries completed cleanly via Ghidra 12.1.4 in WSL (`artifacts/tools/rea/sd-hardware-lock/`):
- `00-procedure_pseudo_code.json`: `mmc_hw_init` (confirms `0xf2a00000`, `kmem_cache_alloc(..., 0xd0)`, and ops table setup).
- `01-procedure_pseudo_code.json`: `mmc_hw_open` (confirms `hw_id` store at byte 0, `+0x08` eventflag, `+0x4c` sem_long, `+0x6c` sem_short).
- `02-procedure_pseudo_code.json`: `mmc_hw_lock_sem` (confirms `mmc_os_lock_sem_long(param_1 + 0x4c)`).
- `03-procedure_pseudo_code.json`: `mmc_os_lock_sem_long` (confirms recursive lock PID comparison at `+0x18`, `nest_count` at `+0x1c`, `_mutex_lock`).
- `04-procedure_pseudo_code.json`: `mmc_hw_exec_command` (confirms `mmc_hwconf_led_on`, `SDHCI_PRESENT_STATE` read at `0x2c`, inhibit checks).

## Reproduction and validation

```powershell
python -m tools.research.sd_hardware_profile --report-dir artifacts/analysis/NEW_HW_PROFILE
python -m unittest tests/test_sd_hardware_profile.py
```

- Verified report `artifacts/analysis/sd-hardware-profile-verified` and repeat are byte-identical with SHA-256 **4e4047127c7d4b39acd7f94132fa2fb0d82c78cd466ce2e2861b47d815731509**.
- 7 new tests in `tests/test_sd_hardware_profile.py`.
- Full regression suite passes: **374 passed**, 0 failed, 0 errors (`artifacts/execution/sd-hardware-final-suite.txt`).
- Updated status visualizations: `status_a6400.png` and `artifacts/reports/status_a6400.png`.
