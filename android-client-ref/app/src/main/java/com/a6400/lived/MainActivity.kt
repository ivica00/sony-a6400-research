package com.a6400.lived

import android.app.Activity
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.CheckBox
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.TextView
import com.a6400.lived.gl.SgsrSurfaceView
import com.a6400.lived.media.LatencyTracker
import com.a6400.lived.usb.FrameSink
import com.a6400.lived.usb.LogSink
import com.a6400.lived.usb.PropCode
import com.a6400.lived.usb.PtpProperty
import com.a6400.lived.usb.PtpSony
import com.a6400.lived.usb.PtpTransport
import com.a6400.lived.usb.SonyValue
import com.a6400.lived.usb.TransportKind
import com.a6400.lived.usb.UsbHost
import com.a6400.lived.usb.UsbHostException
import com.a6400.lived.usb.UvcTransport
import java.util.ArrayDeque
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * The reference client.
 *
 * Transport A (PTP / PC Remote) is the primary path: it is the only one that has
 * ever carried real sensor frames to a real host, and it is the path every
 * camera-setting control uses. Transport B (composite UVC) is selectable but is
 * labelled UNVERIFIED and fails closed with a diagnostic when a step is
 * unsupported.
 *
 * Threading contract (see PtpTransport for the transport-internal rules):
 *  * the UI thread only builds views, starts/stops and reads counters;
 *  * every USB open/handshake/teardown runs on [connectExecutor];
 *  * every camera control transaction runs on [controlExecutor] (never on the
 *    UI thread, never on the GL thread);
 *  * frames arrive on a transport delivery thread and go straight into
 *    `nativePushJpeg`; the render timestamp comes back from the GL thread.
 */
class MainActivity : Activity(), FrameSink, SgsrSurfaceView.Listener {

    private val mainHandler = Handler(Looper.getMainLooper())

    private val connectExecutor: ExecutorService = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "a6400-connect").also { it.isDaemon = true }
    }

    private val controlExecutor: ExecutorService = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "a6400-control").also { it.isDaemon = true }
    }

    private lateinit var usbHost: UsbHost
    private lateinit var surfaceView: SgsrSurfaceView
    private lateinit var statsView: TextView
    private lateinit var stateView: TextView
    private lateinit var readbackView: TextView
    private lateinit var logView: TextView
    private lateinit var logScroll: ScrollView
    private lateinit var transportGroup: RadioGroup
    private lateinit var startButton: Button
    private lateinit var stopButton: Button
    private lateinit var sharpnessBar: SeekBar
    private lateinit var sharpnessLabel: TextView
    private lateinit var peakingToggle: CheckBox
    private lateinit var upscaleButton: Button

    private val tracker = LatencyTracker()
    private val nativeStats = LongArray(NATIVE_STATS_SLOTS)
    private val logEntries = ArrayDeque<String>()

    @Volatile
    private var claim: Any? = null

    @Volatile
    private var ptp: PtpTransport? = null

    @Volatile
    private var sony: PtpSony? = null

    @Volatile
    private var uvc: UvcTransport? = null

    @Volatile
    private var nativeHandle = 0L

    @Volatile
    private var nativeFailure: String? = null

    @Volatile
    private var running = false

    private var pendingKind: TransportKind? = null
    private var lastKind = TransportKind.PTP
    private var upscaleMode = 0
    private var receiverRegistered = false
    private var dropLogCounter = 0
    private var nativePushErrors = 0L

    private val permissionAction = "com.a6400.lived.USB_PERMISSION"

    private val logSink = object : LogSink {
        override fun log(message: String) {
            this@MainActivity.log(message)
        }
    }

    private val usbReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                permissionAction -> {
                    val granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                    val device = deviceExtra(intent)
                    val kind = pendingKind
                    pendingKind = null
                    if (!granted) {
                        log("usb: permission denied for ${device?.deviceName ?: "camera"}")
                        setState("idle (USB permission denied)")
                        return
                    }
                    if (kind == null) {
                        log("usb: permission granted with no pending start")
                        return
                    }
                    log("usb: permission granted, starting ${kind.label}")
                    startRequested(kind)
                }
                UsbManager.ACTION_USB_DEVICE_ATTACHED -> {
                    val device = deviceExtra(intent)
                    log(
                        "usb: attached " + describe(device) +
                            " - press Start (transport A: PTP, transport B: UVC UNVERIFIED)"
                    )
                    setState("camera attached, press Start")
                }
                UsbManager.ACTION_USB_DEVICE_DETACHED -> {
                    val device = deviceExtra(intent)
                    if (device != null && running) {
                        log("usb: detached " + describe(device) + " - stopping session")
                        stopSession("camera detached")
                    } else {
                        log("usb: detached " + describe(device))
                    }
                }
            }
        }
    }

    // --------------------------------------------------------------- lifecycle

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        usbHost = UsbHost(getSystemService(Context.USB_SERVICE) as UsbManager)
        buildUi()
        registerUsbReceiver()
        val restored = savedInstanceState?.getString(STATE_KIND)
        if (restored != null) {
            lastKind = if (restored == TransportKind.UVC.name) TransportKind.UVC else TransportKind.PTP
        }
        selectKindInUi(lastKind)
        mainHandler.postDelayed(overlayTick, 500L)
        handleAttachIntent(intent)
        log(
            "app: ready. transport A = PTP/PC Remote (verified). " +
                "transport B = UVC composite (UNVERIFIED)."
        )
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        if (intent != null) handleAttachIntent(intent)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString(STATE_KIND, lastKind.name)
    }

    override fun onResume() {
        super.onResume()
        surfaceView.onResume()
        val transport = ptp
        if (running && transport != null) {
            try {
                transport.startFrames()
            } catch (e: Exception) {
                log("ptp: could not resume the frame pump: ${e.message}")
            }
        }
    }

    override fun onPause() {
        val transport = ptp
        if (running && transport != null) {
            transport.stopFrames()
        }
        surfaceView.onPause()
        super.onPause()
    }

    override fun onDestroy() {
        mainHandler.removeCallbacksAndMessages(null)
        if (receiverRegistered) {
            try {
                unregisterReceiver(usbReceiver)
            } catch (e: Exception) {
                android.util.Log.w(TAG, "unregisterReceiver failed: ${e.message}")
            }
            receiverRegistered = false
        }
        stopSession("activity destroyed")
        // shutdown() lets the queued teardown task finish on the connect thread:
        // USB I/O never runs on the UI thread, and a queued task is not dropped.
        connectExecutor.shutdown()
        controlExecutor.shutdown()
        super.onDestroy()
    }

    private fun registerUsbReceiver() {
        val filter = IntentFilter(permissionAction).apply {
            addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(usbReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("DEPRECATION")
            registerReceiver(usbReceiver, filter)
        }
        receiverRegistered = true
    }

    private fun handleAttachIntent(intent: Intent?) {
        if (intent?.action == UsbManager.ACTION_USB_DEVICE_ATTACHED) {
            val device = deviceExtra(intent)
            log("usb: launched by attach of " + describe(device))
            setState("camera attached, press Start")
        }
    }

    private fun deviceExtra(intent: Intent?): UsbDevice? {
        if (intent == null) return null
        @Suppress("DEPRECATION")
        return intent.getParcelableExtra(UsbManager.EXTRA_DEVICE) as? UsbDevice
    }

    private fun describe(device: UsbDevice?): String {
        if (device == null) return "unknown USB device"
        return "VID:PID=" + String.format(Locale.US, "%04X:%04X", device.vendorId, device.productId) +
            " '" + device.deviceName + "'"
    }

    // ----------------------------------------------------------------- start/stop

    private fun startRequested(kind: TransportKind) {
        if (running) {
            log("start ignored: a session is already running")
            return
        }
        lastKind = kind
        connectExecutor.execute {
            try {
                val camera = when (kind) {
                    TransportKind.PTP -> usbHost.findPtp(logSink)
                    TransportKind.UVC -> usbHost.findUvc(logSink)
                }
                if (camera == null) {
                    val what = when (kind) {
                        TransportKind.PTP -> "a Sony PTP camera (PID 0x0CAA, or the composite PTP child)"
                        TransportKind.UVC -> "the composite UVC device (PID 0x0322)"
                    }
                    throw UsbHostException("no $what found. Connect the camera with an OTG cable and select PC Remote on the camera.")
                }
                log("usb: found " + camera.label + " " + describe(camera.device))
                if (!usbHost.hasPermission(camera.device)) {
                    pendingKind = kind
                    val pending = PendingIntent.getBroadcast(
                        this,
                        REQUEST_USB_PERMISSION,
                        Intent(permissionAction).setPackage(packageName),
                        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                    )
                    val asked = usbHost.requestPermission(camera.device, pending)
                    log("usb: permission requested (requestPermission=$asked)")
                    setState("waiting for USB permission")
                    return@execute
                }
                openCamera(kind, camera)
            } catch (t: Throwable) {
                failAndStop("start ${kind.label}", t)
            }
        }
    }

    private fun openCamera(kind: TransportKind, camera: UsbHost.Camera) {
        setState("opening ${kind.label}")
        ensureNative()
        when (kind) {
            TransportKind.PTP -> {
                val ptpClaim = usbHost.openPtp(camera, logSink)
                claim = ptpClaim
                val transport = PtpTransport(
                    ptpClaim.connection,
                    ptpClaim.bulkIn,
                    ptpClaim.bulkOut,
                    ptpClaim.interruptIn,
                    this,
                    logSink,
                    PtpTransport.Config()
                )
                ptp = transport
                transport.start()
                val controller = PtpSony(transport, logSink)
                sony = controller
                controller.handshake()
                val properties = controller.refresh()
                publishProperties(properties)
                transport.startFrames()
            }
            TransportKind.UVC -> {
                val uvcClaim = usbHost.openUvc(camera, logSink)
                claim = uvcClaim
                val transport = UvcTransport(
                    uvcClaim.connection,
                    uvcClaim,
                    this,
                    logSink,
                    UvcTransport.Config()
                )
                uvc = transport
                log("uvc: UNVERIFIED transport - bringing up probe/commit")
                transport.start()
                val topology = transport.currentTopology()
                if (topology != null) {
                    surfaceView.setFrameGeometry(topology.width, topology.height)
                    log(
                        "uvc: streaming " + topology.width + "x" + topology.height +
                            " format=" + topology.formatIndex + " frame=" + topology.frameIndex
                    )
                }
            }
        }
        running = true
        setState("streaming via ${kind.label}")
        mainHandler.post { updateRunningUi() }
        log("session: up via ${kind.label}")
    }

    private fun stopSession(reason: String, blocking: Boolean = false) {
        val work = Runnable {
            val transport = ptp
            val controller = sony
            val uvcTransport = uvc
            ptp = null
            sony = null
            uvc = null
            running = false
            try {
                transport?.stopFrames()
            } catch (t: Throwable) {
                log("ptp: stopFrames failed: ${t.javaClass.simpleName}: ${t.message}")
            }
            if (controller != null) controller.closeSession()
            try {
                transport?.shutdown()
            } catch (t: Throwable) {
                log("ptp: shutdown failed: ${t.javaClass.simpleName}: ${t.message}")
            }
            try {
                uvcTransport?.shutdown()
            } catch (t: Throwable) {
                log("uvc: shutdown failed: ${t.javaClass.simpleName}: ${t.message}")
            }
            val currentClaim = claim
            claim = null
            usbHost.release(currentClaim, logSink)
            destroyNative()
            setState("idle ($reason)")
            mainHandler.post { updateRunningUi() }
            log("session: down ($reason)")
        }
        if (blocking) {
            work.run()
        } else {
            try {
                connectExecutor.execute(work)
            } catch (e: java.util.concurrent.RejectedExecutionException) {
                android.util.Log.w(TAG, "stop task rejected (executor already shut down)")
            }
        }
    }

    private fun failAndStop(where: String, t: Throwable) {
        log("error: $where failed: ${t.javaClass.simpleName}: ${t.message}")
        setState("failed: ${t.message}")
        stopSession("startup failure")
    }

    // -------------------------------------------------------------------- native

    private fun ensureNative() {
        if (nativeHandle != 0L) return
        val known = nativeFailure
        if (known != null) {
            throw IllegalStateException("native pipeline unavailable: $known")
        }
        val handle = try {
            NativePipeline.nativeCreate()
        } catch (t: Throwable) {
            nativeFailure = "${t.javaClass.simpleName}: ${t.message}"
            throw IllegalStateException(
                "native pipeline unavailable: liba6400lived could not be loaded or created " +
                    "(${nativeFailure})"
            )
        }
        if (handle == 0L) {
            nativeFailure = "nativeCreate returned 0"
            throw IllegalStateException("native pipeline unavailable: nativeCreate returned 0")
        }
        nativeHandle = handle
        surfaceView.setPipelineHandle(handle)
        try {
            NativePipeline.nativeConfigure(
                handle,
                surfaceView.width.coerceAtLeast(1),
                surfaceView.height.coerceAtLeast(1),
                SgsrSurfaceView.DEFAULT_FRAME_WIDTH,
                SgsrSurfaceView.DEFAULT_FRAME_HEIGHT
            )
        } catch (t: Throwable) {
            log("native: initial configure failed: ${t.javaClass.simpleName}: ${t.message}")
        }
        log("native: pipeline created handle=0x${java.lang.Long.toHexString(handle)}")
    }

    private fun destroyNative() {
        val handle = nativeHandle
        nativeHandle = 0L
        surfaceView.setPipelineHandle(0L)
        if (handle == 0L) return
        try {
            NativePipeline.nativeDestroy(handle)
            log("native: pipeline destroyed")
        } catch (t: Throwable) {
            log("native: destroy failed: ${t.javaClass.simpleName}: ${t.message}")
        }
    }

    // ------------------------------------------------------------------ FrameSink

    override fun onFrame(seq: Long, jpeg: ByteArray, captureNs: Long) {
        val handle = nativeHandle
        if (handle == 0L) return
        tracker.onFramePushed(seq, captureNs)
        val result = try {
            NativePipeline.nativePushJpeg(handle, jpeg, jpeg.size, seq, captureNs)
        } catch (t: Throwable) {
            reportNativeFailure("nativePushJpeg", t)
            tracker.onDropped(1)
            return
        }
        // The native contract is kOk = 0 with negative error codes
        // (kErrInvalidArgument = -2, kErrBusy = -12, ...). Anything else is a drop,
        // never a silent success.
        if (result == NATIVE_OK) {
            tracker.onDecodeComplete()
        } else {
            tracker.onDropped(1)
            nativePushErrors += 1
            if (nativePushErrors == 1L || nativePushErrors % 60L == 0L) {
                log("native: pushJpeg rejected frame seq=$seq with $result (drops=$nativePushErrors)")
            }
        }
    }

    override fun onFrameDropped(reason: String, count: Int) {
        tracker.onDropped(count)
        dropLogCounter += 1
        if (dropLogCounter % DROP_LOG_EVERY == 1) {
            log("frames: dropped $count ($reason)")
        }
    }

    override fun onTransportError(message: String) {
        log("transport: $message")
        setState("transport error: $message")
    }

    private fun reportNativeFailure(where: String, t: Throwable) {
        val message = "native: $where failed: ${t.javaClass.simpleName}: ${t.message}"
        if (nativeFailure == null) {
            nativeFailure = "${t.javaClass.simpleName}: ${t.message}"
            log(message)
        }
    }

    // ------------------------------------------------------- SgsrSurfaceView.Listener

    override fun onSurfaceSizeChanged(width: Int, height: Int) {
        log("gl: surface ${width}x$height")
    }

    override fun onFrameRendered() {
        tracker.onRendered()
    }

    override fun onNativeError(message: String) {
        log(message)
        setState(message)
    }

    override fun onGlInfo(message: String) {
        log(message)
    }

    // -------------------------------------------------------------------- overlay

    private val overlayTick = object : Runnable {
        override fun run() {
            updateOverlay()
            mainHandler.postDelayed(this, 500L)
        }
    }

    private fun updateOverlay() {
        if (!::statsView.isInitialized) return
        val stats = tracker.snapshot()
        val text = StringBuilder()
        text.append(
            String.format(
                Locale.US,
                "fps %.1f   host-side age p50 %.1f ms  p95 %.1f ms  max %.1f ms%n",
                stats.fps, stats.p50AgeMs, stats.p95AgeMs, stats.maxAgeMs
            )
        )
        text.append(
            String.format(
                Locale.US,
                "decode %.1f ms  frames %d  dropped %d  superseded %d  seq %d%n",
                stats.decodeMs, stats.sampledFrames, stats.dropped, stats.superseded, stats.lastSeq
            )
        )
        // Glass-to-glass is an ESTIMATE, not a measurement: the host sees the data
        // phase, the decode and the render submit, but not camera-side encode
        // (assumed 2-8 ms) or display scanout (assumed 8-16 ms). The ranges are the
        // ones stated in USB_GADGET.md 5.4; they are shown as assumptions.
        text.append(
            String.format(
                Locale.US,
                "g2g ESTIMATE %.0f-%.0f ms = host-side p50 + assumed 2-8 ms encode + 8-16 ms scanout%n",
                stats.p50AgeMs + 10.0, stats.p50AgeMs + 24.0
            )
        )
        val transport = ptp?.stats()
        if (transport != null) {
            text.append(
                String.format(
                    Locale.US,
                    "ptp: delivered %d  noFrame %d  timeouts %d  bad %d  queueDrop %d  in %d B%n",
                    transport.framesDelivered,
                    transport.noFrameReplies,
                    transport.frameTimeouts,
                    transport.invalidFrames,
                    transport.queueDrops,
                    transport.bytesIn
                )
            )
            if (transport.fault != null) {
                text.append("ptp FAULT: ").append(transport.fault).append('\n')
            }
        }
        val nativeLine = readNativeStats()
        if (nativeLine != null) {
            text.append("native stats: ").append(nativeLine)
        }
        statsView.text = text.toString()
    }

    private fun readNativeStats(): String? {
        val handle = nativeHandle
        if (handle == 0L) return null
        return try {
            NativePipeline.nativeGetStats(handle, nativeStats)
            // Documented native layout (cpp/pipeline.h): 0 decoded, 1 dropped,
            // 2 avg decode us, 3 last decode us, 4 last upload us, 5 frames
            // rendered, 6 errors, 7 buffer state; 8..13 are diagnostics.
            String.format(
                Locale.US,
                "decoded %d dropped %d decode %.1f/%.1f ms upload %.1f ms rendered %d errors %d buf %d",
                nativeStats[0],
                nativeStats[1],
                nativeStats[2].toDouble() / 1000.0,
                nativeStats[3].toDouble() / 1000.0,
                nativeStats[4].toDouble() / 1000.0,
                nativeStats[5],
                nativeStats[6],
                nativeStats[7]
            )
        } catch (t: Throwable) {
            reportNativeFailure("nativeGetStats", t)
            null
        }
    }

    // -------------------------------------------------------------------- controls

    private fun publishProperties(properties: Map<Int, PtpProperty>) {
        val text = StringBuilder()
        text.append("readback from 0x9209 (").append(properties.size).append(" properties)\n")
        appendSetting(text, properties, PropCode.ISO, "ISO     ")
        appendSetting(text, properties, PropCode.SHUTTER, "SHUTTER ")
        appendSetting(text, properties, PropCode.APERTURE, "APERTURE")
        appendSetting(text, properties, PropCode.EV, "EV      ")
        appendSetting(text, properties, PropCode.FOCUS_MODE, "FOCUS   ")
        appendSetting(text, properties, PropCode.EXPOSURE_MODE, "MODE    ")
        val battery = properties[PropCode.BATTERY]
        text.append("BATTERY ").append(
            if (battery == null) "not exposed on this body (never fabricated)" else battery.current.toString() + "%"
        )
        val value = text.toString()
        mainHandler.post { if (::readbackView.isInitialized) readbackView.text = value }
    }

    private fun appendSetting(
        text: StringBuilder,
        properties: Map<Int, PtpProperty>,
        code: Int,
        label: String
    ) {
        val property = properties[code]
        if (property == null) {
            text.append(label).append(" absent\n")
            return
        }
        val rendered = when (code) {
            PropCode.FOCUS_MODE, PropCode.EXPOSURE_MODE -> focusModeLabel(code, property.current)
            else -> SonyValue.label(code, property.current)
        }
        text.append(label).append(' ').append(rendered)
        text.append("  [writable=").append(property.writable)
        text.append(" options=").append(property.options.size)
        text.append(" form=").append(property.form).append("]\n")
    }

    private fun focusModeLabel(code: Int, value: Long): String {
        val known = if (code == PropCode.FOCUS_MODE) {
            when (value) {
                1L -> "MF"
                2L -> "AF-S"
                3L -> "AF-C"
                0x8004L -> "AF-A"
                0x8005L -> "DMF"
                else -> null
            }
        } else {
            when (value) {
                1L -> "M"
                2L -> "P"
                3L -> "A"
                4L -> "S"
                else -> null
            }
        }
        return known ?: String.format(Locale.US, "code 0x%04X (unlabelled)", value)
    }

    private fun stepControl(code: Int, direction: Int, human: String) {
        val controller = sony
        if (controller == null) {
            log("control ignored: no PTP session (start transport A first)")
            return
        }
        controlExecutor.execute {
            try {
                controller.stepNotch(code, direction)
                val properties = controller.refresh()
                publishProperties(properties)
                val property = properties[code]
                val now = if (property == null) "absent" else SonyValue.label(code, property.current)
                log("control: $human -> $now")
            } catch (t: Throwable) {
                log("control failed: $human: ${t.javaClass.simpleName}: ${t.message}")
                setState("control failed: ${t.message}")
            }
        }
    }

    private fun refreshReadback() {
        val controller = sony
        if (controller == null) {
            log("readback ignored: no PTP session")
            return
        }
        controlExecutor.execute {
            try {
                publishProperties(controller.refresh())
                log("control: readback refreshed")
            } catch (t: Throwable) {
                log("readback failed: ${t.javaClass.simpleName}: ${t.message}")
            }
        }
    }

    private fun applySharpness(value: Float) {
        val handle = nativeHandle
        if (handle == 0L) {
            log("sharpness ignored: native pipeline not created")
            return
        }
        try {
            NativePipeline.nativeSetSharpness(handle, value)
        } catch (t: Throwable) {
            reportNativeFailure("nativeSetSharpness", t)
        }
    }

    private fun applyFocusPeaking(enabled: Boolean) {
        val handle = nativeHandle
        if (handle == 0L) {
            log("focus peaking ignored: native pipeline not created")
            return
        }
        try {
            NativePipeline.nativeSetFocusPeaking(handle, if (enabled) 1 else 0, FOCUS_PEAKING_INTENSITY)
        } catch (t: Throwable) {
            reportNativeFailure("nativeSetFocusPeaking", t)
        }
    }

    private fun cycleUpscaleMode() {
        val handle = nativeHandle
        if (handle == 0L) {
            log("upscale mode ignored: native pipeline not created")
            return
        }
        upscaleMode = (upscaleMode + 1) % UPSCALE_MODES
        try {
            NativePipeline.nativeSetUpscaleMode(handle, upscaleMode)
            upscaleButton.text = getString(R.string.label_upscale) + ": $upscaleMode"
            log("native: upscale mode requested = $upscaleMode (semantics owned by the native renderer)")
        } catch (t: Throwable) {
            reportNativeFailure("nativeSetUpscaleMode", t)
        }
    }

    // ------------------------------------------------------------------------ UI

    private fun buildUi() {
        val root = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }

        val stage = FrameLayout(this)
        surfaceView = SgsrSurfaceView(this)
        surfaceView.setListener(this)
        stage.addView(
            surfaceView,
            FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        )

        statsView = TextView(this).apply {
            setTextColor(0xFFE6E6E6.toInt())
            setBackgroundColor(0x66000000)
            textSize = 11.0f
            typeface = android.graphics.Typeface.MONOSPACE
            setPadding(dp(8), dp(6), dp(8), dp(6))
            text = "waiting for frames"
        }
        stage.addView(
            statsView,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP or Gravity.START
            )
        )

        logView = TextView(this).apply {
            setTextColor(0xFFB8D8B8.toInt())
            textSize = 10.0f
            typeface = android.graphics.Typeface.MONOSPACE
            setPadding(dp(8), dp(4), dp(8), dp(4))
        }
        logScroll = ScrollView(this).apply {
            setBackgroundColor(0x88000000)
            addView(logView)
        }
        stage.addView(
            logScroll,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(120),
                Gravity.BOTTOM
            )
        )

        root.addView(stage, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1.0f))

        val panelScroll = ScrollView(this)
        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(10), dp(10), dp(10), dp(10))
        }
        panelScroll.addView(panel)
        root.addView(
            panelScroll,
            LinearLayout.LayoutParams(dp(350), ViewGroup.LayoutParams.MATCH_PARENT)
        )

        panel.addView(
            TextView(this).apply {
                text = getString(R.string.app_name) + " - reference client"
                textSize = 16.0f
                setTextColor(0xFFF0F0F0.toInt())
            }
        )

        transportGroup = RadioGroup(this).apply { orientation = LinearLayout.VERTICAL }
        val ptpRadio = RadioButton(this).apply {
            id = View.generateViewId()
            text = getString(R.string.transport_ptp)
            isChecked = true
        }
        val uvcRadio = RadioButton(this).apply {
            id = View.generateViewId()
            text = getString(R.string.transport_uvc)
            setTextColor(0xFFFFC080.toInt())
        }
        transportGroup.addView(ptpRadio)
        transportGroup.addView(uvcRadio)
        transportGroup.setOnCheckedChangeListener { _, checkedId ->
            lastKind = if (checkedId == ptpRadio.id) TransportKind.PTP else TransportKind.UVC
            log("ui: transport selected = ${lastKind.label}")
        }
        ptpRadioId = ptpRadio.id
        uvcRadioId = uvcRadio.id
        panel.addView(transportGroup)

        stateView = TextView(this).apply {
            text = "idle"
            textSize = 12.0f
            setTextColor(0xFFC0E0FF.toInt())
            setPadding(0, dp(4), 0, dp(4))
        }
        panel.addView(stateView)

        val buttons = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        startButton = Button(this).apply {
            text = getString(R.string.label_start)
            setOnClickListener { startRequested(selectedKind()) }
        }
        stopButton = Button(this).apply {
            text = getString(R.string.label_stop)
            setOnClickListener { stopSession("stop pressed") }
        }
        buttons.addView(startButton)
        buttons.addView(stopButton)
        panel.addView(buttons)
        updateRunningUi()

        panel.addView(sectionLabel("Camera settings (0x9207 notches, 0x9209 readback)"))

        panel.addView(controlRow("ISO", "lower", "higher", PropCode.ISO))
        panel.addView(controlRow("SHUTTER", "faster", "slower", PropCode.SHUTTER))
        panel.addView(controlRow("APERTURE", "open", "close", PropCode.APERTURE))
        panel.addView(controlRow("EV", "-", "+", PropCode.EV))

        panel.addView(
            Button(this).apply {
                text = getString(R.string.label_refresh)
                setOnClickListener { refreshReadback() }
            }
        )

        readbackView = TextView(this).apply {
            textSize = 11.0f
            typeface = android.graphics.Typeface.MONOSPACE
            setTextColor(0xFFE0E0E0.toInt())
            setText("no readback yet")
        }
        panel.addView(readbackView)

        panel.addView(
            TextView(this).apply {
                textSize = 10.0f
                setTextColor(0xFFFFB0B0.toInt())
                setText(
                    "Note: 0x9207 (signed notch) is the effective control path. " +
                        "0x9205 absolute writes are acknowledged but NOT effective on this body " +
                        "and are never used by these buttons."
                )
            }
        )

        panel.addView(sectionLabel("Native renderer"))

        sharpnessLabel = TextView(this).apply {
            text = getString(R.string.label_sharpness) + ": 0.00"
            textSize = 12.0f
        }
        panel.addView(sharpnessLabel)
        sharpnessBar = SeekBar(this).apply {
            max = 100
            progress = 0
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(bar: SeekBar?, progress: Int, fromUser: Boolean) {
                    val value = progress.toFloat() / 100.0f
                    sharpnessLabel.text = getString(R.string.label_sharpness) +
                        String.format(Locale.US, ": %.2f", value)
                    if (fromUser) applySharpness(value)
                }

                override fun onStartTrackingTouch(bar: SeekBar?) = Unit

                override fun onStopTrackingTouch(bar: SeekBar?) {
                    applySharpness(bar?.progress?.toFloat()?.div(100.0f) ?: 0.0f)
                }
            })
        }
        panel.addView(sharpnessBar)

        peakingToggle = CheckBox(this).apply {
            text = getString(R.string.label_focus_peaking)
            setOnCheckedChangeListener { _, checked -> applyFocusPeaking(checked) }
        }
        panel.addView(peakingToggle)

        upscaleButton = Button(this).apply {
            text = getString(R.string.label_upscale) + ": 0"
            setOnClickListener { cycleUpscaleMode() }
        }
        panel.addView(upscaleButton)

        setContentView(root)
    }

    private var ptpRadioId = 0
    private var uvcRadioId = 0

    private fun selectKindInUi(kind: TransportKind) {
        if (!::transportGroup.isInitialized) return
        val target = if (kind == TransportKind.PTP) ptpRadioId else uvcRadioId
        if (target != 0 && transportGroup.checkedRadioButtonId != target) {
            transportGroup.check(target)
        }
    }

    private fun selectedKind(): TransportKind =
        if (::transportGroup.isInitialized && transportGroup.checkedRadioButtonId == uvcRadioId) {
            TransportKind.UVC
        } else {
            TransportKind.PTP
        }

    private fun sectionLabel(text: String): TextView = TextView(this).apply {
        this.text = text
        textSize = 12.0f
        setTextColor(0xFF9FD0FF.toInt())
        setPadding(0, dp(10), 0, dp(2))
    }

    private fun controlRow(
        title: String,
        minusLabel: String,
        plusLabel: String,
        code: Int
    ): LinearLayout {
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        row.addView(
            TextView(this).apply {
                text = title
                textSize = 12.0f
                width = dp(84)
            }
        )
        row.addView(
            Button(this).apply {
                text = minusLabel
                setOnClickListener { stepControl(code, -1, "$title $minusLabel") }
            }
        )
        row.addView(
            Button(this).apply {
                text = plusLabel
                setOnClickListener { stepControl(code, 1, "$title $plusLabel") }
            }
        )
        return row
    }

    private fun updateRunningUi() {
        if (!::startButton.isInitialized) return
        startButton.isEnabled = !running
        stopButton.isEnabled = running
        transportGroup.isEnabled = !running
        for (index in 0 until transportGroup.childCount) {
            transportGroup.getChildAt(index).isEnabled = !running
        }
    }

    private fun setState(text: String) {
        mainHandler.post {
            if (::stateView.isInitialized) stateView.text = text
        }
    }

    private fun log(message: String) {
        android.util.Log.i(TAG, message)
        val line = String.format(
            Locale.US,
            "%s %s",
            java.text.SimpleDateFormat("HH:mm:ss.SSS", Locale.US).format(java.util.Date()),
            message
        )
        mainHandler.post {
            if (!::logView.isInitialized) return@post
            logEntries.addLast(line)
            while (logEntries.size > MAX_LOG_LINES) logEntries.removeFirst()
            logView.text = logEntries.joinToString("\n")
            logScroll.post { logScroll.fullScroll(View.FOCUS_DOWN) }
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private companion object {
        const val TAG = "a6400-lived"
        const val MAX_LOG_LINES = 200
        const val NATIVE_STATS_SLOTS = 14

        /** Native status code for success (`kOk` in cpp/jpeg_decoder.h). */
        const val NATIVE_OK = 0
        const val REQUEST_USB_PERMISSION = 0x6400
        const val DROP_LOG_EVERY = 30
        const val FOCUS_PEAKING_INTENSITY = 0.5f
        const val UPSCALE_MODES = 3
        const val STATE_KIND = "a6400.transport.kind"
    }
}
