package com.a6400.lived

/**
 * JNI bridge to the native pipeline (`liba6400lived.so`).
 *
 * This is a FIXED contract: the native workstream implements exactly these nine
 * entry points, and the Kotlin side must not add, rename or reorder them. The
 * library is loaded in the object initialiser, so the first touch of any member
 * performs `System.loadLibrary("a6400lived")`; if the library is missing or
 * fails to load, that first touch throws and every caller must treat the
 * pipeline as unavailable (see MainActivity.ensureNative).
 *
 * JNI symbol names produced by this declaration are
 * `Java_com_a6400_lived_NativePipeline_nativeXxx` with a `jobject` second
 * argument (Kotlin `object` members are instance methods), which is what the
 * native side exports.
 */
object NativePipeline {

    init {
        System.loadLibrary("a6400lived")
    }

    external fun nativeCreate(): Long
    external fun nativeDestroy(handle: Long)
    external fun nativePushJpeg(handle: Long, data: ByteArray, length: Int, seq: Long, captureNs: Long): Int
    external fun nativeConfigure(handle: Long, viewportW: Int, viewportH: Int, frameW: Int, frameH: Int)
    external fun nativeRender(handle: Long): Long
    external fun nativeSetSharpness(handle: Long, value: Float)
    external fun nativeSetUpscaleMode(handle: Long, mode: Int)
    external fun nativeSetFocusPeaking(handle: Long, enabled: Int, intensity: Float)
    external fun nativeGetStats(handle: Long, out: LongArray)
}
