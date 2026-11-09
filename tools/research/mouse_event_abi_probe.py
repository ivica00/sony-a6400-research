"""Original MouseEvent getters on explicit records; not physical input routing."""
import json,struct
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from tools.research.active_menu_snapshot_probe import ROOT,HW

def main():
    component=(HW/'native-widget-geometry-component.bin').read_bytes();code=component[0x11000:0x12000]
    entries=[('type',0x6316650),('mouse',0x6316658),('button',0x6316660),('param1',0x6316670),('param2',0x631667a),('param3',0x6316684)]
    checks=[]
    for kind,mouse,button,x,y,z in [(2,0,4,320,200,0),(5,1,0,-123,456,-7),(6,3,2,623,424,42)]:
        packet=struct.pack('<BBhhhIIQ',mouse,button,x,y,z,kind,0,123456)
        expected=dict(type=kind,mouse=mouse,button=button if kind>4 else 5,param1=x&0xffffffff,param2=y&0xffffffff,param3=z&0xffffffff)
        for field,entry in entries:
            u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
            for p in (0x6316000,0x8300000,0x8310000,0x8320000):u.mem_map(p,4096)
            u.mem_write(0x6316000,code);u.mem_write(0x8320000,packet)
            def write(_u,_access,address,size,_value,_data):
                if not 0x8300000<=address<address+size<=0x8301000:raise ValueError('Getter changed input/application bytes')
            u.hook_add(UC_HOOK_MEM_WRITE,write)
            u.reg_write(A.UC_ARM_REG_R0,0x8320000);u.reg_write(A.UC_ARM_REG_SP,0x8300ff0);u.reg_write(A.UC_ARM_REG_LR,0x8310001)
            u.emu_start(entry|1,0x8310000,count=100)
            actual=u.reg_read(A.UC_ARM_REG_R0)
            if u.reg_read(A.UC_ARM_REG_PC)!=0x8310000 or actual!=expected[field]:raise ValueError('Original getter differs')
            checks.append(dict(type=kind,field=field,result=actual,matches=True))
    (ROOT/'artifacts/analysis/mouse-event-abi-controls-e0127.json').write_text(json.dumps(dict(scope=__doc__,checks=checks),indent=2))
    print('18 original MouseEvent getter controls pass; no application-memory writes')
if __name__=='__main__':main()
