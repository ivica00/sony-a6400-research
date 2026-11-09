"""Execute original monitor ring primitives against explicit memory fixtures."""
import hashlib,io,json,struct
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT


def main():
    source=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libMWF.so'
    raw=source.read_bytes()
    inventory=json.loads((ROOT/'artifacts/inventory/elf-inventory.json').read_text())
    expected=next(x['sha256'] for x in inventory['entries'] if x['path']==source.relative_to(ROOT).as_posix())
    assert hashlib.sha256(raw).hexdigest()==expected
    e=ELFFile(io.BytesIO(raw));checks=[]
    for name,operation,read,write,expected in [('empty','empty',0,0,1),('not-empty','empty',0,1,0),('full','full',0,3,1),('wrapped-full','full',2,1,1),('free','full',0,2,0),('enqueue','enqueue',0,0,None),('enqueue-wrap','enqueue',2,3,None),('dequeue','dequeue',0,1,0x7b),('dequeue-wrap','dequeue',3,1,0x7b)]:
        c=Uc(UC_ARCH_ARM,UC_MODE_ARM);c.mem_map(0,0x60000);c.mem_map(0x200000,0x10000);c.mem_map(0x300000,4096)
        for seg in e.iter_segments():
            if seg['p_type']=='PT_LOAD':c.mem_write(seg['p_vaddr'],seg.data())
        obj,rp,wp,data=0x200000,0x200100,0x200104,0x201000
        def put(a,v):c.mem_write(a,struct.pack('<I',v))
        def word(a):return struct.unpack('<I',c.mem_read(a,4))[0]
        c.mem_write(obj,struct.pack('<4I',rp,wp,data,4));put(rp,read);put(wp,write);c.mem_write(data+read,b'\x7b')
        returned=[];writes=[]
        def hook(cpu,a,size,unused):
            if a==0x300000:returned.append(cpu.reg_read(UC_ARM_REG_R0));cpu.emu_stop();return
            if a==0x1ba20:
                n,d=cpu.reg_read(UC_ARM_REG_R0),cpu.reg_read(UC_ARM_REG_R1);assert d==4
                cpu.reg_write(UC_ARM_REG_R0,n//d);cpu.reg_write(UC_ARM_REG_R1,n%d);cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR));return
            if not any(lo<=a<hi for lo,hi in [(0x265a0,0x265e8),(0x26608,0x26626),(0x267fe,0x2681a)]):raise RuntimeError(f'Unexpected execution {a:08x}')
        def memory(cpu,access,a,size,value,unused):
            if data<=a<data+4 or a in (rp,wp):writes.append([a,size,value])
        c.hook_add(UC_HOOK_CODE,hook);c.hook_add(UC_HOOK_MEM_WRITE,memory)
        c.reg_write(UC_ARM_REG_R0,obj);c.reg_write(UC_ARM_REG_R1,0x41);c.reg_write(UC_ARM_REG_SP,0x20f000);c.reg_write(UC_ARM_REG_LR,0x300000)
        c.emu_start({'empty':0x265a1,'full':0x265b7,'enqueue':0x26609,'dequeue':0x267ff}[operation],0xffffffff,count=500)
        assert returned
        if expected is not None:assert returned==[expected]
        if operation=='enqueue':
            assert writes==[[data+write,1,0x41],[wp,4,(write+1)%4]] and word(rp)==read
        elif operation=='dequeue':assert writes==[[rp,4,(read+1)%4]] and word(wp)==write
        else:assert not writes
        checks.append(dict(name=name,result=returned[0],writes=writes))
    out=ROOT/'artifacts/analysis/uvc-monitor-ring-e0224';out.mkdir(parents=True,exist_ok=True)
    (out/'manifest.json').write_text(json.dumps(dict(status='offline_original_monitor_ring_passed',source_sha256=hashlib.sha256(raw).hexdigest(),checks=checks,limitations=['Original ring bodies execute; object/cursors/data are explicit fixtures and division is a service double.', 'No native CPU memory-ordering, exclusive producer/consumer ownership, live command execution or filesystem write proven.']),indent=2)+'\n')
    print(f'{len(checks)} original monitor ring cases passed')


if __name__=='__main__':main()
