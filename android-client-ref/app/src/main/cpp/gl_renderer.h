#pragma once

#include "ahardware_buffer_pool.h"
#include "platform_gl.h"

#include <atomic>
#include <cstdint>

namespace a6400 {

struct DrawSource {
    bool external = false;      // true: EGLImage-backed GL_TEXTURE_EXTERNAL_OES
    GLuint texture = 0;         // valid when external
    int frameWidth = 0;         // active JPEG width
    int frameHeight = 0;        // active JPEG height
    int textureWidth = 0;       // allocated AHB / GL texture width
    int textureHeight = 0;      // allocated AHB / GL texture height
    bool cpuDirty = true;       // false when repeating a stable CPU texture
};

// Context-independent renderer: construction performs no GL calls.  The
// GLSurfaceView's EGL context must be current for ensureInitialized()/draw()/
// release(); those are always called from the GL thread.
class GlRenderer {
public:
    GlRenderer();
    ~GlRenderer();

    GlRenderer(const GlRenderer&) = delete;
    GlRenderer& operator=(const GlRenderer&) = delete;

    // Builds the shader programs and the two CPU-upload textures.  If
    // wantExternal is true, also creates the AHB EGLImages and the external
    // sampler variants.  Returns kOk, kErrNoGlContext, kErrGl or kErrAhb.
    int ensureInitialized(AhbPool* pool, bool wantExternal, int maxWidth, int maxHeight);

    // Draws one frame.  `slot` selects the cached CPU texture for the non-AHB
    // path.  If outFence is non-null, *outFence receives a GLsync that must not
    // be deleted by the caller; pipeline.cpp owns it and tests it before
    // reusing the slot.  A null *outFence means a GL_FINISH was issued instead
    // (fence allocation failed), so the slot is immediately safe.  Passing
    // outFence == nullptr draws without creating a fence; that is used only to
    // repeat an already-presented, immutable texture when no new frame exists.
    int draw(const DrawSource& source,
             int slot,
             const uint8_t* cpuPixels,
             int cpuStride,
             int viewportWidth,
             int viewportHeight,
             int upscaleMode,
             float sharpness,
             bool peaking,
             float peakingIntensity,
             float exposure,
             GLsync* outFence);

    bool ready() const;
    bool externalReady() const;
    int glErrorCount() const;
    uint64_t lastUploadUs() const;

    // Must run with the EGL context current.  Idempotent.
    void release();

private:
    struct Program {
        GLuint id = 0;
        GLint uSrcTexture = -1;
        GLint uSrcSize = -1;
        GLint uSrcTextureSize = -1;
        GLint uDstSize = -1;
        GLint uSharpness = -1;
        GLint uExposure = -1;
        GLint uPeakingIntensity = -1;
    };

    struct ProgramSet {
        Program bilinear;
        Program sgsr;
        Program peaking;
    };

    int buildProgramSet(bool external, ProgramSet* set);
    int buildProgram(const char* fragmentSource, bool external, bool requireDstSize,
                     Program* program);
    void releaseProgramSet(ProgramSet* set);
    void releaseBaseObjects();
    void drainGlErrors(const char* where);
    int ensureCpuTextures(int maxWidth, int maxHeight);
    static void fitLetterbox(int frameW, int frameH, int viewportW, int viewportH,
                             int* outW, int* outH, int* outX, int* outY);

    GLuint vertexShader_ = 0;
    GLuint vao_ = 0;
    GLuint cpuTextures_[2] = {0, 0};
    ProgramSet cpuPrograms_;
    ProgramSet externalPrograms_;
    std::atomic<bool> baseReady_{false};
    std::atomic<bool> externalReady_{false};
    std::atomic<int> glErrors_{0};
    std::atomic<uint64_t> lastUploadUs_{0};
    int64_t lastErrorCheckUs_ = 0;
};

}  // namespace a6400
