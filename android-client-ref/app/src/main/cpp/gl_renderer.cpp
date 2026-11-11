#include "gl_renderer.h"

#include "jpeg_decoder.h"
#include "log.h"

#include "generated/shaders_embed.h"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <string>

namespace a6400 {
namespace {

constexpr int kProgramCount = 3;

std::string makeFragmentVariant(const char* source, bool external, bool bilinear, bool peaking)
{
    std::string out(source != nullptr ? source : "");
    const size_t newline = out.find('\n');
    if (newline == std::string::npos) {
        return out;
    }
    std::string defines;
    if (external) {
        defines += "#define A6400_EXTERNAL_TEXTURE 1\n";
    }
    if (bilinear) {
        defines += "#define A6400_BILINEAR 1\n";
    }
    if (peaking) {
        defines += "#define PEAKING 1\n";
    }
    out.insert(newline + 1, defines);
    return out;
}

GLuint compileShader(GLenum type, const char* source, std::string* error)
{
    const GLuint shader = glCreateShader(type);
    if (shader == 0) {
        if (error != nullptr) {
            *error = "glCreateShader returned 0";
        }
        return 0;
    }
    glShaderSource(shader, 1, &source, nullptr);
    glCompileShader(shader);
    GLint ok = GL_FALSE;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (ok != GL_TRUE) {
        GLint logLength = 0;
        glGetShaderiv(shader, GL_INFO_LOG_LENGTH, &logLength);
        std::string log(static_cast<size_t>(logLength > 1 ? logLength : 1), '\0');
        if (logLength > 1) {
            glGetShaderInfoLog(shader, logLength, nullptr, &log[0]);
        }
        if (error != nullptr) {
            *error = log;
        }
        glDeleteShader(shader);
        return 0;
    }
    return shader;
}

int64_t nowUs()
{
    return static_cast<int64_t>(std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
}

}  // namespace

GlRenderer::GlRenderer() = default;

GlRenderer::~GlRenderer()
{
    release();
}

bool GlRenderer::ready() const
{
    return baseReady_.load(std::memory_order_acquire);
}

bool GlRenderer::externalReady() const
{
    return externalReady_.load(std::memory_order_acquire);
}

int GlRenderer::glErrorCount() const
{
    return glErrors_.load(std::memory_order_acquire);
}

uint64_t GlRenderer::lastUploadUs() const
{
    return lastUploadUs_.load(std::memory_order_acquire);
}

void GlRenderer::drainGlErrors(const char* where)
{
    GLenum err = glGetError();
    while (err != GL_NO_ERROR) {
        glErrors_.fetch_add(1, std::memory_order_acq_rel);
        A6400_LOGW("GL error 0x%04x at %s", static_cast<unsigned>(err), where);
        err = glGetError();
    }
}

int GlRenderer::buildProgram(const char* fragmentSource, bool external,
                             bool requireDstSize, Program* program)
{
    if (program == nullptr || vertexShader_ == 0) {
        return kErrInternal;
    }
    std::string error;
    const GLuint fs = compileShader(GL_FRAGMENT_SHADER, fragmentSource, &error);
    if (fs == 0) {
        A6400_LOGE("fragment shader compile failed: %s", error.c_str());
        return kErrGl;
    }

    const GLuint id = glCreateProgram();
    if (id == 0) {
        glDeleteShader(fs);
        return kErrGl;
    }
    glAttachShader(id, vertexShader_);
    glAttachShader(id, fs);
    glLinkProgram(id);
    glDetachShader(id, fs);
    glDeleteShader(fs);

    GLint linked = GL_FALSE;
    glGetProgramiv(id, GL_LINK_STATUS, &linked);
    if (linked != GL_TRUE) {
        GLint logLength = 0;
        glGetProgramiv(id, GL_INFO_LOG_LENGTH, &logLength);
        std::string log(static_cast<size_t>(logLength > 1 ? logLength : 1), '\0');
        if (logLength > 1) {
            glGetProgramInfoLog(id, logLength, nullptr, &log[0]);
        }
        A6400_LOGE("program link failed (%s): %s",
                   external ? "external" : "2d", log.c_str());
        glDeleteProgram(id);
        return kErrGl;
    }

    program->id = id;
    program->uSrcTexture = glGetUniformLocation(id, "uSrcTexture");
    program->uSrcSize = glGetUniformLocation(id, "uSrcSize");
    program->uSrcTextureSize = glGetUniformLocation(id, "uSrcTextureSize");
    program->uDstSize = glGetUniformLocation(id, "uDstSize");
    program->uSharpness = glGetUniformLocation(id, "uSharpness");
    program->uExposure = glGetUniformLocation(id, "uExposure");
    program->uPeakingIntensity = glGetUniformLocation(id, "uPeakingIntensity");
    if (program->uSrcTexture < 0 || program->uSrcSize < 0 ||
        program->uSrcTextureSize < 0 || (requireDstSize && program->uDstSize < 0)) {
        A6400_LOGE("required shader uniform missing (%s)", external ? "external" : "2d");
        glDeleteProgram(id);
        program->id = 0;
        return kErrGl;
    }
    glUseProgram(id);
    if (program->uSrcTexture >= 0) {
        glUniform1i(program->uSrcTexture, 0);
    }
    glUseProgram(0);
    return kOk;
}

int GlRenderer::buildProgramSet(bool external, ProgramSet* set)
{
    const bool bilinearOk =
        buildProgram(makeFragmentVariant(kA6400Sgsr1Fragment, external, true, false).c_str(),
                     external, false, &set->bilinear) == kOk;
    const bool sgsrOk =
        buildProgram(makeFragmentVariant(kA6400Sgsr1Fragment, external, false, false).c_str(),
                     external, true, &set->sgsr) == kOk;
    const bool peakingOk =
        buildProgram(makeFragmentVariant(kA6400Sgsr1Fragment, external, false, true).c_str(),
                     external, true, &set->peaking) == kOk;
    if (!bilinearOk || !sgsrOk || !peakingOk) {
        releaseProgramSet(set);
        return kErrGl;
    }
    return kOk;
}

void GlRenderer::releaseProgramSet(ProgramSet* set)
{
    if (set == nullptr) {
        return;
    }
    if (set->bilinear.id != 0) {
        glDeleteProgram(set->bilinear.id);
    }
    if (set->sgsr.id != 0) {
        glDeleteProgram(set->sgsr.id);
    }
    if (set->peaking.id != 0) {
        glDeleteProgram(set->peaking.id);
    }
    *set = ProgramSet{};
}

void GlRenderer::releaseBaseObjects()
{
    releaseProgramSet(&cpuPrograms_);
    if (vertexShader_ != 0) {
        glDeleteShader(vertexShader_);
        vertexShader_ = 0;
    }
    if (vao_ != 0) {
        glDeleteVertexArrays(1, &vao_);
        vao_ = 0;
    }
    if (cpuTextures_[0] != 0 || cpuTextures_[1] != 0) {
        glDeleteTextures(2, cpuTextures_);
        cpuTextures_[0] = 0;
        cpuTextures_[1] = 0;
    }
    baseReady_.store(false, std::memory_order_release);
}

int GlRenderer::ensureCpuTextures(int maxWidth, int maxHeight)
{
    if (cpuTextures_[0] != 0 && cpuTextures_[1] != 0) {
        return kOk;
    }
    if (cpuTextures_[0] != 0 || cpuTextures_[1] != 0) {
        glDeleteTextures(2, cpuTextures_);
        cpuTextures_[0] = 0;
        cpuTextures_[1] = 0;
    }
    glGenTextures(2, cpuTextures_);
    if (cpuTextures_[0] == 0 || cpuTextures_[1] == 0) {
        A6400_LOGE("glGenTextures failed for CPU upload textures");
        return kErrGl;
    }
    for (int i = 0; i < 2; ++i) {
        glBindTexture(GL_TEXTURE_2D, cpuTextures_[i]);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8,
                     maxWidth, maxHeight, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    }
    glBindTexture(GL_TEXTURE_2D, 0);
    return kOk;
}

int GlRenderer::ensureInitialized(AhbPool* pool, bool wantExternal,
                                  int maxWidth, int maxHeight)
{
    if (eglGetCurrentContext() == EGL_NO_CONTEXT) {
        return kErrNoGlContext;
    }
    if (maxWidth <= 0 || maxHeight <= 0) {
        return kErrInvalidArgument;
    }

    if (!baseReady_.load(std::memory_order_acquire)) {
        const std::string vertexSource(kA6400PassthroughVertex);
        std::string vertexError;
        vertexShader_ = compileShader(GL_VERTEX_SHADER, vertexSource.c_str(), &vertexError);
        if (vertexShader_ == 0) {
            A6400_LOGE("vertex shader compile failed: %s", vertexError.c_str());
            return kErrGl;
        }

        glGenVertexArrays(1, &vao_);
        if (vao_ == 0) {
            releaseBaseObjects();
            return kErrGl;
        }
        glBindVertexArray(vao_);
        glDisable(GL_DEPTH_TEST);
        glDisable(GL_BLEND);
        glDisable(GL_CULL_FACE);
        glDisable(GL_SCISSOR_TEST);
        glDisable(GL_DITHER);

        if (buildProgramSet(false, &cpuPrograms_) != kOk) {
            releaseBaseObjects();
            return kErrGl;
        }
        if (ensureCpuTextures(maxWidth, maxHeight) != kOk) {
            releaseBaseObjects();
            return kErrGl;
        }

        const int errorsBefore = glErrors_.load(std::memory_order_acquire);
        drainGlErrors("renderer setup");
        if (glErrors_.load(std::memory_order_acquire) != errorsBefore) {
            releaseBaseObjects();
            return kErrGl;
        }
        baseReady_.store(true, std::memory_order_release);
    }

    if (!wantExternal) {
        return kOk;
    }
    if (externalReady_.load(std::memory_order_acquire)) {
        return kOk;
    }
    if (pool == nullptr || !pool->ok()) {
        return kErrAhb;
    }
    if (!pool->ensureGlTextures()) {
        return kErrAhb;
    }

    if (buildProgramSet(true, &externalPrograms_) != kOk) {
        return kErrGl;
    }
    externalReady_.store(true, std::memory_order_release);
    return kOk;
}

void GlRenderer::fitLetterbox(int frameW, int frameH, int viewportW, int viewportH,
                              int* outW, int* outH, int* outX, int* outY)
{
    int rw = viewportW > 0 ? viewportW : 1;
    int rh = viewportH > 0 ? viewportH : 1;
    int x = 0;
    int y = 0;
    if (frameW > 0 && frameH > 0 && viewportW > 0 && viewportH > 0) {
        const double frameAspect = static_cast<double>(frameW) / static_cast<double>(frameH);
        const double viewAspect = static_cast<double>(viewportW) / static_cast<double>(viewportH);
        if (viewAspect > frameAspect) {
            rh = viewportH;
            rw = static_cast<int>(std::lround(static_cast<double>(viewportH) * frameAspect));
            x = (viewportW - rw) / 2;
        } else {
            rw = viewportW;
            rh = static_cast<int>(std::lround(static_cast<double>(viewportW) / frameAspect));
            y = (viewportH - rh) / 2;
        }
    }
    if (rw < 1) {
        rw = 1;
    }
    if (rh < 1) {
        rh = 1;
    }
    *outW = rw;
    *outH = rh;
    *outX = x;
    *outY = y;
}

int GlRenderer::draw(const DrawSource& source,
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
                     GLsync* outFence)
{
    if (outFence != nullptr) {
        *outFence = nullptr;
    }
    if (!baseReady_) {
        return kErrNoGlContext;
    }
    if (viewportWidth <= 0 || viewportHeight <= 0 ||
        source.frameWidth <= 0 || source.frameHeight <= 0 ||
        source.textureWidth <= 0 || source.textureHeight <= 0) {
        return kErrInvalidArgument;
    }

    const bool useExternal = source.external && externalReady_;
    const ProgramSet& set = useExternal ? externalPrograms_ : cpuPrograms_;

    const Program* program = nullptr;
    if (upscaleMode == 0) {
        program = &set.bilinear;
    } else if (peaking) {
        program = &set.peaking;
    } else {
        program = &set.sgsr;
    }
    if (program == nullptr || program->id == 0) {
        return kErrGl;
    }

    GLuint texture = source.texture;
    GLenum target = GL_TEXTURE_EXTERNAL_OES;

    if (!useExternal) {
        if (slot < 0 || slot >= 2 || cpuTextures_[slot] == 0 ||
            cpuPixels == nullptr || cpuStride < source.frameWidth * 4 ||
            (cpuStride % 4) != 0) {
            return kErrInvalidArgument;
        }
        texture = cpuTextures_[slot];
        target = GL_TEXTURE_2D;
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(target, texture);
        if (source.cpuDirty) {
            glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
            glPixelStorei(GL_UNPACK_ROW_LENGTH, cpuStride / 4);
            const auto uploadBegin = std::chrono::steady_clock::now();
            glTexSubImage2D(target, 0, 0, 0,
                            source.frameWidth, source.frameHeight,
                            GL_RGBA, GL_UNSIGNED_BYTE, cpuPixels);
            const auto uploadEnd = std::chrono::steady_clock::now();
            glPixelStorei(GL_UNPACK_ROW_LENGTH, 0);
            lastUploadUs_.store(static_cast<uint64_t>(
                std::chrono::duration_cast<std::chrono::microseconds>(
                    uploadEnd - uploadBegin).count()), std::memory_order_release);
        }
    } else {
        if (texture == 0) {
            return kErrAhb;
        }
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(target, texture);
        lastUploadUs_.store(0, std::memory_order_release);  // zero-copy AHB path
    }

    int drawW = 0;
    int drawH = 0;
    int drawX = 0;
    int drawY = 0;
    fitLetterbox(source.frameWidth, source.frameHeight,
                 viewportWidth, viewportHeight,
                 &drawW, &drawH, &drawX, &drawY);

    // The GLSurfaceView host may have left scissor/blend/depth enabled.  Reset
    // the state this pass depends on; there is no per-frame state cache.
    glDisable(GL_SCISSOR_TEST);
    glDisable(GL_BLEND);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);

    glViewport(0, 0, viewportWidth, viewportHeight);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glViewport(drawX, drawY, drawW, drawH);

    glUseProgram(program->id);
    if (program->uSrcSize >= 0) {
        glUniform2f(program->uSrcSize,
                    static_cast<float>(source.frameWidth),
                    static_cast<float>(source.frameHeight));
    }
    if (program->uSrcTextureSize >= 0) {
        glUniform2f(program->uSrcTextureSize,
                    static_cast<float>(source.textureWidth),
                    static_cast<float>(source.textureHeight));
    }
    if (program->uDstSize >= 0) {
        glUniform2f(program->uDstSize,
                    static_cast<float>(drawW), static_cast<float>(drawH));
    }
    if (program->uSharpness >= 0) {
        glUniform1f(program->uSharpness, sharpness);
    }
    if (program->uExposure >= 0) {
        glUniform1f(program->uExposure, exposure);
    }
    if (program->uPeakingIntensity >= 0) {
        glUniform1f(program->uPeakingIntensity, peakingIntensity);
    }

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    if (outFence != nullptr) {
        GLsync fence = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
        if (fence == nullptr) {
            // Fence allocation is the only case in which the render thread
            // blocks on the GPU.  It is exceptional and keeps the 2-slot
            // ownership rule correct rather than freeing a buffer the GPU may
            // still sample.
            glFinish();
        }
        *outFence = fence;
    }

    const int64_t now = nowUs();
    if (now - lastErrorCheckUs_ >= 1000000) {
        lastErrorCheckUs_ = now;
        drainGlErrors("render loop (1 s)");
    }

    return kOk;
}

void GlRenderer::release()
{
    if (eglGetCurrentContext() == EGL_NO_CONTEXT) {
        // NativeDestroy may be called from the UI thread.  GL object deletion
        // without a current context is undefined; the driver reclaims these
        // when the GLSurfaceView context is destroyed.  AHardwareBuffer/EGLImage
        // teardown is done by AhbPool independently.
        baseReady_.store(false, std::memory_order_release);
        externalReady_.store(false, std::memory_order_release);
        vertexShader_ = 0;
        vao_ = 0;
        cpuTextures_[0] = 0;
        cpuTextures_[1] = 0;
        cpuPrograms_ = ProgramSet{};
        externalPrograms_ = ProgramSet{};
        return;
    }

    if (externalPrograms_.bilinear.id != 0 || externalPrograms_.sgsr.id != 0 ||
        externalPrograms_.peaking.id != 0) {
        releaseProgramSet(&externalPrograms_);
    }
    releaseBaseObjects();
    externalReady_.store(false, std::memory_order_release);
}

}  // namespace a6400
