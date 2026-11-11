#pragma once

#include <cstddef>
#include <cstdint>

// C++ surface behind the JNI exports.  The host tests call these directly so
// handle lifetime, decode and statistics can be exercised without a JVM; the
// JNI functions are thin argument/array adapters over this surface.
namespace a6400 {

int64_t jniCreate();
void jniDestroy(int64_t handle);

int jniPushJpeg(int64_t handle, const uint8_t* data, size_t length,
                int64_t seq, int64_t captureNs);

void jniConfigure(int64_t handle, int viewportW, int viewportH,
                  int frameW, int frameH);

int64_t jniRender(int64_t handle);
void jniSetSharpness(int64_t handle, float value);
void jniSetUpscaleMode(int64_t handle, int mode);
void jniSetFocusPeaking(int64_t handle, int enabled, float intensity);
void jniGetStats(int64_t handle, int64_t* out, int count);

}  // namespace a6400
