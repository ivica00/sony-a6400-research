"""Bounded a6400A inquiry/model-info probe over the existing Windows USBSTOR driver.

No service mode, updater initialization, driver changes, raw-sector commands or
arbitrary SCSI requests. Device association is checked before opening any handle.
"""
from __future__ import annotations

import argparse
import ctypes as c
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import struct
import subprocess
import time

from tools.camera_debugger import host_lock

ROOT = Path(__file__).resolve().parents[2]
INQUIRY_CDB = b"\x12\0\0\0\x24\0"
MODEL_CDB = b"\x7a\x01" + bytes(10)
MODEL_REQUEST = struct.pack("<IHH8x", 0, 1, 0).ljust(8192, b"\0")
IOCTL_SCSI_PASS_THROUGH_DIRECT = 0x4D014
IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x2D1080


class SonyBusy(RuntimeError):
    """Sony's explicit device-busy sense, not a generic SCSI failure."""


DISCOVER = r"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$cameras=@(Get-CimInstance -ClassName Win32_PnPEntity -Filter "PNPDeviceID LIKE 'USB%VID_054C&PID_0F0F%'" |
  Where-Object { $_.Present -ne $false })
if ($cameras.Count -ne 1 -or $cameras[0].Service -ne 'USBSTOR' -or
    $cameras[0].Status -ne 'OK' -or $cameras[0].ConfigManagerErrorCode -ne 0) {
  throw 'Expected exactly one healthy a6400A USBSTOR camera.'
}
$rows=@()
foreach ($disk in @(Get-CimInstance -ClassName Win32_DiskDrive -Filter "InterfaceType='USB'")) {
  $id=$disk.PNPDeviceID
  $lun=$null
  if ($id -match '&([0-9]+)$') { $lun=[int]$Matches[1] }
  for ($depth=0; $depth -lt 16 -and $id; $depth++) {
    if ($id -eq $cameras[0].PNPDeviceID) {
      $rows += [ordered]@{
        disk_index=[int]$disk.Index; model=$disk.Model; lun=$lun
        parent_identity_verified=$true; parent_depth=$depth
      }
      break
    }
    $property=Get-PnpDeviceProperty -InstanceId $id -KeyName DEVPKEY_Device_Parent
    $id=[string]$property.Data
  }
}
[ordered]@{
  usb_pair='054c:0f0f'; service=$cameras[0].Service; status=$cameras[0].Status
  config_error=[int]$cameras[0].ConfigManagerErrorCode; camera_count=$cameras.Count
  disks=$rows; instance_serials_retained=$false
} | ConvertTo-Json -Depth 4 -Compress
"""


def discover() -> dict:
    if os.name != "nt":
        raise RuntimeError("The native metadata/transport probe requires Windows")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", DISCOVER],
        capture_output=True, timeout=45, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Windows PnP discovery failed (exit {result.returncode}); no device opened")
    return json.loads(result.stdout.decode("utf-8-sig"))


def select_target(metadata: dict) -> int:
    if not isinstance(metadata, dict):
        raise ValueError("Malformed camera metadata")
    if (metadata.get("usb_pair") != "054c:0f0f" or metadata.get("service") != "USBSTOR"
            or metadata.get("status") != "OK" or metadata.get("config_error") != 0
            or metadata.get("camera_count") != 1):
        raise ValueError("Camera identity/driver/status admission failed")
    disks = metadata.get("disks")
    if not isinstance(disks, list) or any(not isinstance(row, dict) for row in disks):
        raise ValueError("Malformed camera disk metadata")
    candidates = [row for row in disks
                  if row.get("lun") == 0 and row.get("parent_identity_verified") is True
                  and row.get("model") == "Sony DSC USB Device"]
    if len(candidates) != 1:
        raise ValueError("Expected one parent-verified camera LUN 0, not a guessed disk")
    index = candidates[0]["disk_index"]
    if type(index) is not int or not 0 <= index <= 255:
        raise ValueError("Invalid parent-verified physical disk index")
    return index


def admit_request(command: bytes, data_out: bytes | None, read_size: int) -> str:
    if command == INQUIRY_CDB and data_out is None and read_size == 36:
        return "scsi_inquiry"
    if command == MODEL_CDB:
        if data_out == MODEL_REQUEST and read_size == 0:
            return "sony_get_model_info_request"
        if data_out is None and read_size == 8192:
            return "sony_get_model_info_response"
    raise ValueError("SCSI request is outside the inquiry/model-info allowlist")


def parse_inquiry(raw: bytes) -> dict:
    if len(raw) != 36 or raw[4] + 5 < 36:
        raise ValueError("Short or malformed SCSI inquiry")
    vendor = raw[8:16].decode("ascii").rstrip(" \0")
    product = raw[16:32].decode("ascii").rstrip(" \0")
    if vendor != "Sony" or product != "DSC":
        raise ValueError("SCSI inquiry does not identify a Sony DSC camera")
    return {"vendor": vendor, "product": product,
            "revision": raw[32:36].decode("ascii").rstrip(" \0")}


def parse_model_info(raw: bytes) -> dict:
    if len(raw) < 16:
        raise ValueError("Short Sony external-command header")
    size, command, direction = struct.unpack_from("<IHH", raw)
    if command != 1 or direction != 1:
        raise ValueError("Unexpected model-info response command/direction")
    if not 13 <= size <= 8192 - 16 or size + 16 > len(raw):
        raise ValueError("Invalid Sony model-info payload extent")
    payload = raw[16:16 + size]
    plist_size = struct.unpack_from("<I", payload)[0]
    offset = 4 + plist_size + 4
    if offset >= len(payload):
        raise ValueError("Truncated model-info metadata")
    model_size = payload[offset]
    offset += 1
    if not model_size or offset + model_size + 5 + 4 > len(payload):
        raise ValueError("Truncated model-info identity")
    model = payload[offset:offset + model_size].decode("ascii")
    if model != "ILCE-6400A":
        raise ValueError("Model identity mismatch in model-info response")
    offset += model_size
    return {"model": model, "product_code_wire_hex": payload[offset:offset + 5].hex(),
            "response_bytes": len(raw), "payload_bytes": size,
            "reply_command": command, "reply_direction": direction,
            "serial_retained": False, "property_list_retained": False}


def read_model_info(transport, *, deadline=None) -> dict:
    if deadline is None:
        deadline = time.monotonic() + 8
    for attempt in range(40):
        if time.monotonic() >= deadline:
            raise TimeoutError("Sony model-info remained busy for the bounded read window")
        try:
            return parse_model_info(transport.exchange(MODEL_CDB, read_size=8192))
        except SonyBusy as error:
            if attempt == 39:
                raise TimeoutError("Sony model-info remained busy for 40 read attempts") from error
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))
    raise AssertionError("Unreachable model-info read state")


def probe_identity(transport, *, model_info=False, result=None) -> dict:
    if result is None:
        result = {}
    result["inquiry"] = parse_inquiry(transport.exchange(INQUIRY_CDB, read_size=36))
    if model_info:
        started = time.monotonic()
        timing = {"started_utc": datetime.now(timezone.utc).isoformat(),
                  "transaction_budget_seconds": 8, "status": "not_completed"}
        result["model_transaction"] = timing
        try:
            transport.exchange(MODEL_CDB, data_out=MODEL_REQUEST)
            timing["request_ack_elapsed_seconds"] = round(time.monotonic() - started, 6)
            result["model_info"] = read_model_info(transport, deadline=started + 8)
            timing["status"] = "model_reply_received"
        finally:
            timing["ended_utc"] = datetime.now(timezone.utc).isoformat()
            timing["elapsed_seconds"] = round(time.monotonic() - started, 6)
    return result


class ScsiPassThrough(c.Structure):
    _fields_ = [
        ("Length", c.c_uint16), ("ScsiStatus", c.c_uint8),
        ("PathId", c.c_uint8), ("TargetId", c.c_uint8), ("Lun", c.c_uint8),
        ("CdbLength", c.c_uint8), ("SenseInfoLength", c.c_uint8),
        ("DataIn", c.c_uint8), ("DataTransferLength", c.c_uint32),
        ("TimeOutValue", c.c_uint32), ("DataBuffer", c.c_void_p),
        ("SenseInfoOffset", c.c_uint32), ("Cdb", c.c_uint8 * 16),
    ]


class ScsiPacket(c.Structure):
    _fields_ = [("sptd", ScsiPassThrough), ("filler", c.c_uint32), ("sense", c.c_uint8 * 32)]


class NativeTransport:
    def __init__(self, disk_index: int, operations: list):
        if os.name != "nt":
            raise RuntimeError("Windows SCSI transport is not available on this platform")
        from ctypes import wintypes as w
        self.api = c.WinDLL("kernel32", use_last_error=True)
        self.api.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p,
                                        w.DWORD, w.DWORD, w.HANDLE]
        self.api.CreateFileW.restype = w.HANDLE
        self.api.DeviceIoControl.argtypes = [
            w.HANDLE, w.DWORD, c.c_void_p, w.DWORD, c.c_void_p,
            w.DWORD, c.POINTER(w.DWORD), c.c_void_p]
        self.api.DeviceIoControl.restype = w.BOOL
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.api.CloseHandle.restype = w.BOOL
        self.disk_index = disk_index
        self.operations = operations
        self.handle = None

    def __enter__(self):
        self.handle = self.api.CreateFileW(
            rf"\\.\PhysicalDrive{self.disk_index}", 0xC0000000, 3, None, 3, 0, None)
        if self.handle == c.c_void_p(-1).value:
            self.handle = None
            raise c.WinError(c.get_last_error())
        try:
            number = (c.c_uint32 * 3)()
            self._ioctl(IOCTL_STORAGE_GET_DEVICE_NUMBER, None, 0, c.byref(number), c.sizeof(number))
            if number[1] != self.disk_index:
                raise ValueError("Opened storage object does not match the admitted disk")
        except (OSError, ValueError):
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            if not self.api.CloseHandle(handle):
                raise c.WinError(c.get_last_error())

    def _ioctl(self, code, input_buffer, input_size, output_buffer, output_size):
        returned = c.c_uint32()
        if not self.api.DeviceIoControl(self.handle, code, input_buffer, input_size,
                                         output_buffer, output_size, c.byref(returned), None):
            raise c.WinError(c.get_last_error())
        return returned.value

    def exchange(self, command, *, data_out=None, read_size=0):
        operation = admit_request(command, data_out, read_size)
        if self.handle is None:
            raise RuntimeError("Native transport is not open")
        size = len(data_out) if data_out is not None else read_size
        storage = c.create_string_buffer(size + 4095)
        address = (c.addressof(storage) + 4095) & ~4095
        if data_out is not None:
            c.memmove(address, data_out, size)
        packet = ScsiPacket()
        packet.sptd.Length = c.sizeof(ScsiPassThrough)
        packet.sptd.CdbLength = len(command)
        packet.sptd.SenseInfoLength = 32
        packet.sptd.SenseInfoOffset = ScsiPacket.sense.offset
        packet.sptd.DataIn = 0 if data_out is not None else 1
        packet.sptd.DataTransferLength = size
        packet.sptd.TimeOutValue = 5
        packet.sptd.DataBuffer = address
        packet.sptd.Cdb = (c.c_uint8 * 16).from_buffer_copy(command.ljust(16, b"\0"))
        row = {"operation": operation, "cdb_hex": command.hex(),
               "direction": "out" if data_out is not None else "in", "requested_bytes": size}
        self.operations.append(row)
        self._ioctl(IOCTL_SCSI_PASS_THROUGH_DIRECT, c.byref(packet), c.sizeof(packet),
                    c.byref(packet), c.sizeof(packet))
        sense = bytes(packet.sense)
        row.update(scsi_status=packet.sptd.ScsiStatus,
                   sense=[sense[2] & 15, sense[12], sense[13]],
                   transferred_bytes=packet.sptd.DataTransferLength)
        if packet.sptd.ScsiStatus:
            if packet.sptd.ScsiStatus == 2 and row["sense"] == [9, 129, 129]:
                if data_out is None and packet.sptd.DataTransferLength:
                    raise ValueError("Sony BUSY response contains partial data; no retry")
                row["sony_busy"] = True
                raise SonyBusy("Sony device-busy; the request is not resubmitted")
            raise RuntimeError(f"SCSI command failed: status {row['scsi_status']}, sense {row['sense']}; no retry")
        if packet.sptd.DataTransferLength != size:
            raise ValueError("Short native SCSI transfer; no retry")
        return b"" if data_out is not None else c.string_at(address, size)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inquiry", action="store_true", help="Issue one allowlisted SCSI inquiry")
    parser.add_argument("--model-info", action="store_true", help="Also request Sony model info (feature 1/subcommand 1)")
    parser.add_argument("--finish-model-info", type=Path,
                        help=argparse.SUPPRESS)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.finish_model_info:
        parser.error("Delayed continuation is refused: replies expire; no device discovery or I/O attempted")
    if args.model_info and not args.inquiry:
        parser.error("--model-info requires --inquiry")
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / "artifacts"):
        parser.error("Receipts must remain under artifacts")
    out.mkdir(parents=True, exist_ok=False)
    report = {"scope": "Native Windows inquiry/model info only; not filesystem or root access",
              "status": "in_progress", "operations": [], "mode_switches": False,
              "updater_initialization": False, "driver_changes": False,
              "sector_io": False, "camera_file_writes": False, "serials_retained": False}
    try:
        with host_lock():
            report["metadata"] = discover()
            index = select_target(report["metadata"])
            report["selected_disk_index"] = index
            if args.inquiry:
                with NativeTransport(index, report["operations"]) as transport:
                    report["result"] = {}
                    probe_identity(transport, model_info=args.model_info, result=report["result"])
            report["status"] = "passed" if args.inquiry else "metadata_only"
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        report.update(status="blocked", error_type=type(error).__name__, error=str(error),
                      winerror=getattr(error, "winerror", None))
    (out / "receipt.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
