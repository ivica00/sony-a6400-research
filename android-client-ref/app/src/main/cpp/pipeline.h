#pragma once

#include "ahardware_buffer_pool.h"
#include "gl_renderer.h"
#include "jpeg_decoder.h"

#include <array>
#include <atomic>
#include <cstdint>
#include <mutex>
#include <vector>

namespace a6400 {

// One pipeline owns:
//   * one reusable turbojpeg decompressor,
//   * two decode slots (AHardwareBuffer-backed when possible, CPU RGBA
//     otherwise),
//   * one GL renderer bound to the caller's current EGL context,
//   * the small amount of mutable state needed by the JNI bridge.
//
// Threading: pushJpeg() is called from the USB delivery thread; render(),
// configure() and the setters are called from the GL/UI thread.  Decoded data
// is published only after the slot is complete, and a slot is not eligible for
// reuse until the GL fence for its last draw has signalled.
class Pipeline {
public:
    static constexpr int kMaxFrameWidth = 1280;
    static constexpr int kMaxFrameHeight = 720;
    static constexpr int kSlotCount = 2;
    static constexpr int kMaxJpegBytes = 2 * 1024 * 1024;

    Pipeline();
    ~Pipeline();

    Pipeline(const Pipeline&) = delete;
    Pipeline& operator=(const Pipeline&) = delete;

    bool decoderReady() const;

    void configure(int viewportW, int viewportH, int frameW, int frameH);
    int pushJpeg(const uint8_t* jpeg, size_t length, uint64_t seq, int64_t captureNs);
    int render();

    void setSharpness(float value);
    void setUpscaleMode(int mode);
    void setFocusPeaking(int enabled, float intensity);

    // Fills up to `count` values.  The first eight are the documented contract:
    //   0 decoded, 1 dropped, 2 avg_decode_us, 3 last_decode_us,
    //   4 last_upload_us, 5 frames, 6 errors, 7 buffer_state.
    // Additional values are diagnostics (see cpp/README.md).
    void getStats(int64_t* out, int count) const;

private:
    enum class SlotState : int {
        Free = 0,
        Decoding = 1,
        Ready = 2,
        Rendering = 3,
        Presented = 4
    };

    struct Slot {
        std::atomic<SlotState> state{SlotState::Free};
        bool usingAhb = false;
        uint64_t generation = 0;
        uint64_t seq = 0;
        int64_t captureNs = 0;
        int width = 0;
        int height = 0;
        int stride = 0;
        GLsync fence = nullptr;
        std::vector<uint8_t> cpu;
    };

    bool allocateCpuBuffers();
    int reserveSlot(int* index);
    void markFree(int index);
    void switchToCpu();
    void gcSlotsLocked();
    int64_t bufferState() const;

    JpegDecoder decoder_;
    AhbPool pool_;
    GlRenderer renderer_;

    bool decoderReady_ = false;
    bool cpuAllocated_ = false;
    std::atomic<bool> forceCpu_{false};
    std::atomic<bool> ahbAvailable_{false};

    std::array<Slot, kSlotCount> slots_;
    std::vector<uint8_t> jpegStaging_;

    mutable std::mutex pushMutex_;
    mutable std::mutex slotMutex_;
    mutable std::mutex cpuMutex_;

    std::atomic<int> viewportWidth_{0};
    std::atomic<int> viewportHeight_{0};
    std::atomic<int> configuredFrameWidth_{0};
    std::atomic<int> configuredFrameHeight_{0};
    std::atomic<int> configError_{0};
    std::atomic<int> upscaleMode_{1};
    std::atomic<float> sharpness_{0.35f};
    std::atomic<bool> peaking_{false};
    std::atomic<float> peakingIntensity_{0.5f};

    std::atomic<uint64_t> decoded_{0};
    std::atomic<uint64_t> dropped_{0};
    std::atomic<uint64_t> decodeErrors_{0};
    std::atomic<uint64_t> rendered_{0};
    std::atomic<uint64_t> errors_{0};
    std::atomic<uint64_t> decodeUsSum_{0};
    std::atomic<uint64_t> lastDecodeUs_{0};
    std::atomic<uint64_t> lastSeq_{0};
    std::atomic<int64_t> lastCaptureNs_{0};

    uint64_t generation_ = 0;             // push/decode thread only
    uint64_t lastRenderedGeneration_ = 0; // render thread only
    int lastPresentedSlot_ = -1;           // render thread only; repeat source
};

}  // namespace a6400
