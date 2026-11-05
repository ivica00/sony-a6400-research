# Evidence 0073: Live Hardware Ground Truth and A6400 Boot Telemetry

## Summary
Execution on physical Sony ILCE-6400 camera (Serial 03925553, FW 2.00) confirms unattended bootloader execution and yields 88,415 bytes (1,562 lines) of complete live operating system and hardware telemetry (`reports/a6400_hw_dump.txt`). 

## Key Telemetry Findings

### 1. Kernel Architecture & Command Line
* **Kernel:** `Linux (none) 3.0.27_nl-rt106+ #1 SMP PREEMPT RT Tue Aug 10 13:03:39 JST 2021 armv7l GNU/Linux`
* **SoC:** Sony CXD90045 Quad-Core ARM Cortex-A5 (`CPU0`, `CPU1`, `CPU2`, `CPU3`).
* **Kernel Command Line Parameters:**
  * Root filesystem: `rootfstype=ext2 root=/dev/ram0 init=/sbin/init initrd=0x700000,8M`
  * System RAM: `mem=1G@0 mem=256M@0x80000000@1` (Total 1.25 GB physical RAM).
  * CMA / Reserved memory pools:
    * `memrsv=704M@0x14000000:uc`
    * `memrsv=242M@0x80e00000:uc`
    * `wbimem=0x3916000@0x20200000` (DMM gl_common matches emulator at PA `0x202e0000`!)

### 2. Device Numbers & Peripheral Contracts
Discovered exact device majors and minors matching `devno.ko` and live `/dev` filesystem:
* `/dev/dmpgles2`: Character major **248**, minor **29** (DMP Sugilite GPU)
* `/dev/hdmi`: Character major **248**, minor **25**
* `/dev/hdmi_external_tx`: Character major **248**, minor **26**
* `/dev/hdmi_input`: Character major **248**, minor **30**
* `/dev/gpio`: Character major **240**, minor **0**
* `/dev/mmca1`: Block major **250**, minor **11**
* `/dev/fb0`: Character major **29**, minor **0**

### 3. Main Process (`im.elf`, PID 149) Address Space & Display Mapping
* **PID:** 149 (launched under parent `launch_shell.elf` PID 1).
* **Base Executable:** `0x00008000-0x0000d000` (`/usr/bin/im.elf`).
* **Sugilite Engine (`libObj.so`):** Mapped at virtual address `0x05d18000-0x0700e000` (`.text`), data at `0x07016000-0x07106000`.
* **Primary VRAM DMA Buffer (`/dev/stream`):**
  * Virtual range: `0x08a5f000-0x0aa5f000` (Size: 32 MiB / `0x02000000`).
  * Physical base: `PA 0x202e0000`.
  * Exactly confirms the emulator contract established in Evidence 0066!
* **DMP Sugilite Hardware Register Mapping:**
  * Virtual range: `0x0b5a2000-0x0b5c2000` (Mapped directly from `/dev/dmpgles2`).

### 4. PMCA Senser Driver Bug Fix
* Resolved the 32 KB chunk timeout bug in `Sony-PMCA-RE/pmca/usb/sony.py`: modern Sony cameras (PID `0x0CAA`) do not emit a trailing 512-byte dummy packet for chunk transfers; patched chunk loop avoids blocking `driver.read(512)` timeouts.

## Verification
* Telemetry acquired directly from camera internal memory `/tmp/a6400_hw_dump.txt` via authenticated USB Senser mode.
* Full test suite: 506 unit tests passing.
