"""Original kernel USB request queue/completion controls, no hardware queueing."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE,UC_PROT_READ,UC_PROT_EXEC
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_SP,UC_ARM_REG_PC

ROOT=Path(__file__).resolve().parents[2]
PROFILES=[('a6400','extracted_a6400','12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707'),
          ('zve10','extracted_zve10_v203_linuxnames','74fbef5a7c36149cf3256623950798332f9ead0fa719bf6d61dcac69397950e2')]
EP,NATIVE_EP,OPS,USB_REQUEST,WRAPPER,STACK=0x200000,0x200100,0x200200,0x201000,0x202000,0x400000


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args();out=args.report_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):parser.error('Report must remain under artifacts')
    out.mkdir(parents=True,exist_ok=False);checks=[];traces=[];bodies={}
    def check(name,condition):
        if not condition:raise AssertionError(name)
        checks.append(name)
    for model,folder,sha in PROFILES:
        raw=(ROOT/'firmware'/folder/'firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('Kernel identity mismatch')
        symbols=json.loads((ROOT/'artifacts/analysis/uvc-portability-final-e0135'/(model+'-kallsyms-checked.json')).read_text())
        if symbols['source_sha256']!=sha:raise ValueError('Symbol identity mismatch')
        syms={s['name']:s['address'] for s in symbols['symbols']}
        queue,complete=syms['gcore_queue'],syms['gcore_complete']
        bodies[model]=(raw[queue-0x60108000:queue-0x60108000+120],raw[complete-0x60108000:complete-0x60108000+100])
        for error in (False,True):
            cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);page=queue&~4095
            cpu.mem_map(page,4096);off=page-0x60108000;cpu.mem_write(page,raw[off:off+4096])
            cpu.mem_protect(page,4096,UC_PROT_READ|UC_PROT_EXEC)
            cpu.mem_map(0x200000,0x3000);cpu.mem_map(STACK,4096)
            cpu.mem_write(EP+0x24,struct.pack('<I',NATIVE_EP));cpu.mem_write(NATIVE_EP+8,struct.pack('<I',OPS))
            cpu.mem_write(OPS+0x10,struct.pack('<I',0x500000))
            original=bytearray(struct.pack('<13I',*[0x11000000+i for i in range(13)]))
            struct.pack_into('<I',original,0x1c,0x500100);struct.pack_into('<I',original,0x20,0x12345678)
            cpu.mem_write(WRAPPER,bytes(original));cpu.mem_write(WRAPPER+0x34,struct.pack('<I',USB_REQUEST))
            writes=[];stop=[queue+0x70];stopped=[False]
            def hook(machine,pc,size,context):
                if pc==stop[0]:stopped[0]=True;machine.emu_stop()
            def write(machine,access,address,size,value,context):
                if not (USB_REQUEST<=address and address+size<=USB_REQUEST+52 or
                        WRAPPER<=address and address+size<=WRAPPER+0x3c or
                        STACK<=address and address+size<=STACK+4096):
                    raise RuntimeError('Original write outside explicit request/stack fixture')
                writes.append({'address':hex(address),'size':size})
            cpu.hook_add(UC_HOOK_CODE,hook);cpu.hook_add(UC_HOOK_MEM_WRITE,write)
            for r,v in [(UC_ARM_REG_R0,EP),(UC_ARM_REG_R1,WRAPPER),(UC_ARM_REG_R2,0x20),(UC_ARM_REG_SP,STACK+0xf00)]:cpu.reg_write(r,v)
            cpu.emu_start(queue,queue+124,count=100)
            label=model+('-error' if error else '-normal')
            check(label+'-queue-stop',stopped[0])
            actual=bytes(cpu.mem_read(USB_REQUEST,52));expected=bytearray(original)
            struct.pack_into('<I',expected,0x1c,complete);struct.pack_into('<I',expected,0x20,WRAPPER)
            check(label+'-queue-copy-and-ownership',actual==bytes(expected))
            check(label+'-queue-arguments',[cpu.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2)]==[NATIVE_EP,USB_REQUEST,0x20])
            check(label+'-wrapper-endpoint',struct.unpack('<I',cpu.mem_read(WRAPPER+0x38,4))[0]==EP)
            # Explicit completion input fixtures; no DMA or hardware callback.
            status,amount=(-5,8) if error else (0,26)
            cpu.mem_write(USB_REQUEST+0x2c,struct.pack('<iI',status,amount))
            stop[0]=complete+0x5c;stopped[0]=False
            cpu.reg_write(UC_ARM_REG_R0,NATIVE_EP);cpu.reg_write(UC_ARM_REG_R1,USB_REQUEST)
            cpu.reg_write(UC_ARM_REG_SP,STACK+0xf00)
            cpu.emu_start(complete,complete+100,count=100)
            check(label+'-completion-stop',stopped[0])
            expected=bytearray(original);struct.pack_into('<iI',expected,0x2c,status,amount)
            check(label+'-completion-restores-owner',bytes(cpu.mem_read(WRAPPER,52))==bytes(expected))
            check(label+'-completion-arguments',[cpu.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1)]==[EP,WRAPPER])
            traces.append({'case':label,'queue_stop_before_udc':hex(queue+0x70),
                           'completion_stop_before_callback':hex(complete+0x5c),'status_fixture':status,
                           'actual_fixture':amount,'writes':writes})
    check('queue-instruction-bytes-equal-excluding-completion-literal',bodies['a6400'][0]==bodies['zve10'][0])
    check('complete-all-100-bytes-equal',bodies['a6400'][1]==bodies['zve10'][1])
    report={'status':'passed','count':len(checks),'checks':checks,'traces':traces,
        'camera_access':False,'limitations':['Original queue stops BEFORE underlying UDC submission.',
            'Completion status/length are EXPLICIT input fixtures, not DMA observations.',
            'Final reference completion callback is NOT invoked.',
            'Compatible request-copy layout does not prove isochronous endpoint scheduling or cache coherence.']}
    (out/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(len(checks),'original request-ABI controls passed; UDC and completion callbacks not invoked')


if __name__=='__main__':main()
