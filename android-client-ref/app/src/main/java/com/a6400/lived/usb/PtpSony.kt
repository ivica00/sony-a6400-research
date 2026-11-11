package com.a6400.lived.usb

/**
 * PTP operation codes used by this client.
 *
 * Generic PTP: OpenSession / CloseSession / GetObject. The liveview pseudo
 * object is fetched with `GetObject 0x1009` on handle `0xFFFFC002`
 * (docs/evidence/0151:21, 0260, 0266-0268; sony_ptp.dart:266).
 *
 * Sony vendor opcodes: the camera accepts eight (`0x9201/2/3/5/6/7/8/9`,
 * CONTROL_IPC.md 2.2 table A/B from libInfraRemote.so .data). This client uses
 * the five that have physical receipts and never sends 0x9203/0x9206/0x9208
 * because their semantics are undecoded.
 */
object PtpOpcode {
    const val GET_DEVICE_INFO = 0x1001
    const val OPEN_SESSION = 0x1002
    const val CLOSE_SESSION = 0x1003
    const val GET_OBJECT = 0x1009
}

/** Sony PC Remote (SDIO) vendor opcodes - every one below has a physical receipt. */
object SonyOpcode {
    /** SDIOConnect. Three phases: [1,0,0] -> [2,0,0] -> [3,0,0]. */
    const val SDIO_CONNECT = 0x9201

    /** GetSDIOExtDeviceInfo. Called with [0xC8]; returns the capability blob. */
    const val GET_SDIO_EXT_DEVICE_INFO = 0x9202

    /**
     * Absolute property write. ACKNOWLEDGED BUT NOT EFFECTIVE for shutter,
     * aperture, EV and ISO: the camera's handler maps these codes to directional
     * UI keys (libInfraRemote.so `InfraRemoteUsb::CtrlCode2InputKey`), so an
     * ACK proves the container was accepted, never that the value changed
     * (CONTROL_IPC.md 0, 2.4; docs/CINEMAHUD_STOCK_PTP.md:38-46).
     */
    const val SET_CONTROL_DEVICE_A = 0x9205

    /**
     * Signed notch write: parameters `[propertyCode]`, data phase one signed
     * byte. This is the proven-effective control path (shutter 1/100->1/125
     * ->1/100, aperture f/2.8->f/3.2->f/2.8, EV 0->+0.3->0).
     */
    const val SET_CONTROL_DEVICE_B = 0x9207

    /** All-device-property descriptor read; 1730 bytes on the a6400. */
    const val GET_DEVICE_PROPERTIES = 0x9209
}

/** PTP response codes that this client distinguishes. Values are the standard PTP ones. */
object PtpResponse {
    const val OK = 0x2001
    const val GENERAL_ERROR = 0x2002
    const val SESSION_NOT_OPEN = 0x2003
    const val INVALID_TRANSACTION_ID = 0x2004
    const val OPERATION_NOT_SUPPORTED = 0x2005
    const val PARAMETER_NOT_SUPPORTED = 0x2006
    const val INCOMPLETE_TRANSFER = 0x2007
    const val INVALID_OBJECT_HANDLE = 0x2009
    const val DEVICE_BUSY = 0x2019
    const val INVALID_PARAMETER = 0x201D

    /** OpenSession on an already-open session; the camera accepts it. */
    const val SESSION_ALREADY_OPEN = 0x201E
    const val TRANSACTION_CANCELLED = 0x2020

    fun name(code: Int): String = when (code) {
        OK -> "OK"
        GENERAL_ERROR -> "GeneralError"
        SESSION_NOT_OPEN -> "SessionNotOpen"
        INVALID_TRANSACTION_ID -> "InvalidTransactionID"
        OPERATION_NOT_SUPPORTED -> "OperationNotSupported"
        PARAMETER_NOT_SUPPORTED -> "ParameterNotSupported"
        INCOMPLETE_TRANSFER -> "IncompleteTransfer"
        INVALID_OBJECT_HANDLE -> "InvalidObjectHandle"
        DEVICE_BUSY -> "DeviceBusy"
        INVALID_PARAMETER -> "InvalidParameter"
        SESSION_ALREADY_OPEN -> "SessionAlreadyOpen"
        TRANSACTION_CANCELLED -> "TransactionCancelled"
        else -> "Response${PtpHex.h16(code)}"
    }
}

/**
 * Firmware property codes, as they appear in the 0x9209 blob and in the
 * parameters of 0x9205 / 0x9207. All five below are physically present in the
 * a6400 property set (CONTROL_IPC.md 2.3).
 */
object PropCode {
    const val APERTURE = 0x5007

    /** UINT32, `numerator << 16 | denominator`; denominator 0 = BULB, 0xFFFFFFFF = unavailable. */
    const val SHUTTER = 0xD20D

    /** UINT32, absolute ISO; 0xFFFFFF = Auto. */
    const val ISO = 0xD21E

    /** INT16, millistop (EV x 1000). */
    const val EV = 0x5010

    /** UINT16 enumeration; the camera's enumeration is authoritative, labels are not. */
    const val FOCUS_MODE = 0x500A
    const val EXPOSURE_MODE = 0x500E
    const val WHITE_BALANCE = 0x5005

    /** Absent on the a6400 - never fabricate a battery percentage. */
    const val BATTERY = 0x5001
}

/**
 * One parsed 0x9209 property descriptor.
 *
 * `datatype` is the PTP datatype (1 INT8, 2 UINT8, 3 INT16, 4 UINT16, 5 INT32,
 * 6 UINT32, 7 INT64, 8 UINT64, 9/10 128-bit, 0xFFFF string); `access` follows
 * the proven client's rule `access < 128` = writable; `options` is empty for a
 * range descriptor (form 1), which is exactly why shutter and aperture are
 * notch-only.
 */
class PtpProperty(
    val code: Int,
    val datatype: Int,
    val access: Int,
    val enabled: Boolean,
    val defaultValue: Long,
    val current: Long,
    val form: Int,
    val options: LongArray,
    val limits: LongArray
) {
    val writable: Boolean get() = enabled && access < 128

    /** Byte width of one wire value of this datatype, or 0 when it is not an integer. */
    val datatypeBytes: Int
        get() = when (datatype) {
            in 1..8 -> 1 shl ((datatype - 1) / 2)
            else -> 0
        }

    fun describe(): String =
        "code=${PtpHex.h16(code)} type=$datatype access=$access enabled=$enabled " +
            "form=$form current=$current default=$defaultValue " +
            "options=${options.size} limits=${limits.size}"
}

/**
 * Reader for the Sony blob. Mirrors the proven parsers exactly
 * (`android/cinemahud/lib/sony_ptp.dart:19-116` and
 * `tools/research/sony_ptp_controls.py::parse_properties`), including the
 * bounds checks and the "default then current" order.
 */
class SonyPropertyParser {

    fun parse(blob: ByteArray): Map<Int, PtpProperty> {
        val reader = BlobReader(blob)
        val count = reader.u32()
        val reserved = reader.u32()
        if (count > MAX_PROPERTIES) {
            throw PtpProtocolException("0x9209 blob declares $count properties (cap $MAX_PROPERTIES)")
        }
        if (reserved != 0L) {
            throw PtpProtocolException("0x9209 blob reserved word is $reserved, expected 0")
        }
        val result = LinkedHashMap<Int, PtpProperty>((count.toInt() * 2).coerceAtLeast(16))
        repeat(count.toInt()) {
            val code = reader.u16()
            val datatype = reader.u16()
            val access = reader.u8()
            val enabled = reader.u8() == 1
            val defaultValue = reader.value(datatype)
            val current = reader.value(datatype)
            val form = reader.u8()
            var options = LongArray(0)
            var limits = LongArray(0)
            when (form) {
                0 -> Unit
                1 -> {
                    limits = LongArray(3)
                    for (i in 0 until 3) limits[i] = reader.value(datatype)
                }
                2 -> {
                    val optionCount = reader.u16()
                    if (optionCount > MAX_OPTIONS) {
                        throw PtpProtocolException(
                            "property ${PtpHex.h16(code)} declares $optionCount options"
                        )
                    }
                    options = LongArray(optionCount)
                    for (i in 0 until optionCount) options[i] = reader.value(datatype)
                }
                else -> throw PtpProtocolException(
                    "property ${PtpHex.h16(code)} has unknown form $form"
                )
            }
            if (result.containsKey(code)) {
                throw PtpProtocolException("duplicate property ${PtpHex.h16(code)} in 0x9209 blob")
            }
            // The trailing-byte check is made once, after the loop; checking it
            // per property would reject a well-formed blob that ends exactly
            // on the last descriptor.
            result[code] = PtpProperty(
                code = code,
                datatype = datatype,
                access = access,
                enabled = enabled,
                defaultValue = defaultValue,
                current = current,
                form = form,
                options = options,
                limits = limits
            )
        }
        if (reader.remaining() != 0) {
            throw PtpProtocolException(
                "0x9209 blob has ${reader.remaining()} trailing byte(s) after $count properties"
            )
        }
        return result
    }

    private class BlobReader(private val bytes: ByteArray) {
        private var position = 0

        fun remaining(): Int = bytes.size - position

        fun u8(): Int {
            need(1)
            return bytes[position++].toInt() and 0xFF
        }

        fun u16(): Int {
            need(2)
            val value = (bytes[position].toInt() and 0xFF) or
                ((bytes[position + 1].toInt() and 0xFF) shl 8)
            position += 2
            return value
        }

        fun u32(): Long {
            need(4)
            var value = 0L
            for (i in 0 until 4) {
                value = value or ((bytes[position + i].toLong() and 0xFFL) shl (8 * i))
            }
            position += 4
            return value
        }

        fun value(datatype: Int): Long {
            if (datatype in 1..8) {
                val size = 1 shl ((datatype - 1) / 2)
                need(size)
                var raw = 0L
                for (i in 0 until size) {
                    raw = raw or ((bytes[position + i].toLong() and 0xFFL) shl (8 * i))
                }
                position += size
                val signed = datatype % 2 == 1
                if (signed && size < 8) {
                    val signBit = 1L shl (size * 8 - 1)
                    if (raw and signBit != 0L) {
                        return raw or (-1L shl (size * 8))
                    }
                }
                return raw
            }
            when (datatype) {
                0xFFFF -> {
                    val count = u8()
                    need(count * 2)
                    position += count * 2
                    return 0L
                }
                9, 10 -> {
                    need(16)
                    position += 16
                    return 0L
                }
                else -> {
                    if (datatype and 0x4000 != 0) {
                        val count = u32()
                        if (count > MAX_OPTIONS) {
                            throw PtpProtocolException("array datatype declares $count elements")
                        }
                        for (i in 0 until count.toInt()) {
                            value(datatype and 0x3FFF)
                        }
                        return 0L
                    }
                    throw PtpProtocolException("unsupported 0x9209 datatype ${PtpHex.h16(datatype)}")
                }
            }
        }

        private fun need(count: Int) {
            if (count < 0 || position + count > bytes.size) {
                throw PtpProtocolException(
                    "0x9209 blob truncated: need $count B at offset $position of ${bytes.size} B"
                )
            }
        }
    }

    private companion object {
        const val MAX_PROPERTIES = 4096L
        const val MAX_OPTIONS = 65535L
    }
}

/**
 * Value encodings and labels for the four controls this client drives.
 *
 * Every unit below is the proven client's, not an invention:
 *  * shutter  `numerator << 16 | denominator` (0x00010064 = 1/100)
 *  * aperture f-number x 100 (280 = f/2.8)
 *  * EV       millistop (300 = +0.3 EV)
 *  * ISO      absolute, 0xFFFFFF = Auto
 */
object SonyValue {

    const val ISO_AUTO = 0xFFFFFFL

    fun shutter(numerator: Int, denominator: Int): Long =
        ((numerator.toLong() and 0xFFFFL) shl 16) or (denominator.toLong() and 0xFFFFL)

    fun shutterNumerator(value: Long): Int = ((value shr 16) and 0xFFFFL).toInt()

    fun shutterDenominator(value: Long): Int = (value and 0xFFFFL).toInt()

    fun aperture(fNumberTimes100: Int): Long = (fNumberTimes100 and 0xFFFF).toLong()

    fun apertureFNumber(value: Long): Double = (value and 0xFFFFL).toDouble() / 100.0

    fun evMillistop(milliStops: Int): Long = milliStops.toLong()

    fun iso(value: Int): Long = (value.toLong() and 0xFFFFFFL)

    fun isIsoAuto(value: Long): Boolean = (value and 0xFFFFFFL) == ISO_AUTO

    fun label(code: Int, value: Long): String = when (code) {
        PropCode.ISO -> {
            if (isIsoAuto(value)) {
                "Auto"
            } else {
                val nr = (value shr 24) and 0xFFL
                val base = value and 0xFFFFFFL
                if (nr != 0L) "$base NR$nr" else base.toString()
            }
        }
        PropCode.APERTURE -> {
            val f = apertureFNumber(value)
            if (value % 100L == 0L) "f/${f.toInt()}" else "f/$f"
        }
        PropCode.EV -> {
            val stops = value.toDouble() / 1000.0
            if (stops > 0) String.format(java.util.Locale.US, "+%.1f", stops)
            else String.format(java.util.Locale.US, "%.1f", stops)
        }
        PropCode.SHUTTER -> {
            if (value == 0L) {
                "BULB"
            } else if (value == 0xFFFFFFFFL) {
                "n/a"
            } else {
                val numerator = shutterNumerator(value)
                val denominator = shutterDenominator(value)
                if (denominator == 0) "BULB"
                else if (denominator == 1) "${numerator}\"" else "$numerator/$denominator"
            }
        }
        else -> value.toString()
    }

    /**
     * Monotonic comparison metric for notch stepping, mirroring the proven
     * client: ISO steps by enumeration index, shutter by -(numerator/denominator)
     * (so a larger metric means a longer exposure), everything else by raw value.
     * Returns null when the value cannot be ordered.
     */
    fun metric(code: Int, value: Long, options: LongArray): Double? = when (code) {
        PropCode.ISO -> {
            var index = -1
            for (i in options.indices) {
                if (options[i] == value) {
                    index = i
                    break
                }
            }
            if (index < 0) null else index.toDouble()
        }
        PropCode.SHUTTER -> {
            val denominator = shutterDenominator(value)
            if (value == 0L || value == 0xFFFFFFFFL || denominator == 0) {
                null
            } else {
                -shutterNumerator(value).toDouble() / denominator.toDouble()
            }
        }
        else -> value.toDouble()
    }

    /**
     * Sign to hand to 0x9207 to move from `current` toward `target`, or 0 when
     * the move cannot be ordered. The camera's own key map is directional only
     * (CtrlCode2InputKey), so a sign is the most a client can express.
     */
    fun notchDirection(code: Int, current: Long, target: Long, options: LongArray): Int {
        val from = metric(code, current, options) ?: return 0
        val to = metric(code, target, options) ?: return 0
        if (to == from) return 0
        return if (to > from) 1 else -1
    }

    /**
     * The proven client's fallback option lists, used when the 0x9209
     * descriptor is a *range* (form 1, empty options) - which is the case for
     * shutter and aperture. These are the same arrays as
     * `sony_ptp.dart:124-198`; they are used only to decide a direction, never
     * to claim a camera-advertised value.
     */
    val fallbackApertures: LongArray = longArrayOf(
        100, 110, 120, 140, 160, 180, 200, 220, 250, 280, 320, 350, 400, 450,
        500, 560, 630, 710, 800, 900, 1000, 1100, 1300, 1400, 1600, 1800,
        2000, 2200
    ).map { it.toLong() }.toLongArray()

    val fallbackShutters: LongArray = run {
        val denominators = intArrayOf(
            3, 4, 5, 6, 8, 10, 13, 15, 20, 25, 30, 40, 45, 50, 60, 80, 90, 100,
            125, 160, 180, 200, 250, 320, 350, 400, 500, 640, 725, 800, 1000,
            1250, 1500, 1600, 2000, 2500, 3000, 3200, 4000
        )
        val whole = intArrayOf(1, 2, 4, 5, 6, 8, 10, 13, 15, 20, 25, 30)
        val values = LongArray(denominators.size + whole.size)
        var at = 0
        for (d in denominators) {
            values[at] = shutter(1, d)
            at += 1
        }
        for (n in whole) {
            values[at] = shutter(n, 1)
            at += 1
        }
        values
    }

    fun fallbackOptions(code: Int): LongArray = when (code) {
        PropCode.SHUTTER -> fallbackShutters
        PropCode.APERTURE -> fallbackApertures
        else -> LongArray(0)
    }
}

/**
 * The Sony control surface over one [PtpTransport].
 *
 * The handshake and every opcode here are transcribed from physical evidence
 * (CONTROL_IPC.md 0-2.4, sony_ptp.dart:239-283). Nothing in this class is a
 * guess: if an operation has no evidence, it is not here.
 */
class PtpSony(private val transport: PtpTransport, private val log: LogSink) {

    private val parser = SonyPropertyParser()

    private var properties: Map<Int, PtpProperty> = emptyMap()

    /** Last parsed 0x9209 property set, empty until [refresh] succeeds. */
    fun currentProperties(): Map<Int, PtpProperty> = properties

    /**
     * The exact PC Remote handshake:
     *
     * ```
     * OpenSession(0x1002)[1]        accept 0x2001 or 0x201E
     * 0x9201 [1,0,0]                SDIOConnect phase 1
     * 0x9201 [2,0,0]                SDIOConnect phase 2
     * 0x9202 [0xC8]                 GetSDIOExtDeviceInfo
     * 0x9201 [3,0,0]                SDIOConnect phase 3
     * ```
     */
    fun handshake(sessionId: Int = 1) {
        val open = transport.transact(PtpOpcode.OPEN_SESSION, intArrayOf(sessionId))
        if (open.response != PtpResponse.OK && open.response != PtpResponse.SESSION_ALREADY_OPEN) {
            throw UsbTransportException(
                "OpenSession(0x1002) rejected: ${PtpHex.h16(open.response)} ${PtpResponse.name(open.response)}"
            )
        }
        log.log("sony: OpenSession($sessionId) -> ${PtpResponse.name(open.response)}")
        requireOk("SDIOConnect phase 1", transport.transact(SonyOpcode.SDIO_CONNECT, intArrayOf(1, 0, 0)))
        log.log("sony: SDIOConnect phase 1 ok")
        requireOk("SDIOConnect phase 2", transport.transact(SonyOpcode.SDIO_CONNECT, intArrayOf(2, 0, 0)))
        log.log("sony: SDIOConnect phase 2 ok")
        val info = transport.transact(SonyOpcode.GET_SDIO_EXT_DEVICE_INFO, intArrayOf(0xC8))
        requireOk("GetSDIOExtDeviceInfo(0xC8)", info)
        log.log("sony: 0x9202[0xC8] ok (${info.data?.size ?: 0} B capability blob)")
        requireOk("SDIOConnect phase 3", transport.transact(SonyOpcode.SDIO_CONNECT, intArrayOf(3, 0, 0)))
        log.log("sony: SDIOConnect phase 3 ok - handshake complete")
    }

    /**
     * Reads and parses the full 1730-byte property descriptor.
     *
     * This is the ONLY authoritative readback. It is one transaction, so it is
     * cheap enough to run after every notch (measured ~10.2 ms per PTP fetch,
     * p8-status2.json:898).
     */
    fun refresh(timeoutMs: Int = 3000): Map<Int, PtpProperty> {
        val reply = transport.transact(SonyOpcode.GET_DEVICE_PROPERTIES, IntArray(0), null, timeoutMs)
        val blob = reply.requireOk("0x9209 property read")
        val parsed = parser.parse(blob)
        properties = parsed
        val shutter = labelOrAbsent(parsed, PropCode.SHUTTER)
        val aperture = labelOrAbsent(parsed, PropCode.APERTURE)
        val iso = labelOrAbsent(parsed, PropCode.ISO)
        val ev = labelOrAbsent(parsed, PropCode.EV)
        log.log(
            "sony: 0x9209 -> ${blob.size} B, ${parsed.size} properties " +
                "(shutter=$shutter, aperture=$aperture, iso=$iso, ev=$ev)"
        )
        return parsed
    }

    private fun labelOrAbsent(parsed: Map<Int, PtpProperty>, code: Int): String {
        val property = parsed[code] ?: return "absent"
        return SonyValue.label(code, property.current)
    }

    fun property(code: Int): PtpProperty? = properties[code]

    fun currentValue(code: Int): Long? = properties[code]?.current

    /** Options advertised by the camera, or the proven fallback list for range descriptors. */
    fun optionsFor(code: Int): LongArray {
        val property = properties[code]
        if (property != null && property.options.isNotEmpty()) return property.options
        return SonyValue.fallbackOptions(code)
    }

    /**
     * Sends one signed notch for [code] and returns the camera's response.
     *
     * `direction` is encoded as a single signed byte in the data phase: -1 =
     * 0xFF, +1 = 0x01. That is byte-for-byte what the proven Android and Python
     * clients send (sony_ptp.dart:391-393). A 0x2001 response proves the notch
     * was accepted; it does not by itself prove the value moved, so callers must
     * re-read 0x9209.
     */
    fun stepNotch(code: Int, direction: Int): Int {
        if (direction != 1 && direction != -1) {
            throw IllegalArgumentException("notch direction must be +1 or -1, got $direction")
        }
        val payload = byteArrayOf(direction.toByte())
        val reply = transport.transact(
            SonyOpcode.SET_CONTROL_DEVICE_B,
            intArrayOf(code),
            payload
        )
        if (!reply.ok) {
            throw UsbTransportException(
                "0x9207[${PtpHex.h16(code)}] notch $direction rejected: " +
                    "${PtpHex.h16(reply.response)} ${PtpResponse.name(reply.response)}"
            )
        }
        log.log("sony: 0x9207[${PtpHex.h16(code)}] notch ${if (direction > 0) "+1" else "-1"} -> OK")
        return reply.response
    }

    /**
     * Absolute write (0x9205). KNOWN NOT EFFECTIVE for shutter/aperture/EV/ISO.
     *
     * Kept because it is part of the evidenced surface and because the ACK is a
     * useful protocol probe, but the UI must never present it as a setting
     * change: the camera's handler turns these codes into directional UI keys,
     * so `apply` may be acknowledged and do nothing. Always read back 0x9209.
     */
    fun setAbsolute(code: Int, value: Long): Int {
        val property = properties[code]
            ?: throw UsbTransportException("0x9205[${PtpHex.h16(code)}]: property not in the cached 0x9209 set")
        val size = property.datatypeBytes
        if (size == 0) {
            throw UsbTransportException(
                "0x9205[${PtpHex.h16(code)}]: datatype ${property.datatype} is not an integer"
            )
        }
        if (size > 8) {
            throw UsbTransportException(
                "0x9205[${PtpHex.h16(code)}]: datatype ${property.datatype} is wider than 8 bytes"
            )
        }
        val payload = ByteArray(size)
        for (i in 0 until size) {
            payload[i] = ((value shr (8 * i)) and 0xFFL).toByte()
        }
        val reply = transport.transact(SonyOpcode.SET_CONTROL_DEVICE_A, intArrayOf(code), payload)
        if (!reply.ok) {
            throw UsbTransportException(
                "0x9205[${PtpHex.h16(code)}] rejected: ${PtpHex.h16(reply.response)} ${PtpResponse.name(reply.response)}"
            )
        }
        log.log(
            "sony: 0x9205[${PtpHex.h16(code)}] = $value acknowledged - " +
                "NOT proof of effect (absolute writes are mapped to UI keys)"
        )
        return reply.response
    }

    /**
     * Steps toward [target] one notch at a time, verifying each step with a
     * fresh 0x9209 read. Returns the value the camera reports at the end, which
     * may differ from [target] when the lens/mode clamps the range.
     *
     * This is the same algorithm as the proven client's `apply()`
     * (sony_ptp.dart:380-418) with the client-side 200 ms settle removed: the
     * camera does not require it, and it was pure added latency (USB_GADGET.md
     * 5.3).
     */
    fun stepToward(code: Int, target: Long, maxSteps: Int = 24, perStepTimeoutMs: Int = 900): Long {
        var steps = 0
        var current = refresh(perStepTimeoutMs)[code]?.current
            ?: throw UsbTransportException("property ${PtpHex.h16(code)} absent from 0x9209")
        while (current != target) {
            if (steps >= maxSteps) {
                log.log("sony: ${PtpHex.h16(code)} stopped after $maxSteps notches at ${SonyValue.label(code, current)}")
                return current
            }
            val options = optionsFor(code)
            val direction = SonyValue.notchDirection(code, current, target, options)
            if (direction == 0) {
                log.log("sony: ${PtpHex.h16(code)} cannot order ${SonyValue.label(code, current)} vs ${SonyValue.label(code, target)}")
                return current
            }
            stepNotch(code, direction)
            steps += 1
            val before = current
            var moved = false
            val deadline = System.nanoTime() + perStepTimeoutMs * 1_000_000L
            while (System.nanoTime() < deadline) {
                current = refresh(perStepTimeoutMs)[code]?.current ?: before
                if (current != before) {
                    moved = true
                    break
                }
                try {
                    Thread.sleep(15L)
                } catch (e: InterruptedException) {
                    Thread.currentThread().interrupt()
                    return current
                }
            }
            if (!moved) {
                log.log("sony: ${PtpHex.h16(code)} did not move from ${SonyValue.label(code, current)} (mode or lens limit)")
                return current
            }
        }
        return current
    }

    /** CloseSession 0x1003. Teardown only; never a control. */
    fun closeSession() {
        try {
            val reply = transport.transact(PtpOpcode.CLOSE_SESSION, IntArray(0), null, 1500)
            log.log("sony: CloseSession(0x1003) -> ${PtpResponse.name(reply.response)}")
        } catch (e: Exception) {
            log.log("sony: CloseSession failed: ${e.javaClass.simpleName}: ${e.message}")
        }
    }

    private fun requireOk(what: String, reply: PtpTransport.Reply) {
        if (!reply.ok) {
            throw UsbTransportException(
                "$what rejected: ${PtpHex.h16(reply.response)} ${PtpResponse.name(reply.response)}"
            )
        }
    }
}
