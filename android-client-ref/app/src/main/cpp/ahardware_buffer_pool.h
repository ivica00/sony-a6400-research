#pragma once

#include "platform_gl.h"

#include <android/hardware_buffer.h>

#include <cstdint>
#include <string>

namespace a6400 {

// Small fixed pool of RGBA_8888 AHardwareBuffers used as JPEG decode targets
// and as EGLImage-backed GL textures.  Buffers are allocated once at pipeline
// creation; no per-frame gralloc allocation.
//
// Threading contract:
//   * create()/lock()/unlock() may be called from the USB/decode thread;
//   * ensureGlTextures()/releaseGl() must be called with the GLSurfaceView's
//     EGL context current (i.e. from the GL thread).
class AhbPool {
public:
    static constexpr int kMaxSlots = 3;

    AhbPool();
    ~AhbPool();

    AhbPool(const AhbPool&) = delete;
    AhbPool& operator=(const AhbPool&) = delete;

    // Allocates `count` buffers of maxWidth x maxHeight.  Returns false and
    // leaves the pool unusable when AHardwareBuffer is unavailable.  This is
    // the graceful CPU-fallback trigger, not a fatal error.
    bool create(int count, int maxWidth, int maxHeight, std::string* error);
    void destroy();

    bool ok() const;
    int count() const;
    int width() const;
    int height() const;

    // Locks one buffer for CPU write.  `stride` is in bytes.  Returns false on
    // any gralloc failure; the caller must fall back to CPU RGBA memory.
    bool lock(int index, uint8_t** pixels, int* stride);
    void unlock(int index);

    // Creates one EGLImage + GL_TEXTURE_EXTERNAL_OES texture per buffer.  Must
    // run on the GL thread with the EGL context current.  On failure all
    // partially-created objects are released and false is returned; the caller
    // must stop using the AHB path and switch to CPU textures.
    bool ensureGlTextures();
    bool externalReady() const;
    GLuint texture(int index) const;
    void releaseGl();

private:
    struct Buffer {
        AHardwareBuffer* buffer = nullptr;
        EGLImageKHR image = EGL_NO_IMAGE_KHR;
        GLuint texture = 0;
        int locked = 0;
    };

    void releaseObjects(bool deleteGl);

    Buffer buffers_[kMaxSlots];
    int count_ = 0;
    int width_ = 0;
    int height_ = 0;
    bool buffersReady_ = false;
    bool glReady_ = false;
    EGLDisplay display_ = EGL_NO_DISPLAY;
};

}  // namespace a6400
