#include "jni_bridge.h"

#include "jpeg_decoder.h"
#include "log.h"
#include "pipeline.h"

#include <jni.h>

#include <algorithm>
#include <atomic>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>

namespace a6400 {
namespace {

std::mutex g_handleMutex;
std::unordered_map<jlong, std::shared_ptr<Pipeline>> g_pipelines;
std::atomic<jlong> g_nextHandle{1};

std::shared_ptr<Pipeline> lookup(jlong handle)
{
    std::lock_guard<std::mutex> lock(g_handleMutex);
    const auto it = g_pipelines.find(handle);
    if (it == g_pipelines.end()) {
        return nullptr;
    }
    return it->second;
}

// JNI array staging.  The critical section only copies bytes; the decode runs
// after ReleasePrimitiveArrayCritical.  The buffer is per USB delivery thread
// and grows once during warm-up, never per frame.
thread_local std::vector<uint8_t> tlsJpeg;

}  // namespace

int64_t jniCreate()
{
    std::shared_ptr<Pipeline> pipeline = std::make_shared<Pipeline>();
    if (!pipeline->decoderReady()) {
        A6400_LOGE("nativeCreate: decoder unavailable; handle will report errors");
    }
    jlong handle = g_nextHandle.fetch_add(1);
    if (handle <= 0) {
        handle = 1;
        g_nextHandle.store(2);
    }
    {
        std::lock_guard<std::mutex> lock(g_handleMutex);
        g_pipelines[handle] = pipeline;
    }
    return handle;
}

void jniDestroy(int64_t handle)
{
    std::shared_ptr<Pipeline> removed;
    {
        std::lock_guard<std::mutex> lock(g_handleMutex);
        const auto it = g_pipelines.find(handle);
        if (it != g_pipelines.end()) {
            removed = it->second;
            g_pipelines.erase(it);
        }
    }
    // `removed` releases outside the registry lock.  If the GL thread still has
    // a shared_ptr, destruction waits for that call to finish.
}

int jniPushJpeg(int64_t handle, const uint8_t* data, size_t length,
                int64_t seq, int64_t captureNs)
{
    const std::shared_ptr<Pipeline> pipeline = lookup(handle);
    if (!pipeline) {
        return kErrInvalidHandle;
    }
    return pipeline->pushJpeg(data, length, static_cast<uint64_t>(seq), captureNs);
}

void jniConfigure(int64_t handle, int viewportW, int viewportH,
                  int frameW, int frameH)
{
    const std::shared_ptr<Pipeline> pipeline = lookup(handle);
    if (!pipeline) {
        return;
    }
    pipeline->configure(viewportW, viewportH, frameW, frameH);
}

int64_t jniRender(int64_t handle)
{
    const std::shared_ptr<Pipeline> pipeline = lookup(handle);
    if (!pipeline) {
        return kErrInvalidHandle;
    }
    return pipeline->render();
}

void jniSetSharpness(int64_t handle, float value)
{
    const std::shared_ptr<Pipeline> pipeline = lookup(handle);
    if (pipeline) {
        pipeline->setSharpness(value);
    }
}

void jniSetUpscaleMode(int64_t handle, int mode)
{
    const std::shared_ptr<Pipeline> pipeline = lookup(handle);
    if (pipeline) {
        pipeline->setUpscaleMode(mode);
    }
}

void jniSetFocusPeaking(int64_t handle, int enabled, float intensity)
{
    const std::shared_ptr<Pipeline> pipeline = lookup(handle);
    if (pipeline) {
        pipeline->setFocusPeaking(enabled, intensity);
    }
}

void jniGetStats(int64_t handle, int64_t* out, int count)
{
    const std::shared_ptr<Pipeline> pipeline = lookup(handle);
    if (!pipeline) {
        return;
    }
    pipeline->getStats(out, count);
}

}  // namespace a6400

// ---------------------------------------------------------------------------
// JNI exports for com.a6400.lived.NativePipeline (a Kotlin `object`, so the
// second argument is jobject, not jclass).
// ---------------------------------------------------------------------------

extern "C" JNIEXPORT jlong JNICALL
Java_com_a6400_lived_NativePipeline_nativeCreate(JNIEnv*, jobject)
{
    return static_cast<jlong>(a6400::jniCreate());
}

extern "C" JNIEXPORT void JNICALL
Java_com_a6400_lived_NativePipeline_nativeDestroy(JNIEnv*, jobject, jlong handle)
{
    a6400::jniDestroy(static_cast<int64_t>(handle));
}

extern "C" JNIEXPORT jint JNICALL
Java_com_a6400_lived_NativePipeline_nativePushJpeg(
    JNIEnv* env, jobject, jlong handle, jbyteArray data, jint length,
    jlong seq, jlong captureNs)
{
    if (data == nullptr || length <= 0) {
        return a6400::kErrInvalidArgument;
    }
    if (length > static_cast<jint>(a6400::Pipeline::kMaxJpegBytes)) {
        return a6400::kErrInvalidArgument;
    }
    const jsize arrayLength = env->GetArrayLength(data);
    if (length > arrayLength) {
        return a6400::kErrInvalidArgument;
    }

    void* critical = env->GetPrimitiveArrayCritical(data, nullptr);
    if (critical == nullptr) {
        return a6400::kErrOutOfMemory;
    }
    if (a6400::tlsJpeg.size() < static_cast<size_t>(length)) {
        a6400::tlsJpeg.resize(static_cast<size_t>(length));
    }
    std::copy(static_cast<const uint8_t*>(critical),
              static_cast<const uint8_t*>(critical) + length,
              a6400::tlsJpeg.begin());
    env->ReleasePrimitiveArrayCritical(data, critical, JNI_ABORT);

    return a6400::jniPushJpeg(static_cast<int64_t>(handle),
                              a6400::tlsJpeg.data(),
                              static_cast<size_t>(length),
                              static_cast<int64_t>(seq),
                              static_cast<int64_t>(captureNs));
}

extern "C" JNIEXPORT void JNICALL
Java_com_a6400_lived_NativePipeline_nativeConfigure(
    JNIEnv*, jobject, jlong handle, jint viewportW, jint viewportH,
    jint frameW, jint frameH)
{
    a6400::jniConfigure(static_cast<int64_t>(handle),
                        viewportW, viewportH, frameW, frameH);
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_a6400_lived_NativePipeline_nativeRender(JNIEnv*, jobject, jlong handle)
{
    return static_cast<jlong>(a6400::jniRender(static_cast<int64_t>(handle)));
}

extern "C" JNIEXPORT void JNICALL
Java_com_a6400_lived_NativePipeline_nativeSetSharpness(
    JNIEnv*, jobject, jlong handle, jfloat value)
{
    a6400::jniSetSharpness(static_cast<int64_t>(handle), value);
}

extern "C" JNIEXPORT void JNICALL
Java_com_a6400_lived_NativePipeline_nativeSetUpscaleMode(
    JNIEnv*, jobject, jlong handle, jint mode)
{
    a6400::jniSetUpscaleMode(static_cast<int64_t>(handle), mode);
}

extern "C" JNIEXPORT void JNICALL
Java_com_a6400_lived_NativePipeline_nativeSetFocusPeaking(
    JNIEnv*, jobject, jlong handle, jint enabled, jfloat intensity)
{
    a6400::jniSetFocusPeaking(static_cast<int64_t>(handle), enabled, intensity);
}

extern "C" JNIEXPORT void JNICALL
Java_com_a6400_lived_NativePipeline_nativeGetStats(
    JNIEnv* env, jobject, jlong handle, jlongArray out)
{
    if (out == nullptr) {
        return;
    }
    jlong values[16] = {};
    const jsize length = env->GetArrayLength(out);
    const int count = std::min(static_cast<int>(length), 16);
    a6400::jniGetStats(static_cast<int64_t>(handle), values, count);
    if (count > 0) {
        env->SetLongArrayRegion(out, 0, count, values);
    }
}

extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM*, void*)
{
    // Standard name-mangled exports above are used; no RegisterNatives table
    // is needed.  Returning the JNI version keeps load-time diagnostics simple.
    return JNI_VERSION_1_6;
}
