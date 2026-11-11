#include "ahardware_buffer_pool.h"

#include "log.h"

#include <cstring>

namespace a6400 {

AhbPool::AhbPool() = default;

AhbPool::~AhbPool()
{
    destroy();
}

bool AhbPool::create(int count, int maxWidth, int maxHeight, std::string* error)
{
    if (buffersReady_) {
        return true;
    }
    if (count <= 0 || count > kMaxSlots || maxWidth <= 0 || maxHeight <= 0) {
        if (error != nullptr) {
            *error = "invalid AHardwareBuffer pool geometry";
        }
        return false;
    }

    for (int i = 0; i < count; ++i) {
        AHardwareBuffer_Desc desc{};
        desc.width = static_cast<uint32_t>(maxWidth);
        desc.height = static_cast<uint32_t>(maxHeight);
        desc.layers = 1;
        desc.format = AHARDWAREBUFFER_FORMAT_R8G8B8A8_UNORM;
        // GPU_SAMPLED_IMAGE is the EGLImage sampling side; CPU_WRITE_OFTEN is
        // the turbojpeg decode side.  CPU_READ is deliberately not requested:
        // the shipping path never reads the buffer back into the CPU.
        desc.usage = AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE |
                     AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN;
        const int rc = AHardwareBuffer_allocate(&desc, &buffers_[i].buffer);
        if (rc != 0 || buffers_[i].buffer == nullptr) {
            A6400_LOGW("AHardwareBuffer_allocate failed: %d (slot %d)", rc, i);
            releaseObjects(false);
            for (int j = 0; j < kMaxSlots; ++j) {
                if (buffers_[j].buffer != nullptr) {
                    AHardwareBuffer_release(buffers_[j].buffer);
                    buffers_[j].buffer = nullptr;
                }
            }
            if (error != nullptr) {
                *error = "AHardwareBuffer_allocate failed";
            }
            return false;
        }
    }

    count_ = count;
    width_ = maxWidth;
    height_ = maxHeight;
    buffersReady_ = true;
    return true;
}

void AhbPool::destroy()
{
    releaseObjects(true);
    for (int i = 0; i < kMaxSlots; ++i) {
        if (buffers_[i].buffer != nullptr) {
            AHardwareBuffer_release(buffers_[i].buffer);
            buffers_[i].buffer = nullptr;
        }
    }
    count_ = 0;
    width_ = 0;
    height_ = 0;
    buffersReady_ = false;
}

bool AhbPool::ok() const
{
    return buffersReady_;
}

int AhbPool::count() const
{
    return count_;
}

int AhbPool::width() const
{
    return width_;
}

int AhbPool::height() const
{
    return height_;
}

bool AhbPool::lock(int index, uint8_t** pixels, int* stride)
{
    if (pixels == nullptr || stride == nullptr ||
        !buffersReady_ || index < 0 || index >= count_ ||
        buffers_[index].buffer == nullptr) {
        return false;
    }
    void* mapped = nullptr;
    const int rc = AHardwareBuffer_lock(buffers_[index].buffer,
                                        AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN,
                                        -1, nullptr, &mapped);
    if (rc != 0 || mapped == nullptr) {
        A6400_LOGW("AHardwareBuffer_lock failed: %d (slot %d)", rc, index);
        return false;
    }
    // AHardwareBuffer_Desc::stride is "row stride in pixels".  describe() is
    // used instead of a newer convenience accessor so this stays API-26-safe;
    // convert to the byte pitch turbojpeg needs (RGBA_8888 = 4 bytes/pixel).
    AHardwareBuffer_Desc desc{};
    AHardwareBuffer_describe(buffers_[index].buffer, &desc);
    const uint32_t stridePixels = desc.stride;
    if (stridePixels < static_cast<uint32_t>(width_)) {
        AHardwareBuffer_unlock(buffers_[index].buffer, nullptr);
        A6400_LOGW("AHardwareBuffer stride %u px is too small for %d px",
                   stridePixels, width_);
        return false;
    }
    const int64_t byteStride = static_cast<int64_t>(stridePixels) * 4;
    // Defensive unit check: if a driver ever reported bytes where the API says
    // pixels, the product below would exceed the allocation and this path
    // falls back to CPU instead of decoding past the buffer.
    const int64_t maxBytes = static_cast<int64_t>(width_) *
                             static_cast<int64_t>(height_) * 4;
    if (byteStride > 0x7FFFFFFF || byteStride * height_ > maxBytes) {
        AHardwareBuffer_unlock(buffers_[index].buffer, nullptr);
        A6400_LOGW("AHardwareBuffer stride %u px is implausible; CPU fallback",
                   stridePixels);
        return false;
    }
    buffers_[index].locked += 1;
    *pixels = static_cast<uint8_t*>(mapped);
    *stride = static_cast<int>(byteStride);
    return true;
}

void AhbPool::unlock(int index)
{
    if (!buffersReady_ || index < 0 || index >= count_ ||
        buffers_[index].buffer == nullptr || buffers_[index].locked <= 0) {
        return;
    }
    buffers_[index].locked -= 1;
    const int rc = AHardwareBuffer_unlock(buffers_[index].buffer, nullptr);
    if (rc != 0) {
        A6400_LOGW("AHardwareBuffer_unlock failed: %d (slot %d)", rc, index);
    }
}

bool AhbPool::ensureGlTextures()
{
    if (glReady_) {
        return true;
    }
    if (!buffersReady_ || count_ <= 0) {
        return false;
    }
    const EGLDisplay display = eglGetCurrentDisplay();
    if (display == EGL_NO_DISPLAY) {
        return false;
    }
    // Record the display before creating any image: if a later slot fails,
    // releaseObjects(true) must be able to eglDestroyImageKHR the images that
    // were already created.
    display_ = display;

    for (int i = 0; i < count_; ++i) {
        Buffer& b = buffers_[i];
        if (b.image == EGL_NO_IMAGE_KHR) {
            b.image = eglCreateImageKHR(
                display, EGL_NO_CONTEXT, EGL_NATIVE_BUFFER_ANDROID,
                reinterpret_cast<EGLClientBuffer>(b.buffer), nullptr);
            if (b.image == EGL_NO_IMAGE_KHR) {
                A6400_LOGW("eglCreateImageKHR failed (slot %d)", i);
                releaseObjects(true);
                return false;
            }
        }
        if (b.texture == 0) {
            glGenTextures(1, &b.texture);
            if (b.texture == 0) {
                A6400_LOGW("glGenTextures failed (slot %d)", i);
                releaseObjects(true);
                return false;
            }
            glBindTexture(GL_TEXTURE_EXTERNAL_OES, b.texture);
            glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
            glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
            glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
            glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
            glEGLImageTargetTexture2DOES(GL_TEXTURE_EXTERNAL_OES, b.image);
            const GLenum glErr = glGetError();
            if (glErr != GL_NO_ERROR) {
                A6400_LOGW("glEGLImageTargetTexture2DOES failed: 0x%04x (slot %d)",
                           static_cast<unsigned>(glErr), i);
                glBindTexture(GL_TEXTURE_EXTERNAL_OES, 0);
                releaseObjects(true);
                return false;
            }
        }
    }
    glBindTexture(GL_TEXTURE_EXTERNAL_OES, 0);
    display_ = display;
    glReady_ = true;
    return true;
}

bool AhbPool::externalReady() const
{
    return glReady_;
}

GLuint AhbPool::texture(int index) const
{
    if (!glReady_ || index < 0 || index >= count_) {
        return 0;
    }
    return buffers_[index].texture;
}

void AhbPool::releaseObjects(bool deleteGl)
{
    const bool haveContext = (eglGetCurrentContext() != EGL_NO_CONTEXT);
    for (int i = 0; i < kMaxSlots; ++i) {
        if (buffers_[i].texture != 0) {
            if (deleteGl && haveContext) {
                glDeleteTextures(1, &buffers_[i].texture);
            }
            buffers_[i].texture = 0;
        }
        if (buffers_[i].image != EGL_NO_IMAGE_KHR) {
            if (display_ != EGL_NO_DISPLAY) {
                eglDestroyImageKHR(display_, buffers_[i].image);
            }
            buffers_[i].image = EGL_NO_IMAGE_KHR;
        }
        buffers_[i].locked = 0;
    }
    if (deleteGl) {
        display_ = EGL_NO_DISPLAY;
        glReady_ = false;
    }
}

void AhbPool::releaseGl()
{
    releaseObjects(true);
}

}  // namespace a6400
