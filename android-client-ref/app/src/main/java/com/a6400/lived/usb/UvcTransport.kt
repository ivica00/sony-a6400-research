package com.a6400.lived.usb

import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/** Transport B could not be brought up; the message says exactly which step failed. */
class UvcUnsupportedException(message: String) : Exception(message)

/**
 * UVC (USB Video Class) topology discovered from `UsbDevice.getRawDescriptors()`.
 *
 * Only what this client needs is decoded: the VC header (bcdUVC), the VS input
 * header (the streaming endpoint and terminal link) and the MJPEG format/frame
 * descriptors (indices, geometry, buffer size, frame intervals).
 */
class UvcTopology(
    val bcdUvc: Int,
    val videoControlInterface: Int,
    val videoStreamingInterface: Int,
    val streamingEndpointAddress: Int,
    val terminalLink: Int,
    val formatIndex: Int,
    val frameIndex: Int,
    val width: Int,
    val height: Int,
    val maxFrameBytes: Int,
    val defaultFrameInterval: Int,
    val frameIntervals: IntArray,
    val diagnostics: String
)

/**
 * Parser for the raw configuration descriptors.
 *
 * Descriptor types (USB 2.0 / UVC 1.1): 2 = configuration, 4 = interface,
 * 5 = endpoint, 0x0B = interface association, 0x24 = class-specific interface.
 * UVC class-specific subtypes used here: VC header 0x01, VS input header 0x01,
 * VS_FORMAT_MJPEG 0x06, VS_FRAME_MJPEG 0x07.
 */
object UvcDescriptorParser {

    fun parse(
        device: UsbDevice,
        expectedStreamingInterface: Int,
        expectedEndpointAddress: Int,
        preferredWidth: Int,
        preferredHeight: Int,
        log: LogSink
    ): UvcTopology {
        val raw: ByteArray = try {
            device.rawDescriptors
        } catch (e: Exception) {
            throw UvcUnsupportedException(
                "cannot read rawDescriptors(): ${e.javaClass.simpleName}: ${e.message}"
            )
        }
        if (raw.isEmpty()) {
            throw UvcUnsupportedException("device.rawDescriptors() returned no bytes")
        }

        var at = 0
        var currentInterfaceNumber = -1
        var currentClass = -1
        var currentSubclass = -1
        var currentAlt = 0
        var bcdUvc = 0
        var videoControlInterface = -1
        var videoStreamingInterface = -1
        var streamingEndpointAddress = -1
        var terminalLink = -1
        var formatIndex = -1
        var frameIndex = -1
        var width = 0
        var height = 0
        var maxFrameBytes = 0
        var defaultInterval = 0
        var intervals = IntArray(0)
        var bestScore = Int.MIN_VALUE
        val seen = StringBuilder()

        while (at + 2 <= raw.size) {
            val length = raw[at].toInt() and 0xFF
            val type = raw[at + 1].toInt() and 0xFF
            if (length < 2 || at + length > raw.size) {
                throw UvcUnsupportedException(
                    "malformed USB descriptor at offset $at (length=$length type=0x" +
                        String.format(java.util.Locale.US, "%02X", type) + ")"
                )
            }
            when (type) {
                TYPE_INTERFACE -> {
                    if (length < 9) throw UvcUnsupportedException("short interface descriptor at $at")
                    currentInterfaceNumber = raw[at + 2].toInt() and 0xFF
                    currentAlt = raw[at + 3].toInt() and 0xFF
                    currentClass = raw[at + 5].toInt() and 0xFF
                    currentSubclass = raw[at + 6].toInt() and 0xFF
                    if (currentClass == UsbHost.UVC_INTERFACE_CLASS &&
                        currentSubclass == UsbHost.UVC_SUBCLASS_VIDEOCONTROL &&
                        videoControlInterface < 0
                    ) {
                        videoControlInterface = currentInterfaceNumber
                    }
                    if (currentClass == UsbHost.UVC_INTERFACE_CLASS &&
                        currentSubclass == UsbHost.UVC_SUBCLASS_VIDEOSTREAMING &&
                        currentInterfaceNumber == expectedStreamingInterface
                    ) {
                        videoStreamingInterface = currentInterfaceNumber
                    }
                    seen.append(" if=").append(currentInterfaceNumber)
                        .append("/alt=").append(currentAlt)
                        .append("/class=").append(currentClass)
                        .append("/sub=").append(currentSubclass)
                }
                TYPE_ENDPOINT -> {
                    if (length < 7) throw UvcUnsupportedException("short endpoint descriptor at $at")
                    val address = raw[at + 2].toInt() and 0xFF
                    val attributes = raw[at + 3].toInt() and 0xFF
                    val transferType = attributes and 0x03
                    if (currentClass == UsbHost.UVC_INTERFACE_CLASS &&
                        currentSubclass == UsbHost.UVC_SUBCLASS_VIDEOSTREAMING &&
                        currentInterfaceNumber == expectedStreamingInterface &&
                        transferType == UsbConstants.USB_ENDPOINT_XFER_BULK &&
                        (address and 0x80) != 0
                    ) {
                        streamingEndpointAddress = address
                    }
                }
                TYPE_CS_INTERFACE -> {
                    if (length >= 3) {
                        val subtype = raw[at + 2].toInt() and 0xFF
                        if (currentClass == UsbHost.UVC_INTERFACE_CLASS &&
                            currentSubclass == UsbHost.UVC_SUBCLASS_VIDEOCONTROL &&
                            subtype == VC_HEADER && length >= 12
                        ) {
                            bcdUvc = u16(raw, at + 3)
                            if (videoControlInterface < 0) videoControlInterface = currentInterfaceNumber
                        }
                        if (currentClass == UsbHost.UVC_INTERFACE_CLASS &&
                            currentSubclass == UsbHost.UVC_SUBCLASS_VIDEOSTREAMING &&
                            currentInterfaceNumber == expectedStreamingInterface
                        ) {
                            when (subtype) {
                                VS_INPUT_HEADER -> {
                                    if (length >= 13) {
                                        val endpoint = raw[at + 6].toInt() and 0xFF
                                        if (streamingEndpointAddress < 0) streamingEndpointAddress = endpoint
                                        terminalLink = raw[at + 8].toInt() and 0xFF
                                    }
                                }
                                VS_FORMAT_MJPEG -> {
                                    if (length >= 11 && formatIndex < 0) {
                                        formatIndex = raw[at + 3].toInt() and 0xFF
                                    }
                                }
                                VS_FRAME_MJPEG -> {
                                    if (length >= 26) {
                                        val candidateFrame = raw[at + 3].toInt() and 0xFF
                                        val candidateWidth = u16(raw, at + 5)
                                        val candidateHeight = u16(raw, at + 7)
                                        val candidateMax = u32(raw, at + 17)
                                        val candidateDefault = u32(raw, at + 21)
                                        val intervalType = raw[at + 25].toInt() and 0xFF
                                        val candidateIntervals = readIntervals(raw, at, length, intervalType)
                                        val candidateScore = score(
                                            candidateWidth, candidateHeight, candidateDefault,
                                            candidateMax, preferredWidth, preferredHeight
                                        )
                                        if (candidateScore > bestScore) {
                                            bestScore = candidateScore
                                            frameIndex = candidateFrame
                                            width = candidateWidth
                                            height = candidateHeight
                                            maxFrameBytes = candidateMax
                                            defaultInterval = candidateDefault
                                            intervals = candidateIntervals
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                else -> Unit
            }
            at += length
        }

        if (videoStreamingInterface < 0) {
            throw UvcUnsupportedException(
                "no UVC video-streaming interface $expectedStreamingInterface in the descriptor tree"
            )
        }
        if (streamingEndpointAddress < 0) {
            throw UvcUnsupportedException(
                "VS interface $videoStreamingInterface advertises no bulk IN endpoint in its descriptors"
            )
        }
        if (streamingEndpointAddress != expectedEndpointAddress) {
            log.log(
                "uvc: descriptor VS endpoint is 0x" +
                    String.format(java.util.Locale.US, "%02X", streamingEndpointAddress) +
                    " but the claimed endpoint is 0x" +
                    String.format(java.util.Locale.US, "%02X", expectedEndpointAddress)
            )
        }
        if (formatIndex < 0) {
            throw UvcUnsupportedException(
                "VS interface $videoStreamingInterface advertises no MJPEG format descriptor"
            )
        }
        if (frameIndex < 0 || width == 0 || height == 0) {
            throw UvcUnsupportedException(
                "MJPEG format $formatIndex advertises no frame descriptor with usable geometry"
            )
        }
        if (maxFrameBytes <= 0) {
            throw UvcUnsupportedException(
                "frame $frameIndex ($width x $height) advertises dwMaxVideoFrameBufferSize=0"
            )
        }
        val diagnostics = buildString {
            append("bcdUVC=0x").append(String.format(java.util.Locale.US, "%04X", bcdUvc))
            append(" vc-if=").append(videoControlInterface)
            append(" vs-if=").append(videoStreamingInterface)
            append(" vs-ep=0x").append(String.format(java.util.Locale.US, "%02X", streamingEndpointAddress))
            append(" terminalLink=").append(terminalLink)
            append(" format=").append(formatIndex)
            append(" frame=").append(frameIndex)
            append(" ").append(width).append("x").append(height)
            append(" maxFrame=").append(maxFrameBytes)
            append(" defaultInterval=").append(defaultInterval)
            append(" intervals=").append(intervals.size)
        }
        log.log("uvc: descriptors: $diagnostics")
        log.log("uvc: interface walk:$seen")
        return UvcTopology(
            bcdUvc = bcdUvc,
            videoControlInterface = videoControlInterface,
            videoStreamingInterface = videoStreamingInterface,
            streamingEndpointAddress = streamingEndpointAddress,
            terminalLink = terminalLink,
            formatIndex = formatIndex,
            frameIndex = frameIndex,
            width = width,
            height = height,
            maxFrameBytes = maxFrameBytes,
            defaultFrameInterval = defaultInterval,
            frameIntervals = intervals,
            diagnostics = diagnostics
        )
    }

    private fun u16(bytes: ByteArray, at: Int): Int =
        (bytes[at].toInt() and 0xFF) or ((bytes[at + 1].toInt() and 0xFF) shl 8)

    private fun u32(bytes: ByteArray, at: Int): Int =
        u16(bytes, at) or (u16(bytes, at + 2) shl 16)

    private fun readIntervals(bytes: ByteArray, at: Int, length: Int, intervalType: Int): IntArray {
        if (intervalType == 0) return IntArray(0)
        val available = (length - 26) / 4
        val count = minOf(intervalType, available)
        if (count <= 0) return IntArray(0)
        val out = IntArray(count)
        for (i in 0 until count) out[i] = u32(bytes, at + 26 + i * 4)
        return out
    }

    /**
     * Prefers the requested geometry (1280x720 for the composite reference
     * descriptor), then the largest buffer, then the default interval closest to
     * a 30 fps period. The score never hides the chosen frame: the full walk and
     * the final choice are logged.
     */
    private fun score(
        width: Int,
        height: Int,
        defaultInterval: Int,
        maxFrameBytes: Int,
        preferredWidth: Int,
        preferredHeight: Int
    ): Int {
        var value = 0
        if (width == preferredWidth && height == preferredHeight) value += 1_000_000
        value += minOf(width * height / 16, 500_000)
        value += minOf(maxFrameBytes / 64, 100_000)
        if (defaultInterval > 0) {
            val distance = kotlin.math.abs(defaultInterval - 333333)
            value += (200_000 - minOf(distance, 200_000)) / 8
        }
        return value
    }

    private const val TYPE_INTERFACE = 0x04
    private const val TYPE_ENDPOINT = 0x05
    private const val TYPE_CS_INTERFACE = 0x24
    private const val VC_HEADER = 0x01
    private const val VS_INPUT_HEADER = 0x01
    private const val VS_FORMAT_MJPEG = 0x06
    private const val VS_FRAME_MJPEG = 0x07
}

/**
 * Transport B: composite UVC + PTP device (VID 0x054C, PID 0x0322, VS MJPEG
 * 1280x720, bulk IN 0x84).
 *
 * STATUS: UNVERIFIED. No build of this path has ever produced a frame on this
 * hardware; the transport builds bind on Windows but no samples arrive
 * (USB_GADGET.md 0, 6/B3). This class therefore fails closed at the first step
 * the device does not support and reports exactly which step failed, rather
 * than presenting a black surface as success.
 *
 * Control sequence (UVC 1.1, class requests on EP0):
 *
 * ```
 * bmRequestType 0x21 SET / 0xA1 GET, bRequest 0x01 SET_CUR / 0x81 GET_CUR
 * wValue = CS << 8        CS: 1 = VS_PROBE_CONTROL, 2 = VS_COMMIT_CONTROL
 * wIndex = (entity << 8) | interface   (entity 0 for VS probe/commit)
 * data   = 26-byte uvc_streaming_control struct
 * ```
 *
 * The 26-byte struct is the UVC 1.0/1.1 `uvc_streaming_control`: wHint(2),
 * bFormatIndex(1), bFrameIndex(1), dwFrameInterval(4), wKeyFrameRate(2),
 * wPFrameRate(2), wCompQuality(2), wCompWindowSize(2), wDelay(2),
 * dwMaxVideoFrameSize(4), dwMaxPayloadTransferSize(4).
 */
class UvcTransport(
    private val connection: UsbDeviceConnection,
    private val claim: UsbHost.UvcClaim,
    private val sink: FrameSink,
    private val log: LogSink,
    private val config: Config = Config()
) {

    data class Config(
        val preferredWidth: Int = 1280,
        val preferredHeight: Int = 720,
        val preferredFrameInterval: Int = 333333,
        val maxPayloadTransferSize: Int = 16384,
        val bulkChunkBytes: Int = 16384,
        val readTimeoutMs: Int = 400,
        val controlTimeoutMs: Int = 2000,
        val maxFrameBytes: Int = 4 * 1024 * 1024,
        val maxConsecutiveTimeouts: Int = 8,
        val deliveryDepth: Int = 3,
        /** Compression quality hint, 1 (best) .. 1000 (worst); UVC wCompQuality. */
        val compressionQuality: Int = 100
    )

    private class Frame(val seq: Long, val jpeg: ByteArray, val captureNs: Long)

    private val lock = Object()
    private val queue = ArrayBlockingQueue<Frame>(maxOf(1, config.deliveryDepth))

    private var running = false
    private var faultText: String? = null
    private var readerThread: Thread? = null
    private var deliveryThread: Thread? = null
    private var frameSeq = 0L

    private val framesDelivered = AtomicLong()
    private val framesDropped = AtomicLong()
    private val bytesIn = AtomicLong()
    private val timeouts = AtomicLong()

    private var topology: UvcTopology? = null

    fun currentTopology(): UvcTopology? = topology

    fun isRunning(): Boolean = synchronized(lock) { running && faultText == null }

    fun failureText(): String? = synchronized(lock) { faultText }

    /**
     * Brings the stream up: parse descriptors, negotiate PROBE/COMMIT, then read
     * bulk IN. Any unsupported step throws [UvcUnsupportedException] with the
     * failing step named; nothing is claimed as working.
     */
    fun start() {
        val parsed = UvcDescriptorParser.parse(
            claim.device,
            claim.videoStreaming.id,
            claim.bulkIn.address,
            config.preferredWidth,
            config.preferredHeight,
            log
        )
        topology = parsed
        if (claim.videoStreaming.alternateSetting == 0) {
            log.log(
                "uvc: warning - streaming interface ${claim.videoStreaming.id} is alternate setting 0; " +
                    "a bulk endpoint on alt 0 is unusual for UVC"
            )
        }
        val interval = chooseInterval(parsed)
        val probe = buildProbe(parsed, interval)
        log.log(
            "uvc: probe ${parsed.width}x${parsed.height} format=${parsed.formatIndex} " +
                "frame=${parsed.frameIndex} interval=$interval maxFrame=${parsed.maxFrameBytes}"
        )

        val current = ByteArray(STREAMING_CONTROL_BYTES)
        if (getCur(CS_PROBE, current)) {
            log.log("uvc: GET_CUR(PROBE) before SET: " + describeControl(current))
        } else {
            log.log("uvc: GET_CUR(PROBE) not answered; sending SET_CUR anyway")
        }
        if (!setCur(CS_PROBE, probe)) {
            throw UvcUnsupportedException(
                "SET_CUR(VS_PROBE_CONTROL) rejected by the device (26-byte probe on VS interface " +
                    claim.videoStreaming.id + ")"
            )
        }
        val negotiated = ByteArray(STREAMING_CONTROL_BYTES)
        if (!getCur(CS_PROBE, negotiated)) {
            throw UvcUnsupportedException(
                "GET_CUR(VS_PROBE_CONTROL) failed - the device accepted SET_CUR but will not " +
                    "report the negotiated values, so COMMIT cannot be built safely"
            )
        }
        log.log("uvc: negotiated PROBE: " + describeControl(negotiated))
        if (u32(negotiated, 18) <= 0 || u32(negotiated, 22) <= 0) {
            throw UvcUnsupportedException(
                "negotiated PROBE reports dwMaxVideoFrameSize=" + u32(negotiated, 18) +
                    " dwMaxPayloadTransferSize=" + u32(negotiated, 22) +
                    " - the device will not stream with these values"
            )
        }
        if (!setCur(CS_COMMIT, negotiated.copyOf())) {
            throw UvcUnsupportedException("SET_CUR(VS_COMMIT_CONTROL) rejected by the device")
        }
        log.log("uvc: COMMIT accepted; starting bulk IN reader")

        synchronized(lock) {
            running = true
            faultText = null
        }
        readerThread = startThread("uvc-reader") { readerLoop() }
        deliveryThread = startThread("uvc-delivery") { deliveryLoop() }
    }

    fun shutdown() {
        synchronized(lock) {
            running = false
            lock.notifyAll()
        }
        joinQuietly(readerThread)
        joinQuietly(deliveryThread)
        log.log(
            "uvc: transport stopped (frames=${framesDelivered.get()} dropped=${framesDropped.get()} " +
                "in=${bytesIn.get()} B timeouts=${timeouts.get()})"
        )
    }

    // ------------------------------------------------------------- negotiation

    private fun chooseInterval(parsed: UvcTopology): Int {
        val candidates = if (parsed.frameIntervals.isNotEmpty()) {
            parsed.frameIntervals
        } else {
            intArrayOf(parsed.defaultFrameInterval)
        }
        var chosen = parsed.defaultFrameInterval
        var bestDistance = Int.MAX_VALUE
        for (candidate in candidates) {
            if (candidate <= 0) continue
            val distance = kotlin.math.abs(candidate - parsed.defaultFrameInterval)
            if (distance < bestDistance) {
                bestDistance = distance
                chosen = candidate
            }
        }
        if (chosen <= 0) chosen = config.preferredFrameInterval
        return chosen
    }

    private fun buildProbe(parsed: UvcTopology, interval: Int): ByteArray {
        val probe = ByteArray(STREAMING_CONTROL_BYTES)
        val buffer = ByteBuffer.wrap(probe).order(ByteOrder.LITTLE_ENDIAN)
        buffer.putShort(1.toShort())                       // wHint: dwFrameInterval is fixed
        buffer.put(parsed.formatIndex.toByte())  // bFormatIndex
        buffer.put(parsed.frameIndex.toByte())   // bFrameIndex
        buffer.putInt(interval)                  // dwFrameInterval (100 ns units)
        buffer.putShort(0.toShort())                       // wKeyFrameRate (MJPEG: unused)
        buffer.putShort(0.toShort())                       // wPFrameRate (MJPEG: unused)
        buffer.putShort(config.compressionQuality.toShort()) // wCompQuality
        buffer.putShort(0.toShort())                       // wCompWindowSize
        buffer.putShort(0.toShort())                       // wDelay
        buffer.putInt(parsed.maxFrameBytes)      // dwMaxVideoFrameSize
        buffer.putInt(minOf(config.maxPayloadTransferSize, parsed.maxFrameBytes))
        return probe
    }

    private fun setCur(selector: Int, data: ByteArray): Boolean {
        val transferred = try {
            connection.controlTransfer(
                REQUEST_TYPE_SET,
                UVC_SET_CUR,
                selector shl 8,
                wIndex(),
                data,
                data.size,
                config.controlTimeoutMs
            )
        } catch (e: Exception) {
            log.log("uvc: SET_CUR(CS=$selector) threw ${e.javaClass.simpleName}: ${e.message}")
            -1
        }
        return transferred >= 0
    }

    private fun getCur(selector: Int, out: ByteArray): Boolean {
        val transferred = try {
            connection.controlTransfer(
                REQUEST_TYPE_GET,
                UVC_GET_CUR,
                selector shl 8,
                wIndex(),
                out,
                out.size,
                config.controlTimeoutMs
            )
        } catch (e: Exception) {
            log.log("uvc: GET_CUR(CS=$selector) threw ${e.javaClass.simpleName}: ${e.message}")
            -1
        }
        if (transferred < out.size) return false
        return true
    }

    /**
     * wIndex = (entity << 8) | interface. For VS probe/commit the entity byte is
     * 0 and the interface is the VS interface (mirrors the uvcvideo convention
     * and the repository's own adapter, which preserves the high byte as the
     * entity id: tools/native_camera/uvc_ptp_adapter.c:9-17).
     */
    private fun wIndex(): Int = (0 shl 8) or (claim.videoStreaming.id and 0xFF)

    private fun describeControl(data: ByteArray): String =
        "hint=" + u16(data, 0) +
            " format=" + (data[2].toInt() and 0xFF) +
            " frame=" + (data[3].toInt() and 0xFF) +
            " interval=" + u32(data, 4) +
            " maxFrame=" + u32(data, 18) +
            " maxPayload=" + u32(data, 22)

    private fun u16(bytes: ByteArray, at: Int): Int =
        (bytes[at].toInt() and 0xFF) or ((bytes[at + 1].toInt() and 0xFF) shl 8)

    private fun u32(bytes: ByteArray, at: Int): Int =
        u16(bytes, at) or (u16(bytes, at + 2) shl 16)

    // ------------------------------------------------------------------ reader

    private fun readerLoop() {
        val chunk = ByteArray(config.bulkChunkBytes)
        val frame = java.io.ByteArrayOutputStream(256 * 1024)
        var fid = -1
        var consecutiveTimeouts = 0
        var shortChunks = 0
        while (true) {
            synchronized(lock) { if (!running) return }
            val read = try {
                connection.bulkTransfer(claim.bulkIn, chunk, chunk.size, config.readTimeoutMs)
            } catch (e: Exception) {
                log.log("uvc: bulk IN exception: ${e.javaClass.simpleName}: ${e.message}")
                -1
            }
            if (read <= 0) {
                timeouts.incrementAndGet()
                consecutiveTimeouts += 1
                if (consecutiveTimeouts >= config.maxConsecutiveTimeouts) {
                    raiseFault("$consecutiveTimeouts consecutive bulk IN timeouts")
                    return
                }
                continue
            }
            consecutiveTimeouts = 0
            bytesIn.addAndGet(read.toLong())
            if (read < 2) {
                shortChunks += 1
                if (shortChunks <= 3) log.log("uvc: $read-byte bulk chunk ignored (no UVC payload header)")
                continue
            }
            val declaredHeader = chunk[0].toInt() and 0xFF
            val info = chunk[1].toInt() and 0xFF
            var headerBytes = declaredHeader
            var implied = 2
            if ((info and PAYLOAD_FLAG_PTS) != 0) implied += 4
            if ((info and PAYLOAD_FLAG_SCR) != 0) implied += 6
            if (headerBytes < implied) headerBytes = implied
            if (headerBytes > read) {
                shortChunks += 1
                if (shortChunks <= 3) {
                    log.log(
                        "uvc: payload header of $headerBytes B exceeds the $read-byte chunk; dropped"
                    )
                }
                continue
            }
            val frameId = info and PAYLOAD_FLAG_FID
            if (fid >= 0 && frameId != fid && frame.size() > 0) {
                // FID toggled mid-frame: the previous frame never ended.
                framesDropped.incrementAndGet()
                sink.onFrameDropped("FID toggled before EOF (truncated frame)", 1)
                frame.reset()
            }
            fid = frameId
            val payloadBytes = read - headerBytes
            if (payloadBytes > 0) {
                frame.write(chunk, headerBytes, payloadBytes)
            }
            if (frame.size() > config.maxFrameBytes) {
                frame.reset()
                framesDropped.incrementAndGet()
                sink.onFrameDropped("frame exceeds cap ${config.maxFrameBytes} B", 1)
                continue
            }
            val endOfFrame = (info and PAYLOAD_FLAG_EOF) != 0 || (info and PAYLOAD_FLAG_EOI) != 0
            if (!endOfFrame) continue
            val bytes = frame.toByteArray()
            frame.reset()
            if (bytes.size < 4) continue
            if ((info and PAYLOAD_FLAG_ERR) != 0) {
                framesDropped.incrementAndGet()
                sink.onFrameDropped("device flagged ERR on the frame", 1)
                continue
            }
            var start = -1
            var i = 0
            while (i + 1 < bytes.size) {
                if ((bytes[i].toInt() and 0xFF) == 0xFF && (bytes[i + 1].toInt() and 0xFF) == 0xD8) {
                    start = i
                    break
                }
                i += 1
            }
            var end = -1
            var j = bytes.size - 2
            while (j > start && j >= 0) {
                if ((bytes[j].toInt() and 0xFF) == 0xFF && (bytes[j + 1].toInt() and 0xFF) == 0xD9) {
                    end = j
                    break
                }
                j -= 1
            }
            if (start < 0 || end < 0) {
                framesDropped.incrementAndGet()
                sink.onFrameDropped("assembled payload is not a complete JPEG", 1)
                continue
            }
            val jpeg = bytes.copyOfRange(start, end + 2)
            val seq = synchronized(lock) {
                frameSeq += 1
                frameSeq
            }
            offer(Frame(seq, jpeg, System.nanoTime()))
        }
    }

    private fun offer(frame: Frame) {
        if (queue.offer(frame)) return
        queue.poll()
        framesDropped.incrementAndGet()
        sink.onFrameDropped("display queue full (drop-oldest)", 1)
        queue.offer(frame)
    }

    private fun deliveryLoop() {
        while (true) {
            val done = synchronized(lock) { !running && queue.isEmpty() }
            if (done) return
            val frame = try {
                queue.poll(100L, TimeUnit.MILLISECONDS)
            } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
                return
            }
            if (frame == null) continue
            framesDelivered.incrementAndGet()
            try {
                sink.onFrame(frame.seq, frame.jpeg, frame.captureNs)
            } catch (t: Throwable) {
                log.log("uvc: frame sink threw ${t.javaClass.simpleName}: ${t.message}")
            }
        }
    }

    private fun raiseFault(message: String) {
        synchronized(lock) {
            if (faultText == null) faultText = message
            running = false
            lock.notifyAll()
        }
        log.log("uvc: FAULT $message")
        sink.onTransportError("UVC: $message")
    }

    private fun startThread(name: String, body: () -> Unit): Thread {
        val thread = Thread({
            try {
                body()
            } catch (t: Throwable) {
                raiseFault("$name crashed: ${t.javaClass.simpleName}: ${t.message}")
            }
        }, name)
        thread.isDaemon = true
        thread.start()
        return thread
    }

    private fun joinQuietly(thread: Thread?) {
        if (thread == null) return
        try {
            thread.join(2000L)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
        }
    }

    companion object {
        /** UVC class requests (UVC 1.1, table 4-1). */
        const val UVC_SET_CUR = 0x01
        const val UVC_GET_CUR = 0x81
        const val REQUEST_TYPE_SET = 0x21
        const val REQUEST_TYPE_GET = 0xA1

        /** VideoStreaming interface control selectors. */
        const val CS_PROBE = 0x01
        const val CS_COMMIT = 0x02

        /** Size of the UVC 1.0/1.1 `uvc_streaming_control` structure. */
        const val STREAMING_CONTROL_BYTES = 26

        /** Payload header bits (`bmHeaderInfo`). */
        const val PAYLOAD_FLAG_FID = 0x01
        const val PAYLOAD_FLAG_EOF = 0x02
        const val PAYLOAD_FLAG_PTS = 0x04
        const val PAYLOAD_FLAG_SCR = 0x08
        const val PAYLOAD_FLAG_ERR = 0x40
        const val PAYLOAD_FLAG_EOI = 0x80
    }
}
