# Verification record — a6400 reference Android client

This file is the honest record of what was proven about this client, what was not, and
exactly how to bring it up on hardware. It is written after the fact, from the commands
that were actually run.

**Nothing in `android-client-ref/` has been compiled or executed on a device.** The
environment has no Android SDK, no Gradle, no JDK 17 and no Kotlin compiler (evidence in
§1): the Kotlin was **not compiled** and the APK was never built. Everything claimed as
"verified" below is either (a) a static check over the source tree, or (b) a protocol fact
pinned to a physical receipt produced by earlier rounds of this repository (see
`README.md` §4).

---

## 1. Environment — why nothing could be compiled

Commands run in the authoring environment (Windows, repo root):

```text
gradle   -> NOT FOUND
javac    -> NOT FOUND
kotlinc  -> NOT FOUND
adb      -> NOT FOUND
java     -> C:\Program Files (x86)\Common Files\Oracle\Java\java8path\java.exe   (Java 8 JRE, no compiler)
cmake    -> C:\mingw64\bin\cmake.exe                                            (host CMake, no Android toolchain)
ANDROID_HOME      = <unset>
ANDROID_SDK_ROOT  = <unset>
%LOCALAPPDATA%\Android\Sdk -> does not exist
```

Consequences, stated plainly:

* `./gradlew assembleDebug` was never run. Gradle syntax, AGP 8.5.2 / Kotlin 1.9.24
  compatibility, manifest merging and resource linking are **unverified**.
* The Kotlin was never type-checked. It was written conservatively (no coroutines, no
  AndroidX, no third-party libraries, platform APIs only, explicit nullability) to keep the
  first compile boring, but the first compile is still a real step.
* `app/src/main/cpp/**` (the native renderer, its `CMakeLists.txt`, and the vendored
  libjpeg-turbo hooks) and `android-client-ref/tests/**` are owned by the native-pipeline
  workstream. They appeared in the tree *during* this session and were **not** authored,
  modified or executed by this workstream; the Kotlin side was cross-checked read-only
  against them (see §2.4). A build still needs the native tree's own `turbojpeg` source,
  which is not vendored yet.
* `externalNativeBuild` points at `src/main/cpp/CMakeLists.txt`, so a build without that
  directory fails at the native step, not silently.

---

## 2. What was statically verified

### 2.1 The static gate: `tools/verify_structure.py`

```powershell
.\venv\Scripts\python.exe android-client-ref\tools\verify_structure.py
```

Result on the final tree: **PASS: all 112 checks** (exit code 0). The gate fails loudly on:

| Group | What it proves |
|---|---|
| required files | all 22 source/doc/build files exist and are non-empty |
| JNI contract | `NativePipeline.kt` declares **exactly** the nine agreed `external fun`s, in order, character-for-character, and calls `System.loadLibrary("a6400lived")` |
| PTP surface | `0x1002`, `0x1003`, `0x1009`, `0x9201`, `0x9202`, `0x9205`, `0x9207`, `0x9209`, `0x2001`, `0x201E`, handle `0xFFFFC002`, property codes `0x5007`, `0xD20D`, `0xD21E`, `0x5010`, `0x500A`, `0x5001`, the `0xC8` argument, and both the notch (`stepNotch`) and absolute (`setAbsolute`) paths |
| manifest | `uses-feature android.hardware.usb.host` with `required="true"`, the `USB_DEVICE_ATTACHED` intent filter **and** its meta-data, `@xml/usb_device_filter`, `configChanges` containing `orientation`, `MainActivity` declared, and **no** CAMERA `uses-permission` |
| device filter | VID `1356` (0x054C) with PID `3242` (0x0CAA) and PID `802` (0x0322) |
| Gradle | `path = file("src/main/cpp/CMakeLists.txt")`, compileSdk 34 / minSdk 26 / targetSdk 34, `JVM_17`, `abiFilters += "arm64-v8a"`, `ndkVersion = pinnedNdkVersion`, the literal `"26.3.11579264"`, no AndroidX dependency coordinate, `android.useAndroidX=false` |
| hygiene | zero `TODO`/`FIXME`/`XXX`/`HACK`/`stub`/`not implemented` markers in shipping Kotlin, zero `import androidx` |
| structure | braces balanced per `.kt` file using a comment- and string-aware scanner |
| docs | README/PROTOCOL/VERIFICATION keep the verified-vs-unverified split, the 0x9205 "not effective" warning, the libjpeg-turbo vendoring path, the 1730-byte blob, the endpoint map and the UVC PROBE/COMMIT sequence |

Additional throw-away checks run during authoring (not shipped):

* parenthesis and bracket balance per Kotlin file — 0 problems;
* every file decodes as strict UTF-8 with no BOM and no U+FFFD;
* no two statements merged onto one line (a real syntax bug that this caught once).

### 2.2 Protocol facts encoded (not proven by this client)

Every opcode, code, unit and rule in this client is transcribed from a physical receipt of a
previous round. The pins are listed in `README.md` §4 and `docs/PROTOCOL.md`. The load-bearing
ones:

* handshake order `0x1002[1] → 0x9201[1,0,0] → 0x9201[2,0,0] → 0x9202[0xC8] → 0x9201[3,0,0]`;
* one `0x9209` read returns the whole 1730-byte property set;
* `0x9207` with a one-byte signed notch is the effective control path (shutter, aperture, EV,
  ISO all confirmed physically);
* `0x9205` absolute writes are acknowledged and **not effective** (the camera turns the code
  into a directional UI key);
* `GetObject 0x1009 [0xFFFFC002]` returns a complete JPEG, or 8 zero bytes for "no new frame";
* measured PTP fetch ≈ 10.2 ms; liveview 1024×680, 52–141 KB, 24.6–30.8 fps.

### 2.3 Repository test baseline (must not regress)

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -q
Ran 1181 tests in 21.445s     <- measured at the start of this work
OK
Ran 1196 tests in 21.669s     <- re-measured at the end; still OK
OK
```

The 1181 → 1196 drift is **not** from this tree: `git diff --stat tests` shows 7 test files
and ≈1400 inserted lines written concurrently by other workstreams, and no file under
`tests/` references `android-client-ref` (verified by search). This client adds no file under
`tests/` and no import into the Python package, so it cannot move that number in either
direction.

### 2.4 Read-only cross-check against the native JNI implementation

The native workstream's `app/src/main/cpp/jni_bridge.cpp` appeared while this client was being
written. It was read (not modified) and the following were confirmed to line up with
`NativePipeline.kt`:

| Contract item | Native side | Kotlin side |
|---|---|---|
| library name | `add_library(a6400lived SHARED ...)` | `System.loadLibrary("a6400lived")` |
| symbol shape | `Java_com_a6400_lived_NativePipeline_nativeXxx(JNIEnv*, **jobject**, ...)` | Kotlin `object` members (instance methods) — matches |
| `nativePushJpeg` result | `kOk = 0`, errors negative (`kErrInvalidArgument = -2`, `kErrBusy = -12`, …) | success is `result == 0`; anything else is a drop, logged |
| `nativeRender` result | `int` status (`kOk = 0`, negative errors) — **not** a frame identity | status only logged; a presented frame is detected from `nativeGetStats` index 5 |
| `nativeGetStats` layout | `0 decoded, 1 dropped, 2 avg decode us, 3 last decode us, 4 last upload us, 5 frames rendered, 6 errors, 7 buffer state, 8..13 diagnostics` | overlay reads 0..7 and passes a 14-slot array |
| `nativeConfigure` | `configure(viewportW, viewportH, frameW, frameH)` | called on every surface-size change with the liveview geometry |

That cross-check is why the two integration bugs above (inverted `kOk` test and using
`nativeRender`'s status as a frame signal) were caught **before** any hardware existed. It is
still a source-level check, not a link.

---

## 3. On-device bring-up checklist

Ordered, with the **exact log lines** the client emits (the in-app log pane and `adb logcat
-s a6400-lived`). A step is only done when its line appears.

### 3.0 Camera preparation

1. Camera menu → **USB → PC Remote**. (This transition is the proven-safe one; leave the
   camera in PC Remote for the session.)
2. Cable the phone with an OTG adapter. Expect the system USB-permission dialog (or the
   attach broadcast, if the app is already open).

### 3.1 Permission

```
usb: attached VID:PID=054C:0CAA '...' - press Start (transport A: PTP, transport B: UVC UNVERIFIED)
usb: found ILCE-6400 PC Remote (PTP) VID:PID=054C:0CAA '...'
usb: permission requested (requestPermission=true)
```
After granting:
```
usb: permission granted, starting PTP / PC Remote (primary)
```
If instead you see `usb: permission denied` or `usb: permission requested (requestPermission=false)`,
the OTG role or the dialog is the problem — not the protocol.

### 3.2 Claim

```
usb: claimed PTP function: vid=0x054C pid=0x0CAA name=/dev/bus/usb/00X/00Y interfaces=1 ptp-if=0/alt=0 class=6/1/1 bulk-in=0x81(512B) bulk-out=0x02(512B) interrupt-in=0x83
```
* A `MISMATCH:` suffix means the descriptors differ from the documented 0x02/0x81/0x83 —
  the client still uses what it resolved, but record the difference.
* `claimInterface(interface 0, force=true) failed` means another process owns the PTP
  function. On Android that is usually MTP/`usbhid` or a media app; unplug other USB apps
  and retry. This is one of the top risks (§4).

### 3.3 Handshake

```
sony: OpenSession(1) -> OK
sony: SDIOConnect phase 1 ok
sony: SDIOConnect phase 2 ok
sony: 0x9202[0xC8] ok (<n> B capability blob)
sony: SDIOConnect phase 3 ok - handshake complete
sony: 0x9209 -> 1730 B, <n> properties (shutter=1/100, aperture=f/2.8, iso=Auto, ev=0.0)
```
Failure shapes and meaning:

| Log | Meaning |
|---|---|
| `OpenSession(0x1002) rejected: 0x2003 SessionNotOpen` | the camera is not in PC Remote |
| `SDIOConnect phase N rejected: 0x2005` | wrong vendor opcode set for this body / mode |
| `0x9209 property read failed: ...` | session up but the property service is not ready |
| `PTP operation 0x9209 timed out` | transport-level stall; the client stops rather than guessing |

### 3.4 First frame

```
native: pipeline created handle=0x...
gl: ES context version='OpenGL ES 3.2 ...' es32Requested=true es32Granted=true
gl: surface 1080x2400
ptp: frame pump enabled - GetObject 0x1009 handle 0xFFFFC002
ptp: no-frame sentinel (8 B) seen 1 time(s)
```
Then the overlay shows a live `fps` and age line:
```
fps 29.4   host-side age p50 12.3 ms  p95 28.1 ms  max 41.0 ms
decode 3.1 ms  frames 240  dropped 0  superseded 2  seq 300
g2g ESTIMATE 22-36 ms = host-side p50 + assumed 2-8 ms encode + 8-16 ms scanout
ptp: delivered 300  noFrame 1180  timeouts 0  bad 0  queueDrop 0  in 24000000 B
native stats: decoded 240 dropped 0 decode 3.1/3.4 ms upload 1.2 ms rendered 240 errors 0 buf 2
```
* `ptp: no-frame sentinel` many times is normal — it is the camera's retry token.
* `ptp: GetObject timeout (consecutive N)` up to 5 is survivable; at 5 the transport faults
  by design.
* `host-side age` is **not** glass-to-glass. It starts at the bulk-IN data phase and ends at
  `nativeRender` returning; camera encode and sensor readout are excluded, which is why the
  `g2g ESTIMATE` line adds the two assumed terms from USB_GADGET.md §5.4 and labels itself an
  estimate.
* `nativePushJpeg` returns `kOk = 0` on success and negative codes otherwise
  (`kErrInvalidArgument = -2`, `kErrBusy = -12`, …). A non-zero result is counted as a dropped
  frame and logged, never treated as decoded.
* a "rendered" frame is detected from `nativeGetStats` index 5 (the native rendered counter),
  because `nativeRender` returns a *status*, not a frame identity: a draw can succeed while
  repeating the previous texture.

### 3.5 First control

Press `SHUTTER faster` (or ISO `−`/`+`):
```
sony: 0x9207[0xD20D] notch -1 -> OK
sony: 0x9209 -> 1730 B, <n> properties (shutter=1/125, ...)
control: SHUTTER faster -> 1/125
```
The readback panel must change. If the notch is `OK` but the value is unchanged, the client
logs `did not move ... (mode or lens limit)` — that is the camera refusing, and it is reported,
not hidden. Nothing in this app ever claims an applied setting from a 0x9205 ACK.

### 3.6 Transport B (UVC) — expect failure, read the reason

Select `UVC composite (UNVERIFIED)` and press Start:
```
usb: found Sony composite UVC+PTP (transport B, UNVERIFIED) VID:PID=054C:0322 '...'
usb: claimed UVC function: vid=0x054C pid=0x0322 vc-if=1 vs-if=2/alt=1 bulk-in=0x84(1024B) raw-descriptors=...B
uvc: UNVERIFIED transport - bringing up probe/commit
uvc: descriptors: bcdUVC=0x0110 vc-if=1 vs-if=2 vs-ep=0x84 terminalLink=<n> format=1 frame=1 1280x720 maxFrame=<n> defaultInterval=<n> intervals=<n>
uvc: probe 1280x720 format=1 frame=1 interval=<n> maxFrame=<n>
uvc: GET_CUR(PROBE) before SET: hint=1 format=1 frame=1 interval=<n> maxFrame=<n> maxPayload=<n>
uvc: negotiated PROBE: ...
uvc: COMMIT accepted; starting bulk IN reader
```
If any step is unsupported the session aborts with a message naming it, for example:
```
error: start UVC composite (UNVERIFIED) failed: UvcUnsupportedException: SET_CUR(VS_PROBE_CONTROL) rejected by the device (26-byte probe on VS interface 2)
```
That is the expected outcome on today's evidence (no UVC build has ever delivered a frame):
the path is selectable, labelled UNVERIFIED, and never presents a black surface as success.

---

## 4. What remains unverified, and the three riskiest unknowns

### 4.1 Not verified at all

1. **Compilation.** No Kotlin/AGP/Gradle run (§1).
2. **JNI linkage.** The native library does not exist here; symbol names, handle lifetime and
   `nativePushJpeg`'s return convention (0 = rejected) are assumptions from the agreed
   contract, not a link.
3. **GL surface behaviour.** EGL 3.2 probe, `nativeConfigure`/`nativeRender` sequencing and
   `RENDERMODE_CONTINUOUSLY` behaviour were never executed.
4. **Timing.** No fps/latency number in this tree was measured; the overlay is a measurement
   tool, not a claim.
5. **Android USB specifics.** `claimInterface(force=true)` against a composite device, UVC
   `SET_INTERFACE` on a phone, and coexistence with MTP/`uvcvideo`/Camera2 are untested.

### 4.2 Three riskiest on-device unknowns

1. **USB claim contention on the phone.** On many Android builds the PTP function is grabbed
   by MTP/USB-host services the moment the device is enumerated; `claimInterface(..., true)`
   may fail or succeed-then-stall. Mitigation: the client logs the exact claim result and
   refuses to continue; remedy is unplugging other USB apps (or using a phone build without
   MTP auto-mount). If this fails, transport A is dead on that phone regardless of protocol.
2. **Control interleave discipline under real timing.** The client refuses to write a control
   container while any frame transaction is live, and drains the 2–3-deep pipeline first. If
   the camera's data phase for a GetObject can arrive *after* an unrelated command container
   is accepted (i.e. if the strict rule is stricter than the camera needs), controls will feel
   ~10–30 ms slower than the proven single-transaction client but must still work. The
   opposite failure — a control landing inside a data phase and corrupting it — is what the
   rule is there to prevent; it has never been exercised on hardware from this code.
3. **The native renderer's contract details.** `nativePushJpeg` accepting a 140 KB JPEG per
   frame at 30 fps, its 0/1 return, and `nativeRender`'s "new frame" return value decide
   whether the overlay's fps/latency numbers mean anything. If the native side returns non-zero
   on every draw, `LatencyTracker` refuses to attribute renders (it requires a pending decoded
   frame), so the failure mode is "no samples", not "wrong samples".

### 4.3 Deliberate limitations, not defects

* **One ABI** (`arm64-v8a`), because a 32-bit path would change the measured SIMD/decode cost.
* **No 200 ms settle** after a control. That sleep was client politeness, not a camera
  requirement (USB_GADGET.md §5.3), so `stepToward` polls `0x9209` instead — which is slower
  than a single notch but is the only honest way to confirm a change.
* **The PTP event endpoint `0x83` is not read by default.** It exists and is resolved, but no
  client in this repository has ever read it and no event code is decoded, so enabling it
  would be an experiment; the flag is documented in `PtpTransport.Config.readEventEndpoint`.
* **No AF/REC/touch-focus/WB controls.** There is no decoded code, property or mechanism for
  them anywhere in the evidence base; inventing one would be the exact failure mode this
  project is built to avoid.
* **`0x9205` is implemented but unreachable from the UI.** It is kept as a protocol probe and
  logs its own warning on every use.

---

## 5. Re-verification

After any change to this tree, run both:

```powershell
.\venv\Scripts\python.exe android-client-ref\tools\verify_structure.py
.\venv\Scripts\python.exe -m unittest discover -s tests -q
```

Expected: `PASS: all 112 checks` and an `OK` suite (the test count moves with the other
workstreams; at the time of writing it was 1196, up from the 1181 baseline observed when this
client was started).

If the check count changes because the gate gained checks, update this file in the same
commit — the number in this document is a receipt, not decoration.

---

## 6. First-compile watch list

Ranked by likelihood of being the first error you hit when a real toolchain is available:

1. `kotlinOptions`/`kotlin { compilerOptions { jvmTarget } }` syntax against the pinned
   AGP/Kotlin pair (`build.gradle.kts` uses the `kotlin { compilerOptions { ... } }` form).
2. `GLSurfaceView` synthetic-property access (`setEGLContextClientVersion`,
   `setPreserveEGLContextOnPause`) — all written as explicit setters.
3. `UsbDevice.getRawDescriptors()` nullability (platform type, guarded by an empty check).
4. `PendingIntent.FLAG_IMMUTABLE` combined with `FLAG_UPDATE_CURRENT` on API 26–30.
5. Manifest `android:screenOrientation="fullSensor"` + `configChanges` lint warnings on
   targetSdk 34 (warnings, not errors).
6. `proguard-rules.pro` referencing the `NativePipeline` object by name — only matters for
   release builds.
