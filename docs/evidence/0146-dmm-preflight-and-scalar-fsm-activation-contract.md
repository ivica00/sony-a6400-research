# E0146: DMM Preflight, ScalarInfra FSM Activation Contract, and Shooting Stage Analysis

Date: 2026-11-07. All writes on the camera were strictly limited to `/tmp_bt`; no SD/NAND/backup/preload/boot modifications. No blocking `0x8120` (`ScalarJpegOpen`) call was issued on the live camera. Debugger PID 703 active and responsive in Mass Storage mode. All 599 emulator tests pass.

## 1. DMM Preflight on Live Camera (`/proc/udm/`)

The DMM subsystem was located and inspected on the live camera via `/proc/udm/`:
- `/proc/udm/dmm_units`: List of active units. Units `UnitType 0x276` (JPEG sequence buffer) and `UnitType 0x274` (JPEG frame buffer) **are not present**.
- `/proc/udm/dmm_rule`: Current allocation rule is exclusively `[0000] < ffff < ffff < ffff < ffff < ffff < ffff < ffff`.
- `/proc/udm/dmm_extents`: Root extent `0005` (type `0x000004ec`) is mapped at physical address `0x14000000` (size 96 MB, `0x06000000`).
- Comparison with `DmmConfig.bin` (ilc8g-astra):
  - `UnitType 0x274` (JPEG frame buffer, 12 slots of 256 KiB, `0x40000`) uses extent `0x32e`.
  - `UnitType 0x276` (JPEG sequence buffer, 2 MiB, `0x200000`) uses extent `0x333`.
  - Both extents are under parent table `0x32f` -> `0x41d` -> root extent `0x4ec` (`0x14000000`).
  - In Mass Storage mode rule `0` does not carve extents `0x32e` and `0x333`. Calling `dmm_unit_ctrl_Alloc` for `0x276` in this mode deterministically returns status `-3` (`0xfffd`, `handle = 0xffff`).

## 2. Thread Deadlock Prevention in `ScalarJpegOpen_candidate` (`0x63a918c0`)

Decompilation of `ScalarJpegOpen_candidate` (`0x63a918c0`) in `oril-jpeg-open-close-e0144`:
```c
while (true) {
    iVar2 = FUN_63a8c7b8(0x276, 0, auStack_8c);
    *(undefined2 *)(param_1 + 0x78) = local_88;
    if (iVar2 == 0) break;
    *(undefined2 *)(param_1 + 0x78) = 0xffff;
    local_28 = 2000; // 2000 ms sleep
    func_0x635dd4a8(0x910041, local_40);
    if (uVar4 == 0x14) {
        func_0x63c26e94("[SFRA][ERROR] MEMORY SHORTAGE!!! file=%s line=%d", "ScalarInfraSequenceJpeg.cpp", 0x65);
    } else if (15000 < uVar4) {
        // break only after 15,000 iterations (> 8 hours!)
    }
    uVar4 = uVar4 + 1;
}
```
**Conclusion:** Thanks to Phase 1, sending an unverified `0x8120` (`SET_PATH(OPEN)`) was prevented, saving the `ScalarInfraAsyncMain` thread from an 8-hour stall.

## 3. Internal ScalarInfra FSM Analysis (`0x01670464`)

Disassembling and decompiling `av-cam-camera-original.bin` (base `0x635c6000`):
1. **External receivers**:
   - `CMD_JPEG` (`0x50` on `0x0167046a`, function `FUN_63a90a84`) repacks parameters (including `path_enable` at `+0x40`) and sends a DataflowInfra message to queue **`0x01670464`**.
   - `CMD_LIVEVIEW` (`0x51` on `0x0167046a`, function `FUN_63a90b70`) also sends to queue **`0x01670464`**.
2. **Internal FSM transition (`ScalarInfraPathCmdSetPath`)**:
   - `ScalarInfraPathCmdSetPath::TransPathIdle()` (`0x63a8fc94`):
     - Calls `msg->GetStatus()`.
     - If status is `1`, calls `SendOpenPathCmdToAsyncTask()` (`0x63a8fa6c`) and transitions to state `2`.
     - `SendOpenPathCmdToAsyncTask()` sends internal message `0x8120` (`SET_PATH(OPEN)`) to `ScalarInfraAsyncMain`.
     - If status is `0`, calls `0x63a8fbec` which sends internal message `0x8110` (`SET_PATH(CLOSE)`).
   - `ScalarInfraPathCmdSetPath::TransPathLiveView()` (`0x63a90100` -> `0x63a99810`):
     - Iterates from 0 to `0x31` (sequence selectors, including `0x30`/`0x31` for JPEG) and requests allocation of DMM `UnitType 0x2d5`.

## 4. Architectural Implication for Option B (Sensor / LiveView)

In USB Mass Storage mode:
- The camera is in passive disk mode, the sensor is in standby/off, and DMM holds only rule `0` (no active recording buffers).
- For the sensor to start generating real 720p frames:
  1. DMM rule must transition to shooting state (Shooting mode / PC Remote), in which extents `0x32e` and `0x333` are allocated under `0x14000000`.
  2. BIONZ X ISP and scaler start cyclically writing JPEG frames into 12 slots of the circular buffer at `0x643c3708 + 0xf4` (`ready = 1`).
  3. Coherent UVC feeder reads `ready = 1` slots, transfers them into DMA buffer (`0x05280000`), and sends them to host over the UVC streaming interface.

## 5. Regression and Stability

- All emulator tests: **599 tests passed in 14.884s**.
- Camera state: MSC mode, debugger PID 703 intact and responsive, module `usbg_video` removed, no changes on flash or SD card.
