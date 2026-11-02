# Evidence 0070: Sugilite Display Pipeline Handshake, Render Loop, and Surface Memory Transfer

## Summary

In Evidence 0069, execution reached 100M instructions with `GuestUsbBusPower` integrated, but thread 1008 was observed polling `GLES_GET_RESOURCE_SUB` (`0xc004820d`) repeatedly (1,012,670 times). Disassembly of `libObj.so` at `0x72baf0`–`0x72bb30` revealed that userland was waiting for `dev->sub_device_id` (display sub-device / panel ready) to be non-zero. Updating `GuestGles` with `sub_device_id: 1` (sub-device 1 = active camera display panel) and `resource_table[2]: 1` resolved the handshake.

In the subsequent 100M instruction boot run (`artifacts/execution/ui-boot-subdevice1-100m.json`):
1. **Wait-loop Exit**: Thread 1008 exited the polling wait at `0x72baf0` and acquired graphics semaphores.
2. **Continuous Frame Render Cycles**: The Sugilite display pipeline executed **61,582 continuous frame rendering cycles**:
   - `GLES_GET_POWER_STATE_ALT` (`0x8004820a`): 61,582 calls
   - `GLES_GET_RESOURCE_SUB` (`0xc004820d`): 61,582 calls
   - `GLES_LOCK_SEMAPHORE` (`0xc0048211`): 123,168 calls
   - `GLES_UNLOCK_SEMAPHORE` (`0xc0048212`): 123,166 calls
3. **Surface Transfer**: During each render cycle, `libObj.so` at `0x72c250` traverses 800 display elements (`0x320`, corresponding to display width/elements) and transfers surface memory via authentic ARM `memcpy` in `libc-2.11.2.so` at `0x502601c0`.
4. **Execution Dynamics**: Syscall frequency dropped from 1,013,768 to 370,584 because the CPU budget was actively consumed by real rendering computation and memory block transfers rather than syscall spinning.

## Disassembly Analysis

### 1. Panel Readiness Polling Handshake (`libObj.so` `0x72baf0`–`0x72bb30`)
```arm
0x0072baf0:  push       {r4, r5, r6, r7, lr}
0x0072baf2:  sub        sp, #0xc
0x0072baf4:  add        r7, sp, #0
0x0072baf6:  ldr        r5, [pc, #0x48]
0x0072bb08:  movw       r1, #0x820d         ; GLES_GET_RESOURCE_SUB
0x0072bb0c:  ldr        r0, [r5]            ; fd 10 (/dev/dmpgles2)
0x0072bb14:  blx        ioctl
0x0072bb18:  cbnz       r0, #0x72bb30       ; check ioctl return
0x0072bb1a:  ldr        r0, [r7, #4]        ; read sub-device status word
0x0072bb1c:  cmp        r0, #0              ; 0 => not ready, loop
0x0072bb1e:  beq        #0x72bb08
0x0072bb20:  add.w      r7, r7, #0xc
0x0072bb24:  mov        sp, r7
0x0072bb26:  pop        {r4, r5, r6, r7, pc} ; panel ready! Return to render loop
```

### 2. Display Element Traversal and Surface Update (`libObj.so` `0x72c250`)
```arm
0x0072c250:  push.w     {r4, r5, r6, r7, r8, sb, sl, fp, lr}
0x0072c254:  sub        sp, #0x3c
0x0072c25e:  bl         #0x72bbb0           ; lock semaphore 1
0x0072c2fc:  mov.w      ip, #0x320          ; 800 display elements / width
0x0072c300:  movt       r0, #0x51eb         ; reciprocal multiply for /800
0x0072c304:  mul        r5, r6, r3          ; element offset (stride 0x8c bytes)
...
0x0072c398:  mls        r3, ip, r8, r4
0x0072c41c:  movs       r2, #1              ; mark element active
0x0072c420:  strb       r2, [r1]
...
```

### 3. Frame Render Cycle Trace
The steady-state cycle per frame:
```
1. ioctl(fd 10, GLES_GET_POWER_STATE_ALT, ...) -> power active (status 0)
2. ioctl(fd 10, GLES_UNLOCK_SEMAPHORE, sem=1)
3. ioctl(fd 10, GLES_GET_RESOURCE_SUB, &subdev) -> subdev = 1 (panel ready)
4. ioctl(fd 10, GLES_LOCK_SEMAPHORE, sem=1) -> lock acquired
5. Traversal and surface block transfer (libc memcpy at 0x502601c0)
6. ioctl(fd 10, GLES_LOCK_SEMAPHORE, sem=2)
7. ioctl(fd 10, GLES_UNLOCK_SEMAPHORE, sem=2)
```

## Regression and Validation

- Test suite: 486 tests pass cleanly (`Ran 486 tests in 14.822s, OK`).
- Physical SD card `E:\` remains strictly read-only (`\\.\E:`).
- GPU rendering operates authentically via genuine Sugilite driver contracts and memory mappings.
