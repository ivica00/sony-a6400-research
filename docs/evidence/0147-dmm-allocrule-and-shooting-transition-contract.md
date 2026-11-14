# E0147: DMM AllocRule Architecture and Shooting State Transition Contract

Date: 2026-11-07.  
Scope: Sony ILCE-6400 (firmware 2.00, kernel 3.0.27_nl-rt106+).  
Goal: Determine the mechanism for setting DMM rules (`AllocRule`), the reason `0x276`/`0x274` are unallocated in Mass Storage mode, and the architecture for transitioning to an active shooting state (Shooting / PC Remote) to acquire the native 720p 30 FPS JPEG video stream for CinemaHUD via Windows inbox `usbvideo.sys`.

---

## 1. DMM AllocRule and Rule Structure in Kernel (`dmm.ko`)

Analysis of disassembled code of module `dmm.ko` and unpacked `DmmConfig.bin` (ilc8g-astra, 77,108 bytes) established the exact allocation rule check algorithm:

1. **Extent Table Header Format (`dmm_ext_tbl_Init`, 80 bytes per entry)**:
   - Each extent header in `DmmConfig.bin` contains 20 words (80 bytes).
   - Words 4 to 19 (offsets `+0x10` to `+0x4f`) form an array of exactly 64 bytes representing activation attributes for 64 possible allocation rules (`rule` from 0 to 63):
     $$\text{rule\_byte} = \text{header}[0x10 + \text{rule}]$$

2. **Rule Verification in Kernel (`0x0000a658` inside `dmm_ext_ctrl_AllocExtent`)**:
   - When allocating an extent, the kernel retrieves the currently active rule by calling `dmm_ext_ctrl_GetCurrentAllocRule`:
     ```arm
     0x0000b720: add r0, r4, #8
     0x0000b724: bl  dmm_ext_ctrl_GetCurrentAllocRule
     0x0000b738: bl  #0xa658
     ```
   - Inside function `0xa658`, the kernel checks the rule byte in the extent header:
     ```arm
     0x0000a78c: mov  r2, #0x50           ; 80 bytes per header
     0x0000a790: mla  r3, r2, r0, r3      ; header address
     0x0000a794: add  r3, r3, r8          ; r8 = rule number (0..63)
     0x0000a798: ldrb sl, [r3, #0x10]     ; sl = header[0x10 + rule]
     0x0000a79c: cmp  sl, #0              ; is byte != 0?
     0x0000a7a0: bne  #0xa7b0             ; YES: extent is allowed
     0x0000a7a4: b    #0xa7d0             ; NO (0): skip extent (reject allocation)
     ```
   - If `sl == 0` or does not meet the minimum attribute (`sl < r0`), function `0xa658` returns `-1`, and `dmm_unit_ctrl_Alloc` returns error code `-3` (`ERR_DMM_HANDLE`) with handle `0xffff`.

3. **State in Mass Storage Mode (`/proc/udm/dmm_rule`)**:
   - On the live camera `/proc/udm/dmm_rule` reads:
     ```text
     Information on AllocRule.
     [0000] < ffff < ffff < ffff < ffff < ffff < ffff < ffff
     ```
   - Active rule is exclusively `[0000]` (Rule 0).
   - Root extent `0005` (type `0x000004ec`, 96 MB at physical address `0x14000000`) is mapped in the kernel, but has exactly zero allocated sub-extents because the sensor and ISP pipeline is not initialized in USB storage standby mode.

---

## 2. Shooting State Transition in Camera Application (`av-cam-camera-original.bin`)

Decompiling the user-space camera application (`av-cam-camera-original.bin`, base `0x635c6000`) located the original video output and DMM rule-setting subsystem:

1. **Video Pipeline Source References (`SyncYCOut.cpp`)**:
   - A set of string references confirmed the original C++ components:
     - `SyncYCOut.cpp` (synchronous YCbCr video output management)
     - `ScalarInfraSequenceLiveView.cpp` (LiveView JPEG sequence)
     - `ScalarInfraSequenceJpeg.cpp` (JPEG encoding and ring buffer)
     - `sfmc_enc_timing_i_a1_diadem_streaming_30p25p.cpp` (30 FPS video stream timing control)
   - In `SyncYCOut.cpp` (`0x63939486`) and related functions:
     ```arm
     0x63939482: mov  r0, r6
     0x63939484: movs r1, #5              ; Rule 5 (Shooting / LiveView)!
     0x63939486: bl   #0x63d51ff0
     ```
   - All 8 callers of function `0x63d51ff0` (`0x638b812c`, `0x638b821c`, `0x639250c2`, `0x63928834`, `0x63939486`, `0x6393a5b6`, `0x6393ad3a`, `0x6394ab84`) pass `r1 = 5`!

2. **DMM Transfer and UIPC Queue `0x0061003c`**:
   - `0x63d51ff0` calls `0x6394f820`, which sends a message with event 6 and the desired rule to the Infra controller.
   - Transitioning to Rule 5 activates DMM allocations of extents `0x32e` (UnitType `0x274`, 12 slots of 256 KiB) and `0x333` (UnitType `0x276`, 2 MiB sequence buffer) within the 96 MB window at `0x14000000`.

---

## 3. USB Mode Architecture (`libUsbControl.so` and CinemaHUD)

1. **Mode Comparison**:
   - **Mass Storage (MSC)**:
     - Launches `libInfraMscServer.so` (loaded in PID 149 at `0x0c6d5000`).
     - Sensor, BIONZ X ISP, and video encoder are idle. Screen displays static text "USB Mode: Mass Storage".
     - DMM holds Rule 0; circular buffer at `0x643c3708 + 0xf4` is empty (`ready = 0`).
   - **PC Remote / PTP (CinemaHUD contract from E0137)**:
     - Camera is in full active shooting state (Shooting mode). Sensor and ISP are active.
     - Launches `libInfraStreamingServer.so` and PTP subsystem (`libptp.so`).
     - JPEG ring buffer is continuously filled with live frames.
     - CinemaHUD fetches frames via PTP transaction `PTP_OC_GetObject(0xFFFFC002)`.

2. **Debugger Compatibility**:
   - Root debugger (PID 703) uses Sony vendor extension (Feature `0x23`) which is supported on both MSC (`SonyMscExtCmdDevice`) and PTP/MTP (`SonyMtpExtCmdDevice`).
   - Verified in E0137: Debugger remains fully accessible and responsive in PC Remote mode.

---

## 4. Regression Verification

- Full emulator test suite executed successfully:
  ```text
  Ran 599 tests in 14.681s - OK
  ```
- Physical camera: Connected via USB, Mass Storage mode, debugger PID 703 active and responsive.
- All camera writes remain strictly limited to RAM `/tmp_bt`.
