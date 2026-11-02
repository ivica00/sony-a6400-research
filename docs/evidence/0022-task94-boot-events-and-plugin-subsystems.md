# Evidence Record 0022: Task 94 Boot Events, Dynamic ID Contract, and Camera Subsystem Activation

## Context and Goal

Evidence Record 0021 established the structure of Task 94's event callback table and identified the `/dev/fb0` display subsystem architecture. The objective of this milestone is Package H: activating authentic camera subsystem loading by implementing the `UIPC_CMD_DYNAMIC_ID` (`0x8000000c`) kernel contract, delivering authentic boot events (`0x00940007`, `0x0092014b`, `0x00940036`, `0x00940038`) into Task 94's queue `0x0094016a`, and tracing `im.elf`'s plugin initialization sequence through `libObj.so` and camera framework subsystems.

## Findings

### 1. `UIPC_CMD_DYNAMIC_ID` (`0x8000000c`) Kernel Contract
Reverse engineering of `osal_uipc.ko` (`__k_uipc_cdev_ioctl` at offset `0x618` and `__k_4u_dynamic_id` at offset `0x6a4`) and `libosal_uipc.so` (`osal_dynamic_id` at `0x4840`) identified the dynamic identifier management protocol:
- User space passes a 12-byte request block: `struct { uint32_t type; uint32_t key; uint32_t *out_id_ptr; }`.
- When `type & 0x40 != 0`, the driver releases the dynamic ID and returns 0.
- When allocating (`type & 0x40 == 0`), the driver allocates a dynamic ID (`0x80001001`+), associates it with `key`, writes the 32-bit identifier back to `*out_id_ptr`, and returns 0.
- Implemented in `GuestUipc.handle_dynamic_id` and registered under `UIPC_CMD_DYNAMIC_ID`.

### 2. Event Dispatch and Handler Switching Architecture
Disassembly of `im.elf` event processing (`0x9360` - `0x93d0` and `0xa344` - `0xa388`) revealed the two-level handler state machine:
- Handler 1 (`0x9361`): Active during boot state 5 (`0xa2fc`).
  - Upon receiving Event `0x00940001`: calls `0xab80`, switches handler pointer at `[0x14ee4]` to Handler 2 (`0x92d9`), and transitions state to 1 (`main` exits).
  - Upon receiving Event `0x00940007`: verifies boot state 5 (`0xaae4`), loads target bitmask (`0xa410`), and calls plugin initialization routine `0xac18`.
- Injected authentic boot events on queue `0x0094016a`:
  - `0x00940007`: Boot Phase 7 / Plugin Activation.
  - `0x0092014b`: `Is` (Initialize Shared Subsystems via `libIMDB.so`).
  - `0x00940036`: Phase 6 (`libDpro_EVF.so` Electronic Viewfinder).
  - `0x00940038`: Phase 8 (`appFw.so` and `gui.so` Application Framework).

### 3. Large-Scale Camera Subsystem Activation
When Event `0x00940007` and subsequent boot stimuli are delivered:
- `im.elf` calls `0xac18`, triggering dynamic linking and loading across the entire camera software stack.
- Successfully loaded and linked over 30 Sony camera shared libraries (86 open file operations):
  - Windowing & Graphics: `/usr/lib/libObj.so` (`ux::wgtsys::WidgetSystem`, `ObjDisplay`).
  - Framework & Business Logic: `libBizFw.so`, `libBizFw2.so`, `libMWF.so`, `libSysDef.so`.
  - Media & Hardware Services: `libInfraFsys.so`, `libmprctrl.so`, `libmpr.so`, `libsencore.so`, `libclema.so`, `libAK8975.so`.
  - Communication & Network: `libNetRemote.so`, `libNetCommon.so`, `libGOConnectionManager.so`, `libUsbControl.so`.
  - Cryptography & System: `libcrypto.so.1.0.0`, `libssl.so.1.0.0`, `libexpat.so.1`, `dataflowInfraFramework.so`.
- The execution reached **15,000,000 instructions** and **592 serviced syscalls** in the probe without crashing or encountering an unsupported exception, executing the real GNU dynamic linker relocation loop (`do_lookup_x` at `0x40007048` in `ld-linux.so.3`).

## Verification

- `src/a6400/execution/guest_uipc.py`: implemented `handle_dynamic_id` and wired `UIPC_CMD_DYNAMIC_ID`.
- `tests/test_guest_uipc.py`: added `test_dynamic_id_allocation_and_free`.
- Full regression suite: **204 passing tests** (100% pass rate, 0 failures).
- All 10 historical baselines maintained strictly intact.
