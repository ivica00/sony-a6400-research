package com.a6400.lived.gl

import android.content.Context
import android.graphics.PixelFormat
import android.opengl.EGL14
import android.opengl.GLES20
import android.opengl.GLSurfaceView
import com.a6400.lived.NativePipeline
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10

/**
 * The GL surface the native SGSR renderer draws into.
 *
 * Responsibilities, and nothing else:
 *  * create and keep one EGL context (ES 3.x; 3.2 is requested and reported),
 *  * call `nativeConfigure` whenever the surface size or the frame geometry
 *    changes,
 *  * call `nativeRender` once per frame and tell the listener when a new frame
 *    was actually presented (that instant is the render timestamp the latency
 *    tracker needs).
 *
 * All native calls are guarded: if `liba6400lived.so` is missing or a call
 * throws, the surface keeps clearing to black and the listener gets one clear
 * error message - it never pretends a frame was drawn.
 */
class SgsrSurfaceView(context: Context) : GLSurfaceView(context) {

    interface Listener {
        fun onSurfaceSizeChanged(width: Int, height: Int)
        fun onFrameRendered()
        fun onNativeError(message: String)
        fun onGlInfo(message: String)
    }

    private val sgsrRenderer = SgsrRenderer()

    @Volatile
    private var pipelineHandle = 0L

    @Volatile
    private var frameWidth = DEFAULT_FRAME_WIDTH

    @Volatile
    private var frameHeight = DEFAULT_FRAME_HEIGHT

    @Volatile
    private var listener: Listener? = null

    private var probeDone = false
    private var es32Granted = false

    init {
        setEGLContextClientVersion(3)
        setEGLConfigChooser(8, 8, 8, 8, 16, 0)
        setPreserveEGLContextOnPause(true)
        holder.setFormat(PixelFormat.RGBA_8888)
        setRenderer(sgsrRenderer)
        setRenderMode(RENDERMODE_CONTINUOUSLY)
    }

    fun setListener(target: Listener?) {
        listener = target
    }

    fun setPipelineHandle(handle: Long) {
        pipelineHandle = handle
    }

    /**
     * Sets the geometry the native renderer should scale from. The default is
     * the physically measured liveview size of the a6400 (1024x680,
     * docs/evidence/0339, 0343); the value is advisory and the native side is
     * free to ignore it.
     */
    fun setFrameGeometry(width: Int, height: Int) {
        if (width <= 0 || height <= 0) return
        frameWidth = width
        frameHeight = height
    }

    fun isEs32Granted(): Boolean = es32Granted

    private inner class SgsrRenderer : Renderer {

        private var reportedNativeFailure = false
        private var reportedRenderStatus = 0
        private var lastRenderedFrames = 0L
        private val frameStats = LongArray(STATS_FIELDS_NEEDED)

        override fun onSurfaceCreated(gl: GL10?, config: EGLConfig?) {
            GLES20.glClearColor(0.0f, 0.0f, 0.0f, 1.0f)
            GLES20.glDisable(GLES20.GL_DEPTH_TEST)
            if (!probeDone) {
                probeDone = true
                es32Granted = probeEs32()
                val version = try {
                    GLES20.glGetString(GLES20.GL_VERSION) ?: "unknown"
                } catch (e: Exception) {
                    "unknown"
                }
                listener?.onGlInfo(
                    "gl: ES context version='$version' es32Requested=true es32Granted=$es32Granted"
                )
                if (!es32Granted) {
                    listener?.onGlInfo(
                        "gl: the driver did not grant an ES 3.2 context; the surface is " +
                            "still created at the highest 3.x the driver offers. If the native " +
                            "renderer needs 3.2 features it will report that itself."
                    )
                }
            }
        }

        override fun onSurfaceChanged(gl: GL10?, width: Int, height: Int) {
            GLES20.glViewport(0, 0, width, height)
            val handle = pipelineHandle
            if (handle != 0L) {
                try {
                    NativePipeline.nativeConfigure(handle, width, height, frameWidth, frameHeight)
                } catch (t: Throwable) {
                    reportNativeFailure("nativeConfigure", t)
                }
            }
            listener?.onSurfaceSizeChanged(width, height)
        }

        override fun onDrawFrame(gl: GL10?) {
            GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT)
            val handle = pipelineHandle
            if (handle == 0L) return
            val status = try {
                NativePipeline.nativeRender(handle)
            } catch (t: Throwable) {
                reportNativeFailure("nativeRender", t)
                0L
            }
            if (status != 0L && status != reportedRenderStatus) {
                // The native render() returns 0 (kOk) on success and a negative
                // status otherwise; log the first occurrence of each status.
                reportedRenderStatus = status.toInt()
                listener?.onGlInfo("gl: nativeRender status=$status (non-zero, see native log)")
            }
            // A presented frame is signalled by the native "frames rendered"
            // counter (nativeGetStats index 5), not by the status code: a draw
            // can succeed while repeating the previous texture.
            val frames = readRenderedFrames(handle)
            if (frames > lastRenderedFrames) {
                lastRenderedFrames = frames
                listener?.onFrameRendered()
            }
        }

        private fun readRenderedFrames(handle: Long): Long {
            return try {
                NativePipeline.nativeGetStats(handle, frameStats)
                frameStats[STATS_INDEX_RENDERED]
            } catch (t: Throwable) {
                reportNativeFailure("nativeGetStats", t)
                0L
            }
        }

        private fun reportNativeFailure(where: String, t: Throwable) {
            if (reportedNativeFailure) return
            reportedNativeFailure = true
            listener?.onNativeError(
                "gl: $where failed: ${t.javaClass.simpleName}: ${t.message}"
            )
        }
    }

    /**
     * Requests an OpenGL ES 3.2 context through EGL and immediately releases it.
     *
     * GLSurfaceView can only ask for "ES 3" (`setEGLContextClientVersion(3)`;
     * there is no 3.2 setter), so the 3.2 request is made here with the
     * KHR_create_context attributes and the answer is reported to the UI. The
     * probe context is never made current on this thread, so it cannot disturb
     * the surface's own context.
     */
    private fun probeEs32(): Boolean {
        var display: android.opengl.EGLDisplay? = null
        var context: android.opengl.EGLContext? = null
        try {
            display = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY)
            if (display == null || display == EGL14.EGL_NO_DISPLAY) return false
            val version = IntArray(2)
            if (!EGL14.eglInitialize(display, version, 0, version, 1)) return false
            val renderable = intArrayOf(
                EGL14.EGL_RENDERABLE_TYPE,
                EGL_OPENGL_ES3_BIT_KHR,
                EGL14.EGL_NONE
            )
            val configs = arrayOfNulls<android.opengl.EGLConfig>(1)
            val configCount = IntArray(1)
            if (!EGL14.eglChooseConfig(display, renderable, 0, configs, 0, 1, configCount, 0)) {
                return false
            }
            if (configCount[0] <= 0 || configs[0] == null) return false
            val attributes = intArrayOf(
                EGL_CONTEXT_MAJOR_VERSION_KHR, 3,
                EGL_CONTEXT_MINOR_VERSION_KHR, 2,
                EGL14.EGL_NONE
            )
            context = EGL14.eglCreateContext(display, configs[0], EGL14.EGL_NO_CONTEXT, attributes, 0)
            if (context == null || context == EGL14.EGL_NO_CONTEXT) return false
            return true
        } catch (t: Throwable) {
            listener?.onGlInfo(
                "gl: ES 3.2 probe threw ${t.javaClass.simpleName}: ${t.message}"
            )
            return false
        } finally {
            if (display != null && display != EGL14.EGL_NO_DISPLAY) {
                if (context != null && context != EGL14.EGL_NO_CONTEXT) {
                    try {
                        EGL14.eglDestroyContext(display, context)
                    } catch (t: Throwable) {
                        // A failed destroy of a probe context is not actionable.
                    }
                }
                try {
                    EGL14.eglTerminate(display)
                } catch (t: Throwable) {
                    // Same: the surface has its own display connection via EGL10.
                }
            }
        }
    }

    companion object {
        /** Physically measured a6400 liveview geometry (docs/evidence/0339, 0343). */
        const val DEFAULT_FRAME_WIDTH = 1024
        const val DEFAULT_FRAME_HEIGHT = 680

        /**
         * `nativeGetStats` documented layout: 0 decoded, 1 dropped, 2 avg decode us,
         * 3 last decode us, 4 last upload us, 5 frames rendered, 6 errors, 7 buffer state.
         * Only the rendered counter is needed here, but ask for all eight so the
         * array size matches the documented contract.
         */
        private const val STATS_FIELDS_NEEDED = 8
        private const val STATS_INDEX_RENDERED = 5

        /** EGL_KHR_create_context attribute names and the ES3 renderable bit. */
        private const val EGL_CONTEXT_MAJOR_VERSION_KHR = 0x3098
        private const val EGL_CONTEXT_MINOR_VERSION_KHR = 0x30FB
        private const val EGL_OPENGL_ES3_BIT_KHR = 0x0040
    }
}
