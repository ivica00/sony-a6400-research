# a6400lived — native live-view pipeline

This is the native half of the reference Android client for a Sony ILCE-6400 in
PC Remote mode.  It owns JPEG decode, the GL ES 3.2 upscaling/present pass, the
JNI bridge and the optional UVC payload parser.  Kotlin owns USB I/O and calls
the fixed JNI contract below; this directory does not touch Kotlin, Gradle, or
`android/`.

**Transport A (primary, physically verified):** raw PTP over USB, `GetObject
0x1009` handle `0xFFFFC002`, complete JPEGs (1024x680 or up to 1280x720,
52–141 KB, ~25–30 fps).
**Transport B (secondary, UNVERIFIED):** composite UVC bulk IN, endpoint
`0x84`, complete MJPEG frames assembled by Kotlin.  The byte parser is supplied
here; it has never seen a real frame.

## Pipeline

```
 Kotlin USB delivery thread                       GLSurfaceView / GL thread
 ─────────────────────────                        ─────────────────────────
 ByteArray (complete JPEG)
   │ GetPrimitiveArrayCritical
   │ copy only length bytes
   ▼
 thread_local staging (2 MiB max)
   │ ReleasePrimitiveArrayCritical
   ▼
 Pipeline::pushJpeg ── pushMutex ──> turbojpeg
   │                                  │
   │  AHardwareBuffer_lock            │  CPU fallback
   │  RGBA_8888, stride = px*4        │  preallocated RGBA
   ▼                                  ▼
 2-slot double buffer: Free → Decoding → Ready
                                            │
                                            │ nativeRender
                                            ▼
                              select newest Ready generation
                                            │
                       AHardwareBuffer → EGLImage → GL_TEXTURE_EXTERNAL_OES
                       CPU fallback    → glTexSubImage2D GL_TEXTURE_2D
                                            │
                              full-screen triangle (no VBO)
                                            │
                              bilinear OR SGSR-1.0-class (12+5 taps)
                                            │
                              letterboxed glViewport; GLSurfaceView swaps
                                            │
                              glFenceSync → Presented → Free after signal
```

There are exactly two decode slots.  A slot is not eligible for a new decode
until the GL fence from its last draw has signalled.  That is what makes a CPU
decode into an AHardwareBuffer safe while the GPU may still be sampling the
previous contents: the second slot is the overlap, and the fence gates reuse.
If both slots are busy, the frame is dropped and counted (`dropped`), never
queued without bound.

The most recently presented slot is retained as the idle repeat source.
`nativeRender` still returns `1` when there is no new frame, but it redraws
that retained texture (without creating another fence) because GLSurfaceView
always swaps after `onDrawFrame`; otherwise the Kotlin renderer's pre-clear
would leave a black surface.  The `frames` statistic and the returned status
still report "no new frame", so this is not counted as a decoded/presented
frame.

## Files

| File | Role |
| --- | --- |
| `CMakeLists.txt` | arm64-v8a shared library, C++17, shader embedding, libjpeg-turbo link/fatal diagnostic |
| `jni_bridge.{h,cpp}` | fixed JNI exports + opaque handle table |
| `pipeline.{h,cpp}` | slot state machine, timing/statistics, CPU fallback, render dispatch |
| `jpeg_decoder.{h,cpp}` | libjpeg-turbo wrapper, marker/SOF/EOI validation, stride-aware direct decode |
| `ahardware_buffer_pool.{h,cpp}` | 2× `AHardwareBuffer` RGBA_8888, lock/unlock, EGLImage + external texture |
| `gl_renderer.{h,cpp}` | GLES 3.2 programs, letterbox, fences, cached textures, 1 Hz `glGetError` |
| `shaders/sgsr1_fragment.glsl` | single-pass spatial upscaler + focus-peaking variant |
| `shaders/passthrough_vertex.glsl` | `gl_VertexID` full-screen triangle |
| `uvc_frame_parser.{h,cpp}` | UVC payload-header assembly for the secondary transport |
| `../../../../tests/host_stub/` | compile-only host fakes; never on the Android include path |
| `../../../../tests/host_main.cpp` | host assertions: UVC, JPEG/SOF, handle lifecycle |
| `../../../../tests/host_compile.sh` | `g++ -std=c++17 -Wall -Wextra -Werror -DA6400_HOST_COMPILE` |
| `../../../../tests/validate_shaders.py` | static GLSL checks (stdlib only) |

## JNI contract (exact)

Kotlin declares these in `com.a6400.lived.NativePipeline` (a Kotlin `object`,
so the second JNI argument is `jobject`).  The standard exports are:

```text
Java_com_a6400_lived_NativePipeline_nativeCreate()J
Java_com_a6400_lived_NativePipeline_nativeDestroy(J)V
Java_com_a6400_lived_NativePipeline_nativePushJpeg(J[BIJJ)I
Java_com_a6400_lived_NativePipeline_nativeConfigure(JIIII)V
Java_com_a6400_lived_NativePipeline_nativeRender(J)J
Java_com_a6400_lived_NativePipeline_nativeSetSharpness(JF)V
Java_com_a6400_lived_NativePipeline_nativeSetUpscaleMode(JI)V
Java_com_a6400_lived_NativePipeline_nativeSetFocusPeaking(JIF)V
Java_com_a6400_lived_NativePipeline_nativeGetStats(J[J)V
```

`JNI_OnLoad` returns `JNI_VERSION_1_6`; no `RegisterNatives` table is required.
`nativeCreate` returns a positive opaque id, not a C++ pointer.  If turbojpeg
initialisation itself failed, the handle is still returned so the caller can
read the error counters; pushes then return `kErrJpegDecode` and the decoder
bit in `buffer_state` is clear.  The registry
holds `shared_ptr<Pipeline>` values, so a `nativeDestroy` racing a render or
USB push cannot free the object under that call.  Stale ids return
`kErrInvalidHandle` instead of dereferencing a dangling pointer.

`nativePushJpeg` rejects `length <= 0`, `length > arrayLength` and
`length > 2 MiB`, copies exactly `length` JPEG bytes, releases the critical
section before the decode and returns `0` or a negative code.  It never blocks the GL thread; the
USB delivery thread owns decode.  `nativeRender` returns `0` when a frame was
drawn, `1` when no new frame was available, and a negative code on error.

### Error codes (`pipeline.h` / `jpeg_decoder.h`)

| Value | Name | Meaning |
| ---: | --- | --- |
| 0 | `kOk` | success / frame drawn |
| -1 | `kErrInvalidHandle` | id not in the live registry |
| -2 | `kErrInvalidArgument` | null/oversize argument, bad stride/geometry |
| -3 | `kErrJpegInvalid` | SOI/EOI/SOF/marker validation failed |
| -4 | `kErrJpegDimensions` | decoded dimensions exceed the 1280x720 allocation |
| -5 | `kErrJpegDecode` | turbojpeg init/decode failed |
| -6 | `kErrNoSlot` | both decode slots are busy; frame dropped |
| -7 | `kErrOutOfMemory` | a required staging/CPU allocation is unavailable |
| -8 | `kErrNoGlContext` | no EGL context current on the render call |
| -9 | `kErrGl` | GL program/texture/fence failure |
| -10 | `kErrNotConfigured` | `nativeConfigure` has not supplied a viewport |
| -11 | `kErrUnsupported` | reserved for an unsupported mode/extension |
| -12 | `kErrBusy` | transient switch/drop; retry next frame |
| -13 | `kErrAhb` | AHardwareBuffer/EGLImage unavailable |
| -14 | `kErrInternal` | internal invariant failure |

### Statistics (`nativeGetStats`, at least 8 longs)

```text
0 decoded         successful JPEGs published to a slot
1 dropped         frames dropped (no free slot, stale, or switch)
2 avg_decode_us   mean turbojpeg decode time
3 last_decode_us  last turbojpeg decode time
4 last_upload_us  last glTexSubImage2D time (0 on the AHB zero-copy path)
5 frames          frames actually drawn
6 errors          total errors
7 buffer_state    packed: bits 0..2 slot0, 3..5 slot1, bit6 AHB available,
                  bit7 CPU-forced, bit8 GL ready, bit9 decoder ready
8 decode_errors
9 gl_errors
10 last_seq
11 config_error
12 last_capture_ns
13 reserved (0)
```

## AHardwareBuffer / EGLImage rationale

The camera's JPEG is decoded straight into a locked `AHardwareBuffer` plane
with `AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN`; no intermediate CPU RGBA copy is
made on that path.  `AHardwareBuffer_describe()` reports `stride` in
**pixels**, so the byte pitch passed to `tjDecompress2` is `stride * 4` for
RGBA_8888.  The same buffer is wrapped by
`eglCreateImageKHR(..., EGL_NATIVE_BUFFER_ANDROID, ...)` and bound with
`glEGLImageTargetTexture2DOES(GL_TEXTURE_EXTERNAL_OES, ...)`, which is why the
shader has a `samplerExternalOES` variant.

All buffers are allocated once (2 buffers, `GPU_SAMPLED_IMAGE |
CPU_WRITE_OFTEN`, 1 layer, RGBA_8888).  A CPU RGBA buffer is allocated only
when AHardwareBuffer creation fails (or after a gralloc lock failure): the
renderer then uploads with `glTexSubImage2D` and the 2D sampler variants.  A
partial failure of EGLImage creation flips the pipeline to CPU once and drops
the AHB frame(s) that cannot be sampled through the external texture.

The renderer has no EGL context of its own.  `nativeRender` is called on the
GLSurfaceView thread, and construction performs no GL calls.  `nativeDestroy`
may run on another thread; if no EGL context is current, GL object deletion is
deferred to the driver's context teardown (documented limitation), while
AHardwareBuffer/EGLImage objects are released by the pool.

## Shader

`shaders/sgsr1_fragment.glsl` is a **single-pass spatial** upscaler in the
SGSR-1.0 class, not Qualcomm's proprietary temporal SGSR 2.0.  It is:

1. **12-tap directional edge estimate (EASU-like).**  Four horizontal, four
   vertical, four down-right and two anti-diagonal source samples produce four
   first-difference gradients.  Inverse-gradient mixing selects the edge
   tangent; four cubic windowed-sinc ("Lanczos-like") weights interpolate along
   that direction.  The cubic kernel avoids per-pixel `sin()` calls on Adreno.
2. **5-tap contrast-adaptive sharpen (RCAS-like).**  Output-step neighbours
   form a 5-tap cross; the local min/max is the ringing guard and the
   detail/contrast lobe ratio clamps the sharpening amount.  Focus peaking
   reuses the same five taps, adding a red tint only when `PEAKING` is defined.

Compile-time variants inserted by `gl_renderer.cpp`: `A6400_EXTERNAL_TEXTURE`
(external sampler), `A6400_BILINEAR` (mode 0), `PEAKING` (focus variant).
Focus peaking is a property of the SGSR path; mode 0 intentionally uses plain
bilinear and does not overlay peaking.
The shader contains no `discard`, no dependent texture feedback, no branching
on sampled values, and a fixed 12+5 SGSR tap budget.  The bilinear variant adds
one ordinary fetch.  The vertex shader is a `gl_VertexID` full-screen triangle;
a VAO is bound but empty (no VBO churn).

### Attribution

The algorithm is an independent implementation for this project, structurally
inspired by AMD FidelityFX Super Resolution 1.0 (FSR 1.0), Copyright (c) 2022
Advanced Micro Devices, Inc., MIT License.  No AMD source code is copied.  The
MIT permission notice applies to the FSR 1.0 material that inspired the
EASU/RCAS structure:

```text
Copyright (c) 2022 Advanced Micro Devices, Inc.
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

No Qualcomm SGSR source or proprietary code is used.  "SGSR-1.0-class" is a
description of the spatial algorithm class, not a compatibility claim.

## UVC parser (secondary transport)

`uvc::Parser` consumes one UVC bulk transfer per `feed()` call.  Each call starts
at a payload header and may contain a whole frame, a chunk, or several complete
frames after an EOI.  `HeaderMode::UvcStandard` uses byte 0 as
`bHeaderLength`, byte 1 as `bmHeaderInfo` (bit0 FID, bit1 EOF, bit2 PTS) and
little-endian PTS at offset 2.  `HeaderMode::CompositeBits01` implements the
task's composite variant: bits 0–1 of `bmHeaderInfo` encode the header length
(2, 6, 10, 14 bytes), with FID/EOF/PTS in bits 2/3/4.  The parser rejects a
missing SOI, a changed FID mid-frame, a frame over `maxFrameBytes`, an EOF
payload without EOI, and a stream that ends mid-frame.  It reports explicit
`ParseCode` values rather than silently fabricating a frame.

Documented expectations, **not** hardcoded requirements: VS endpoint `0x84`,
MJPEG 1280x720, default frame interval `333333` (100 ns units, 30 fps).  The
parser never checks the endpoint and accepts any dimensions that the JPEG
validator/decode stage accepts.

## Build (Android, not runnable offline here)

libjpeg-turbo is not vendored.  Build it for arm64-v8a and place:

```text
android-client-ref/third_party/libjpeg-turbo/
  include/turbojpeg.h
  lib/libturbojpeg.a        (or .so)
```

Then Gradle's existing `externalNativeBuild` invokes `CMakeLists.txt`.  The
CMake file fails with a clear message if `find_library(turbojpeg-lib ...)` does
not find it.  `abiFilters` is arm64-v8a in the app Gradle file; CMake also
rejects any other `ANDROID_ABI`.  The app passes `-fno-exceptions -fno-rtti`;
this code uses no throw/catch and no RTTI.

## Latency expectations

From `artifacts/analysis/recon-e0348/USB_GADGET.md` §5.4 (assumptions are
marked as such there):

| Term | Value | Basis |
| --- | ---: | --- |
| Frame quantisation (next complete frame) | 0–33.3 ms, avg ≈17 ms | 30 fps producer |
| Camera encode/copy to DMA window | unknown, assumed 2–8 ms | not measured |
| USB HS transport (140 KB) | 3–5 ms | §5.2 arithmetic |
| Host JPEG decode | **3–8 ms** | assumption for Snapdragon 8 Gen 3; not measured |
| Host compose/present | **8–16 ms** | assumption for a 60 Hz display pipeline |
| **Total** | **≈33–70 ms, typical ≈40–55 ms** | |

The native work can reduce the decode/compose part; it cannot remove the
producer's frame period or the transport.  Do not claim `<35 ms` from this code
without measured p95 on the target.  The renderer reports `avg_decode_us`,
`last_decode_us` and `last_upload_us` so the on-device bring-up can replace the
assumptions with measurements.

## Verification status (offline only)

**What was actually verified in this workspace:**

* host compile of `jni_bridge.cpp`, `pipeline.cpp`, `jpeg_decoder.cpp`,
  `ahardware_buffer_pool.cpp`, `gl_renderer.cpp`, `uvc_frame_parser.cpp` with
  `g++ -std=c++17 -Wall -Wextra -Werror -DA6400_HOST_COMPILE` and the
  `tests/host_stub` fakes — zero warnings;
* 67 host assertions covering UVC single/chunked/EOF/PTS/composite/FID/
  truncated assembly, JPEG SOI/SOF/EOI/stride validation, and pipeline
  create/configure/push/stats/render-no-context/destroy/stale-handle behavior;
* static shader validation with `tests/validate_shaders.py` (version, uniforms,
  braces, no `discard`, 12-tap/5-tap comments).

**What could not be verified offline, and is not claimed:**

* no Android SDK, NDK, Gradle, device or emulator on this machine; the arm64
  `.so` was **not built**;
* no GPU/Adreno driver, so the GLSL was **not compiled by a real GLSL
  compiler**, the `samplerExternalOES`/EGLImage path was not exercised, and no
  GPU timing exists;
* no AHardwareBuffer/gralloc on the host; the host stubs force the CPU fallback,
  so the zero-copy path, stride conversion and EGLImage creation are unverified
  on hardware;
* the real libjpeg-turbo was not linked (the host uses a synthetic SOF/pattern
  decoder), so real 52–141 KB camera JPEG decode timing is unverified;
* no camera, USB transfer, UVC payload capture, or PTP frame was available;
* no performance measurements, no thermal/battery validation, and no HDR/
  exposure behaviour beyond `uExposure = 1.0`.

## Known bring-up risks

1. **AHardwareBuffer usage/stride and EGLImage compatibility on the Xiaomi 14
   driver.**  The code assumes RGBA_8888 + `GPU_SAMPLED_IMAGE | CPU_WRITE_OFTEN`
   is lockable and that `glEGLImageTargetTexture2DOES(GL_TEXTURE_EXTERNAL_OES)`
   succeeds.  If either fails, the pipeline falls back to CPU but pays a full
   upload; that fallback must be measured.
2. **GLSL driver acceptance.**  The 17-tap shader uses `samplerExternalOES`,
   `#extension` inside a compile-time `#ifdef`, and mediump/highp mixing.  A
   real Adreno compile is the only proof; if the extension or precision
   qualifiers are rejected, external mode falls back to CPU/2D but the SGSR
   quality path is unavailable.
3. **Timing / slot pressure.**  Two slots plus a render-thread fence are enough
   at 30 fps in the model, but a slow first-frame shader compile, a stalled
   GLSurfaceView, or `nativeRender` being called only on frame arrival can
   starve the decoder and increase `dropped`.  The counter in `nativeGetStats`
   is the first thing to watch on device.
