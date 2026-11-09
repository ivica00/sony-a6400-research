"""Instrumentation ABI unit control; original consumer body is an explicit test double.

No menu navigation, rendering or camera behavior is simulated/proven here.
"""
import json,struct
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_INTR,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from tools.research.active_menu_snapshot_probe import ROOT,HW

def run(enabled=1,mouse=0,system=0x956f0,changed_position=False):
    meta=json.loads((HW/'menu-touch-trace-build.json').read_text());code=(HW/'menu-touch-trace-payload.bin').read_bytes()
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for page,size in [(0x700d000,4096),(0x7143000,4096),(0x6309000,4096),(0x95000,8192),(0x8300000,0x4000),(0x8310000,4096),(0x8321000,4096)]:u.mem_map(page,size)
    u.mem_write(0x700d708,code)
    state=struct.pack('<8I',0x4d544c47,1,enabled,0,0,24,0,0x956f0)+bytes(1152);u.mem_write(0x7143920,state)
    message=bytearray(32);struct.pack_into('<2I',message,8,123,456);struct.pack_into('<I',message,16,2);message[20]=mouse;message[21]=1;u.mem_write(0x8321000,bytes(message))
    u.mem_write(0x95b98,struct.pack('<3I',320|(200<<16),640|(400<<16),1))
    saved={getattr(A,'UC_ARM_REG_R'+str(i)):0x440000+i*0x1111 for i in range(4,12)}
    for reg,value in saved.items():u.reg_write(reg,value)
    initial_sp=0x8303000;sentinel=0x13579bdf;calls=[]
    def instruction(_u,address,_size,_data):
        if address==0x6309d54:
            if changed_position:u.mem_write(0x95b98,struct.pack('<I',111|(222<<16)))
            # Validate actual copied original prologue, then emulate ONLY its
            # omitted body/epilogue as a deterministic forwarding test double.
            if u.reg_read(A.UC_ARM_REG_R0)!=system or u.reg_read(A.UC_ARM_REG_R1)!=0x8321000:raise ValueError('Arguments changed')
            if u.reg_read(A.UC_ARM_REG_R2)!=1 or u.reg_read(A.UC_ARM_REG_R8)!=20:raise ValueError('Original prologue differs')
            sp=u.reg_read(A.UC_ARM_REG_SP)
            if sp&7:raise ValueError('AAPCS stack alignment changed')
            words=struct.unpack('<8I',u.mem_read(sp+32,32));regs=[A.UC_ARM_REG_R4,A.UC_ARM_REG_R5,A.UC_ARM_REG_R6,A.UC_ARM_REG_R7,A.UC_ARM_REG_R8,A.UC_ARM_REG_R9,A.UC_ARM_REG_R10,A.UC_ARM_REG_LR]
            for reg,value in zip(regs,words):u.reg_write(reg,value)
            u.reg_write(A.UC_ARM_REG_SP,sp+64);u.reg_write(A.UC_ARM_REG_R0,sentinel);u.reg_write(A.UC_ARM_REG_PC,words[-1]);calls.append('explicit_consumer_test_double')
    def interrupt(_u,number,_data):
        if number!=2 or u.reg_read(A.UC_ARM_REG_R7)!=224:raise ValueError('Unexpected syscall')
        u.reg_write(A.UC_ARM_REG_R0,149)
    def write(_u,_access,address,size,_value,_data):
        if not (0x8300000<=address<address+size<=0x8304000 or 0x7143920<=address<address+size<=0x7143920+1184):raise ValueError('Logger wrote application state')
    u.hook_add(UC_HOOK_CODE,instruction);u.hook_add(UC_HOOK_INTR,interrupt);u.hook_add(UC_HOOK_MEM_WRITE,write)
    u.reg_write(A.UC_ARM_REG_R0,system);u.reg_write(A.UC_ARM_REG_R1,0x8321000);u.reg_write(A.UC_ARM_REG_SP,initial_sp);u.reg_write(A.UC_ARM_REG_LR,0x8310001)
    u.emu_start(int(meta['entry'],16),0x8310000,count=10000)
    if u.reg_read(A.UC_ARM_REG_PC)!=0x8310000 or u.reg_read(A.UC_ARM_REG_R0)!=sentinel or u.reg_read(A.UC_ARM_REG_SP)!=initial_sp:raise ValueError('Forwarding/return/stack changed')
    if any(u.reg_read(reg)!=value for reg,value in saved.items()) or len(calls)!=1:raise ValueError('Callee-saved registers or call count changed')
    result=struct.unpack('<8I',u.mem_read(0x7143920,32));record=struct.unpack('<12I',u.mem_read(0x7143940,48))
    expected=int(bool(enabled and mouse<4 and system==0x956f0))
    if result[3]!=expected or result[4]!=0:raise ValueError('Trace count/inflight differs')
    if expected and record!=(1,149,system,320|(200<<16),256,(111|(222<<16)) if changed_position else (320|(200<<16)),640|(400<<16),1,123,456,sentinel,2):raise ValueError('Trace record differs')
    return dict(enabled=enabled,mouse=mouse,system=hex(system),forwarded_once=True,callee_saved_preserved=True,stack_restored=True,original_return_preserved=True,application_memory_writes=False,trace_count=result[3],inflight=result[4])
def main():
    results=[run(),run(enabled=0),run(mouse=4),run(system=0x95700),run(changed_position=True)]
    (ROOT/'artifacts/analysis/menu-touch-trace-abi-controls.json').write_text(json.dumps(dict(scope=__doc__,controls=results),indent=2))
    print('5 explicit instrumentation ABI controls pass; original consumer body NOT tested')
if __name__=='__main__':main()
