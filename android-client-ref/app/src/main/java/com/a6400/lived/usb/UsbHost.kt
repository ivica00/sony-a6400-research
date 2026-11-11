package com.a6400.lived.usb

import android.app.PendingIntent
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager

/** A host-side USB problem with a message fit for the log pane. */
class UsbHostException(message: String) : Exception(message)

/**
 * USB discovery, permission and interface claiming.
 *
 * Discovery is by VENDOR ID plus the two documented product ids; the interface
 * to claim is found by CLASS (6 = still image / PTP), never by interface index
 * and never by hardcoded endpoint number. Endpoint addresses are resolved from
 * descriptors and then *compared* with the documented values, logging any
 * mismatch, because the documented values are evidence (E0315:10-14 for PTP,
 * E0339 for the composite) and a mismatch is worth seeing in the log.
 *
 * Claiming always uses `force = true` (as the proven client does,
 * MainActivity.kt:99): on Android that detaches any kernel driver bound to the
 * interface, which is what makes a raw PTP claim possible at all.
 */
class UsbHost(private val manager: UsbManager) {

    /** A Sony device that could serve one of the two transports. */
    class Camera(
        val device: UsbDevice,
        val hasPtp: Boolean,
        val hasUvc: Boolean,
        val label: String
    ) {
        val productId: Int get() = device.productId
        val vendorId: Int get() = device.vendorId
    }

    /** Result of [openPtp]: the claimed interface and the resolved endpoints. */
    class PtpClaim(
        val device: UsbDevice,
        val connection: UsbDeviceConnection,
        val usbInterface: UsbInterface,
        val bulkIn: UsbEndpoint,
        val bulkOut: UsbEndpoint,
        val interruptIn: UsbEndpoint?,
        val diagnostics: String
    )

    /** Result of [openUvc]: claimed VC + the VS alternate setting carrying the bulk IN. */
    class UvcClaim(
        val device: UsbDevice,
        val connection: UsbDeviceConnection,
        val videoControl: UsbInterface?,
        val videoStreaming: UsbInterface,
        val bulkIn: UsbEndpoint,
        val diagnostics: String
    )

    /**
     * Every Sony camera currently enumerated, with the transports it could
     * serve. Devices of the right vendor but an undocumented product id are
     * logged and skipped rather than guessed at.
     */
    fun enumerate(log: LogSink): List<Camera> {
        val cameras = ArrayList<Camera>(2)
        for (device in manager.deviceList.values) {
            if (device.vendorId != SONY_VENDOR_ID) continue
            if (device.productId != PID_PC_REMOTE && device.productId != PID_COMPOSITE_UVC_PTP) {
                log.log(
                    "usb: ignoring Sony device ${PtpHex.h16(device.vendorId)}:" +
                        PtpHex.h16(device.productId) + " (undocumented product id)"
                )
                continue
            }
            var ptp = false
            var uvc = false
            for (index in 0 until device.interfaceCount) {
                val iface = device.getInterface(index)
                if (iface.interfaceClass == PTP_INTERFACE_CLASS) ptp = true
                if (iface.interfaceClass == UVC_INTERFACE_CLASS) uvc = true
            }
            val label = when (device.productId) {
                PID_PC_REMOTE -> "ILCE-6400 PC Remote (PTP)"
                PID_COMPOSITE_UVC_PTP -> "Sony composite UVC+PTP (transport B, UNVERIFIED)"
                else -> "Sony USB device"
            }
            cameras.add(Camera(device, ptp, uvc, label))
        }
        return cameras
    }

    /** The camera to use for transport A: the single-function PTP device wins over the composite. */
    fun findPtp(log: LogSink): Camera? {
        val cameras = enumerate(log)
        val single = cameras.firstOrNull { it.hasPtp && it.productId == PID_PC_REMOTE }
        if (single != null) return single
        val composite = cameras.firstOrNull { it.hasPtp }
        if (composite != null) {
            log.log(
                "usb: no 0x0CAA device; using the composite PTP child on PID " +
                    PtpHex.h16(composite.productId) + " (unverified path, interface 0)"
            )
        }
        return composite
    }

    /** The camera to use for transport B - requires the composite device. */
    fun findUvc(log: LogSink): Camera? =
        enumerate(log).firstOrNull { it.hasUvc && it.productId == PID_COMPOSITE_UVC_PTP }

    fun hasPermission(device: UsbDevice): Boolean = manager.hasPermission(device)

    fun requestPermission(device: UsbDevice, intent: PendingIntent): Boolean =
        manager.requestPermission(device, intent)

    /**
     * Opens and claims the PTP function.
     *
     * `force = true` detaches a bound kernel driver. The interface is located by
     * class 6 (echoing MainActivity.kt:95-99) and the endpoints by descriptor
     * direction/type, then validated against the documented 0x02/0x81/0x83.
     */
    fun openPtp(camera: Camera, log: LogSink): PtpClaim {
        val device = camera.device
        var ptpInterface: UsbInterface? = null
        for (index in 0 until device.interfaceCount) {
            val iface = device.getInterface(index)
            if (iface.interfaceClass == PTP_INTERFACE_CLASS) {
                ptpInterface = iface
                break
            }
        }
        val usbInterface = ptpInterface
            ?: throw UsbHostException(
                "no interface with class 6 on ${PtpHex.h16(device.vendorId)}:${PtpHex.h16(device.productId)}"
            )

        var bulkIn: UsbEndpoint? = null
        var bulkOut: UsbEndpoint? = null
        var interruptIn: UsbEndpoint? = null
        for (index in 0 until usbInterface.endpointCount) {
            val endpoint = usbInterface.getEndpoint(index)
            val isBulk = endpoint.type == UsbConstants.USB_ENDPOINT_XFER_BULK
            val isInterrupt = endpoint.type == UsbConstants.USB_ENDPOINT_XFER_INT
            when {
                isBulk && endpoint.direction == UsbConstants.USB_DIR_IN && bulkIn == null -> bulkIn = endpoint
                isBulk && endpoint.direction == UsbConstants.USB_DIR_OUT && bulkOut == null -> bulkOut = endpoint
                isInterrupt && endpoint.direction == UsbConstants.USB_DIR_IN && interruptIn == null -> interruptIn = endpoint
            }
        }
        val inEndpoint = bulkIn
            ?: throw UsbHostException("PTP interface ${usbInterface.id} has no bulk IN endpoint")
        val outEndpoint = bulkOut
            ?: throw UsbHostException("PTP interface ${usbInterface.id} has no bulk OUT endpoint")

        val notes = StringBuilder()
        if (inEndpoint.address != DOCUMENTED_BULK_IN) {
            notes.append(" bulk-in=0x").append(addr(inEndpoint.address)).append(" (documented 0x81)")
        }
        if (outEndpoint.address != DOCUMENTED_BULK_OUT) {
            notes.append(" bulk-out=0x").append(addr(outEndpoint.address)).append(" (documented 0x02)")
        }
        if (interruptIn == null) {
            notes.append(" no interrupt IN endpoint (documented 0x83)")
        } else if (interruptIn.address != DOCUMENTED_INTERRUPT_IN) {
            notes.append(" interrupt-in=0x").append(addr(interruptIn.address)).append(" (documented 0x83)")
        }

        val connection = manager.openDevice(device)
            ?: throw UsbHostException("UsbManager.openDevice returned null (permission or power problem)")
        if (!connection.claimInterface(usbInterface, true)) {
            try {
                connection.close()
            } catch (e: Exception) {
                log.log("usb: close after failed claim threw ${e.javaClass.simpleName}")
            }
            throw UsbHostException(
                "claimInterface(interface ${usbInterface.id}, force=true) failed - " +
                    "another process may own the PTP function"
            )
        }
        val diagnostics = buildString {
            append("vid=").append(PtpHex.h16(device.vendorId))
            append(" pid=").append(PtpHex.h16(device.productId))
            append(" name=").append(device.deviceName)
            append(" interfaces=").append(device.interfaceCount)
            append(" ptp-if=").append(usbInterface.id)
            append("/alt=").append(usbInterface.alternateSetting)
            append(" class=").append(usbInterface.interfaceClass)
            append("/").append(usbInterface.interfaceSubclass)
            append("/").append(usbInterface.interfaceProtocol)
            append(" bulk-in=0x").append(addr(inEndpoint.address))
            append("(").append(inEndpoint.maxPacketSize).append("B)")
            append(" bulk-out=0x").append(addr(outEndpoint.address))
            append("(").append(outEndpoint.maxPacketSize).append("B)")
            append(" interrupt-in=")
            append(if (interruptIn == null) "none" else "0x" + addr(interruptIn!!.address))
            if (notes.isNotEmpty()) append(" MISMATCH:").append(notes)
        }
        log.log("usb: claimed PTP function: $diagnostics")
        return PtpClaim(device, connection, usbInterface, inEndpoint, outEndpoint, interruptIn, diagnostics)
    }

    /**
     * Opens and claims the UVC function of the composite device.
     *
     * The video-streaming alternate setting that carries the bulk IN endpoint
     * (documented 0x84) is chosen from the interface list, then activated with
     * SET_INTERFACE. The class-specific frame descriptors are parsed by
     * [UvcTransport] from `device.rawDescriptors`.
     */
    fun openUvc(camera: Camera, log: LogSink): UvcClaim {
        val device = camera.device
        var videoControl: UsbInterface? = null
        var streaming: UsbInterface? = null
        var streamingEndpoint: UsbEndpoint? = null
        var fallbackStreaming: UsbInterface? = null
        var fallbackEndpoint: UsbEndpoint? = null

        for (index in 0 until device.interfaceCount) {
            val iface = device.getInterface(index)
            if (iface.interfaceClass != UVC_INTERFACE_CLASS) continue
            if (iface.interfaceSubclass == UVC_SUBCLASS_VIDEOCONTROL && videoControl == null) {
                videoControl = iface
                continue
            }
            if (iface.interfaceSubclass != UVC_SUBCLASS_VIDEOSTREAMING) continue
            for (endpointIndex in 0 until iface.endpointCount) {
                val endpoint = iface.getEndpoint(endpointIndex)
                if (endpoint.type != UsbConstants.USB_ENDPOINT_XFER_BULK) continue
                if (endpoint.direction != UsbConstants.USB_DIR_IN) continue
                if (endpoint.address == DOCUMENTED_UVC_BULK_IN) {
                    streaming = iface
                    streamingEndpoint = endpoint
                } else if (fallbackStreaming == null) {
                    fallbackStreaming = iface
                    fallbackEndpoint = endpoint
                }
            }
            if (streaming != null) break
        }
        if (streaming == null) {
            streaming = fallbackStreaming
            streamingEndpoint = fallbackEndpoint
        }
        val videoStreaming = streaming
            ?: throw UsbHostException(
                "no UVC video-streaming interface with a bulk IN endpoint on PID " +
                    PtpHex.h16(device.productId)
            )
        val bulkIn = streamingEndpoint
            ?: throw UsbHostException("UVC streaming interface ${videoStreaming.id} has no bulk IN endpoint")
        if (bulkIn.address != DOCUMENTED_UVC_BULK_IN) {
            log.log(
                "usb: UVC bulk IN is 0x" + addr(bulkIn.address) + " (documented 0x" +
                    addr(DOCUMENTED_UVC_BULK_IN) + ")"
            )
        }

        val connection = manager.openDevice(device)
            ?: throw UsbHostException("UsbManager.openDevice returned null (permission or power problem)")
        val claimed = ArrayList<UsbInterface>(2)
        val control = videoControl
        if (control != null) {
            if (connection.claimInterface(control, true)) {
                claimed.add(control)
            } else {
                log.log("usb: could not claim UVC video-control interface ${control.id} (continuing)")
            }
        }
        if (!connection.claimInterface(videoStreaming, true)) {
            releaseInterfaces(connection, claimed, log)
            try {
                connection.close()
            } catch (e: Exception) {
                log.log("usb: close after failed claim threw ${e.javaClass.simpleName}")
            }
            throw UsbHostException(
                "claimInterface(UVC streaming ${videoStreaming.id}/alt ${videoStreaming.alternateSetting}) failed"
            )
        }
        claimed.add(videoStreaming)
        if (!connection.setInterface(videoStreaming)) {
            releaseInterfaces(connection, claimed, log)
            try {
                connection.close()
            } catch (e: Exception) {
                log.log("usb: close after failed setInterface threw ${e.javaClass.simpleName}")
            }
            throw UsbHostException(
                "SET_INTERFACE to alternate setting ${videoStreaming.alternateSetting} was rejected"
            )
        }
        val diagnostics = buildString {
            append("vid=").append(PtpHex.h16(device.vendorId))
            append(" pid=").append(PtpHex.h16(device.productId))
            append(" vc-if=").append(control?.id ?: -1)
            append(" vs-if=").append(videoStreaming.id)
            append("/alt=").append(videoStreaming.alternateSetting)
            append(" bulk-in=0x").append(addr(bulkIn.address))
            append("(").append(bulkIn.maxPacketSize).append("B)")
            append(" raw-descriptors=").append(device.rawDescriptors.size).append("B")
        }
        log.log("usb: claimed UVC function: $diagnostics")
        return UvcClaim(device, connection, control, videoStreaming, bulkIn, diagnostics)
    }

    /** Releases every claimed interface and closes the connection. Never throws. */
    fun release(claim: Any?, log: LogSink) {
        when (claim) {
            is PtpClaim -> {
                releaseInterfaces(claim.connection, listOf(claim.usbInterface), log)
                closeQuietly(claim.connection, log)
            }
            is UvcClaim -> {
                val interfaces = ArrayList<UsbInterface>(2)
                val control = claim.videoControl
                if (control != null) interfaces.add(control)
                interfaces.add(claim.videoStreaming)
                releaseInterfaces(claim.connection, interfaces, log)
                closeQuietly(claim.connection, log)
            }
            null -> Unit
            else -> log.log("usb: release() got an unknown claim type ${claim.javaClass.simpleName}")
        }
    }

    private fun releaseInterfaces(
        connection: UsbDeviceConnection,
        interfaces: List<UsbInterface>,
        log: LogSink
    ) {
        for (iface in interfaces) {
            try {
                connection.releaseInterface(iface)
            } catch (e: Exception) {
                log.log("usb: releaseInterface(${iface.id}) threw ${e.javaClass.simpleName}: ${e.message}")
            }
        }
    }

    private fun closeQuietly(connection: UsbDeviceConnection, log: LogSink) {
        try {
            connection.close()
        } catch (e: Exception) {
            log.log("usb: close() threw ${e.javaClass.simpleName}: ${e.message}")
        }
    }

    private fun addr(address: Int): String = String.format(java.util.Locale.US, "%02X", address and 0xFF)

    companion object {
        const val SONY_VENDOR_ID = 0x054C

        /** Single-function PC Remote PTP device - transport A, physically verified. */
        const val PID_PC_REMOTE = 0x0CAA

        /** Composite UVC + PTP device - transport B, never produced a frame. */
        const val PID_COMPOSITE_UVC_PTP = 0x0322

        const val PTP_INTERFACE_CLASS = 6
        const val UVC_INTERFACE_CLASS = 0x0E
        const val UVC_SUBCLASS_VIDEOCONTROL = 1
        const val UVC_SUBCLASS_VIDEOSTREAMING = 2

        /** Documented PTP endpoints (E0315:10-14): bulk OUT, bulk IN, interrupt IN. */
        const val DOCUMENTED_BULK_OUT = 0x02
        const val DOCUMENTED_BULK_IN = 0x81
        const val DOCUMENTED_INTERRUPT_IN = 0x83

        /** Documented UVC bulk IN (E0339 composite capture). */
        const val DOCUMENTED_UVC_BULK_IN = 0x84
    }
}
