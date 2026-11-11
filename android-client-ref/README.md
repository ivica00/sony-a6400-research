# a6400 live-view reference client (Android, raw USB)

A dependency-light Android client for the Sony ILCE-6400 that pulls live view over
**raw USB host** â€” no Windows, no WPD, no Camera2 â€” and drives camera settings over the
**physically verified Sony PTP control surface**.

The client is deliberately boring: `android.*` + the Kotlin stdlib only, plain
`Thread`/`Executor` concurrency (no coroutines), one bulk-OUT writer thread, one bulk-IN
reader thread, and a fixed JNI contract for the native renderer.

> **Status honesty.** The Kotlin in this directory has never been compiled: this
> environment has no Android SDK, no Gradle, no JDK 17 and no `kotlinc` (see
> `docs/VERIFICATION.md`). Everything here is offline-authoring plus the static
> verifier `tools/verify_structure.py`. Treat the first `./gradlew assembleDebug` as a
> bring-up step, not as a formality.

---

## 1. Architecture

```
                        â”Śâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                        â”‚                     MainActivity (UI thread)             â”‚
                        â”‚  transport selector Â· Start/Stop Â· step buttons Â· log    â”‚
                        â”‚  FPS / age p50-p95 / drop overlay Â· sharpness Â· peaking   â”‚
                        â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                                        â”‚ FrameSink                â”‚ controlExecutor
                                        â”‚ (delivery thread)        â”‚ (single thread)
      â”Śâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–Ľâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”Śâ”€â”€â”€â”€â”€â”€â”€â–Ľâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
      â”‚            usb/PtpTransport  (transport A)     â”‚   â”‚  usb/PtpSony           â”‚
      â”‚                                                â”‚   â”‚  0x1002 / 0x9201 x3    â”‚
      â”‚  pump thread â”€â”€â–ş window of 2-3 GetObject 0x1009 â”‚   â”‚  0x9202 / 0x9209       â”‚
      â”‚  writer thread â”€â”€â–ş bulk OUT 0x02 (one owner)    â”‚   â”‚  0x9207 notch (effective)â”‚
      â”‚  reader thread â”€â”€â–ş bulk IN  0x81 (one owner)     â”‚   â”‚  0x9205 absolute (ACKs, â”‚
      â”‚  delivery thread â”€â”€â–ş drop-oldest frame queue     â”‚   â”‚          NOT effective) â”‚
      â”‚  control queue: priority + strict drain rule     â”‚   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
      â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                 â”‚                       â”‚
                 â”‚ frames                â”‚ controls
                 â–Ľ                       â–Ľ
      â”Śâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”Śâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
      â”‚ NativePipeline (JNI) â”‚   â”‚ ILCE-6400 PC Remote, VID 0x054C PID 0x0CAA â”‚
      â”‚  liba6400lived.so    â”‚   â”‚ interface class 6/1/1                      â”‚
      â”‚  decode â†’ SGSR renderâ”‚   â”‚ bulk OUT 0x02 Â· bulk IN 0x81 Â· int IN 0x83 â”‚
      â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                 â”‚ GLES 3.x
                 â–Ľ
      â”Śâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”        â”Śâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
      â”‚ gl/SgsrSurfaceView   â”‚        â”‚ usb/UvcTransport  (transport B, SECONDARY)â”‚
      â”‚  EGL 3.2 request     â”‚        â”‚ composite VID 0x054C PID 0x0322           â”‚
      â”‚  nativeRender/frame  â”‚        â”‚ PTP if 0 Â· UVC VC if 1 Â· VS if 2 Â· EP 0x84â”‚
      â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”        â”‚ PROBE/COMMIT + MJPEG reassembly           â”‚
                                      â”‚ **UNVERIFIED: never produced a frame**    â”‚
                                      â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
```

Two transports, one UI, one renderer:

| | Transport A â€” PTP (default) | Transport B â€” UVC |
|---|---|---|
| Device | `054C:0CAA` (single function) | `054C:0322` (composite UVC+PTP) |
| Frames | `GetObject 0x1009 [0xFFFFC002]`, complete JPEGs | UVC bulk IN `0x84`, MJPEG payload headers |
| Camera side | **nothing** (stock PC Remote) | requires the camera-side daemon workstream |
| Evidence | physically verified, 24.6â€“30.8 fps, 1024x680, 52â€“141 KB | descriptor verified only; **no frame ever** |
| Controls | PTP `0x9207`/`0x9209` (this app) | PTP (same session) â€” never UVC XU |
| UI label | `PTP / PC Remote (primary)` | `UVC composite (UNVERIFIED)` |

Frame latency is reported as **host-side age** (`captureNs` from the transport data phase to
the render return). The camera-side sensor/encode/DMA terms are not observable from the
host and are therefore never claimed; `artifacts/analysis/recon-e0348/USB_GADGET.md` Â§5.4
does the full arithmetic and lands on **â‰40â€“55 ms realistic glass-to-glass**, not <35 ms.

---

## 2. What the app does, and what it refuses to do

* **Frames** â€” `PtpTransport` keeps 2â€“3 `GetObject` requests in flight, treats the camera's
  8-zero-byte reply as a retry token, reassembles a length-prefixed container stream with a
  512 KiB frame cap, drops the oldest frame when the display queue is full, and hands
  complete JPEGs to `NativePipeline.nativePushJpeg`.
* **Controls** â€” only `0x9207` (signed notch) changes a setting. `0x9209` readback is the
  only source of truth, rendered in the panel. The step buttons send one notch, then
  re-read `0x9209`; nothing is reported as applied without a readback.
* **`0x9205` absolute writes** are implemented (`PtpSony.setAbsolute`) because they are
  part of the evidenced surface, but **no UI path calls them**: on this body the firmware
  maps those codes to directional UI keys, so an absolute write can be acknowledged and
  have no effect (`artifacts/analysis/recon-e0348/CONTROL_IPC.md` Â§0, Â§2.4).
* **No invented features.** There is no AF trigger, no touch focus, no REC, no white
  balance setting: none of them has a decoded code/property/mechanism in the evidence base.
* **Fail closed.** Missing native library, unsupported UVC step, a PTP fault or a control
  timeout all produce a visible error and no frames â€” never a black surface presented as
  success.

---

## 3. Build

### 3.1 Toolchain (pinned)

| Component | Version | Where |
|---|---|---|
| Android Gradle Plugin | `8.5.2` | `build.gradle.kts` |
| Kotlin | `1.9.24` | `build.gradle.kts` |
| Gradle | `8.7+` | no wrapper is vendored; run `gradle wrapper --gradle-version 8.7` once |
| JDK | 17 | `compileOptions` / `jvmTarget` |
| compileSdk / targetSdk / minSdk | 34 / 34 / 26 | `app/build.gradle.kts` |
| NDK | `26.3.11579264` (r26d) | `pinnedNdkVersion` in `app/build.gradle.kts` |
| CMake | `3.22.1` (bundled with that NDK) | `app/build.gradle.kts` |
| ABI | `arm64-v8a` only | `defaultConfig.ndk.abiFilters` |

No AndroidX, no Kotlin extensions, no third-party dependency of any kind. That is a
design constraint, not an unfinished dependency list: adding a dependency to a raw-USB
transport is how this kind of client acquires threads it does not own.

### 3.2 Native renderer (`app/src/main/cpp`)

`app/build.gradle.kts` declares:

```kotlin
externalNativeBuild { cmake { path = file("src/main/cpp/CMakeLists.txt") } }
```

That directory is owned by the native-pipeline workstream and is **not** authored here.
`NativePipeline.kt` declares exactly nine `external fun`s and loads `a6400lived`; the
native side must export `Java_com_a6400_lived_NativePipeline_nativeXxx` (Kotlin `object`
members are instance methods, so the JNI signature takes a `jobject`).

If `liba6400lived.so` is missing, the first `NativePipeline` touch throws, the app logs
`native pipeline unavailable: ...` and refuses to start a session. There is no silent
fallback renderer.

Result conventions this client relies on (and reads back from the native side):

* `nativePushJpeg` → `0` = accepted (native `kOk`); negative = rejected
  (`kErrInvalidArgument = -2`, `kErrBusy = -12`, …). A non-zero result is counted as a
  dropped frame and logged.
* `nativeRender` → a **status** (`0` = ok), not a frame identity. A presented frame is
  detected by watching `nativeGetStats` index 5 ("frames rendered") on the GL thread.
* `nativeGetStats` → `0 decoded, 1 dropped, 2 avg decode us, 3 last decode us, 4 last upload
  us, 5 frames rendered, 6 errors, 7 buffer state`, `8..13` diagnostics.

### 3.3 Vendoring libjpeg-turbo

The renderer decodes MJPEG, so the native build needs libjpeg-turbo. It is vendored as a
source tree â€” never as a prebuilt `.so` â€” under:

```
app/src/main/cpp/third_party/libjpeg-turbo/
â”śâ”€â”€ CMakeLists.txt          (upstream, unmodified)
â”śâ”€â”€ jpeglib.h  jconfig.h  turbojpeg.h  ...
â””â”€â”€ simd/  src/  ...
```

Procedure (once, on a machine with network access):

```powershell
# from the repository root, with the native cpp tree already present
cd android-client-ref\app\src\main\cpp\third_party
git clone --depth 1 --branch 3.0.4 https://github.com/libjpeg-turbo/libjpeg-turbo.git libjpeg-turbo
Remove-Item -Recurse -Force libjpeg-turbo\.git
```

Then, in `app/src/main/cpp/CMakeLists.txt` (native workstream):

```cmake
set(JPEG_ENABLE_SHARED FALSE CACHE BOOL "" FORCE)
set(JPEG_ENABLE_STATIC TRUE  CACHE BOOL "" FORCE)
set(JPEG_ENABLE_TESTS  FALSE CACHE BOOL "" FORCE)
set(WITH_SIMD TRUE CACHE BOOL "" FORCE)
add_subdirectory(third_party/libjpeg-turbo EXCLUDE_FROM_ALL)
target_link_libraries(a6400lived PRIVATE turbojpeg-static)
```

Rules for that tree:

1. **Pin the version** (`3.0.4` above) and record its SHA-256 in the CMake comment; do not
   track a branch.
2. Do not set `ANDROID_STL` differently from the app (`c++_static`, already in
   `app/build.gradle.kts`).
3. Only `arm64-v8a` is built; a 32-bit or multi-ABI build would silently change the SIMD
   path this client measures latency on.

### 3.4 Build and install

```powershell
cd android-client-ref
gradle wrapper --gradle-version 8.7      # once
.\gradlew.bat :app:assembleDebug
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

The APK needs no CAMERA permission and no runtime permission other than the USB grant the
system shows when the camera is attached.

---

## 4. Evidence pins

Every opcode and every unit in this client is pinned to a repo receipt. Nothing here is
from memory or from a PTP reference document alone.

| What | Value | Evidence |
|---|---|---|
| USB identity (transport A) | `VID 054C / PID 0CAA`, PTP class 6/1/1, EP `0x02`/`0x81`/`0x83` | `docs/evidence/0343-cinemahud-ptp-demo-verified.md:8-26`, `docs/evidence/0315` (descriptor capture `09 04 00 00 03 06 01 01 05`) |
| Discovery rule | first interface with class 6, force claim, first bulk IN/OUT | `android/cinemahud/android/.../MainActivity.kt:95-99` |
| Container framing | 12-byte LE header `{len u32, type u16, code u16, tid u32}` | `MainActivity.kt:109`, reader `:120-138` |
| Handshake | `0x1002[1]` â†’ `0x9201[1,0,0]` â†’ `0x9201[2,0,0]` â†’ `0x9202[0xC8]` â†’ `0x9201[3,0,0]` | `CONTROL_IPC.md` Â§1.2, `sony_ptp.dart:239-250`, `tools/research/ptp_liveview_client.py:340-358` |
| Liveview frame | `GetObject 0x1009` handle `0xFFFFC002`, complete JPEG 1024x680, 52â€“141 KB, 24.6â€“30.8 fps | `docs/evidence/0339`, `0343`, `0151:21` |
| No-frame sentinel | 8 zero bytes means "no new frame, retry" | `docs/evidence/0151:21`, `USB_GADGET.md` Â§3.3/C1 |
| Settings read | `0x9209` â†’ one 1730-byte property blob | `CONTROL_IPC.md` Â§1.3, Â§5; `sony_ptp_controls.py:358` |
| Settings write (effective) | `0x9207` params `[code]`, data = one signed byte; confirmed shutter 1/100â†’1/125â†’1/100, aperture f/2.8â†’f/3.2â†’f/2.8, EV 0â†’+0.3â†’0 | `docs/CINEMAHUD_STOCK_PTP.md:71-74`, `sony_ptp.dart:380-418` |
| Settings write (ack'd, ineffective) | `0x9205`; camera handler `InfraRemoteUsb::CtrlCode2InputKey` maps codes to directional UI keys | `CONTROL_IPC.md` Â§0, Â§2.4 |
| Property codes | aperture `0x5007`, shutter `0xD20D`, ISO `0xD21E`, EV `0x5010`, focus mode `0x500A`, battery `0x5001` (absent) | `CONTROL_IPC.md` Â§2.3, `sony_ptp.dart:118-123` |
| Value units | shutter `num<<16` combined with `den`, aperture fĂ—100, EV millistop, ISO absolute with `0xFFFFFF`=Auto | `sony_ptp.dart:200-214`, `CONTROL_IPC.md` Â§2.3 |
| PTP fetch cost | `ptp_fetch_ms = 10.233` | `artifacts/analysis/p8-status2.json:898` |
| Interleave rule + no 200 ms settle | two queues over one serialized writer; controls only in a gap; the 200 ms `apply()` sleep was client politeness | `USB_GADGET.md` Â§5.3 |
| Transport B identity | `054C:0322`, PTP interface 0, UVC VC/VS 1/2, VS MJPEG 1280x720, bulk IN `0x84` | `docs/evidence/0339`, `0347`, `USB_GADGET.md` Â§0 |
| UVC request shape | `bmRequestType 0x21/0xA1`, `bRequest 0x01/0x81`, `wValue=CS<<8`, `wIndex=(entity<<8)|interface` | `USB_GADGET.md`/`CONTROL_IPC.md` Â§4.7(a), `tools/native_camera/uvc_ptp_adapter.c:9-17` |
| Why <35 ms is not promised | producer is frame-based MJPEG at ~30 fps | `USB_GADGET.md` Â§5.4 |

---

## 5. Verified vs unverified

| Item | State |
|---|---|
| PTP handshake, `0x9209` read, `0x9207` notch, `0x1009` liveview on `054C:0CAA` | **Verified physically** (prior rounds; see pins above) |
| Kotlin sources in this directory compile | **No** â€” no SDK/Gradle/JDK in this environment |
| APK build, JNI link, GL surface on a phone | **No** â€” nothing has been run |
| `0x9205` having any effect | **Verified ineffective** (handler maps codes to UI keys) |
| Transport B producing a frame on this camera | **Never observed** â€” descriptor/transport only; UI labels it UNVERIFIED |
| Transport B on Android (`uvcvideo` detach, claim of `0x84`, Camera2 competing) | **Unknown** â€” this client force-claims and reports diagnostics |
| Camera-side encode/DMA latency | **Unknown** â€” excluded from the overlay by construction |
| ISO/EV/shutter/aperture step direction semantics (`CtrlCode2InputKey` key order) | **Partially inferred**: directions come from the proven client's metric, not from a decoded key table |

---

## 6. Threading and ownership (hard rules)

1. One writer thread owns bulk OUT; it is the only place a transaction becomes live.
2. One reader thread owns bulk IN and the reassembly buffer.
3. A control transaction is written **only when no frame transaction is in flight**, and
   the frame pump stops adding frames as soon as a control is queued. The pipeline drains
   first; a control therefore costs at most one pipeline drain (~10 ms measured fetch),
   never an interleave inside a live data phase.
4. A transaction id is never reused while it is live.
5. Frames are delivered on a dedicated thread with a bounded queue and drop-oldest, so a
   slow decoder can never stall the USB pipe.
6. All USB open/handshake/teardown runs on the connect executor; all controls run on the
   control executor; the UI thread only builds views and reads counters.

---

## 7. Layout

```
android-client-ref/
â”śâ”€â”€ settings.gradle.kts, build.gradle.kts, gradle.properties
â”śâ”€â”€ app/build.gradle.kts, app/proguard-rules.pro
â”śâ”€â”€ app/src/main/AndroidManifest.xml
â”śâ”€â”€ app/src/main/res/xml/usb_device_filter.xml
â”śâ”€â”€ app/src/main/res/values/strings.xml
â”śâ”€â”€ app/src/main/java/com/a6400/lived/
â”‚   â”śâ”€â”€ MainActivity.kt            USB permission, attach/detach, panel, overlay, log
â”‚   â”śâ”€â”€ NativePipeline.kt          the nine fixed JNI entry points
â”‚   â”śâ”€â”€ gl/SgsrSurfaceView.kt      EGL 3.2 request + nativeConfigure/nativeRender
â”‚   â”śâ”€â”€ media/LatencyTracker.kt    (capture, decode, render) ring, fps, p50/p95, drops
â”‚   â””â”€â”€ usb/
â”‚       â”śâ”€â”€ TransportContracts.kt  TransportKind, LogSink, FrameSink, exceptions
â”‚       â”śâ”€â”€ UsbHost.kt             discover by VID/PID, permission, claim, endpoints
â”‚       â”śâ”€â”€ PtpContainer.kt        container codec + stream assembler + 0x9209 parser helpers
â”‚       â”śâ”€â”€ PtpTransport.kt        reader/writer/pump/delivery threads, window, control lane
â”‚       â”śâ”€â”€ PtpSony.kt             handshake, 0x9205/0x9207/0x9209, units, labels
â”‚       â””â”€â”€ UvcTransport.kt        transport B: descriptors, PROBE/COMMIT, MJPEG assembly
â”śâ”€â”€ docs/PROTOCOL.md               exact wire formats
â”śâ”€â”€ docs/VERIFICATION.md           what was and was not verified, bring-up checklist
â””â”€â”€ tools/verify_structure.py      the static gate (stdlib only)
```

## 8. Verifying the tree without an SDK

```powershell
.\venv\Scripts\python.exe android-client-ref\tools\verify_structure.py
```

It fails loudly on: a missing file, a changed JNI signature, a missing PTP opcode, a
manifest without USB host declarations, a Gradle file without the CMake path, any
`TODO`/`FIXME`/stub marker in shipping Kotlin, and unbalanced braces per file.
