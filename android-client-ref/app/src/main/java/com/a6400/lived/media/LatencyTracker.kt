package com.a6400.lived.media

/**
 * Latency and frame-rate accounting for the live view.
 *
 * A frame has three host-observable instants:
 *
 *  * `captureNs`  - the transport's data phase completed (PTP: the bulk IN
 *                   container was fully reassembled; UVC: the EOF payload
 *                   header arrived). This is NOT the photon time: camera-side
 *                   sensor readout, encode and DMA are not observable from the
 *                   host, so they are excluded and must never be presented as
 *                   measured.
 *  * `decodeNs`   - `nativePushJpeg` returned, i.e. the native decoder accepted
 *                   and decoded the frame.
 *  * `renderNs`   - `nativeRender` reported a new frame presented to the GL
 *                   surface.
 *
 * `p50Age`/`p95Age` are therefore HOST-SIDE frame age. The overlay labels them
 * as such; USB_GADGET.md 5.4 contains the full glass-to-glass arithmetic with
 * the camera-side terms marked unknown.
 *
 * The ring keeps the newest [capacity] completed records; all methods are
 * thread safe because producers (transport delivery thread, GL thread) and the
 * overlay reader run on different threads.
 */
class LatencyTracker(private val capacity: Int = 240) {

    data class Stats(
        val sampledFrames: Int,
        val fps: Double,
        val p50AgeMs: Double,
        val p95AgeMs: Double,
        val maxAgeMs: Double,
        val decodeMs: Double,
        val lastSeq: Long,
        val pushed: Long,
        val dropped: Long,
        val superseded: Long
    )

    private val lock = Object()

    private val captureRing = LongArray(capacity)
    private val decodeRing = LongArray(capacity)
    private val renderRing = LongArray(capacity)
    private var stored = 0
    private var nextSlot = 0

    private var pushed = 0L
    private var dropped = 0L
    private var superseded = 0L
    private var lastSeq = -1L

    private var pendingSeq = -1L
    private var pendingCaptureNs = 0L
    private var pendingDecodeNs = 0L

    /** A new frame entered the pipeline; the previous unrendered one is superseded. */
    fun onFramePushed(seq: Long, captureNs: Long) {
        synchronized(lock) {
            if (pendingSeq >= 0L) superseded += 1
            pushed += 1
            lastSeq = seq
            pendingSeq = seq
            pendingCaptureNs = captureNs
            pendingDecodeNs = 0L
        }
    }

    /** The native decoder accepted the pending frame. */
    fun onDecodeComplete(decodeNs: Long = System.nanoTime()) {
        synchronized(lock) {
            if (pendingSeq < 0L) return
            pendingDecodeNs = decodeNs
        }
    }

    /**
     * The renderer presented a new frame. Returns true when a full
     * capture/decode/render triple was recorded, false when the render cannot be
     * attributed to a pending frame (e.g. the first draw, or a repeat draw of the
     * same texture).
     */
    fun onRendered(renderNs: Long = System.nanoTime()): Boolean {
        synchronized(lock) {
            if (pendingSeq < 0L || pendingDecodeNs == 0L) return false
            captureRing[nextSlot] = pendingCaptureNs
            decodeRing[nextSlot] = pendingDecodeNs
            renderRing[nextSlot] = renderNs
            nextSlot = (nextSlot + 1) % capacity
            if (stored < capacity) stored += 1
            pendingSeq = -1L
            pendingCaptureNs = 0L
            pendingDecodeNs = 0L
            return true
        }
    }

    /** Frames lost before they reached the pipeline (transport drop / bad JPEG). */
    fun onDropped(count: Int = 1) {
        synchronized(lock) { dropped += count.toLong() }
    }

    fun reset() {
        synchronized(lock) {
            stored = 0
            nextSlot = 0
            pushed = 0L
            dropped = 0L
            superseded = 0L
            lastSeq = -1L
            pendingSeq = -1L
            pendingCaptureNs = 0L
            pendingDecodeNs = 0L
        }
    }

    /**
     * Computes fps over the newest records inside [fpsWindowNs] and percentiles
     * over the same set. Percentiles use nearest-rank on a sorted copy, which is
     * stable and cheap at this size.
     */
    fun snapshot(nowNs: Long = System.nanoTime(), fpsWindowNs: Long = 2_000_000_000L): Stats {
        synchronized(lock) {
            if (stored == 0) {
                return Stats(0, 0.0, 0.0, 0.0, 0.0, 0.0, lastSeq, pushed, dropped, superseded)
            }
            val ages = DoubleArray(stored)
            var considered = 0
            var oldestRender = Long.MAX_VALUE
            var newestRender = Long.MIN_VALUE
            var decodeSum = 0.0
            var decodeCount = 0
            var maxAge = 0.0
            for (i in 0 until stored) {
                val slot = if (stored < capacity) i else (nextSlot + i) % capacity
                val rendered = renderRing[slot]
                if (rendered < nowNs - fpsWindowNs) continue
                val ageNs = rendered - captureRing[slot]
                if (ageNs <= 0L) continue
                val ageMs = ageNs.toDouble() / 1_000_000.0
                ages[considered] = ageMs
                considered += 1
                if (rendered < oldestRender) oldestRender = rendered
                if (rendered > newestRender) newestRender = rendered
                val decodeMs = (decodeRing[slot] - captureRing[slot]).toDouble() / 1_000_000.0
                if (decodeMs > 0.0) {
                    decodeSum += decodeMs
                    decodeCount += 1
                }
                if (ageMs > maxAge) maxAge = ageMs
            }
            if (considered == 0) {
                return Stats(0, 0.0, 0.0, 0.0, 0.0, 0.0, lastSeq, pushed, dropped, superseded)
            }
            val sorted = ages.copyOf(considered)
            sorted.sort()
            val fps = if (considered >= 2 && newestRender > oldestRender) {
                (considered - 1).toDouble() * 1_000_000_000.0 / (newestRender - oldestRender).toDouble()
            } else {
                0.0
            }
            return Stats(
                sampledFrames = considered,
                fps = fps,
                p50AgeMs = percentile(sorted, 0.50),
                p95AgeMs = percentile(sorted, 0.95),
                maxAgeMs = maxAge,
                decodeMs = if (decodeCount == 0) 0.0 else decodeSum / decodeCount,
                lastSeq = lastSeq,
                pushed = pushed,
                dropped = dropped,
                superseded = superseded
            )
        }
    }

    private fun percentile(sorted: DoubleArray, fraction: Double): Double {
        if (sorted.isEmpty()) return 0.0
        val index = ((sorted.size - 1) * fraction).toInt().coerceIn(0, sorted.size - 1)
        return sorted[index]
    }
}
