"""Read Sony descriptors through Windows hubs while WPD keeps the camera.

Only GET_NODE_INFORMATION, GET_NODE_CONNECTION_INFORMATION_EX and
GET_DESCRIPTOR_FROM_NODE_CONNECTION are issued. No reset/claim/config write.
See Microsoft usbioctl.h documentation for USB_DESCRIPTOR_REQUEST.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]


def parse_configuration(raw):
    if len(raw) < 9 or raw[:2] != b'\x09\x02':
        raise ValueError('Missing configuration header')
    total = struct.unpack_from('<H', raw, 2)[0]
    if total != len(raw):
        raise ValueError('Truncated configuration')
    interfaces = []
    current = None
    offset = 9
    while offset < total:
        length = raw[offset]
        if length < 2 or offset + length > total:
            raise ValueError('Invalid descriptor length')
        item = raw[offset:offset + length]
        if item[1] == 4:
            if length < 9:
                raise ValueError('Short interface')
            current = dict(number=item[2], alternate=item[3],
                           declared_endpoints=item[4], **{'class': item[5]},
                           subclass=item[6], protocol=item[7], endpoints=[])
            interfaces.append(current)
        elif item[1] == 5:
            if length < 7 or current is None:
                raise ValueError('Invalid endpoint')
            current['endpoints'].append(dict(address=hex(item[2]),
                attributes=item[3], max_packet=struct.unpack_from('<H', item, 4)[0],
                interval=item[6]))
        offset += length
    for interface in interfaces:
        if len(interface['endpoints']) != interface['declared_endpoints']:
            raise ValueError('Endpoint count mismatch')
    if len({i['number'] for i in interfaces}) != raw[4]:
        raise ValueError('Interface count mismatch')
    return dict(value=raw[5], interfaces=interfaces, raw_hex=raw.hex())


def capture(include_strings=False):
    sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))
    from pmca.usb.driver.windows import setupapi as api
    from comtypes import GUID
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR,w.DWORD,w.DWORD,c.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.DeviceIoControl.argtypes = [w.HANDLE,w.DWORD,c.c_void_p,w.DWORD,c.c_void_p,w.DWORD,c.POINTER(w.DWORD),c.c_void_p]
    kernel.DeviceIoControl.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL

    def ioctl(handle, code, data, capacity):
        buf = c.create_string_buffer(capacity)
        c.memmove(buf, data, len(data))
        returned = w.DWORD()
        if not kernel.DeviceIoControl(handle, code, buf, len(data), buf, capacity, c.byref(returned), None):
            raise c.WinError(c.get_last_error())
        return buf.raw[:returned.value]

    devices, errors = [], []
    guid = GUID('{F18A0E88-C30C-11D0-8815-00A0C906BED8}')
    for _, (_, paths) in api.listDeviceClass(guid=guid):
        for path in paths:
            handle = kernel.CreateFileW(path, 0, 3, None, 3, 0, None)
            if handle == c.c_void_p(-1).value:
                errors.append({'hub': path, 'error': c.get_last_error()})
                continue
            try:
                node = ioctl(handle, 0x220408, bytes(76), 76)
                if len(node) < 7:
                    raise ValueError('Short hub information')
                for port in range(1, node[6] + 1):
                    try:
                        info = ioctl(handle, 0x220448, struct.pack('<I', port) + bytes(4092), 4096)
                        if len(info) < 22 or info[4:6] != b'\x12\x01':
                            continue
                        vid, pid = struct.unpack_from('<HH', info, 12)
                        if vid != 0x054c:
                            continue
                        def get_descriptor(value, language, length):
                            request=struct.pack('<IBBHHH',port,0x80,6,value,language,length)
                            return ioctl(handle,0x220410,request,12+length)[12:]
                        configs = []
                        for index in range(info[21]):
                            def descriptor(length):
                                return get_descriptor(0x0200 | index,0,length)
                            header = descriptor(9)
                            if len(header) != 9:
                                raise ValueError('Short configuration header')
                            raw = descriptor(struct.unpack_from('<H', header, 2)[0])
                            configs.append(parse_configuration(raw))
                        device=dict(vid=hex(vid), pid=hex(pid), hub=path,
                            port=port, device_descriptor_hex=info[4:22].hex(), configurations=configs)
                        if include_strings:
                            languages=get_descriptor(0x0300,0,255)
                            if len(languages)<4 or languages[0]!=len(languages) or languages[1]!=3 or len(languages)%2:
                                raise ValueError('Invalid language descriptor')
                            ids=list(struct.unpack('<'+'H'*((len(languages)-2)//2),languages[2:]))
                            strings=[]
                            for language in ids:
                                for string_index in sorted(set(info[18:21])-{0}):
                                    value=get_descriptor(0x0300|string_index,language,255)
                                    if len(value)<2 or value[0]!=len(value) or value[1]!=3 or len(value)%2:
                                        raise ValueError('Invalid string descriptor')
                                    strings.append(dict(index=string_index,language=hex(language),
                                        text=value[2:].decode('utf-16-le'),raw_hex=value.hex()))
                            device.update(language_descriptor_hex=languages.hex(),strings=strings)
                        devices.append(device)
                    except (OSError,ValueError) as error:
                        errors.append(dict(hub=path, port=port, error=str(error)))
            finally:
                kernel.CloseHandle(handle)
    return dict(captured_utc=datetime.now(timezone.utc).isoformat(),
        read_only=True, mode_switch=False, devices=devices, errors=errors,
        limitations=['USB descriptors do not prove simultaneous UVC/PTP operation or sensor activity.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--strings', action='store_true', help='Also read actual device-referenced language/string descriptors')
    args = parser.parse_args()
    report = capture(include_strings=args.strings)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['devices'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
