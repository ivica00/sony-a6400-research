package com.a6400.lived.usb

/**
 * The two transports this client can use.
 *
 * [PTP] is the PRIMARY transport and the only one that has ever carried real
 * sensor frames to a real host (ILCE-6400 PC Remote, VID 0x054C / PID 0x0CAA,
 * interface class 6, bulk OUT 0x02 / bulk IN 0x81, GetObject 0x1009 handle
 * 0xFFFFC002).
 *
 * [UVC] is the SECONDARY transport (composite VID 0x054C / PID 0x0322, UVC
 * VC/VS interfaces with bulk IN 0x84). It has never produced a frame on this
 * hardware and is labelled UNVERIFIED everywhere it is shown.
 */
enum class TransportKind(val label: String, val verified: Boolean) {
    PTP("PTP / PC Remote (primary)", true),
    UVC("UVC composite (UNVERIFIED)", false)
}

/** A place to send human-readable diagnostics (the in-app log pane). */
interface LogSink {
    fun log(message: String)
}

/**
 * Frame delivery contract shared by both transports.
 *
 * `onFrame` is called on a transport-owned delivery thread, never on the UI
 * thread: implementations must be cheap and must not block on the GL surface.
 * `captureNs` is `System.nanoTime()` taken when the frame's data phase
 * completed on the host, i.e. the start of the host-observable latency, not the
 * photon time.
 */
interface FrameSink {
    fun onFrame(seq: Long, jpeg: ByteArray, captureNs: Long)
    fun onFrameDropped(reason: String, count: Int)
    fun onTransportError(message: String)
}

/** Transport-level failure with a caller-facing message. */
open class UsbTransportException(message: String) : Exception(message)

/** A control transaction that did not answer in time; nothing may be assumed about the camera. */
class PtpTimeoutException(message: String) : Exception(message)
