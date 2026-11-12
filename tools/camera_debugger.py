"""Native Sony USB debugger client. Never enters Senser or updater mode.

Protocol v2 (E0401) adds the always-on debugger commands:

* ``usb-state``  - camera/USB/debugger state receipt (op 8)
* ``recover``    - camera-side process-context cleanup of allowlisted authored
                   modules plus an optional host-side Sony request to switch the
                   camera back to Mass Storage (op 9 + PTP 0x9282)
* ``dmesg``      - non-destructive kernel printk readout (op 10)
* ``dump-ring``  - warm-reboot klog ring readout with CRC32 verification (op 11/12)

The existing file/shell/ptrace surface is unchanged.
"""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
import os
import errno
import shlex

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MAGIC = 0x44343641
HEADER = struct.Struct('<IHHIiIIII')
FRAME_SIZE = 4096
MAX_DATA = FRAME_SIZE - HEADER.size
FEATURE = 0x23
OP_INFO = 1
OP_READ = 2
OP_EXEC = 3
OP_MEM = 4
OP_PS = 6
OP_THREADS = 7
OP_USB_STATE = 8
OP_RECOVER = 9
OP_DMESG = 10
OP_RING_DUMP = 11
OP_RING_INFO = 12
OP_PING = 13
OP_STOP = 255
RECOVER_ARG = 0x52454356
RING_LIMIT = 0x20000
RING_CAPACITY_DEFAULT = 0x20000


class ProtocolError(RuntimeError):
    pass


class DebuggerError(RuntimeError):
    def __init__(self, status, payload=b''):
        super().__init__(f'Camera error {status}: {payload.decode(errors="replace")}')
        self.status = status
        self.payload = payload


def encode(op, request_id, payload=b'', arg0=0, arg1=0):
    if not 0 <= op <= 65535 or not 0 <= request_id <= 0xffffffff:
        raise ValueError('Operation or request ID outside wire range')
    if len(payload) > MAX_DATA or not 0 <= arg0 <= 0xffffffff or not 0 <= arg1 <= 0xffffffff:
        raise ValueError('Payload or argument outside wire range')
    return (HEADER.pack(MAGIC, 1, op, request_id, 0, len(payload), 0, arg0, arg1) + payload).ljust(FRAME_SIZE,b'\0')


def decode(raw, op, request_id):
    if len(raw) != FRAME_SIZE:
        raise ProtocolError(f'Expected {FRAME_SIZE} response bytes, received {len(raw)}')
    magic,version,actual_op,actual_id,status,length,flags,arg0,arg1 = HEADER.unpack_from(raw)
    if (magic,version,actual_op,actual_id) != (MAGIC,1,op,request_id):
        raise ProtocolError('Wrong protocol, version, operation, or request ID')
    if length > MAX_DATA or flags & ~3:
        raise ProtocolError('Invalid response length or flags')
    return {'status':status,'flags':flags,'payload':raw[HEADER.size:HEADER.size+length], 'arg0':arg0,'arg1':arg1}


class Debugger:
    def __init__(self, exchange):
        self.exchange = exchange
        self.sequence = 0

    def request(self, op, payload=b'', arg0=0, arg1=0):
        self.sequence = (self.sequence + 1) & 0xffffffff
        result = decode(self.exchange(encode(op,self.sequence,payload,arg0,arg1)),op,self.sequence)
        if result['status'] < 0:
            raise DebuggerError(result['status'], result['payload'])
        return result

    def read(self, path, offset=0, size=MAX_DATA):
        encoded = path.encode('utf-8')
        if not path.startswith('/') or '\0' in path or not 0 < len(encoded) < 512:
            raise ValueError('Expected an absolute camera path shorter than 512 bytes')
        if not 0 < size <= MAX_DATA or not 0 <= offset <= 0x7fffffff-size:
            raise ValueError('Read range outside supported file bounds')
        return self.request(OP_READ,encoded,offset,size)['payload']

    def read_all(self,path,limit=2*1024*1024):
        if limit <= 0:
            raise ValueError('Positive read limit required')
        data=bytearray()
        while len(data)<limit:
            block=self.read(path,len(data),min(MAX_DATA,limit-len(data)))
            if not block:
                return bytes(data),False
            data.extend(block)
        return bytes(data),bool(self.read(path,len(data),1))

    def memory(self,pid,address,size):
        if not 0 < pid <= 0x7fffffff or not 0 < size <= MAX_DATA or not 0 <= address <= 0xffffffff-size:
            raise ValueError('Invalid process memory range')
        result=self.request(OP_MEM,struct.pack('<I',size),pid,address)
        if len(result['payload'])!=size:
            raise ProtocolError('Short successful process-memory read')
        return result['payload']

    def push(self,path,data):
        if not path.startswith('/') or '\0' in path or len(path.encode())>=512 or len(data)>1024*1024:
            raise ValueError('Invalid camera upload path or file larger than 1 MiB')
        quoted=shlex.quote(path)
        chunks=[data[i:i+640] for i in range(0,len(data),640)] or [b'']
        for index,chunk in enumerate(chunks):
            escaped=''.join('\\0%03o'%byte for byte in chunk)
            command="printf '%b' "+shlex.quote(escaped)+(' > ' if index==0 else ' >> ')+quoted
            result=self.request(OP_EXEC,command.encode())
            if result['status'] or result['flags']:
                raise DebuggerError(result['status'] or -5,result['payload'])
        actual,truncated=self.read_all(path,max(1,len(data)+1))
        if truncated or actual!=data:
            raise ProtocolError('Upload read-back mismatch')
        return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'readback_verified':True}

    # ---- protocol v2 -------------------------------------------------
    def _stream(self, op, limit, chunk=MAX_DATA):
        """Chunked readout whose first response carries the snapshot length.

        Rejects a snapshot that changes between chunks; never fabricates bytes.
        Returns (data, snapshot_length, secondary_value).
        """
        data = bytearray()
        expected = None
        secondary = None
        while True:
            remaining = limit - len(data)
            if remaining <= 0:
                break
            size = min(chunk, remaining)
            result = self.request(op, arg0=len(data), arg1=size)
            total = result['arg0']
            if expected is None:
                expected = total
            elif total != expected:
                raise ProtocolError('Snapshot length changed during readout; retry')
            if secondary is None and result['arg1']:
                secondary = result['arg1']
            if not result['payload']:
                if len(data) < min(expected, limit):
                    raise ProtocolError(f'Short readout: {len(data)} of {expected} bytes')
                break
            data.extend(result['payload'])
            if expected is not None and len(data) > expected:
                # ring_dump may return whole region chunks; the receipt-verified
                # valid ring length is authoritative.
                del data[expected:]
                break
            if len(data) >= min(expected, limit):
                break
        return bytes(data), min(expected, limit), secondary

    def usb_state(self):
        return self.request(OP_USB_STATE)['payload'].decode('utf-8', 'replace')

    def recover(self):
        return self.request(OP_RECOVER, arg1=RECOVER_ARG)['payload'].decode('utf-8', 'replace')

    def ring_info(self):
        return self.request(OP_RING_INFO)['payload'].decode('utf-8', 'replace')

    def dmesg(self, limit=RING_LIMIT):
        return self._stream(OP_DMESG, limit)

    def ring_dump(self, limit=RING_LIMIT):
        return self._stream(OP_RING_DUMP, limit)

    def ring_capture(self):
        """Read the verified warm klog ring and verify it against the receipt."""
        from src.a6400 import usb_debug_ring
        receipt = usb_debug_ring.parse_ring_info(self.ring_info())
        if not receipt['valid']:
            raise usb_debug_ring.RingFormatError('klog ring unavailable: ' + receipt['error'])
        capacity = receipt['klog.capacity']
        if not 0 < capacity <= RING_LIMIT:
            raise usb_debug_ring.RingFormatError(f'capacity outside supported range: {capacity}')
        raw, _, _ = self.ring_dump(capacity)
        analysis = usb_debug_ring.analyze(raw, capacity)
        verification = usb_debug_ring.cross_check(analysis, receipt)
        return raw, analysis, receipt, verification

    def ping(self, nonce=0xA6400001):
        """Transport round-trip check; the daemon echoes the nonce."""
        result = self.request(OP_PING, arg0=nonce)
        if result['arg0'] != nonce:
            raise ProtocolError(f'ping nonce mismatch: {result["arg0"]:#x} != {nonce:#x}')
        return result['payload'].decode('utf-8', 'replace')


@contextlib.contextmanager
def host_lock(path=None,timeout=12):
    """Serialize this workspace's clients so USB request/reply pairs cannot mix."""
    path=Path(path) if path else ROOT/'artifacts/hardware/native-usb-debugger.host.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0,2)
        if not handle.tell(): handle.write(b'\0'); handle.flush()
        acquired=False; deadline=time.monotonic()+timeout
        while not acquired:
            try:
                handle.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                acquired=True
            except OSError as exc:
                if exc.errno not in (errno.EACCES,errno.EAGAIN): raise
                if time.monotonic()>=deadline:
                    raise TimeoutError('Another workspace client is using the camera debugger') from exc
                time.sleep(.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name=='nt': msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


class NativeExchange:
    """Same Sony ext-command framing, with bounded busy retries."""
    def __init__(self,device,timeout=8):
        self.device=device
        self.timeout=timeout

    def __call__(self,payload):
        device=self.device
        from pmca.usb.sony import SonyMscExtCmdDevice
        msc=isinstance(device,SonyMscExtCmdDevice)
        command=b'\x7a'+struct.pack('<I',FEATURE)+b'\0'*7
        busy=device.MSC_SENSE_DeviceBusy if msc else device.PTP_RC_DeviceBusy
        deadline=time.monotonic()+self.timeout
        for writing in (True,False):
            while True:
                if time.monotonic()>=deadline:
                    raise TimeoutError('Sony USB command stayed busy; no mode switch attempted')
                if msc:
                    if writing:
                        response=device.driver.sendWriteCommand(command,payload)
                    else:
                        response,data=device.driver.sendReadCommand(command,FRAME_SIZE)
                elif writing:
                    response=device.driver.sendWriteCommand(device.PTP_OC_SonyDiExtCmd_write,[FEATURE],payload)
                else:
                    response,data=device.driver.sendReadCommand(device.PTP_OC_SonyDiExtCmd_read,[FEATURE])
                if response==busy:
                    time.sleep(.02)
                    continue
                device._checkResponse(response)
                break
        return data


@contextlib.contextmanager
def connect(transport='auto'):
    """Prefer the persistent WinUSB bulk transport, fall back to ext-command."""
    if transport in ('auto', 'winusb'):
        try:
            from src.a6400.winusb_transport import open_winusb_exchange, TransportUnavailable
            exchange, details = open_winusb_exchange()
        except TransportUnavailable as exc:
            if transport == 'winusb':
                raise
            transport = 'extcmd'
        else:
            with host_lock():
                try:
                    yield Debugger(exchange)
                finally:
                    exchange.close()
            return
    with connect_device() as (debugger, _device):
        yield debugger


@contextlib.contextmanager
def connect_device():
    """Yield (Debugger, device) so a mode switch can use the same open session."""
    sys.path.insert(0,str(ROOT/'Sony-PMCA-RE'))
    from pmca.commands.usb import importDriver,listDevices
    from pmca.usb.sony import SonyMscExtCmdDevice,SonyMtpExtCmdDevice
    with host_lock(),importDriver(None) as driver:
        devices=[d for d in listDevices(driver,True) if isinstance(d,(SonyMscExtCmdDevice,SonyMtpExtCmdDevice))]
        if len(devices)!=1:
            raise RuntimeError(f'Expected one existing MSC/MTP camera; found {len(devices)}. No mode switch attempted.')
        yield Debugger(NativeExchange(devices[0])), devices[0]


def sony_ptp_devices(driver):
    """Raw Sony PTP candidates, independent of PMCA's MTP-camera operation list."""
    from pmca.usb.driver import USB_CLASS_PTP
    for device, usb_class, driver_handle in driver.listDevices(0x054c):
        if usb_class == USB_CLASS_PTP:
            yield device, driver_handle


def request_msc_switch():
    """Send Sony PTP 0x9282 (SonyReqReconnect arg 0): camera -> mass storage."""
    sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))
    from pmca.commands.usb import importDriver
    from pmca.usb.sony import SonyMtpExtCmdDevice
    attempts = []
    with importDriver(None) as driver:
        for device, driver_handle in sony_ptp_devices(driver):
            entry = {'idVendor': device.idVendor, 'idProduct': device.idProduct}
            try:
                SonyMtpExtCmdDevice(driver_handle).switchToMsc()
                entry['sent'] = True
            except Exception as exc:  # a failed switch is reported, never retried blindly
                entry['sent'] = False
                entry['error'] = f'{type(exc).__name__}: {exc}'
            attempts.append(entry)
    return attempts


def wait_for_msc(timeout=30, poll=1.0):
    """Wait until the camera enumerates in mass storage mode (054c:0caa)."""
    sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))
    from pmca.commands.usb import importDriver, listDevices
    from pmca.usb.sony import SonyMscExtCmdDevice
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with importDriver(None) as driver:
            devices = [d for d in listDevices(driver, True) if isinstance(d, SonyMscExtCmdDevice)]
        if devices:
            return True
        time.sleep(poll)
    return False


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')
    return path


def recover_to_msc(output=None, timeout=30, transport='auto'):
    """Camera-side cleanup then an in-band Sony reconnect, with a JSON receipt.

    When the debugger is reachable over MTP, the Sony 0x9282 request is sent on
    that same open session so it cannot lose the device to a re-enumeration
    between separate connections. The raw-enumeration fallback is used only when
    the debugger is unreachable. A WinUSB-transport recovery is camera-side only
    until the gadget module implements the mode switch itself.
    """
    receipt = {'operation': 'recover_to_msc', 'transport': transport, 'steps': []}
    switched_in_band = False
    try:
        with connect(transport) as debugger:
            receipt['camera_side'] = debugger.recover()
            receipt['steps'].append({'camera_side': 'ok'})
    except Exception as exc:
        receipt['camera_side'] = 'unreachable'
        receipt['camera_side_error'] = f'{type(exc).__name__}: {exc}'
        receipt['steps'].append({'camera_side': 'unreachable'})
    if transport != 'winusb':
        try:
            with connect_device() as (debugger, device):
                if hasattr(device, 'switchToMsc'):
                    device.switchToMsc()
                    switched_in_band = True
                    receipt['in_band_switch'] = 'sent'
                    receipt['steps'].append({'in_band_switch': 'sent'})
                else:
                    receipt['in_band_switch'] = 'already_mass_storage'
                    receipt['steps'].append({'in_band_switch': 'already_mass_storage'})
            if not switched_in_band:
                receipt.setdefault('in_band_switch', 'not_sent')
        except Exception as exc:
            receipt['in_band_switch'] = f'unavailable: {type(exc).__name__}: {exc}'
            receipt['steps'].append({'in_band_switch': 'unavailable'})
    else:
        receipt['in_band_switch'] = 'daemon_mode_switch_not_implemented'
        receipt['steps'].append({'in_band_switch': 'daemon_mode_switch_not_implemented'})
    receipt['msc_present'] = wait_for_msc(timeout)
    receipt['steps'].append({'wait_for_msc': receipt['msc_present']})
    if receipt['msc_present']:
        try:
            with connect() as debugger:
                info = debugger.request(OP_INFO)['payload'].decode('utf-8', 'replace')
            receipt['debugger_reachable_in_msc'] = True
            receipt['debugger_info'] = info
        except Exception as exc:
            receipt['debugger_reachable_in_msc'] = False
            receipt['debugger_error'] = f'{type(exc).__name__}: {exc}'
    else:
        receipt['debugger_reachable_in_msc'] = False
    receipt['result'] = ('msc_recovered' if receipt['msc_present'] and receipt['debugger_reachable_in_msc']
                         else ('msc_no_debugger' if receipt['msc_present'] else 'msc_not_reached'))
    if output:
        _write_json(output, receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transport',choices=('auto','extcmd','winusb'),default='auto',
                        help='auto prefers the E0402 WinUSB bulk transport, then ext-command')
    sub=parser.add_subparsers(dest='operation',required=True)
    for name in ('info','ps','stop','ping'):
        sub.add_parser(name)
    state=sub.add_parser('usb-state'); state.add_argument('--output',type=Path)
    maps=sub.add_parser('maps'); maps.add_argument('pid',type=int)
    threads=sub.add_parser('threads'); threads.add_argument('pid',type=int)
    read=sub.add_parser('read'); read.add_argument('path'); read.add_argument('--output',type=Path)
    read.add_argument('--limit',type=int,default=2*1024*1024)
    memory=sub.add_parser('mem'); memory.add_argument('pid',type=int)
    memory.add_argument('address',type=lambda x:int(x,0)); memory.add_argument('size',type=lambda x:int(x,0))
    memory.add_argument('--output',type=Path)
    command=sub.add_parser('exec'); command.add_argument('command')
    push=sub.add_parser('push'); push.add_argument('local',type=Path); push.add_argument('remote')
    snapshot=sub.add_parser('snapshot'); snapshot.add_argument('pid',type=int); snapshot.add_argument('directory',type=Path)
    dmesg=sub.add_parser('dmesg'); dmesg.add_argument('--output',type=Path)
    ring=sub.add_parser('dump-ring'); ring.add_argument('--output',type=Path)
    ring.add_argument('--json',type=Path)
    recover=sub.add_parser('recover')
    recover.add_argument('--to-msc',action='store_true')
    recover.add_argument('--output',type=Path)
    recover.add_argument('--timeout',type=float,default=30)
    args=parser.parse_args()
    if args.operation=='recover':
        receipt = recover_to_msc(args.output, args.timeout, args.transport) if args.to_msc else None
        if receipt is None:
            with connect(args.transport) as debugger:
                text = debugger.recover()
            print(text, end='')
            return 0
        print(json.dumps(receipt, indent=2))
        return 0 if receipt['result']=='msc_recovered' else 2
    with connect(args.transport) as debugger:
        if args.operation=='ping':
            print(debugger.ping(), end='')
        elif args.operation in ('info','ps','stop','threads','usb-state'):
            op={'info':OP_INFO,'ps':OP_PS,'stop':OP_STOP,'threads':OP_THREADS,'usb-state':OP_USB_STATE}[args.operation]
            result=debugger.request(op,arg0=getattr(args,'pid',0))
            text=result['payload'].decode(errors='replace')
            output=getattr(args,'output',None)
            if output:
                output.parent.mkdir(parents=True,exist_ok=True)
                output.write_text(text,encoding='utf-8')
                print(output)
            else:
                print(text,end='')
            if result['flags']&1: print('\n[Output truncated]')
        elif args.operation=='exec':
            result=debugger.request(OP_EXEC,args.command.encode())
            print(result['payload'].decode(errors='replace'),end='')
            if result['flags']&1: print('\n[Output truncated]')
            return result['status']
        elif args.operation=='push':
            print(json.dumps(debugger.push(args.remote,args.local.read_bytes()),indent=2))
        elif args.operation=='snapshot':
            args.directory.mkdir(parents=True,exist_ok=False)
            manifest={'pid':args.pid,'mode_switches':False,'files':{}}
            for name in ('comm','status','maps'):
                data,truncated=debugger.read_all(f'/proc/{args.pid}/{name}')
                (args.directory/name).write_bytes(data)
                manifest['files'][name]={'bytes':len(data),'truncated':truncated,'sha256':hashlib.sha256(data).hexdigest()}
            info=debugger.request(OP_INFO)['payload']; (args.directory/'debugger-info.txt').write_bytes(info)
            (args.directory/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
            print(args.directory.resolve())
        elif args.operation=='dmesg':
            data,total,_=debugger.dmesg()
            output=getattr(args,'output',None)
            if output:
                output.parent.mkdir(parents=True,exist_ok=True)
                output.write_bytes(data)
                print(f'{output} ({len(data)} of {total} bytes)')
            else:
                print(data.decode(errors='replace'),end='')
        elif args.operation=='dump-ring':
            raw,analysis,receipt,verification=debugger.ring_capture()
            output=getattr(args,'output',None) or (ROOT/'artifacts/analysis/klog-ring-dump.bin')
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_bytes(raw)
            summary={
                'capture': str(output.resolve()),
                'bytes': len(raw),
                'daemon_receipt': receipt,
                'analysis': {key: analysis[key] for key in ('valid','capacity','data_bytes','crc32','boot_count','preamble_bytes')},
                'header': analysis['header'],
                'boots': analysis['boots'],
                'verification': verification,
            }
            json_path=getattr(args,'json',None) or output.with_suffix('.json')
            _write_json(json_path,summary)
            print(json.dumps(summary['analysis'],indent=2))
            print(f'boots={analysis["boot_count"]} crc32=0x{analysis["crc32"]:08x} '
                  f'header_magic_distance={analysis["header"]["magic_bit_distance"]}')
            print(f'{output} / {json_path}')
        else:
            if args.operation=='mem':
                data=debugger.memory(args.pid,args.address,args.size); truncated=False
            else:
                path=f'/proc/{args.pid}/maps' if args.operation=='maps' else args.path
                data,truncated=debugger.read_all(path,getattr(args,'limit',2*1024*1024))
            output=getattr(args,'output',None)
            if output: output.write_bytes(data)
            elif args.operation=='mem': print(data.hex())
            else: print(data.decode(errors='replace'),end='')
            if truncated: print('\n[Read limit reached]')
    return 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'Debugger: {exc}',file=sys.stderr)
        sys.exit(1)
