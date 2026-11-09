"""Build an exact-version finite UI trace payload; does not deploy it."""
import hashlib,json,os,struct,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    compiler=['arm-linux-gnueabi-gcc'] if os.name=='posix' else ['wsl.exe','--cd','/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:],'--exec','arm-linux-gnueabi-gcc']
    elf='devcrashday_a6400/menu_touch_trace.elf'
    flags='-std=gnu11 -march=armv7-a -mthumb -mfloat-abi=softfp -Os -Wall -Wextra -Werror -nostdlib -ffreestanding -fno-builtin -fno-stack-protector -fomit-frame-pointer -fno-unwind-tables -fno-asynchronous-unwind-tables'.split()
    subprocess.run(compiler+flags+['-Wl,-Ttext=0x0700d708,-e,mt_trace_release,--build-id=none','-o',elf,'tools/native_camera/menu_touch_trace.c','tools/native_camera/menu_touch_trace_trampoline.S'],cwd=ROOT,check=True)
    raw=(ROOT/elf).read_bytes();h=struct.unpack_from('<16sHHIIIIIHHHHHH',raw)
    if h[0][:7]!=b'\x7fELF\x01\x01\x01' or h[2]!=40 or h[-3]!=40:raise ValueError('Wrong ARM ELF')
    sections=[struct.unpack_from('<10I',raw,h[6]+i*40) for i in range(h[-2])]
    ns=sections[h[-1]];names=raw[ns[4]:ns[4]+ns[5]];text=None
    for section in sections:
        name=names[section[0]:names.index(0,section[0])].decode()
        if name=='.text':text=section
        if section[2]&2 and section[5] and name not in ('.text','.ARM.exidx'):raise ValueError('Unmapped runtime section '+name)
    if text is None or text[3]!=0x700d708 or text[5]>2296 or text[5]%4 or not h[4]&1:raise ValueError('Payload exceeds owned executable padding')
    code=raw[text[4]:text[4]+text[5]]
    p=ROOT/'artifacts/hardware/menu-touch-trace-payload.bin';p.write_bytes(code)
    m=dict(entry=hex(h[4]),code_address='0x700d708',code_bytes=len(code),state_address='0x7143920',state_bytes=1184,capacity=24,hook_address='0x6309d48',expected_prologue='2de9f04788b04ff014080122',sha256=hashlib.sha256(code).hexdigest(),deployed=False,selection_enabled=False)
    (ROOT/'artifacts/hardware/menu-touch-trace-build.json').write_text(json.dumps(m,indent=2));print(m)
if __name__=='__main__':main()
