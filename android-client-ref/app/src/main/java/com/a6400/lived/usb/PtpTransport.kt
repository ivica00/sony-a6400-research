package com.a6400.lived.usb

import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import java.util.ArrayDeque
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/**
 * Transport A: the physically verified PC Remote PTP link.
 *
 * ```
 * host                                     ILCE-6400 (PID 0x0CAA, class 6/1/1)
 *  |-- bulk OUT 0x02 : command container, then data container ------------------>
 *  |<- bulk IN  0x81 : data container (JPEG) then response container ------------
 *  |<- int IN   0x83 : PTP events (optional, read only) ------------------------
 * ```
 *
 * Threading / ownership (hard rules, do not relax):
 *
 *  * exactly ONE writer thread writes bulk OUT; it is the only place a
 *    transaction id becomes "live";
 *  * exactly ONE reader thread reads bulk IN and owns the reassembly buffer;
 *  * a frame pump thread only *enqueues* GetObject transactions - it never
 *    touches the endpoint;
 *  * a delivery thread decouples the reader from the consumer so a slow
 *    decoder/GL push can never stall the USB pipe (drop-oldest, bounded queue);
 *  * a control transaction is written ONLY when no frame transaction is live
 *    (see [pickNextLocked]); this is the interleave rule that keeps a control
 *    from landing between a GetObject request and its data phase;
 *  * a transaction id is never reused while it is live ([allocateTransactionIdLocked]).
 *
 * Latency policy: the window keeps 2-3 GetObject requests in flight and the next
 * request is issued as soon as a slot frees, with no client-side settle. The
 * camera answers "no new frame" with 8 zero bytes, which is a retry token, not
 * an error (docs/evidence/0151:21, USB_GADGET.md 4.2).
 */
class PtpTransport(
    private val connection: UsbDeviceConnection,
    private val endpointIn: UsbEndpoint,
    private val endpointOut: UsbEndpoint,
    private val endpointEvent: UsbEndpoint?,
    private val sink: FrameSink,
    private val log: LogSink,
    private val config: Config = Config()
) {

    /**
     * All timings are host-side and deliberately explicit. `readTimeoutMs` is a
     * service interval for the bulk IN poll, not a transaction deadline: a NAK
     * (bulkTransfer returning negative) simply falls through to the next poll.
     */
    data class Config(
        val pipelineWindow: Int = 3,
        val maxFrameBytes: Int = 512 * 1024,
        val bulkChunkBytes: Int = 16 * 1024,
        val readTimeoutMs: Int = 400,
        val writeTimeoutMs: Int = 1000,
        val frameTransactionTimeoutMs: Int = 1500,
        val controlTransactionTimeoutMs: Int = 2000,
        /** Extra time a control may spend waiting for the frame pipeline to drain. */
        val controlDrainSlackMs: Int = 2000,
        val deliveryDepth: Int = 3,
        /** GetObject handle for the liveview pseudo-object (0xFFFFC002 as a signed Int). */
        val liveViewHandle: Int = 0xFFFFC002L.toInt(),
        val maxConsecutiveFrameTimeouts: Int = 5,
        /** Read the PTP event endpoint 0x83. Off by default: no client has ever read it. */
        val readEventEndpoint: Boolean = false
    )

    /** One answered (or failed) transaction. */
    class Reply(val operation: Int, val response: Int, val data: ByteArray?) {
        val ok: Boolean get() = response == PtpResponse.OK

        fun requireOk(what: String): ByteArray {
            if (!ok) {
                throw UsbTransportException(
                    "$what failed: response ${PtpHex.h16(response)}"
                )
            }
            return data ?: ByteArray(0)
        }
    }

    data class Stats(
        val framesDelivered: Long,
        val noFrameReplies: Long,
        val frameTimeouts: Long,
        val invalidFrames: Long,
        val queueDrops: Long,
        val controlTimeouts: Long,
        val bytesIn: Long,
        val bytesOut: Long,
        val nakPolls: Long,
        val inFlight: Int,
        val fault: String?
    )

    private class Frame(val seq: Long, val jpeg: ByteArray, val captureNs: Long)

    private class Transaction(
        val operation: Int,
        val params: IntArray,
        val outData: ByteArray?,
        val isControl: Boolean
    ) {
        var transactionId: Int = 0
        var state: Int = STATE_QUEUED
        var response: Int = -1
        var failure: String? = null
        var deadlineNs: Long = 0L
        val data = java.io.ByteArrayOutputStream()
        val latch = CountDownLatch(1)
    }

    private val lock = Object()
    private val assembler = PtpContainerAssembler()
    private val eventAssembler = PtpContainerAssembler()

    private val pendingControls = ArrayDeque<Transaction>()
    private val pendingFrames = ArrayDeque<Transaction>()
    private val inFlight = LinkedHashMap<Int, Transaction>()
    private val liveIds = HashSet<Int>()

    private var controlBusy = false
    private var acceptFrames = false
    private var running = false
    private var faultText: String? = null
    private var nextTransactionId = 1
    private var frameSeq = 0L
    private var consecutiveTimeouts = 0

    private val noFrameReplies = AtomicLong()
    private val frameTimeouts = AtomicLong()
    private val invalidFrames = AtomicLong()
    private val queueDrops = AtomicLong()
    private val controlTimeouts = AtomicLong()
    private val bytesIn = AtomicLong()
    private val bytesOut = AtomicLong()
    private val nakPolls = AtomicLong()
    private val framesDelivered = AtomicLong()

    private val frameQueue = ArrayBlockingQueue<Frame>(maxOf(1, config.deliveryDepth))

    private var writerThread: Thread? = null
    private var readerThread: Thread? = null
    private var pumpThread: Thread? = null
    private var deliveryThread: Thread? = null
    private var eventThread: Thread? = null

    // ---------------------------------------------------------------- lifecycle

    fun start() {
        synchronized(lock) {
            if (running) return
            running = true
            faultText = null
            lock.notifyAll()
        }
        writerThread = startThread("ptp-writer") { writerLoop() }
        readerThread = startThread("ptp-reader") { readerLoop() }
        pumpThread = startThread("ptp-pump") { pumpLoop() }
        deliveryThread = startThread("ptp-delivery") { deliveryLoop() }
        if (config.readEventEndpoint && endpointEvent != null) {
            eventThread = startThread("ptp-event") { eventLoop() }
        }
        log.log(
            "ptp: transport started (window=${config.pipelineWindow}, " +
                "frame cap=${config.maxFrameBytes} B, chunk=${config.bulkChunkBytes} B, " +
                "in=0x${PtpHex.h16(endpointIn.address).substring(2)} " +
                "out=0x${PtpHex.h16(endpointOut.address).substring(2)})"
        )
    }

    fun isRunning(): Boolean = synchronized(lock) { running && faultText == null }

    fun failureText(): String? = synchronized(lock) { faultText }

    /** Enables the GetObject pipeline. Must be called after the Sony handshake. */
    fun startFrames() {
        synchronized(lock) {
            val reason = faultText
            if (reason != null) throw UsbTransportException("PTP transport faulted: $reason")
            if (!running) throw UsbTransportException("PTP transport is not running")
            acceptFrames = true
            lock.notifyAll()
        }
        log.log(
            "ptp: frame pump enabled - GetObject ${PtpHex.h16(PtpOpcode.GET_OBJECT)} " +
                "handle ${PtpHex.h32(config.liveViewHandle)}"
        )
    }

    /** Pauses the pump and drops queued (never sent) frame requests. */
    fun stopFrames() {
        synchronized(lock) {
            acceptFrames = false
            for (txn in pendingFrames) liveIds.remove(txn.transactionId)
            pendingFrames.clear()
            lock.notifyAll()
        }
        log.log("ptp: frame pump disabled")
    }

    /** Stops every thread. Does not close the connection (UsbHost owns that). */
    fun shutdown() {
        synchronized(lock) {
            acceptFrames = false
            running = false
            for (txn in pendingFrames) liveIds.remove(txn.transactionId)
            pendingFrames.clear()
            pendingControls.clear()
            lock.notifyAll()
        }
        joinQuietly(writerThread)
        joinQuietly(readerThread)
        joinQuietly(pumpThread)
        joinQuietly(deliveryThread)
        joinQuietly(eventThread)
        val latches = ArrayList<CountDownLatch>()
        synchronized(lock) {
            for (txn in inFlight.values) {
                txn.failure = "transport shut down"
                latches.add(txn.latch)
            }
            inFlight.clear()
            liveIds.clear()
            controlBusy = false
        }
        for (latch in latches) latch.countDown()
        log.log(
            "ptp: transport stopped (in=${bytesIn.get()} B out=${bytesOut.get()} B " +
                "noFrame=${noFrameReplies.get()} timeouts=${frameTimeouts.get()} " +
                "dropped=${queueDrops.get()})"
        )
    }

    fun stats(): Stats = synchronized(lock) {
        Stats(
            framesDelivered = framesDelivered.get(),
            noFrameReplies = noFrameReplies.get(),
            frameTimeouts = frameTimeouts.get(),
            invalidFrames = invalidFrames.get(),
            queueDrops = queueDrops.get(),
            controlTimeouts = controlTimeouts.get(),
            bytesIn = bytesIn.get(),
            bytesOut = bytesOut.get(),
            nakPolls = nakPolls.get(),
            inFlight = inFlight.size,
            fault = faultText
        )
    }

    // ------------------------------------------------------------------- control

    /**
     * Blocking control transaction. MUST NOT be called on the UI thread.
     *
     * The call waits for the frame pipeline to drain (bounded by
     * `controlDrainSlackMs`), issues the command + optional data phase, and
     * returns the camera's response. A timeout throws [PtpTimeoutException]:
     * the camera state is then unknown and the caller must not report success.
     */
    fun transact(
        operation: Int,
        params: IntArray = IntArray(0),
        outData: ByteArray? = null,
        timeoutMs: Int = config.controlTransactionTimeoutMs
    ): Reply {
        if (params.size > PtpContainer.MAX_PARAMETERS) {
            throw PtpProtocolException(
                "${params.size} parameters exceeds PTP maximum of ${PtpContainer.MAX_PARAMETERS}"
            )
        }
        val transaction = Transaction(operation, params, outData, true)
        synchronized(lock) {
            val reason = faultText
            if (reason != null) throw UsbTransportException("PTP transport faulted: $reason")
            if (!running) throw UsbTransportException("PTP transport is not running")
            transaction.transactionId = allocateTransactionIdLocked()
            pendingControls.addLast(transaction)
            lock.notifyAll()
        }
        val waitMs = timeoutMs.toLong() + config.controlDrainSlackMs
        if (!transaction.latch.await(waitMs, TimeUnit.MILLISECONDS)) {
            synchronized(lock) {
                pendingControls.remove(transaction)
                inFlight.remove(transaction.transactionId)
                liveIds.remove(transaction.transactionId)
                if (inFlight.isEmpty()) controlBusy = false
                controlTimeouts.incrementAndGet()
                lock.notifyAll()
            }
            throw PtpTimeoutException(
                "PTP operation ${PtpHex.h16(operation)} timed out after $waitMs ms"
            )
        }
        val failure = transaction.failure
        if (failure != null) throw UsbTransportException("PTP operation ${PtpHex.h16(operation)}: $failure")
        val body = if (transaction.data.size() > 0) transaction.data.toByteArray() else null
        return Reply(operation, transaction.response, body)
    }

    // -------------------------------------------------------------------- writer

    private fun writerLoop() {
        while (true) {
            var next: Transaction? = null
            synchronized(lock) {
                while (next == null) {
                    if (!running) return
                    next = pickNextLocked()
                    if (next == null) {
                        try {
                            lock.wait(20L)
                        } catch (e: InterruptedException) {
                            Thread.currentThread().interrupt()
                            return
                        }
                    }
                }
            }
            val transaction = next ?: return
            send(transaction)
        }
    }

    /**
     * Chooses the next transaction to put on bulk OUT, or null to wait.
     *
     * The control rule is intentionally strict: a control command container may
     * only be written while NOTHING is in flight, because the camera's data
     * phase for a live GetObject arrives on the same bulk IN pipe and must not
     * be preceded by an unrelated command container. The pump therefore stops
     * adding frames as soon as a control is queued, and the pipeline drains
     * (window x one round trip, measured ~10.2 ms per fetch) before the control
     * goes out.
     */
    private fun pickNextLocked(): Transaction? {
        if (controlBusy) return null
        if (pendingControls.isNotEmpty()) {
            if (inFlight.isNotEmpty()) return null
            val control = pendingControls.removeFirst()
            return markSentLocked(control, true)
        }
        if (!acceptFrames) return null
        if (pendingFrames.isEmpty()) return null
        if (inFlight.size >= config.pipelineWindow) return null
        val frame = pendingFrames.removeFirst()
        return markSentLocked(frame, false)
    }

    private fun markSentLocked(transaction: Transaction, control: Boolean): Transaction? {
        if (inFlight.containsKey(transaction.transactionId)) {
            log.log("ptp: refusing to reuse live transaction id ${PtpHex.h32(transaction.transactionId)}")
            transaction.failure = "transaction id ${PtpHex.h32(transaction.transactionId)} is already live"
            transaction.latch.countDown()
            liveIds.remove(transaction.transactionId)
            return null
        }
        val now = System.nanoTime()
        transaction.state = STATE_SENT
        transaction.deadlineNs = now +
            if (control) {
                config.controlTransactionTimeoutMs * 1_000_000L
            } else {
                config.frameTransactionTimeoutMs * 1_000_000L
            }
        inFlight[transaction.transactionId] = transaction
        if (control) controlBusy = true
        return transaction
    }

    private fun send(transaction: Transaction) {
        val command = PtpContainer.command(transaction.operation, transaction.transactionId, transaction.params)
        if (!writeAll(command)) {
            failTransaction(transaction, "bulk OUT command write failed")
            return
        }
        val data = transaction.outData
        if (data != null) {
            val containers = PtpContainer.dataContainers(
                transaction.operation, transaction.transactionId, data, config.bulkChunkBytes
            )
            for (container in containers) {
                if (!writeAll(container)) {
                    failTransaction(transaction, "bulk OUT data phase write failed")
                    return
                }
            }
        }
    }

    private fun writeAll(bytes: ByteArray): Boolean {
        var at = 0
        var attempts = 0
        while (at < bytes.size) {
            val written = try {
                connection.bulkTransfer(endpointOut, bytes, at, bytes.size - at, config.writeTimeoutMs)
            } catch (e: Exception) {
                log.log("ptp: bulk OUT exception: ${e.javaClass.simpleName}: ${e.message}")
                -1
            }
            if (written <= 0) {
                attempts += 1
                if (attempts >= 3) {
                    log.log("ptp: bulk OUT gave up after $attempts attempts at offset $at/${bytes.size}")
                    return false
                }
                continue
            }
            at += written
        }
        bytesOut.addAndGet(bytes.size.toLong())
        return true
    }

    // -------------------------------------------------------------------- reader

    private fun readerLoop() {
        val chunk = ByteArray(config.bulkChunkBytes)
        while (true) {
            synchronized(lock) { if (!running) return }
            val read = try {
                connection.bulkTransfer(endpointIn, chunk, chunk.size, config.readTimeoutMs)
            } catch (e: Exception) {
                log.log("ptp: bulk IN exception: ${e.javaClass.simpleName}: ${e.message}")
                -1
            }
            if (read <= 0) {
                // NAK / no pending data. Normal while the camera has no new frame.
                nakPolls.incrementAndGet()
                sweepTimeouts()
                continue
            }
            bytesIn.addAndGet(read.toLong())
            try {
                assembler.append(chunk, 0, read)
            } catch (e: PtpProtocolException) {
                raiseFault("container stream: ${e.message}")
                return
            }
            while (true) {
                val container = try {
                    assembler.next()
                } catch (e: PtpProtocolException) {
                    raiseFault("container parse: ${e.message}")
                    return
                }
                if (container == null) break
                dispatch(container)
            }
        }
    }

    private fun dispatch(container: PtpContainer) {
        val target = synchronized(lock) { inFlight[container.transactionId] }
        if (target == null) {
            log.log(
                "ptp: discarding unsolicited container type=${container.type} " +
                    "code=${PtpHex.h16(container.code)} tid=${PtpHex.h32(container.transactionId)} " +
                    "payload=${container.payloadSize} B"
            )
            return
        }
        when (container.type) {
            PtpContainer.TYPE_DATA -> {
                if (container.payloadSize > config.maxFrameBytes) {
                    failTransaction(
                        target,
                        "data phase ${container.payloadSize} B exceeds cap ${config.maxFrameBytes} B"
                    )
                    return
                }
                var overflow = false
                synchronized(lock) {
                    if (target.state == STATE_SENT) target.state = STATE_DATA
                    if (target.data.size() + container.payloadSize > config.maxFrameBytes) {
                        overflow = true
                    } else {
                        target.data.write(container.payload)
                    }
                }
                if (overflow) {
                    failTransaction(
                        target,
                        "reassembled data phase exceeds cap ${config.maxFrameBytes} B"
                    )
                }
            }
            PtpContainer.TYPE_RESPONSE -> completeTransaction(target, container.code)
            else -> log.log("ptp: unexpected container type ${container.type} on bulk IN")
        }
    }

    private fun completeTransaction(transaction: Transaction, response: Int) {
        synchronized(lock) {
            inFlight.remove(transaction.transactionId)
            liveIds.remove(transaction.transactionId)
            if (transaction.isControl) controlBusy = false
            transaction.response = response
            transaction.state = STATE_DONE
            if (!transaction.isControl) consecutiveTimeouts = 0
            lock.notifyAll()
        }
        if (transaction.isControl) {
            transaction.latch.countDown()
            return
        }
        handleFrame(transaction, response)
    }

    private fun handleFrame(transaction: Transaction, response: Int) {
        if (response != PtpResponse.OK) {
            invalidFrames.incrementAndGet()
            sink.onFrameDropped("GetObject response ${PtpHex.h16(response)}", 1)
            return
        }
        val bytes = transaction.data.toByteArray()
        if (bytes.isEmpty() || bytes.size == PtpContainer.NO_FRAME_BYTES) {
            val count = noFrameReplies.incrementAndGet()
            if (count == 1L || count % 100L == 0L) {
                log.log("ptp: no-frame sentinel (${bytes.size} B) seen $count time(s)")
            }
            return
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
        if (start < 0) {
            invalidFrames.incrementAndGet()
            sink.onFrameDropped("data phase has no JPEG SOI", 1)
            return
        }
        var end = -1
        var j = bytes.size - 2
        while (j > start) {
            if ((bytes[j].toInt() and 0xFF) == 0xFF && (bytes[j + 1].toInt() and 0xFF) == 0xD9) {
                end = j
                break
            }
            j -= 1
        }
        if (end < 0) {
            invalidFrames.incrementAndGet()
            sink.onFrameDropped("data phase has no JPEG EOI", 1)
            return
        }
        val length = end + 2 - start
        if (length > config.maxFrameBytes) {
            invalidFrames.incrementAndGet()
            sink.onFrameDropped("JPEG $length B exceeds cap ${config.maxFrameBytes} B", 1)
            return
        }
        val jpeg = bytes.copyOfRange(start, end + 2)
        val seq = synchronized(lock) {
            frameSeq += 1
            frameSeq
        }
        // captureNs is taken at DATA COMPLETION, the first instant the host can
        // prove the frame existed. It excludes camera-side encode and the
        // display pipeline, so the overlay reports it as "host-side age".
        offerFrame(Frame(seq, jpeg, System.nanoTime()))
    }

    private fun offerFrame(frame: Frame) {
        if (frameQueue.offer(frame)) return
        // Drop-oldest: a stale frame is worse than a missing one for latency.
        frameQueue.poll()
        queueDrops.incrementAndGet()
        sink.onFrameDropped("display queue full (drop-oldest)", 1)
        frameQueue.offer(frame)
    }

    private fun failTransaction(transaction: Transaction, reason: String) {
        synchronized(lock) {
            inFlight.remove(transaction.transactionId)
            liveIds.remove(transaction.transactionId)
            if (transaction.isControl) controlBusy = false
            transaction.failure = reason
            transaction.state = STATE_DONE
            lock.notifyAll()
        }
        log.log("ptp: transaction ${PtpHex.h32(transaction.transactionId)} failed: $reason")
        if (transaction.isControl) {
            transaction.latch.countDown()
        } else {
            sink.onFrameDropped(reason, 1)
        }
    }

    // ------------------------------------------------------------------ timeouts

    private fun sweepTimeouts() {
        val expired = ArrayList<Transaction>(4)
        synchronized(lock) {
            if (inFlight.isEmpty()) return
            val now = System.nanoTime()
            val iterator = inFlight.values.iterator()
            while (iterator.hasNext()) {
                val transaction = iterator.next()
                if (transaction.state != STATE_DONE && now - transaction.deadlineNs >= 0L) {
                    iterator.remove()
                    liveIds.remove(transaction.transactionId)
                    if (transaction.isControl) controlBusy = false
                    expired.add(transaction)
                }
            }
            if (expired.isNotEmpty()) lock.notifyAll()
        }
        for (transaction in expired) {
            if (transaction.isControl) {
                controlTimeouts.incrementAndGet()
                transaction.failure =
                    "timed out; camera state for this operation is unknown and must not be assumed applied"
                transaction.latch.countDown()
                log.log("ptp: control ${PtpHex.h16(transaction.operation)} timed out")
            } else {
                frameTimeouts.incrementAndGet()
                val streak = synchronized(lock) {
                    consecutiveTimeouts += 1
                    consecutiveTimeouts
                }
                log.log("ptp: GetObject timeout (consecutive $streak)")
                sink.onFrameDropped("GetObject timed out", 1)
                if (streak >= config.maxConsecutiveFrameTimeouts) {
                    raiseFault("$streak consecutive GetObject timeouts")
                }
            }
        }
    }

    private fun raiseFault(message: String) {
        val latches = ArrayList<CountDownLatch>(4)
        synchronized(lock) {
            if (faultText == null) faultText = message
            acceptFrames = false
            running = false
            for (transaction in inFlight.values) {
                transaction.failure = "transport fault: $message"
                latches.add(transaction.latch)
            }
            inFlight.clear()
            liveIds.clear()
            for (transaction in pendingFrames) transaction.failure = "transport fault: $message"
            pendingFrames.clear()
            for (transaction in pendingControls) {
                transaction.failure = "transport fault: $message"
                latches.add(transaction.latch)
            }
            pendingControls.clear()
            controlBusy = false
            lock.notifyAll()
        }
        log.log("ptp: FAULT $message")
        for (latch in latches) latch.countDown()
        sink.onTransportError(message)
    }

    // ---------------------------------------------------------------- pump/deliver

    private fun pumpLoop() {
        while (true) {
            var queued = false
            synchronized(lock) {
                if (!running) return
                if (acceptFrames && pendingControls.isEmpty() && !controlBusy &&
                    pendingFrames.size + inFlight.size < config.pipelineWindow
                ) {
                    val transaction = Transaction(
                        PtpOpcode.GET_OBJECT,
                        intArrayOf(config.liveViewHandle),
                        null,
                        false
                    )
                    transaction.transactionId = allocateTransactionIdLocked()
                    pendingFrames.addLast(transaction)
                    queued = true
                    lock.notifyAll()
                }
            }
            if (!queued) {
                synchronized(lock) {
                    try {
                        lock.wait(5L)
                    } catch (e: InterruptedException) {
                        Thread.currentThread().interrupt()
                        return
                    }
                }
            }
            sweepTimeouts()
        }
    }

    private fun deliveryLoop() {
        while (true) {
            val done = synchronized(lock) { !running && frameQueue.isEmpty() }
            if (done) return
            val frame = try {
                frameQueue.poll(100L, TimeUnit.MILLISECONDS)
            } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
                return
            }
            if (frame == null) continue
            framesDelivered.incrementAndGet()
            try {
                sink.onFrame(frame.seq, frame.jpeg, frame.captureNs)
            } catch (t: Throwable) {
                log.log("ptp: frame sink threw ${t.javaClass.simpleName}: ${t.message}")
            }
        }
    }

    private fun eventLoop() {
        val endpoint = endpointEvent ?: return
        val buffer = ByteArray(endpoint.maxPacketSize.coerceAtLeast(64))
        log.log("ptp: reading event endpoint 0x${PtpHex.h16(endpoint.address).substring(2)}")
        while (true) {
            synchronized(lock) { if (!running) return }
            val read = try {
                connection.bulkTransfer(endpoint, buffer, buffer.size, config.readTimeoutMs)
            } catch (e: Exception) {
                -1
            }
            if (read <= 0) continue
            try {
                eventAssembler.append(buffer, 0, read)
            } catch (e: PtpProtocolException) {
                log.log("ptp: event stream desync (${e.message}); buffer dropped")
                eventAssembler.reset()
                continue
            }
            while (true) {
                val event = try {
                    eventAssembler.next()
                } catch (e: PtpProtocolException) {
                    log.log("ptp: event parse failed (${e.message}); buffer dropped")
                    eventAssembler.reset()
                    break
                }
                if (event == null) break
                log.log(
                    "ptp: event ${PtpHex.h16(event.code)} code " +
                        "tid=${PtpHex.h32(event.transactionId)} payload=${event.payloadSize} B"
                )
            }
        }
    }

    // ------------------------------------------------------------------- helpers

    private fun allocateTransactionIdLocked(): Int {
        var candidate = nextTransactionId
        var guard = 0
        while (guard < 0x10000) {
            if (candidate <= 0) candidate = 1
            if (!liveIds.contains(candidate)) {
                liveIds.add(candidate)
                nextTransactionId = if (candidate >= 0x7FFFFFFF) 1 else candidate + 1
                return candidate
            }
            candidate = if (candidate >= 0x7FFFFFFF) 1 else candidate + 1
            guard += 1
        }
        throw UsbTransportException("PTP transaction id space exhausted")
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

    private companion object {
        const val STATE_QUEUED = 0
        const val STATE_SENT = 1
        const val STATE_DATA = 2
        const val STATE_DONE = 3
    }
}
