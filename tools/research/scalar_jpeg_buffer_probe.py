"""Execute original LIRO JPEG queue helpers on captured and explicit fixtures."""
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_READ, UC_PROT_EXEC
from unicorn.arm_const import (UC_CPU_ARM_CORTEX_A9, UC_ARM_REG_R0, UC_ARM_REG_R1,
                              UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP,
                              UC_ARM_REG_LR, UC_ARM_REG_PC)
from tools.research.oril_scalar_elf_view import ROOT, SOURCE, SHA, BASE

BUFFER, INDEX, STACK, RETURN = 0x200000, 0x201000, 0x210000, 0x300000


def main():
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SHA:raise ValueError('ORIL identity mismatch')
    capture=ROOT/'artifacts/hardware/uvc-native-source-e0144/jpeg-sequence-current-512.bin'
    snapshot=capture.read_bytes(); captured=snapshot[0xf4:0xf4+12*12]
    if len(snapshot)!=512 or len(captured)!=144:raise ValueError('Incomplete queue capture')
    live=(capture.parent/'buffer-helpers-current.bin').read_bytes()
    if live!=raw[0x7ce894:0x7ce994]:raise ValueError('Live helpers not source-equal')
    checks=[]
    def run(address, data, arguments):
        cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB);cpu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A9)
        cpu.mem_map(BASE+0x7ce000,4096)
        cpu.mem_write(BASE+0x7ce000,raw[0x7ce000:0x7cf000])
        cpu.mem_protect(BASE+0x7ce000,4096,UC_PROT_READ|UC_PROT_EXEC)
        cpu.mem_map(BUFFER,8192);cpu.mem_write(BUFFER,bytes(data))
        cpu.mem_map(STACK,4096);cpu.mem_map(RETURN,4096)
        cpu.reg_write(UC_ARM_REG_SP,STACK+4096);cpu.reg_write(UC_ARM_REG_LR,RETURN|1)
        for reg,value in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),arguments):
            cpu.reg_write(reg,value)
        cpu.emu_start(address|1,RETURN,count=10000)
        if cpu.reg_read(UC_ARM_REG_PC)!=RETURN:raise ValueError('Helper did not return')
        return cpu.reg_read(UC_ARM_REG_R0),bytes(cpu.mem_read(BUFFER,len(data))),struct.unpack('<H',cpu.mem_read(INDEX,2))[0]
    def find(data,state,mode):return run(0x63d948ca,data,[BUFFER,state,INDEX,mode])
    def check(name,ok):
        if not ok:raise AssertionError(name)
        checks.append(name)
    value,after,index=find(captured,3,1)
    check('captured-no-ready',value==0 and index==0xffff and after==captured)
    check('captured-all-twelve-empty',all(captured[i*12]==1 for i in range(12)))
    fixture=bytearray(captured)
    for index,handle,age,size in [(2,0x1234,10,64000),(7,0x5678,11,65000)]:
        struct.pack_into('<BBHII',fixture,index*12,3,0,handle,age,size)
    for mode,selected in [(0,2),(1,7),(2,2)]:
        value,after,index=find(fixture,3,mode)
        check('selection-mode-'+str(mode),value==1 and index==selected and after==fixture)
    struct.pack_into('<I',fixture,2*12+4,0xfffffe)
    struct.pack_into('<I',fixture,7*12+4,1)
    for mode,selected in [(1,7),(2,2)]:
        value,after,index=find(fixture,3,mode)
        check('24bit-age-wrap-mode-'+str(mode),value==1 and index==selected)
    value,after,_=run(0x63d948b0,fixture,[BUFFER,7])
    check('detach-ready-success',value==0 and after[7*12]==1)
    check('detach-other-slot-preserved',after[2*12:3*12]==fixture[2*12:3*12])
    value,unchanged,_=run(0x63d948b0,after,[BUFFER,7])
    check('detach-not-ready-rejected',value==0x8000 and unchanged==after)
    report={'status':'passed','count':len(checks),'checks':checks,
            'image_sha256':SHA,'capture_sha256':hashlib.sha256(snapshot).hexdigest(),
            'live_helper_source_equal':True,'physical_camera_calls':False,
            'limitations':['Explicit readiness/handle/age fixtures are not camera frames.',
                           'No DMM open/free, encoder or DMA operations are emulated here.',
                           'Live snapshot was not CPU-frozen and is not a lifecycle epoch.']}
    destination=ROOT/'artifacts/analysis/scalar-jpeg-buffer-controls-e0144.json'
    destination.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(len(checks),'original JPEG queue controls passed')


if __name__=='__main__':main()
