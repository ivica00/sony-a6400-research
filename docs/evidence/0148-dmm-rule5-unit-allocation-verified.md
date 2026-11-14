# E0148: DMM Rule 5 Activation and Native Unit Allocation Verified

Date: 2026-11-07.  
Scope: Sony ILCE-6400 (firmware 2.00, kernel 3.0.27_nl-rt106+).  
Goal: Verify programmatic activation of DMM Rule 5 (`AllocRule 5`) and native allocation of units `0x276` (JPEG sequence buffer) and `0x274` (JPEG frame buffer) on the live camera via OSAL UIPC queue `0x0061003c`, with full resource release lifecycle and regression verification.

---

## 1. DMM UIPC Protocol and Message Structure (`QUEUE_DMM 0x0061003c`)

Decompiling the `msg_hdlr` table in kernel module `dmm.ko` (offset `0x80` in `.rodata`) and disassembling handler functions established the exact binary message format for communication over `/dev/uipc`:

1. **Header and Message Field Layout**:
   - `msg[-4]` (OSAL reply queue header): `reply_qid` (dynamic queue allocated via `ioctl 0x8000000c`, op `0x2a`).
   - `msg[0x00..0x01]` (`uint16_t`): Command opcode.
   - `msg[0x02..0x03]` (`uint16_t` or `uint8_t`):
     - For `SetAllocRule` (20 / `0x14`): Rule number (`rule`, e.g., 5 for Shooting / LiveView).
     - For `FreeUnit` (4 / `0x04`): Unit handle (`handle`).
   - `msg[0x04..0x07]` (`uint32_t`): `unit_type` (e.g., `0x00000276` or `0x00000274`) for `AllocUnitNew` and `GetUnitHandle`.
   - `msg[0x16..0x17]` (`uint16_t`):
     - For `SetAllocRule`: Mode (`mode`: `0` = replace base rule, `0x100` = push onto stack, `0x101` = pop from stack).
     - For `AllocUnitNew`: Attribute flags (`flags`: `0`).

2. **Supported Opcodes in `msg_hdlr`**:
   - `[01]` (`0x01`): `dmm_ctrl_AllocUnitNewHdlr`
   - `[04]` (`0x04`): `dmm_ctrl_FreeUnitHdlr`
   - `[05]` (`0x05`): `dmm_ctrl_OpenUnitHdlr`
   - `[06]` (`0x06`): `dmm_ctrl_CloseUnitHdlr`
   - `[20]` (`0x14`): `dmm_ctrl_SetAllocRuleHdlr`
   - `[26]` (`0x1a`): `dmm_ctrl_GetUnitHandleHdlr`

---

## 2. Physical Verification on Camera

Standalone ARM tools without libc dependencies (`probe_dmm_rule_arm`, `test_single_jpeg_pipeline_arm`, `free_both_units_arm`) were developed and run directly in RAM directory `/tmp_bt`:

1. **Pre-Activation State Check**:
   - `GetUnitHandle(0x276)`: returns status `6`, handle `0xffff` (rejected).
   - `GetUnitHandle(0x274)`: returns status `6`, handle `0xffff` (rejected).
   - `/proc/udm/dmm_rule`: `[0000]`.

2. **Rule 5 Activation (`SetAllocRule(5, 0)`)**:
   - `SetAllocRule(5, 0)` returns status `0` (success).
   - `/proc/udm/dmm_rule` transitions to:
     ```text
     Information on AllocRule.
     [0005] < ffff < ffff < ffff < ffff < ffff < ffff < ffff
     ```

3. **Native Unit Allocation under Rule 5**:
   - `AllocUnitNew(0x276, 0)`: returns status `0`, handle `0x08d0`.
   - `AllocUnitNew(0x274, 0)`: returns status `0`, handle `0x08cd`.
   - Reading `/proc/udm/dmm_units` confirmed physical existence and exact addresses in camera RAM:
     ```text
     08cd     00000274  0001    01     00    00    02      00000606  14000000  00040000  0390 < 0388 < 0153 < 0005
     08d0     00000276  0001    01     00    00    02      00000605  14300000  00200000  039c < 0388 < 0153 < 0005
     ```
     - **Unit `0x274`**: physical address `0x14000000`, size 256 KiB (`0x00040000`).
     - **Unit `0x276`**: physical address `0x14300000`, size 2 MiB (`0x00200000`).
     - Both units belong to root extent `0005` (96 MB at `0x14000000`).

4. **Clean Resource Release and Restoration to Initial State**:
   - `FreeUnit(0x08cd)` and `FreeUnit(0x08d0)` executed via `free_both_units_arm`.
   - `/proc/udm/dmm_units` confirmed completely clean (0 leftover handles).
   - `SetAllocRule(0, 0)` restored `AllocRule` to `[0000]`.

---

## 3. Video Pipeline Synchronization Findings (`Sugilite` ISP)

1. When sending `SET_PATH start (1280x720, 30 FPS)` in Mass Storage mode:
   - Thread 355 (`THREAD_INFRA0`) communicates with the ISP driver via `sugilite_ioctl`.
   - Hardware initialization takes longer than 800 ms. Premature termination of the client process causes a dmesg error:
     ```text
     [K]**UIPC ERROR** osal_snd_msg: snd to invalid qid 02d96104 != 00000000 @ 635dd483
     ```
   - For reliable operation, the client timeout for `SET_PATH start` must be set to at least 3000 ms.

---

## 4. Regression Verification

- Full emulator test suite executed successfully:
  ```text
  Ran 599 tests in 15.092s - OK
  ```
- Physical camera: Mass Storage mode, debugger PID 703 responsive, `/proc/udm/dmm_units` clean, no memory leaks.
- All camera writes remain strictly limited to RAM `/tmp_bt`.
