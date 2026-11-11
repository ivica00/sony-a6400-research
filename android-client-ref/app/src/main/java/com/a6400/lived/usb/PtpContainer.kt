package com.a6400.lived.usb

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * PTP container framing, exactly as the camera and the proven clients use it.
 *
 * Wire header, 12 bytes, little-endian:
 *
 * ```
 * offset  size  field
 *   0      4    length   total container length including this header
 *   4      2    type     1 = command, 2 = data, 3 = response, 4 = event
 *   6      2    code     operation code (command/response) or 0 (data)
 *   8      4    tid      transaction id, echoed by the camera
 *  12      n    payload  parameters (command) or data phase (data)
 * ```
 *
 * Sources: `android/cinemahud/android/.../MainActivity.kt:109` (encoder) and
 * `MainActivity.kt:120-138` (length-prefixed reader); byte-identical to the
 * Python client in `tools/research/ptp_liveview_client.py`.
 */
class PtpProtocolException(message: String) : Exception(message)

/** One decoded container. `payload` is a fresh array owned by the caller. */
class PtpContainer(
    val type: Int,
    val code: Int,
    val transactionId: Int,
    val payload: ByteArray
) {
    val isCommand: Boolean get() = type == PtpContainer.TYPE_COMMAND
    val isData: Boolean get() = type == PtpContainer.TYPE_DATA
    val isResponse: Boolean get() = type == PtpContainer.TYPE_RESPONSE
    val isEvent: Boolean get() = type == PtpContainer.TYPE_EVENT
    val payloadSize: Int get() = payload.size
}

object PtpContainer {

    const val HEADER_BYTES = 12

    const val TYPE_COMMAND = 1
    const val TYPE_DATA = 2
    const val TYPE_RESPONSE = 3
    const val TYPE_EVENT = 4

    /** PTP allows at most five 32-bit parameters in a command container. */
    const val MAX_PARAMETERS = 5

    /**
     * Hard cap for a single container. A liveview JPEG is 52-141 KB
     * (docs/evidence/0339, 0343) so 4 MiB is ~28x headroom and still bounds a
     * hostile or desynchronised stream.
     */
    const val MAX_CONTAINER_BYTES = 4 * 1024 * 1024

    /**
     * The camera answers GetObject with 8 zero bytes when no new liveview frame
     * is ready (docs/evidence/0151:21). That is a "retry soon" token, not an
     * error and not a frame.
     */
    const val NO_FRAME_BYTES = 8

    /**
     * Encodes one container.
     *
     * @param payload optional body; `offset`/`length` select a slice so a data
     *   phase can be chunked without copying it first.
     */
    fun encode(
        type: Int,
        code: Int,
        transactionId: Int,
        payload: ByteArray? = null,
        offset: Int = 0,
        length: Int = payload?.size ?: 0
    ): ByteArray {
        if (type < TYPE_COMMAND || type > TYPE_EVENT) {
            throw PtpProtocolException("invalid PTP container type $type")
        }
        var count = 0
        if (payload == null) {
            if (offset != 0 || length != 0) {
                throw PtpProtocolException("payload slice given without a payload")
            }
        } else {
            if (offset < 0 || length < 0 || offset > payload.size - length) {
                throw PtpProtocolException(
                    "payload slice out of bounds (offset=$offset length=$length size=${payload.size})"
                )
            }
            count = length
        }
        val total = HEADER_BYTES + count
        if (total > MAX_CONTAINER_BYTES) {
            throw PtpProtocolException("container of $total B exceeds cap $MAX_CONTAINER_BYTES B")
        }
        val out = ByteArray(total)
        val header = ByteBuffer.wrap(out).order(ByteOrder.LITTLE_ENDIAN)
        header.putInt(total)
        header.putShort((type and 0xFFFF).toShort())
        header.putShort((code and 0xFFFF).toShort())
        header.putInt(transactionId)
        if (payload != null && count > 0) {
            System.arraycopy(payload, offset, out, HEADER_BYTES, count)
        }
        return out
    }

    /** Command container: `params` become 4-byte little-endian parameters. */
    fun command(code: Int, transactionId: Int, params: IntArray): ByteArray {
        if (params.size > MAX_PARAMETERS) {
            throw PtpProtocolException("${params.size} parameters exceeds PTP maximum of $MAX_PARAMETERS")
        }
        if (params.isEmpty()) {
            return encode(TYPE_COMMAND, code, transactionId, null)
        }
        val body = ByteBuffer.allocate(params.size * 4).order(ByteOrder.LITTLE_ENDIAN)
        for (p in params) body.putInt(p)
        return encode(TYPE_COMMAND, code, transactionId, body.array())
    }

    /**
     * Splits an outbound data phase into one or more data containers that all
     * carry the same transaction id, in order. A single-container data phase is
     * the common case (0x9205/0x9207 payloads are 1-4 bytes); chunking exists so
     * a larger payload can never block the bulk OUT pipe in one transfer.
     */
    fun dataContainers(
        code: Int,
        transactionId: Int,
        payload: ByteArray,
        maxChunkBytes: Int
    ): List<ByteArray> {
        val chunk = if (maxChunkBytes <= 0) payload.size else maxChunkBytes
        if (payload.isEmpty() || chunk <= 0) {
            return listOf(encode(TYPE_DATA, code, transactionId, payload))
        }
        val containers = ArrayList<ByteArray>((payload.size / chunk) + 1)
        var offset = 0
        while (offset < payload.size) {
            val n = minOf(chunk, payload.size - offset)
            containers.add(encode(TYPE_DATA, code, transactionId, payload, offset, n))
            offset += n
        }
        return containers
    }
}

/** Small hex helpers so every log line uses the same spelling. */
object PtpHex {
    fun h16(value: Int): String = String.format(java.util.Locale.US, "0x%04X", value and 0xFFFF)
    fun h32(value: Int): String = String.format(java.util.Locale.US, "0x%08X", value)
}

/**
 * Incremental container reassembly over a byte stream.
 *
 * The bulk IN pipe hands over arbitrary chunk boundaries: a 140 KB data
 * container arrives as ~9 x 16 KB transfers, and two containers can share one
 * transfer. The assembler buffers, validates the 12-byte header against a
 * bounds check, and yields whole containers only.
 *
 * Not thread safe: exactly one reader thread may call [append]/[next].
 */
class PtpContainerAssembler(
    private val maxContainerBytes: Int = PtpContainer.MAX_CONTAINER_BYTES,
    initialCapacity: Int = 64 * 1024
) {

    private var buffer = ByteArray(if (initialCapacity < PtpContainer.HEADER_BYTES) 64 else initialCapacity)
    private var size = 0
    private var readPos = 0

    fun reset() {
        size = 0
        readPos = 0
    }

    fun bufferedBytes(): Int = size - readPos

    /** True when at least one whole container is buffered (header is parsed). */
    fun hasContainer(): Boolean {
        if (size - readPos < PtpContainer.HEADER_BYTES) return false
        val length = le32(readPos)
        return length >= PtpContainer.HEADER_BYTES && length <= maxContainerBytes && size - readPos >= length
    }

    fun append(chunk: ByteArray, offset: Int, length: Int) {
        if (length <= 0) return
        if (offset < 0 || length < 0 || offset > chunk.size - length) {
            throw PtpProtocolException("append out of bounds (offset=$offset length=$length size=${chunk.size})")
        }
        if (readPos > 0) compact()
        ensureCapacity(size + length)
        System.arraycopy(chunk, offset, buffer, size, length)
        size += length
        if (size - readPos > maxContainerBytes + PtpContainer.HEADER_BYTES) {
            throw PtpProtocolException(
                "buffered ${size - readPos} B without a complete container (cap $maxContainerBytes B)"
            )
        }
    }

    /**
     * Returns the next complete container, or null when more bytes are needed.
     * Throws [PtpProtocolException] when the stream is not a valid container
     * stream; the caller must then reset or fail the transport, never skip bytes.
     */
    fun next(): PtpContainer? {
        if (size - readPos < PtpContainer.HEADER_BYTES) return null
        val length = le32(readPos)
        if (length < PtpContainer.HEADER_BYTES) {
            throw PtpProtocolException("container length $length B is shorter than the 12 B header")
        }
        if (length > maxContainerBytes) {
            throw PtpProtocolException("container length $length B exceeds cap $maxContainerBytes B")
        }
        if (size - readPos < length) return null
        val type = le16(readPos + 4)
        val code = le16(readPos + 6)
        val transactionId = le32(readPos + 8)
        val payloadBytes = length - PtpContainer.HEADER_BYTES
        val payload = ByteArray(payloadBytes)
        if (payloadBytes > 0) {
            System.arraycopy(buffer, readPos + PtpContainer.HEADER_BYTES, payload, 0, payloadBytes)
        }
        readPos += length
        if (readPos == size) {
            readPos = 0
            size = 0
        }
        return PtpContainer(type, code, transactionId, payload)
    }

    private fun compact() {
        val remaining = size - readPos
        if (remaining > 0) {
            System.arraycopy(buffer, readPos, buffer, 0, remaining)
        }
        size = remaining
        readPos = 0
    }

    private fun ensureCapacity(required: Int) {
        if (buffer.size >= required) return
        var capacity = buffer.size
        while (capacity < required) {
            capacity = capacity shl 1
            if (capacity <= 0) throw PtpProtocolException("container buffer overflow")
        }
        buffer = buffer.copyOf(capacity)
    }

    private fun le16(at: Int): Int =
        (buffer[at].toInt() and 0xFF) or ((buffer[at + 1].toInt() and 0xFF) shl 8)

    private fun le32(at: Int): Int =
        le16(at) or (le16(at + 2) shl 16)
}
