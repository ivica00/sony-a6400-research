"""Native Sony USB debugger client. Never enters Senser or updater mode."""
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
MAGIC = 0x44343641
HEADER = struct.Struct('<IHHIiIIII')
FRAME_SIZE = 4096
MAX_DATA = FRAME_SIZE - HEADER.size
FEATURE = 0x23


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
        return self.request(2,encoded,offset,size)['payload']

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
        result=self.request(4,struct.pack('<I',size),pid,address)
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
            result=self.request(3,command.encode())
            if result['status'] or result['flags']:
                raise DebuggerError(result['status'] or -5,result['payload'])
        actual,truncated=self.read_all(path,max(1,len(data)+1))
        if truncated or actual!=data:
            raise ProtocolError('Upload read-back mismatch')
        return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'readback_verified':True}


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
def connect():
    sys.path.insert(0,str(ROOT/'Sony-PMCA-RE'))
    from pmca.commands.usb import importDriver,listDevices
    from pmca.usb.sony import SonyMscExtCmdDevice,SonyMtpExtCmdDevice
    with host_lock(),importDriver('libusb') as driver:
        devices=[d for d in listDevices(driver,True) if isinstance(d,(SonyMscExtCmdDevice,SonyMtpExtCmdDevice))]
        if len(devices)!=1:
            raise RuntimeError(f'Expected one existing MSC/MTP camera; found {len(devices)}. No mode switch attempted.')
        yield Debugger(NativeExchange(devices[0]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='operation',required=True)
    for name in ('info','ps','stop'):
        sub.add_parser(name)
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
    args=parser.parse_args()
    with connect() as debugger:
        if args.operation in ('info','ps','stop','threads'):
            op={'info':1,'ps':6,'stop':255,'threads':7}[args.operation]
            result=debugger.request(op,arg0=getattr(args,'pid',0))
            print(result['payload'].decode(errors='replace'),end='')
            if result['flags']&1: print('\n[Output truncated]')
        elif args.operation=='exec':
            result=debugger.request(3,args.command.encode())
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
            info=debugger.request(1)['payload']; (args.directory/'debugger-info.txt').write_bytes(info)
            (args.directory/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
            print(args.directory.resolve())
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
