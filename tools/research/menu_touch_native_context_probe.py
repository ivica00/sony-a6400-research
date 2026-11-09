"""Compiled MOD context bindings + original methods on coupled camera state.

gettid is an explicit kernel-contract fixture, epoch an explicit test token.
This is not a live lifetime observer or proof of every overlay exclusion.
"""
import io
import json
import struct
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_INTR, UC_HOOK_MEM_INVALID
from unicorn import arm_const as A
from tools.research.active_menu_snapshot_probe import HW, ROOT


def control(case):
    capture = json.loads((HW/'native-touch-geometry-pid1673.json').read_text())
    menu = next(int(r['address'], 16) for r in capture['records'] if r['size'] == 0x186bc)
    elf = ELFFile(io.BytesIO((ROOT/'devcrashday_a6400/menu_touch_native.elf').read_bytes()))
    text = elf.get_section_by_name('.text')
    entry = next(s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()
                 if s.name == 'mt_native_context')
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    pages, known, executable = set(), {}, []
    stack, output, end, epoch = 0x8300000, 0x8310000, 0x8320000, 0x8330000
    def supply(address, data, code=False):
        for i, v in enumerate(data):
            if address+i in known and known[address+i] != v:
                raise ValueError('Conflicting inputs '+hex(address+i))
        for page in range(address & ~4095, (address+len(data)+4095) & ~4095, 4096):
            if page not in pages:
                u.mem_map(page, 4096);pages.add(page)
        u.mem_write(address, data)
        known.update({address+i:v for i,v in enumerate(data)})
        if code: executable.append((address, address+len(data)))
    supply(text['sh_addr'], text.data(), True)
    for r in capture['records']:
        supply(int(r['address'], 16), bytes.fromhex(r['data']),
               int(r['address'], 16) in (0x157e584c, 0x159589f8))
    for address, filename in [(0x6305000,'native-widget-geometry-component.bin'),
                              (0x62dc800,'native-layout-lookup-component.bin'),
                              (0x15b90000,'native-listtab-code-component.bin'),
                              (0x16925a00,'native-setting-node-code.bin')]:
        supply(address, (HW/filename).read_bytes(), True)
    registry = json.loads((HW/'native-widget-layout-registry-contracts.json').read_text())
    for name, window in registry.items():
        if name.startswith('0x'): supply(int(name,16), bytes.fromhex(window['code']), True)
    supply(int(registry['singleton']['slot'],16), struct.pack('<I',0x7107f34))
    for r in json.loads((HW/'native-layout-lookup-got.json').read_text()):
        supply(int(r['address'],16),bytes.fromhex(r['data']))
    for r in json.loads((HW/'native-widget-worldpos-contracts.json').read_text())['additional']:
        supply(int(r['address'],16),bytes.fromhex(r['data']),r['code'])
    ancestor = json.loads((HW/'native-widget-ancestor-mode-e0131.json').read_text())
    supply(int(ancestor['address'],16),bytes.fromhex(ancestor['data']),True)
    hierarchy = json.loads((HW/'native-setting-node-hierarchy-usb.json').read_text())
    supply(0x16c183e8, bytes.fromhex(hierarchy['vtable']))
    for address in (stack, output, end, epoch): supply(address, bytes(4096))
    if case == 'header_focus':u.mem_write(menu+0x1d8,b'\x01')
    if case == 'cached_row_mismatch':u.mem_write(menu+0x1f8,struct.pack('<I',5))
    u.mem_write(epoch,struct.pack('<I',0 if case=='zero_epoch' else 7))
    trace=[]
    setting_fixture = False
    def instruction(_u,a,size,_data):
        if not any(lo<=a<a+size<=hi for lo,hi in executable):
            raise ValueError('Unprovided code '+hex(a))
        trace.append(a)
    def read(_u,_access,a,size,_value,_data):
        if not all(a+i in known for i in range(size)):
            raise ValueError('Uncaptured read '+hex(a))
    def write(_u,_access,a,size,_value,_data):
        setter_write = setting_fixture and (
            (a,size,u.reg_read(A.UC_ARM_REG_PC)) == (menu+0xfb20+0x648e,1,0x15b95a5e) or
            (a,size,u.reg_read(A.UC_ARM_REG_PC)) == (menu+0x1e0,4,0x15b90524))
        if not (stack<=a<a+size<=stack+4096 or output<=a<a+size<=output+36 or setter_write):
            raise ValueError('Unexpected application write '+hex(a))
        known.update({a+i:0 for i in range(size)})
    def interrupt(_u,number,_data):
        pc=u.reg_read(A.UC_ARM_REG_PC)
        if (number!=2 or u.reg_read(A.UC_ARM_REG_R7)!=224 or
                not text['sh_addr']<=pc<text['sh_addr']+text['sh_size']):
            raise ValueError('Unexpected syscall')
        u.reg_write(A.UC_ARM_REG_R0,149 if case=='wrong_thread' else 380)
    def invalid(_u,access,a,size,_value,_data):
        raise ValueError(f'Unmapped access={access} address={hex(a)} size={size} r0={hex(u.reg_read(A.UC_ARM_REG_R0))}')
    u.hook_add(UC_HOOK_CODE,instruction);u.hook_add(UC_HOOK_MEM_READ,read)
    u.hook_add(UC_HOOK_MEM_WRITE,write);u.hook_add(UC_HOOK_INTR,interrupt)
    u.hook_add(UC_HOOK_MEM_INVALID,invalid)
    u.reg_write(A.UC_ARM_REG_C1_C0_2,0xf<<20);u.reg_write(A.UC_ARM_REG_FPEXC,0x40000000)
    if case in ('popup_open','state3'):
        setting_fixture = True
        u.reg_write(A.UC_ARM_REG_R0,menu+0xfb20 if case=='popup_open' else menu)
        u.reg_write(A.UC_ARM_REG_R1,1 if case=='popup_open' else 3)
        u.reg_write(A.UC_ARM_REG_SP,stack+0xff0);u.reg_write(A.UC_ARM_REG_LR,end|1)
        u.emu_start(0x15b95a57 if case=='popup_open' else 0x15b90521,end,count=100)
        if u.reg_read(A.UC_ARM_REG_PC)!=end:raise ValueError('Original fixture setter did not return')
        setting_fixture = False
    u.reg_write(A.UC_ARM_REG_R0,epoch);u.reg_write(A.UC_ARM_REG_R1,output)
    u.reg_write(A.UC_ARM_REG_SP,stack+0xff0);u.reg_write(A.UC_ARM_REG_LR,end|1)
    try:u.emu_start(entry,end,count=10000)
    except Exception as e:
        # This coupled capture lacks the layer's outer tree sentinel. Preserve
        # the boundary; do not manufacture a null parent to make it pass.
        if case=='main' and u.reg_read(A.UC_ARM_REG_PC)==0x64c6a06 and u.reg_read(A.UC_ARM_REG_R0)==0x12a160:
            return dict(case=case,status=None,returned=False,instructions=len(trace),
                        boundary=dict(kind='missing_captured_ancestor',address='0x12a16c',size=4),
                        error=str(e))
        raise ValueError(f'{case}: {e}; pc={hex(u.reg_read(A.UC_ARM_REG_PC))}') from e
    returned=u.reg_read(A.UC_ARM_REG_PC)==end
    status=u.reg_read(A.UC_ARM_REG_R0)
    if not returned or status!=int(case=='main'):
        raise ValueError('Native context guard differs: '+case)
    return dict(case=case,status=status,instructions=len(trace),context=list(struct.unpack('<9I',u.mem_read(output,36))))


def main():
    checks=[control(c) for c in ['main','popup_open','state3','header_focus',
                                'cached_row_mismatch','zero_epoch','wrong_thread']]
    (ROOT/'artifacts/analysis/menu-touch-native-context-e0131.json').write_text(
        json.dumps(dict(scope=__doc__,checks=checks,live_deployed=False),indent=2))
    print('6 compiled negative guards return correctly; positive control stops at uncaptured ancestor12a16c')
    print('No invented parent or live lifecycle token; module not deployed')


if __name__=='__main__':main()
