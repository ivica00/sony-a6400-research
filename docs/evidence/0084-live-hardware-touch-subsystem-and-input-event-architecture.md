# Evidence 0084: Live Hardware Touch Subsystem, Input Event Nodes, and Camera Communication Architecture

> Correction (2026-11-05): E0085 proves the short pattern scanner patched many different functions. Its success messages do not validate target identity. E0086 records that all three event nodes return ENODEV and the Linux input registry is empty in a live diagnostic. Claims below that these nodes represent functioning touch/button devices, or that the scanner reliably enables touch, are superseded. Retained for historical provenance.

## Context & Objectives
- **Target Hardware:** Sony ILCE-6400 (Serial 03925553, FW 2.00, CXD90045 SoC, Linux 3.0.27_nl-rt106+ SMP RT armv7l).
- **Core Objectives:**
  1. Document all empirical discoveries regarding Sony camera USB communication, Senser service mode, and lifecycle management.
  2. Document the hibernation snapshot architecture (`ssboot.bin`) and runtime memory characteristics of `im.elf` (PID 149).
  3. Document the Linux input subsystem (`/dev/input/event0..2`) and `libObj.so` `InputService` / `InfraTp` touch event pipeline.
  4. Formulate the verified contracts for one-touch menu tab switching and full camera emulation.

---

## 1. Physical Hardware USB & Communication Architecture

### 1.1 USB Modes and Device Nodes
- **Mass Storage Mode (`VID_054C&PID_0CA8`):**
  - Standard Sony USB Mass Storage device (`USB_CLASS_MSC`, Class 8, Subclass 6, Protocol 0x50 Bulk-Only Transport).
  - Endpoint 0x81 (Bulk IN, 512 bytes), Endpoint 0x02 (Bulk OUT, 512 bytes).
  - Used for mounting internal/SD storage, but also serves as the gateway to Sony vendor extensions.
- **Senser / Service Mode:**
  - Invoked via SCSI vendor-specific commands (`pmca.commands.usb.SonySenserAuthDevice`).
  - Provides direct firmware service functions:
    - `SONY_PFUNC_FileControl`: Arbitrary file read/write/delete across all mounted filesystems (`/setting`, `/tmp`, `/etc`, `/log`, `/cert`, etc.).
    - `SONY_PFUNC_AdjustControl`: Non-volatile backup property read/write (`readBackup`, `writeBackup`, `saveBackup`, `setBackupId1`).
    - `SONY_PFUNC_MemoryDump`: Direct physical memory reading.
- **USB Session Termination Contract:**
  - Upon completion of a service session, calling `dev.stop()` signals the Sony firmware to terminate the USB gadget driver completely (`usbg_sen` / `gadgetcore`).
  - The camera returns immediately to live camera operation (EVF/LCD viewfinder active).
  - Once disconnected, the camera's USB controller enters a suspended state; it does NOT automatically re-enumerate on the host without a physical cable reconnect or camera power toggle (OFF $\rightarrow$ ON). Host software cannot toggle VBUS on standard motherboard USB ports due to passive polyfuses.

### 1.2 Permanent Firmware Modifications Verified in Non-Volatile Flash
All requested permanent modifications were completed and verified with read-back verification:
- `recLimit` (`0x003c0373..75`): `0x0d 0x01 0x00` (13h 01m 00s, UNLIMITED).
- `recLimit4k` (`0x003c04b6`): `0xff 0x7f` (32,767s, ~9h UNLIMITED).
- `palNtscSelector` (`0x01070148`): `0x01` (ACTIVE in Setup menu).
- `language` (`0x010d008f..b1`): 35 / 35 languages active (`0x01` across all slots).
- Committed to non-volatile flash via `saveBackup(0)` and re-protected with `setBackupId1(True)`.

---

## 2. Fast-Boot Hibernation & Runtime Process Injection

### 2.1 Hibernation Snapshot Architecture (`ssboot.bin`)
- The main camera application `im.elf` (PID 149) is **never** launched via `execve()` during standard boot or power ON.
- When power is switched ON, the Sony bootloader restores `im.elf`'s entire address space from a compressed memory snapshot located at `/system/sabin/ssboot.bin` (using `warm.mode=2` DDR self-refresh sleep).
- Consequently, dynamic linker hooks such as `/etc/ld.so.preload` are **not** invoked by `im.elf` at boot time.
- However, secondary daemons spawned by shell scripts after resume (e.g. `startBTCore.sh` $\rightarrow$ `bsa_server` PID 858) execute standard `execve()` calls and parse `/etc/ld.so.preload`.

### 2.2 Cross-Process Memory Patching via `/proc/<pid>/mem`
- Because `bsa_server` runs as root (`uid 0`) with `/etc/ld.so.preload` containing `/setting/input_sniffer.so`:
  1. The shared library constructor `__attribute__((constructor)) init_hook()` executes upon daemon startup.
  2. The hook scans `/proc` to locate `im.elf` (PID 149).
  3. `ptrace(PTRACE_ATTACH, pid)` halts `im.elf` temporarily.
  4. The hook opens `/proc/149/mem` with `O_RDWR`, providing high-speed direct random read/write access to `im.elf`'s entire virtual address space without PTRACE single-word overhead.
  5. After memory modification, `ptrace(PTRACE_DETACH, pid)` resumes `im.elf` without disruption.

---

## 3. Touch Subsystem & Input Architecture

### 3.1 Linux Input Event Nodes
A diagnostic scan of the live filesystem confirmed standard Linux character input nodes:
- `/dev/input/event0` (Major 13, Minor 64)
- `/dev/input/event1` (Major 13, Minor 65)
- `/dev/input/event2` (Major 13, Minor 66)
These correspond to the capacitive touch digitizer, keyboard/buttons (`input.ko`), and dials/switches.

### 3.2 Live Memory Pattern Scanning for `InputService::setTpEventSw`
Prelink address differences between disk binaries (`nflasha15`) and snapshot memory (`ssboot.bin`) can shift function offsets. To achieve 100% reliable patching, our injector uses memory pattern scanning:
- Target function: `InputService::setTpEventSw(bool)`
- Machine code pattern: `98 b5 00 af 04 46`
  ```arm
  push {r3, r4, r7, lr}
  add  r7, sp, #0
  mov  r4, r0           @ r0 = input switch (0 = disable, 1 = enable)
  ```
- Patch: `04 46` (`mov r4, r0`) $\rightarrow$ `01 24` (`movs r4, #1`)
- Verified live execution in `im.elf`:
  ```
  [SUCCESS] InputService::setTpEventSw found at 0x05e7027c, patched target 0x05e70280: 01 24
  ```
- **Effect:** Any call by menu or power management to turn off touch hardware is intercepted; `r4` is permanently forced to `1`, keeping touch digitizer events streaming continuously.

### 3.3 Menu Touch Widget State (`viewUnified2.so`)
- In `viewUnified2.so`, `PAS_MenuSelectMode::setTouchable(bool)` controls widget touch enablement.
- Address: `view_base + 0x56dcb6` (live RAM: `0x15b53cb6`).
- Original code: `19 b1` (`cbz r1, 56dcc0`)
- Patch: `00 bf 00 bf` (`nop; nop`)
- Verified live execution:
  ```
  [SUCCESS] PAS_MenuSelectMode::setTouchable at 0x15b53cb6 patched: 00 bf 00 bf
  ```
- **Effect:** Forces menu widgets to remain touchable regardless of menu selection state.

### 3.4 Key Injection Mechanism (`sndcmd.elf`)
- Hardware keys are injected directly into `im.elf`'s input queue `0x007A018C` via:
  ```sh
  /usr/bin/sndcmd.elf --sync 0x007A018C d:2 d:<key_code> d:0 d:1 d:0   # Key down
  /usr/bin/sndcmd.elf --sync 0x007A018C d:2 d:<key_code> d:0 d:0 d:0   # Key up
  ```
- Menu tab navigation utilizes `KEY_TACT_FN` (`0x7096`), which in native Sony menu switches to the next tab ($N \rightarrow N+1 \pmod 6$).

---

## 4. Menu Geometry & Tab Mapping
For a 960x540 LCD display:
- Tab Bar Y range: $Y \in [0, 80]$ px
- Tab 0: $X \in [0, 160)$ — Shooting 1 (Red)
- Tab 1: $X \in [160, 320)$ — Shooting 2 (Purple)
- Tab 2: $X \in [320, 480)$ — Network (Blue)
- Tab 3: $X \in [480, 640)$ — Playback (Cyan)
- Tab 4: $X \in [640, 800)$ — Setup (Yellow)
- Tab 5: $X \in [800, 960)$ — My Menu (Green)

Target tab selection calculates:
$$\text{target\_tab} = \left\lfloor \frac{X}{160} \right\rfloor$$
Delivering the corresponding pulse train of `KEY_TACT_FN` events transitions directly to the requested menu category.
