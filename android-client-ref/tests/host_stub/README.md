# Host stubs — compile-only, not shipping code

Everything in this directory exists solely so `tests/host_compile.sh` can
type-check the portable half of `app/src/main/cpp` on a normal Windows/Linux
host.  None of it is an Android implementation:

- `jni.h` — no JVM; function bodies return failure/zero.
- `android/log.h` — no logd; the host uses `cpp/log.h` and stderr.
- `android/hardware_buffer.h` — `AHardwareBuffer_allocate` always fails, so
  the pipeline exercises its CPU-RGBA fallback.
- `android/bitmap.h` — unused compile placeholder.
- `EGL/egl.h`, `GLES3/gl32.h`, `GLES2/gl2ext.h` — no EGL/GL; the current
  context is `EGL_NO_CONTEXT`, so the renderer takes its no-GL error path.
- `turbojpeg.h` / `turbojpeg_stub.cpp` — parses only synthetic SOF dimensions
  and fills a deterministic RGBA pattern; it does not decode JPEG entropy.
- `generated/shaders_embed.h` — placeholder shader strings; the host never
  compiles them with a driver.

The Android build does **not** add this directory to the include path; CMake
includes only the source tree, the generated shader directory and the vendored
libjpeg-turbo include directory.  The compile flag `-DA6400_HOST_COMPILE` is
likewise host-only.
