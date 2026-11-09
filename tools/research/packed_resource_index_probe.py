"""Execute original format-0 resource index lookup on retained USB tables."""
import json
import struct
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.active_menu_snapshot_probe import ROOT, HW

def main():
    capture = json.loads((HW/'native-packed-resource-indices-usb-e0123.json').read_text())
    if not capture['complete_binary']: raise ValueError('Complete index capture required')
    deps = json.loads((HW/'native-menu-activation-dependencies-pid713.json').read_text())
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    pages, known = set(), {}
    def supply(address, data):
        for i, byte in enumerate(data):
            if address+i in known and known[address+i] != byte: raise ValueError('Conflicting code/input')
        for page in range(address & ~4095, (address+len(data)+4095)&~4095,4096):
            if page not in pages: uc.mem_map(page,4096); pages.add(page)
        uc.mem_write(address,data);known.update({address+i:b for i,b in enumerate(data)})
    for row in deps:
        if row.get('code') is True and row.get('source_equal') is True:
            supply(int(row['address'],16),bytes.fromhex(row['data']))
    for row in capture['records']: supply(int(row['address'],16),bytes.fromhex(row['data']))
    stack,end=0x8300000,0x8310000
    supply(stack,bytes(4096));supply(end,bytes(4096))
    def read(_uc,_access,address,size,_value,_data):
        if not all(address+i in known for i in range(size)): raise ValueError('Uncaptured read')
    def write(_uc,_access,address,size,_value,_data):
        if not stack <= address < address+size <= stack+4096: raise ValueError('Original index wrote outside scratch stack')
    uc.hook_add(UC_HOOK_MEM_READ,read);uc.hook_add(UC_HOOK_MEM_WRITE,write)
    checks=[]
    for row in capture['records']:
        address=int(row['address'],16);raw=bytes.fromhex(row['data']);word=struct.unpack_from('<I',raw,4)[0]
        count=word&0x1fff;header=raw[0]&0x7c
        if raw[0]&3 or len(raw)!=header+((word>>11)&0x7ffc):raise ValueError('Unexpected original index encoding')
        entries=struct.unpack_from('<'+'H'*count,raw,header)
        controls={0,1,count//2,count-1,count,0xffffffff}
        if 0xc10<count:controls.add(0xc10)
        if 0xffff in entries:controls.add(entries.index(0xffff))
        for index in sorted(controls):
            expected=0xffffffff if index>=count or entries[index]==0xffff else entries[index]*4
            uc.reg_write(UC_ARM_REG_R0,address);uc.reg_write(UC_ARM_REG_R1,index)
            uc.reg_write(UC_ARM_REG_SP,stack+0xff0);uc.reg_write(UC_ARM_REG_LR,end|1)
            uc.emu_start(0x64b54b7,end,count=1000)
            actual=uc.reg_read(UC_ARM_REG_R0)
            if uc.reg_read(UC_ARM_REG_PC)!=end or actual!=expected:raise ValueError('Original lookup disagrees with captured index')
            checks.append(dict(table=hex(address),index=index,result=hex(actual),matches=True))
    report=dict(scope=__doc__,source_capture_sha256=capture['sha256'],menu_activation_proven=False,checks=checks)
    (ROOT/'artifacts/analysis/packed-resource-index-controls-e0123.json').write_text(json.dumps(report,indent=2))
    print(len(checks),'original lookup controls pass; no resource-table writes')
if __name__=='__main__':main()
