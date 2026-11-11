#include "pipeline.h"

#include "log.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <string>

namespace a6400 {
namespace {

float clamp01(float value)
{
    if (!std::isfinite(value)) {
        return 0.0f;
    }
    return std::max(0.0f, std::min(1.0f, value));
}

}  // namespace

Pipeline::Pipeline()
    : jpegStaging_(static_cast<size_t>(kMaxJpegBytes))
{
    std::string error;
    decoderReady_ = decoder_.init(&error);
    if (!decoderReady_) {
        ++errors_;
        A6400_LOGE("turbojpeg initialisation failed: %s", error.c_str());
    }

    std::string poolError;
    if (pool_.create(kSlotCount, kMaxFrameWidth, kMaxFrameHeight, &poolError)) {
        ahbAvailable_.store(true);
        A6400_LOGI("AHardwareBuffer decode path enabled (%d slots, %dx%d)",
                   kSlotCount, kMaxFrameWidth, kMaxFrameHeight);
    } else {
        ahbAvailable_.store(false);
        A6400_LOGW("AHardwareBuffer unavailable (%s); using preallocated CPU RGBA",
                   poolError.c_str());
        if (!allocateCpuBuffers()) {
            ++errors_;
            A6400_LOGE("CPU RGBA fallback allocation failed");
        }
    }
}

Pipeline::~Pipeline()
{
    if (eglGetCurrentContext() != EGL_NO_CONTEXT) {
        for (int i = 0; i < kSlotCount; ++i) {
            if (slots_[i].fence != nullptr) {
                glDeleteSync(slots_[i].fence);
                slots_[i].fence = nullptr;
            }
        }
    }
    renderer_.release();
    pool_.destroy();
}

bool Pipeline::decoderReady() const
{
    return decoderReady_;
}

bool Pipeline::allocateCpuBuffers()
{
    if (cpuAllocated_) {
        return true;
    }
    const size_t bytes = static_cast<size_t>(kMaxFrameWidth) *
                         static_cast<size_t>(kMaxFrameHeight) * 4u;
    for (int i = 0; i < kSlotCount; ++i) {
        slots_[i].cpu.resize(bytes);
    }
    cpuAllocated_ = true;
    return true;
}

void Pipeline::configure(int viewportW, int viewportH, int frameW, int frameH)
{
    if (viewportW <= 0 || viewportH <= 0) {
        configError_.store(kErrInvalidArgument);
        ++errors_;
        return;
    }
    if (frameW <= 0 || frameH <= 0) {
        configError_.store(kErrInvalidArgument);
        ++errors_;
        return;
    }
    if (frameW > kMaxFrameWidth || frameH > kMaxFrameHeight) {
        // The JPEG dimensions are authoritative; this is a configuration
        // error, not a reason to crop or silently scale the camera stream.
        configError_.store(kErrJpegDimensions);
        ++errors_;
        A6400_LOGE("configure frame %dx%d exceeds %dx%d", frameW, frameH,
                   kMaxFrameWidth, kMaxFrameHeight);
        return;
    }
    viewportWidth_.store(viewportW);
    viewportHeight_.store(viewportH);
    configuredFrameWidth_.store(frameW);
    configuredFrameHeight_.store(frameH);
    configError_.store(kOk);
}

int Pipeline::reserveSlot(int* index)
{
    std::lock_guard<std::mutex> lock(slotMutex_);
    for (int i = 0; i < kSlotCount; ++i) {
        if (slots_[i].state.load(std::memory_order_acquire) == SlotState::Free) {
            slots_[i].state.store(SlotState::Decoding, std::memory_order_release);
            slots_[i].usingAhb = !forceCpu_.load(std::memory_order_acquire) &&
                                 ahbAvailable_.load(std::memory_order_acquire) &&
                                 pool_.ok();
            slots_[i].width = 0;
            slots_[i].height = 0;
            slots_[i].stride = 0;
            slots_[i].fence = nullptr;
            *index = i;
            return kOk;
        }
    }
    return kErrNoSlot;
}

void Pipeline::markFree(int index)
{
    if (index < 0 || index >= kSlotCount) {
        return;
    }
    std::lock_guard<std::mutex> lock(slotMutex_);
    slots_[index].state.store(SlotState::Free, std::memory_order_release);
    slots_[index].usingAhb = false;
    slots_[index].fence = nullptr;
}

void Pipeline::switchToCpu()
{
    std::lock_guard<std::mutex> cpuLock(cpuMutex_);
    if (!forceCpu_.load(std::memory_order_acquire)) {
        A6400_LOGW("switching to CPU RGBA upload path");
    }
    forceCpu_.store(true, std::memory_order_release);
    ahbAvailable_.store(false, std::memory_order_release);
    if (!allocateCpuBuffers()) {
        ++errors_;
        return;
    }

    std::lock_guard<std::mutex> slotLock(slotMutex_);
    for (int i = 0; i < kSlotCount; ++i) {
        Slot& s = slots_[i];
        const SlotState state = s.state.load(std::memory_order_acquire);
        if (state == SlotState::Ready) {
            // The EGLImage path is the only consumer of an AHB-ready frame; it
            // cannot be rendered through the CPU texture without reading it
            // back, so this one frame is dropped rather than mis-displayed.
            s.state.store(SlotState::Free, std::memory_order_release);
            s.fence = nullptr;
            ++dropped_;
        }
        if (state == SlotState::Free) {
            s.usingAhb = false;
        }
        // Decoding slots finish under the new forceCpu_ flag; publish drops
        // them.  Presented slots are reclaimed by gcSlotsLocked() after their
        // fence signals.
    }
}

int Pipeline::pushJpeg(const uint8_t* jpeg, size_t length, uint64_t seq, int64_t captureNs)
{
    if (!decoderReady_) {
        ++errors_;
        return kErrJpegDecode;
    }
    if (jpeg == nullptr || length == 0 || length > static_cast<size_t>(kMaxJpegBytes)) {
        ++errors_;
        return kErrInvalidArgument;
    }

    // One USB delivery thread calls this.  The mutex also protects the single
    // reusable turbojpeg handle and the staging buffer.
    std::lock_guard<std::mutex> pushLock(pushMutex_);
    std::memcpy(jpegStaging_.data(), jpeg, length);

    int index = -1;
    const int reserve = reserveSlot(&index);
    if (reserve != kOk) {
        ++dropped_;
        return reserve;
    }

    Slot& slot = slots_[index];
    bool usedAhb = slot.usingAhb;
    uint8_t* destination = nullptr;
    int stride = 0;

    if (usedAhb) {
        if (pool_.lock(index, &destination, &stride)) {
            // Fast path: turbojpeg writes directly into the locked
            // AHardwareBuffer plane with the gralloc row stride.
        } else {
            // A gralloc lock can fail even after allocation.  Treat it as
            // AHardwareBuffer becoming unavailable for this pipeline and use
            // the preallocated CPU fallback for this and all later frames.
            switchToCpu();
            usedAhb = false;
            slot.usingAhb = false;
            destination = slot.cpu.data();
            stride = kMaxFrameWidth * 4;
        }
    } else {
        destination = slot.cpu.data();
        stride = kMaxFrameWidth * 4;
    }

    if (destination == nullptr) {
        if (usedAhb) {
            pool_.unlock(index);
        }
        markFree(index);
        ++errors_;
        return kErrOutOfMemory;
    }

    JpegFrameInfo info;
    uint64_t decodeUs = 0;
    std::string error;
    const int rc = decoder_.decode(jpegStaging_.data(), length,
                                   destination, stride,
                                   kMaxFrameWidth, kMaxFrameHeight,
                                   &info, &decodeUs, &error);
    if (usedAhb) {
        pool_.unlock(index);
    }
    if (rc != kOk) {
        markFree(index);
        ++decodeErrors_;
        ++errors_;
        A6400_LOGW("JPEG decode rejected: %s", error.c_str());
        return rc;
    }

    {
        std::lock_guard<std::mutex> lock(slotMutex_);
        // Re-check under the slot lock: the render thread may have switched to
        // the CPU path while this AHB frame was decoding.  switchToCpu() also
        // takes this lock, so one of the two orderings wins cleanly.
        if (forceCpu_.load(std::memory_order_acquire) && usedAhb) {
            slot.state.store(SlotState::Free, std::memory_order_release);
            slot.usingAhb = false;
            slot.fence = nullptr;
            ++dropped_;
            return kErrBusy;
        }
        slot.generation = ++generation_;
        slot.seq = seq;
        slot.captureNs = captureNs;
        slot.width = info.width;
        slot.height = info.height;
        slot.stride = stride;
        slot.state.store(SlotState::Ready, std::memory_order_release);
    }

    ++decoded_;
    lastDecodeUs_.store(decodeUs);
    decodeUsSum_.fetch_add(decodeUs);
    lastSeq_.store(seq);
    lastCaptureNs_.store(captureNs);
    return kOk;
}

void Pipeline::gcSlotsLocked()
{
    for (int i = 0; i < kSlotCount; ++i) {
        Slot& slot = slots_[i];
        if (slot.state.load(std::memory_order_acquire) != SlotState::Presented) {
            continue;
        }
        // The last presented slot is the repeat source for an idle display.
        // Do not release it here; a newly presented frame replaces it and then
        // this slot becomes eligible on a later tick.
        if (i == lastPresentedSlot_) {
            continue;
        }
        if (slot.fence == nullptr) {
            // glFenceSync failed and draw() already issued glFinish().
            slot.state.store(SlotState::Free, std::memory_order_release);
            continue;
        }
        const GLenum status = glClientWaitSync(slot.fence, GL_SYNC_FLUSH_COMMANDS_BIT, 0);
        if (status == GL_ALREADY_SIGNALED || status == GL_CONDITION_SATISFIED) {
            glDeleteSync(slot.fence);
            slot.fence = nullptr;
            slot.state.store(SlotState::Free, std::memory_order_release);
        } else if (status == GL_WAIT_FAILED) {
            glDeleteSync(slot.fence);
            slot.fence = nullptr;
            slot.state.store(SlotState::Free, std::memory_order_release);
            ++errors_;
        }
        // GL_TIMEOUT_EXPIRED: the GPU is still sampling this buffer.  Leave it
        // Presented; the next render tick retries.
    }
}

int Pipeline::render()
{
    const int viewportW = viewportWidth_.load(std::memory_order_acquire);
    const int viewportH = viewportHeight_.load(std::memory_order_acquire);
    if (viewportW <= 0 || viewportH <= 0) {
        return kErrNotConfigured;
    }

    const bool wantExternal = !forceCpu_.load(std::memory_order_acquire) &&
                              ahbAvailable_.load(std::memory_order_acquire) &&
                              pool_.ok();
    int rc = renderer_.ensureInitialized(&pool_, wantExternal,
                                         kMaxFrameWidth, kMaxFrameHeight);
    if (rc == kErrAhb || rc == kErrGl) {
        A6400_LOGW("external texture setup failed (%d); switching to CPU upload", rc);
        switchToCpu();
        rc = renderer_.ensureInitialized(&pool_, false,
                                         kMaxFrameWidth, kMaxFrameHeight);
    }
    if (rc != kOk) {
        if (rc != kErrNoGlContext) {
            ++errors_;
        }
        return rc;
    }

    int index = -1;
    uint64_t generation = 0;
    int repeatSlot = -1;
    DrawSource repeatSource;
    {
        std::lock_guard<std::mutex> lock(slotMutex_);
        for (int i = 0; i < kSlotCount; ++i) {
            Slot& candidate = slots_[i];
            if (candidate.state.load(std::memory_order_acquire) != SlotState::Ready) {
                continue;
            }
            if (candidate.generation > lastRenderedGeneration_ &&
                candidate.generation > generation) {
                generation = candidate.generation;
                index = i;
            }
        }
        if (index < 0) {
            // GLSurfaceView always swaps after onDrawFrame, and the Kotlin
            // renderer clears the default framebuffer before calling us.  If
            // we simply returned 1 without drawing, an idle display would go
            // black.  Repeat the last presented texture, which is retained and
            // therefore not eligible for reuse; do not count it as a new frame
            // and do not create another fence.
            const int retained = lastPresentedSlot_;
            if (retained >= 0 && retained < kSlotCount) {
                Slot& r = slots_[retained];
                if (r.state.load(std::memory_order_acquire) == SlotState::Presented) {
                    const bool retainedExternal = r.usingAhb &&
                        !forceCpu_.load(std::memory_order_acquire) &&
                        pool_.externalReady() && pool_.texture(retained) != 0;
                    if (!r.usingAhb || retainedExternal) {
                        repeatSlot = retained;
                        repeatSource.external = retainedExternal;
                        repeatSource.texture = retainedExternal ? pool_.texture(retained) : 0;
                        repeatSource.frameWidth = r.width;
                        repeatSource.frameHeight = r.height;
                        repeatSource.textureWidth = kMaxFrameWidth;
                        repeatSource.textureHeight = kMaxFrameHeight;
                        repeatSource.cpuDirty = false;  // texture already holds it
                    }
                }
            }
            gcSlotsLocked();
        } else {
            slots_[index].state.store(SlotState::Rendering, std::memory_order_release);
        }
    }

    if (index < 0) {
        if (repeatSlot >= 0) {
            const int repeatRc = renderer_.draw(
                repeatSource, repeatSlot,
                repeatSource.external ? nullptr : slots_[repeatSlot].cpu.data(),
                slots_[repeatSlot].stride,
                viewportW, viewportH,
                upscaleMode_.load(std::memory_order_acquire),
                sharpness_.load(std::memory_order_acquire),
                peaking_.load(std::memory_order_acquire),
                peakingIntensity_.load(std::memory_order_acquire),
                1.0f,
                nullptr);
            if (repeatRc != kOk) {
                ++errors_;
                return repeatRc;
            }
        }
        return 1;  // no new frame
    }

    Slot& slot = slots_[index];
    const bool external = slot.usingAhb &&
                          !forceCpu_.load(std::memory_order_acquire) &&
                          pool_.externalReady() &&
                          pool_.texture(index) != 0;
    if (slot.usingAhb && !external) {
        // A concurrent switchToCpu() can win between candidate selection and
        // the external-texture check.  Discard this AHB frame once; do not put
        // it back as Ready, otherwise every later render would select a frame
        // that has no CPU texture to upload.
        std::lock_guard<std::mutex> lock(slotMutex_);
        if (slot.state.load(std::memory_order_acquire) == SlotState::Rendering) {
            slot.state.store(SlotState::Free, std::memory_order_release);
            slot.usingAhb = false;
            slot.fence = nullptr;
            ++dropped_;
        }
        return 1;
    }

    DrawSource source;
    source.external = external;
    source.texture = external ? pool_.texture(index) : 0;
    source.frameWidth = slot.width;
    source.frameHeight = slot.height;
    source.textureWidth = kMaxFrameWidth;
    source.textureHeight = kMaxFrameHeight;

    GLsync fence = nullptr;
    rc = renderer_.draw(source, index,
                        external ? nullptr : slot.cpu.data(),
                        slot.stride,
                        viewportW, viewportH,
                        upscaleMode_.load(std::memory_order_acquire),
                        sharpness_.load(std::memory_order_acquire),
                        peaking_.load(std::memory_order_acquire),
                        peakingIntensity_.load(std::memory_order_acquire),
                        1.0f,
                        &fence);
    if (rc != kOk) {
        std::lock_guard<std::mutex> lock(slotMutex_);
        if (slot.state.load(std::memory_order_acquire) == SlotState::Rendering) {
            slot.state.store(SlotState::Ready, std::memory_order_release);
        }
        ++errors_;
        return rc;
    }

    {
        std::lock_guard<std::mutex> lock(slotMutex_);
        slot.fence = fence;
        slot.state.store(SlotState::Presented, std::memory_order_release);
        lastRenderedGeneration_ = generation;
        lastPresentedSlot_ = index;
        ++rendered_;

        // A second Ready slot older than the one just presented is now stale.
        for (int i = 0; i < kSlotCount; ++i) {
            Slot& other = slots_[i];
            if (i == index) {
                continue;
            }
            if (other.state.load(std::memory_order_acquire) == SlotState::Ready &&
                other.generation < generation) {
                other.state.store(SlotState::Free, std::memory_order_release);
                ++dropped_;
            }
        }
        gcSlotsLocked();
    }
    return kOk;
}

void Pipeline::setSharpness(float value)
{
    sharpness_.store(clamp01(value));
}

void Pipeline::setUpscaleMode(int mode)
{
    if (mode != 0 && mode != 1) {
        configError_.store(kErrInvalidArgument);
        ++errors_;
        return;
    }
    upscaleMode_.store(mode);
}

void Pipeline::setFocusPeaking(int enabled, float intensity)
{
    peaking_.store(enabled != 0);
    peakingIntensity_.store(clamp01(intensity));
}

int64_t Pipeline::bufferState() const
{
    int64_t value = 0;
    for (int i = 0; i < kSlotCount; ++i) {
        const int state = static_cast<int>(slots_[i].state.load(std::memory_order_acquire));
        value |= (static_cast<int64_t>(state) & 0x7) << (i * 3);
    }
    if (ahbAvailable_.load(std::memory_order_acquire)) {
        value |= int64_t{1} << 6;
    }
    if (forceCpu_.load(std::memory_order_acquire)) {
        value |= int64_t{1} << 7;
    }
    if (renderer_.ready()) {
        value |= int64_t{1} << 8;
    }
    if (decoderReady_) {
        value |= int64_t{1} << 9;
    }
    return value;
}

void Pipeline::getStats(int64_t* out, int count) const
{
    if (out == nullptr || count <= 0) {
        return;
    }
    int64_t values[14] = {};
    const uint64_t decoded = decoded_.load(std::memory_order_acquire);
    values[0] = static_cast<int64_t>(decoded);
    values[1] = static_cast<int64_t>(dropped_.load(std::memory_order_acquire));
    values[2] = decoded == 0 ? 0 : static_cast<int64_t>(
        decodeUsSum_.load(std::memory_order_acquire) / decoded);
    values[3] = static_cast<int64_t>(lastDecodeUs_.load(std::memory_order_acquire));
    values[4] = static_cast<int64_t>(renderer_.lastUploadUs());
    values[5] = static_cast<int64_t>(rendered_.load(std::memory_order_acquire));
    values[6] = static_cast<int64_t>(errors_.load(std::memory_order_acquire));
    values[7] = bufferState();
    values[8] = static_cast<int64_t>(decodeErrors_.load(std::memory_order_acquire));
    values[9] = static_cast<int64_t>(renderer_.glErrorCount());
    values[10] = static_cast<int64_t>(lastSeq_.load(std::memory_order_acquire));
    values[11] = static_cast<int64_t>(configError_.load(std::memory_order_acquire));
    values[12] = lastCaptureNs_.load(std::memory_order_acquire);
    values[13] = 0;  // reserved for a future transport statistic

    const int n = std::min(count, static_cast<int>(sizeof(values) / sizeof(values[0])));
    std::memcpy(out, values, static_cast<size_t>(n) * sizeof(values[0]));
}

}  // namespace a6400
