# E0177 — Physical USB Owner and Verified State of Original Service

Date: 2026-11-08. User switched the camera to Mass Storage. Existing debugger PID703 is available again as root. The shared PTP/UVC module was neither transferred nor loaded. All new payload/log writes on the camera remain in `/tmp_bt`.

## Owner Inventory on Camera

The new `tools/research/capture_uvc_ptp_owner_inventory.py` transfers only the small read-only tool, verifies byte-equal readback, executes it with output in `/tmp_bt`, and archives its full output to the host. It does not replace the USB configuration and does not stop any thread group.

The first attempt was archived in `artifacts/hardware/uvc-ptp-live-owners-e0177`: the E0176 tool mistakenly used `0x10000` for `O_DIRECTORY`. On ARM that is a different flag, so opening `/proc` was rejected and the tool exited with `proc_unavailable`/exit 3. It was not a valid owner inventory. The previous fixture audit used the same wrong assumption and did not prove the real kernel ABI flag.

The fix uses the original cross-target `<asm/fcntl.h>` and `O_RDONLY|O_DIRECTORY` (ARM `0x4000`). The fixed tool is 3376 bytes, SHA-256 `6302bf9333e0cb2032771b0f4b1abfe4fac40bea85a44d0684990ae17ba4ef83`. New build: `artifacts/native/uvc-ptp-owner-inventory-e0177/uvc_ptp_owner_inventory`; the fixed offline audit passes 23 checks again.

The first successful physical read at 13:08:57 UTC and a repeated read yield the same OWNER/TASK records:

- character device `242:1` (`usb/gadgetcore`) is held by **PID149, FD85**;
- the owner has **175 threads**;
- both exits: `owners=1, threads=175, errors=0`;
- both logs were archived without truncation.

These are two observational snapshots, not atomic confirmation that no new owners or already-started syscalls exist. Details: `artifacts/hardware/uvc-ptp-live-owners-e0177-corrected/{manifest.json,repeat-manifest.json,owners.log,owners-repeat.log}`.

## Real Threads and Waits

`comm`/`wchan` were read for all 175 threads. OSAL proxy TID150/151/152/156 all four show `__k_4u_wait_cb`. `UsbControl` names have TID323/650/651/818/821; TID650 waits in `usb_event_read`, while the other observed `UsbControl` threads wait in `futex_wait_queue_me`.

Names alone are not proof of a specific C++ object or a single executor. `/proc/149/task/<tid>/syscall` and `/stack` return `ENOENT` on this camera; all 18 failed read-only attempts are retained in `kernel-waits-manifest.json`. There is no conclusion that the kernel stack was inspected thereby.

## Original Libraries and Live Object

The first whole-file hash check stopped further reading because hashes of the real `/usr/lib` libraries differ from the extracted files. The real files were then read and saved before continuing:

| Library | Real SHA-256 |
|---|---|
| libUsbControl.so | b5cea9d2c92a0b0810353900871fa2806ca3064aa5d8cf3ca7db5ddb6f3940e2 |
| libInfraUsbCmn.so | 733acef066e3e3691f7258e7416b638a7960d99b70f27e85ddc4daad2b5ecef2 |

Sectional comparison shows identical addresses and byte-equal contents of **all allocatable sections**, including `.text`, `.plt`, `.rodata`, `.data`, and relocations; among the compared contents, `.comment` differs. Whole-file hashes were not declared equal. Selected dynamic symbols and bodies of `doStop`/`doSyncStartStop`/`doInitialize` and `CUsbSvc::stop`/`usbif_initialize` were separately compared. No generic offset between different builds was used.

Based on the real maps/ELF `PT_LOAD` contracts, bases `libUsbControl=0x04857000` and `libInfraUsbCmn=0x04161000` were obtained. A bounded debugger memory read compared the real `doStop` body against the file before reading data. Every data address and size was verified against readable maps ranges.

Observed:

| Field | Value |
|---|---|
| pending completion queue | 0 |
| public USB interface object | 0x001f09f8 |
| CUsbSvc object | 0x00056e28 |
| original start/stop pointers | 0x0416e551 / 0x0416e37d |
| CUsbSvc gadgetcore FD (+0x90) | **85**, matching FD inventory |
| service state (+0x98) | 3 |
| gadget/host handle | 0 / 0xffffffff |

Original service state 3 and pending queue 0 were observed in separate short reads. They are not proof that all kernel entries or EP0 callbacks are drained. The debugger memory read temporarily uses `ptrace` on the single thread being read; there is no group CPU freeze or writes to application memory. The final status confirms that `ptrace` did not remain attached.

## Final State and Next Step

The camera is in Mass Storage mode, debugger PID703 remains responsive. `/proc/version` confirms `3.0.27_nl-rt106+ SMP PREEMPT RT`; the saved `/proc/modules` does not contain a new shared UVC candidate. Artifacts, libraries, real data, and final status are in the successful capture folder.

Physical proof now exists of which process holds gadgetcore and which original object belongs to it. The next step is a bounded check of completely stopping those entries and resuming them before installing the wrapper, along with a separate boundary for kernel/gadget callbacks. E0164 remains `physical_test_ready:false`; shared enumeration, camera control during UVC, and sensor UVC streaming have not been tested.
