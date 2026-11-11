#!/usr/bin/env python3
"""E0351 - offline decision tool for the Track B UVC stream failure.

Runs the REAL compiled objects shipped in
artifacts/native/uvc-transport-e0349-fixed/ under Unicorn and decodes the
reference UVC class handler statically with capstone:

1. static decode of the reference `core_cb_class` (.text 0x17B0, 708 B) and
   its two helpers (0x11BC and 0x1390) with `.rel.text` applied, producing the
   EP0 decision table (setup fields -> path -> return/stall);
2. Unicorn harness for `a6400_uvc_ptp_select_endpoint` (uvc_ptp_adapter.o) and
   the session gate `shared_endpoint` (uvc_ptp_session.o), the LIVE START path
   of the shared build;
3. Unicorn harness for the bridge CLASS forwarding
   (`callback-bridge.o` -> class_cb -> invoke(CLASS)) with a recorder target,
   plus a bounded execution of the real reference class handler.

Only stdlib + capstone + unicorn are imported. The prebuilt fixture ELFs are
read with a small built-in ELF32 reader; `--rebuild` re-links them through
arm-linux-gnueabi-ld (that step needs a host interpreter that can spawn WSL;
the venv interpreter cannot in this sandbox).

Offline only: no camera, no USB, no module load.
"""
import argparse
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UcError
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4,
    UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9,
    UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR,
    UC_ARM_REG_PC, UC_CPU_ARM_CORTEX_A9,
)

ROOT = Path(__file__).resolve().parents[2]
OUT_DEFAULT = ROOT / 'artifacts/analysis/unicorn-uvc-e0351'
FIXTURE_DIR = OUT_DEFAULT
REF_KO = ROOT / ('firmware/extracted_zve10_v203_linuxnames/firmware.tar_unpacked/'
                 '0700_part_image/dev/nflasha15_unpacked/kmod/usbg_video.ko')
REF_SHA = 'd385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb'
SHIPPED_KO = ROOT / 'artifacts/native/uvc-transport-e0349-fixed/usbg_video_a6400_shared_candidate.ko'
SHIPPED_SHA = 'a1d959752d1ec665834d6f17a58e6137821bab75c9362cca75b2887c087b6692'
NATIVE = ROOT / 'artifacts/native/uvc-transport-e0349-fixed'

CLASS_ENTRY, CLASS_SIZE = 0x17B0, 0x2C4
HELPER_GET, HELPER_GET_SIZE = 0x1390, 0x420
HELPER_TEMPLATE, HELPER_TEMPLATE_SIZE = 0x11BC, 0x1D4
REF_TEXT_FILE_OFF = 0x34

SELECTOR_ELF = FIXTURE_DIR / 'selector-unicorn.elf'
BRIDGE_ELF = FIXTURE_DIR / 'bridge-unicorn.elf'
REFLASS_ELF = FIXTURE_DIR / 'reference-class-unicorn.elf'
BUILD_SCRIPT = FIXTURE_DIR / 'build-fixtures.sh'

# hashes of the audited-build objects the fixtures were linked from. If a later
# rebuild of artifacts/native/uvc-transport-e0349-fixed/ changes them, the tool
# reports fixture_inputs_match=false (the fixture ELFs stay pinned).
FIXTURE_INPUT_SHA = {
    'uvc_ptp_adapter.o': '4d97373fdc5b27a6741485d9617f85a896c7b031f36a89c57104e5508bcbdf3a',
    'uvc_ptp_session.o': '558206a653003763ba9226f1137408206b592ea3bb64ed3c2fc7b8e654275925',
    'callback-bridge.o': '54bd60e93b585df8087f8c616d00c172a84440b801453434407e4ceed08d5ba9',
    'reference.rebound.o': '800299aa2d355c61d61c251200993fd1a4cced9284e0027a1704c236c57e6653',
}

SENTINEL_PAGE = 0x5FFFFFFF & ~0xFFF          # 0x5ffff000
RET_SENTINEL = SENTINEL_PAGE

# selector harness scratch
DWC, DEP, DESC, WRAP0, WRAP1, LIST, GC, SESSION = (
    0x60100000, 0x60101000, 0x60102000, 0x60103000, 0x60104000, 0x60105000,
    0x60110000, 0x60120000)
STACK = 0x60180000
GADGET = DWC + 0x150

# bridge harness scratch
BR, REFDESC, IFACES, NAMES, RECORDER, SLOT, SETUP = (
    0x60000000, 0x60001000, 0x60002000, 0x60003000, 0x60010000, 0x60011000, 0x60012000)

# reference-class harness scratch
R_CTX, R_THISEX, R_EP, R_OPS, R_REQ, R_SETUP = (
    0x5e200000, 0x5e201000, 0x5e202000, 0x5e203000, 0x5e204000, 0x5e205000)
R_CODE = 0x5e206000
R_STUB = 0x5e100000
R_STUB_MEMCPY = R_STUB + 0x000
R_STUB_EVENTQ = R_STUB + 0x100
R_STUB_OSALALLOC = R_STUB + 0x200
R_STUB_SNDSYNC = R_STUB + 0x300
R_STUB_SNDMSG = R_STUB + 0x400
R_STUB_FREE = R_STUB + 0x500
R_STUB_SNPRINTF = R_STUB + 0x600
R_STUB_MEMSET = R_STUB + 0x700
R_STUB_PRINTK = R_STUB + 0x800
R_STACK = 0x5e210000
R_SP = 0x5e214000


# --------------------------------------------------------------------------
# minimal ELF32 reader (stdlib only)
# --------------------------------------------------------------------------
class Elf32:
    def __init__(self, path):
        self.path = Path(path)
        self.raw = self.path.read_bytes()
        r = self.raw
        if r[:4] != b'\x7fELF' or r[4] != 1 or r[5] != 1:
            raise ValueError(f'{self.path.name}: not a little-endian ELF32')
        (self.e_phoff,) = struct.unpack_from('<I', r, 0x1C)
        self.e_phentsize, self.e_phnum = struct.unpack_from('<HH', r, 0x2A)
        (self.e_shoff,) = struct.unpack_from('<I', r, 0x20)
        self.e_shentsize, self.e_shnum, self.e_shstrndx = struct.unpack_from('<HHH', r, 0x2E)
        self.segments = []      # (vaddr, bytes, memsz, flags)
        for i in range(self.e_phnum):
            o = self.e_phoff + i * self.e_phentsize
            p_type, p_offset, p_vaddr, _p_paddr, p_filesz, p_memsz, p_flags, _al = \
                struct.unpack_from('<IIIIIIII', r, o)
            if p_type == 1:     # PT_LOAD
                self.segments.append((p_vaddr, r[p_offset:p_offset + p_filesz], p_memsz, p_flags))
        self._sections = []
        names = b''
        if self.e_shoff and self.e_shnum:
            shs = []
            for i in range(self.e_shnum):
                o = self.e_shoff + i * self.e_shentsize
                shs.append(struct.unpack_from('<IIIIIIIIII', r, o))
            if self.e_shstrndx < len(shs):
                noff, nsize = shs[self.e_shstrndx][4], shs[self.e_shstrndx][5]
                names = r[noff:noff + nsize]
            for sh in shs:
                nm = _cstr(names, sh[0])
                self._sections.append({'name': nm, 'type': sh[1], 'addr': sh[3],
                                       'offset': sh[4], 'size': sh[5], 'link': sh[6],
                                       'entsize': sh[9]})
        self._syms = None

    def section(self, name):
        for s in self._sections:
            if s['name'] == name:
                return s
        return None

    def symbols(self):
        if self._syms is not None:
            return self._syms
        out = {}
        symtab = next((s for s in self._sections if s['type'] == 2), None)
        if not symtab:
            raise ValueError(f'{self.path.name}: no .symtab')
        strtab = self._sections[symtab['link']]
        strdata = self.raw[strtab['offset']:strtab['offset'] + strtab['size']]
        base = symtab['offset']
        count = symtab['size'] // 16
        for i in range(count):
            st_name, st_value, st_size, st_info, _other, st_shndx = \
                struct.unpack_from('<IIIBBH', self.raw, base + i * 16)
            if st_shndx == 0:
                continue
            name = _cstr(strdata, st_name)
            if name:
                out[name] = (st_value, st_size, st_shndx)
        self._syms = out
        return out

    def load(self, uc):
        ranges = []
        for vaddr, data, memsz, _flags in self.segments:
            start = vaddr & ~0xFFF
            end = (vaddr + max(memsz, len(data)) + 0xFFF) & ~0xFFF
            ranges.append((start, end))
        merged = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        for start, end in merged:
            uc.mem_map(start, end - start)
        for vaddr, data, _memsz, _flags in self.segments:
            if data:
                uc.mem_write(vaddr, data)
        return merged


def _cstr(buf, off):
    if off >= len(buf):
        return ''
    end = buf.find(b'\x00', off)
    return buf[off:end if end >= 0 else len(buf)].decode('ascii', 'replace')


def _map(uc, addr, size=0x1000):
    start = addr & ~0xFFF
    end = (addr + size + 0xFFF) & ~0xFFF
    try:
        uc.mem_map(start, end - start)
    except UcError:
        pass


def put32(uc, addr, value):
    uc.mem_write(addr, int(value & 0xFFFFFFFF).to_bytes(4, 'little'))


def put8(uc, addr, value):
    uc.mem_write(addr, bytes([value & 0xFF]))


def get32(uc, addr):
    return struct.unpack('<I', uc.mem_read(addr, 4))[0]


def _mov32(uc, addr, rd, value):
    """movw rd,#lo ; movt rd,#hi  (ARM, little endian)."""
    value &= 0xFFFFFFFF
    lo, hi = value & 0xFFFF, value >> 16
    movw = 0xE3000000 | ((lo >> 12) << 16) | ((rd & 0xF) << 12) | (lo & 0xFFF)
    movt = 0xE3400000 | ((hi >> 12) << 16) | ((rd & 0xF) << 12) | (hi & 0xFFF)
    uc.mem_write(addr, struct.pack('<II', movw, movt))


def _stub_return(uc, addr, value):
    """mov r0,#value ; bx lr"""
    uc.mem_write(addr, struct.pack('<II', 0xE3A00000 | (value & 0xFF), 0xE12FFF1E))


def _stub_pointer(uc, addr, value):
    """mov32 r0,value ; bx lr"""
    _mov32(uc, addr, 0, value)
    uc.mem_write(addr + 8, struct.pack('<I', 0xE12FFF1E))


def _new_cpu():
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A9)
    _map(cpu, SENTINEL_PAGE)
    cpu.mem_write(RET_SENTINEL, struct.pack('<I', 0xE12FFF1E))  # bx lr
    return cpu


def call_arm(cpu, entry, args=(), stack=R_SP, max_insns=4000, stop_pc=None,
             hooks=(), read_log=None):
    """Call an ARM function, stop at the return sentinel or a stub's LR."""
    stop = RET_SENTINEL if stop_pc is None else stop_pc
    done = {'hit': False}
    handles = []

    def _code(uc, pc, size, user):
        if pc == stop:
            done['hit'] = True
            uc.emu_stop()

    handles.append(cpu.hook_add(UC_HOOK_CODE, _code))
    if read_log is not None:
        watched = read_log['addresses']

        def _read(uc, access, addr, size, value, user):
            if addr in watched and len(read_log['reads']) < 24:
                try:
                    raw = int.from_bytes(uc.mem_read(addr, 4), 'little')
                except UcError:
                    raw = 0
                read_log['reads'].append({'pc': hex(uc.reg_read(UC_ARM_REG_PC)),
                                          'addr': hex(addr), 'size': size,
                                          'value': hex(raw)})
        handles.append(cpu.hook_add(UC_HOOK_MEM_READ, _read))
    pre_hooks = []
    for hook in hooks:
        pre_hooks.append(hook(cpu))
    for i, value in enumerate(args):
        cpu.reg_write([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                       UC_ARM_REG_R3][i], value)
    cpu.reg_write(UC_ARM_REG_SP, stack)
    cpu.reg_write(UC_ARM_REG_LR, stop)
    error = None
    try:
        cpu.emu_start(entry, 0xFFFFFFFF, count=max_insns)
    except UcError as exc:
        error = f'{exc.__class__.__name__}: {exc}'
    finally:
        for handle in handles:
            try:
                cpu.hook_del(handle)
            except UcError:
                pass
    return {'stopped': done['hit'], 'error': error,
            'pc': cpu.reg_read(UC_ARM_REG_PC),
            'r0': cpu.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF,
            'insn_count': None}


# --------------------------------------------------------------------------
# reference class handler: static decode
# --------------------------------------------------------------------------
def _relocations(elf):
    rel = elf.section('.rel.text')
    symtab = next(s for s in elf._sections if s['type'] == 2)
    strtab = elf._sections[symtab['link']]
    strdata = elf.raw[strtab['offset']:strtab['offset'] + strtab['size']]
    names = []
    for i in range(symtab['size'] // 16):
        st_name, _val, _size, _info, _other, st_shndx = \
            struct.unpack_from('<IIIBBH', elf.raw, symtab['offset'] + i * 16)
        name = _cstr(strdata, st_name)
        if not name and st_shndx < len(elf._sections):
            name = f"<section {elf._sections[st_shndx]['name']}>"
        names.append(name)
    out = {}
    if not rel:
        return out
    count = rel['size'] // 8
    for i in range(count):
        r_offset, r_info = struct.unpack_from('<II', elf.raw, rel['offset'] + i * 8)
        index = r_info >> 8
        out[r_offset] = {'type': r_info & 0xFF,
                         'symbol': names[index] if index < len(names) else ''}
    return out


def _literal_addr(insn):
    """Return the PC-relative literal address of an `ldr rX,[pc,#imm]`, else None."""
    if insn.mnemonic != 'ldr' or '[pc' not in insn.op_str:
        return None
    try:
        imm = insn.op_str.split('#', 1)[1].rstrip(']')
        return insn.address + 8 + int(imm, 0)
    except (IndexError, ValueError):
        return None


def decode_class_handler():
    raw = REF_KO.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != REF_SHA:
        raise ValueError(f'reference module hash mismatch: {digest}')
    text = raw[REF_TEXT_FILE_OFF:REF_TEXT_FILE_OFF + 0x2B90]
    elf = Elf32(REF_KO)
    rel = _relocations(elf)
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    md.detail = False

    def disasm(start, size):
        rows = []
        for insn in md.disasm(text[start:start + size], start):
            note = ''
            r = rel.get(insn.address)
            if r and r['type'] == 28:
                note = r['symbol']
            lit = _literal_addr(insn)
            lit_note = ''
            if lit is not None and lit in rel:
                lr = rel[lit]
                lit_note = (lr['symbol'] or f"<section reloc>")
                if lit < len(text):
                    lit_note += f" (word {struct.unpack_from('<I', text, lit)[0]:#010x})"
            rows.append({'addr': f'0x{insn.address:04x}', 'bytes': insn.bytes.hex(),
                         'insn': f'{insn.mnemonic} {insn.op_str}'.strip(),
                         'call': note, 'literal': lit_note})
        return rows

    class_rows = disasm(CLASS_ENTRY, CLASS_SIZE)
    get_rows = disasm(HELPER_GET, HELPER_GET_SIZE)
    tmpl_rows = disasm(HELPER_TEMPLATE, HELPER_TEMPLATE_SIZE)

    shipped = SHIPPED_KO.read_bytes()
    if hashlib.sha256(shipped).hexdigest() != SHIPPED_SHA:
        raise ValueError('shipped module hash mismatch')
    s_elf = Elf32(SHIPPED_KO)
    s_text = s_elf.section('.text')
    shipped_class = shipped[s_text['offset'] + CLASS_ENTRY:s_text['offset'] + CLASS_ENTRY + CLASS_SIZE]
    ref_class = text[CLASS_ENTRY:CLASS_ENTRY + CLASS_SIZE]

    rodata = raw[0x2DEC:0x2DEC + 0x94]
    uvc_template = rodata[0x7A:0x7A + 26]

    return {
        'reference_module': str(REF_KO.relative_to(ROOT)).replace('\\', '/'),
        'reference_sha256': digest,
        'shipped_module': str(SHIPPED_KO.relative_to(ROOT)).replace('\\', '/'),
        'shipped_sha256': SHIPPED_SHA,
        'class_handler_sha256': hashlib.sha256(ref_class).hexdigest(),
        'class_handler_identical_in_shipped_build': shipped_class == ref_class,
        'raw_hex': {'class_0x17b0': ref_class.hex(),
                    'helper_0x1390': text[HELPER_GET:HELPER_GET + HELPER_GET_SIZE].hex(),
                    'helper_0x11bc': text[HELPER_TEMPLATE:HELPER_TEMPLATE + HELPER_TEMPLATE_SIZE].hex(),
                    'rodata_template_0x7a': uvc_template.hex()},
        'disassembly': {'core_cb_class': class_rows, 'helper_0x1390': get_rows,
                        'helper_0x11bc': tmpl_rows},
        'uvc_streaming_control_template': {
            'bytes_hex': uvc_template.hex(),
            'parsed': {
                'bmHint': int.from_bytes(uvc_template[0:2], 'little'),
                'bFormatIndex': uvc_template[2],
                'bFrameIndex': uvc_template[3],
                'dwFrameInterval': int.from_bytes(uvc_template[4:8], 'little'),
                'wKeyFrameRate': int.from_bytes(uvc_template[8:10], 'little'),
                'wPFrameRate': int.from_bytes(uvc_template[10:12], 'little'),
                'wCompQuality': int.from_bytes(uvc_template[12:14], 'little'),
                'wCompWindowSize': int.from_bytes(uvc_template[14:16], 'little'),
                'wDelay': int.from_bytes(uvc_template[16:18], 'little'),
                'dwMaxVideoFrameSize': int.from_bytes(uvc_template[18:22], 'little'),
                'dwMaxPayloadTransferSize': int.from_bytes(uvc_template[22:26], 'little'),
                'dwClockFrequency_present': False,
            },
            'note': ('26-byte template: UVC 1.0 probe fields 0..25. dwClockFrequency '
                     '(26..29) and bmFramingInfo/versions (30..33) are not in the template; '
                     'the GET reply copies wLength bytes from this stack frame.'),
        },
        'relocations_in_range': {f'0x{off:04x}': r for off, r in sorted(rel.items())
                                 if 0x11BC <= off < 0x1AC8},
        'decision_table': decision_table(),
        'undecidable': [
            {'item': 'indirect dispatch through the user callback vector',
             'detail': ('core_cb_class notifies this_ex callback slot 7 through '
                        'usbg_video_call_user_cb -> usb_event_add_queue; the slot is '
                        'installed by libInfraUsbCmn, not present in usbg_video.ko')},
            {'item': 'controller-side semantics of return values 1 and 2',
             'detail': ('gadgetcore maps class-handler returns to stall/handled; the '
                        'mapping is in vmlinux (0x602bxxx), not in this module. '
                        '2 is used as NOT_HANDLED by the a6400 bridge (E0136).')},
            {'item': 'which this_ex state (+0xa8) selects the frame interval',
             'detail': ('no str to +0xa8 exists in usbg_video.ko .text; 1 -> 333333 '
                        '(30 fps), 2 -> 400000 (25 fps), other -> template value kept')},
        ],
    }


def decision_table():
    """EP0 class-request decision table, keyed to instruction addresses."""
    return [
        {'id': 'T1', 'request': 'bmRequestType bit5 clear (e.g. 0x01 SET_INTERFACE, 0x00 GET_STATUS)',
         'field': 'setup[0]&0x20 == 0', 'addr': '0x17d4 tst r3,#0x20 / 0x17d8 beq 0x1a58',
         'action': 'not a class request', 'return': '2 (NOT_HANDLED)',
         'evidence': '0x1a58 mov r4,#2; 0x1a64 mov r0,r4'},
        {'id': 'T2', 'request': 'class, recipient 0 or >=3 (e.g. 0x20 device, 0x23 other)',
         'field': '(setup[0]&0x1f)-1 > 1', 'addr': '0x17dc and #0x1f / 0x17e0 sub #1 / 0x17e8 bhi 0x1a58',
         'action': 'recipient not interface(1)/endpoint(2)', 'return': '2 (NOT_HANDLED)',
         'evidence': '0x1a58'},
        {'id': 'T3', 'request': 'class, bRequest not in {0x01,0x81..0x87}',
         'field': 'setup[1]', 'addr': '0x17ec ldrb r4,[r1,#1]; 0x180c/0x1834 bne 0x1a60',
         'action': 'unsupported class request', 'return': '1 (stall)',
         'evidence': '0x1a60 mov r4,#1'},
        {'id': 'T4', 'request': '0x21/0x22 bRequest 0x01 SET_CUR (any wValue/wIndex/wLength)',
         'field': 'setup[1]==1', 'addr': '0x1808 cmp r4,#1 / 0x1810 b 0x183c',
         'action': ('alloc ep0 request, buf=usbg_video_get_ep0_buffer() (this_ex+0x1c), '
                    'length=wLength (no selector or length bound), complete=uvc_ep0_comp, '
                    'queue via ep->ops+0x10'),
         'return': '0 if alloc+queue succeed; 1 if either fails',
         'evidence': ('0x183c..0x1914 (wLength 0x184c; alloc 0x1858; ep0 buf 0x188c; '
                      'req fill 0x18e8..0x1904; queue 0x1914; success 0x191c mov r4,#0; '
                      'failure path 0x1968..0x1978 -> r4=1')},
        {'id': 'T5', 'request': 'SET_CUR with wValue==0x0200 (VS_COMMIT_CONTROL)',
         'field': 'setup[2..3]==0x0200', 'addr': '0x1980..0x1990 / 0x19e8 bl usbg_video_call_user_cb',
         'action': 'after a successful queue: notify user callback slot 7 with (7,{2},4)',
         'return': '0 (the notify return is discarded)',
         'evidence': '0x198c cmp r3,#0x200; 0x199c mov r0,#7; 0x19e8 reloc usbg_video_call_user_cb'},
        {'id': 'T6', 'request': '0xA1 bRequest 0x81/0x82/0x83 (GET_CUR/MIN/MAX)',
         'field': 'setup[0]==0xA1, setup[1] in 0x81..0x83',
         'addr': '0x1800/0x1804 -> 0x19b0/0x19c4/0x19f0 -> bl 0x1390',
         'action': 'helper 0x1390 validates wIndex/wValue and builds the reply',
         'return': 'helper result (0 ok / 1 stall); 0x82 and 0x83 also notify slot 7',
         'evidence': '0x19b8/0x19cc/0x19f8 reloc bl 0x1390'},
        {'id': 'T6a', 'request': 'GET_* with wIndex high byte != 0 (entity ID in wIndex)',
         'field': 'setup[5]!=0', 'addr': '0x13d4..0x13e0 lsrs r7,r5,#8 / 0x13e4 bne 0x16f8',
         'action': 'reject; writes .bss+0x34 = 6', 'return': '1 (stall)',
         'evidence': '0x16f8 ldr r3,[pc,#0xac] (.bss); 0x170c strb r2,[r3,#0x34]'},
        {'id': 'T6b', 'request': 'GET_* wIndex!=0 and wValue 0x0100/0x0200 (VS PROBE/COMMIT)',
         'field': 'setup[4]&0xff != 0 and setup[2..3] in {0x0100,0x0200}',
         'addr': '0x13e8 ands/bne 0x1690; 0x1694/0x169c cmp; 0x16a4 -> bl 0x11bc',
         'action': ('reply = 26-byte probe template from .rodata+0x7a, dwFrameInterval '
                    'patched from this_ex+0xa8, memcpy(ep0buf, template, wLength)'),
         'return': ('0 on success; -12 when usbg_video_get_ep0_buffer() is NULL; '
                    '1 when request alloc or queue fails'),
         'evidence': ('0x11d4 mov r2,#0x1a; 0x11e4 memcpy; 0x11ec ldr [this_ex+0xa8]; '
                      '0x12cc/0x12d4 memcpy(ep0buf, fp-0x46, wLength); 0x1318 queue')},
        {'id': 'T6c', 'request': 'GET_* wIndex!=0 and other wValue',
         'field': 'setup[2..3] not 0x0100/0x0200', 'addr': '0x16b0',
         'action': 'reject', 'return': '1 (stall)', 'evidence': '0x16b0..0x174c -> 0x179c mov r0,#1'},
        {'id': 'T6d', 'request': 'GET_* wIndex==0, wValue==0x0100',
         'field': 'setup[4..5]==0 and setup[2..3]==0x0100', 'addr': '0x13f8..0x1400 -> 0x1410',
         'action': 'queue wLength bytes from a stack byte holding wIndex low (0x00)',
         'return': '0', 'evidence': '0x141c strb r5,[fp,#-0x2c]; 0x1488 memcpy'},
        {'id': 'T6e', 'request': 'GET_* wIndex==0, wValue==0x0200',
         'field': 'setup[4..5]==0 and setup[2..3]==0x0200', 'addr': '0x1404/0x140c -> 0x14f4',
         'action': 'queue wLength bytes; first byte = .bss+0x34',
         'return': '0', 'evidence': '0x1504 ldr r3,[pc,#0x2a0] (.bss); 0x1508 ldrb r3,[r3,#0x34]'},
        {'id': 'T6f', 'request': 'GET_* wIndex==0 and other wValue',
         'field': 'setup[2..3] not 0x0100/0x0200', 'addr': '0x13fc..0x1408 bne 0x1648',
         'action': 'reject', 'return': '1 (stall)', 'evidence': '0x1648..0x168c -> 0x1794'},
        {'id': 'T7', 'request': '0xA1 bRequest 0x84 GET_RES', 'field': 'setup[1]==0x84',
         'addr': '0x1814..0x1824 -> 0x1a40 -> 0x1a50 bl usbg_video_call_user_cb',
         'action': 'notify slot 7 with (7,{6},4)', 'return': '1 (stall)',
         'evidence': '0x181c movlo r3,#6; 0x1a54 b 0x1a60'},
        {'id': 'T8', 'request': '0xA1 bRequest 0x85 GET_LEN', 'field': 'setup[1]==0x85',
         'addr': '0x1818 -> 0x1a1c -> 0x1a48 -> 0x1a50 bl usbg_video_call_user_cb',
         'action': 'notify slot 7 with (7,{7},4)', 'return': '1 (stall)',
         'evidence': '0x1a20 mov r0,#7'},
        {'id': 'T9', 'request': '0xA1 bRequest 0x86/0x87 GET_INFO/GET_DEF',
         'field': 'setup[1]==0x86/0x87', 'addr': '0x182c/0x1834 -> 0x1a2c/0x1a38 -> 0x1a40',
         'action': 'notify slot 7 with (7,{8/9},4)', 'return': '1 (stall)',
         'evidence': '0x1a2c mov r3,#8; 0x1a38 mov r3,#9'},
    ]


# --------------------------------------------------------------------------
# harness 1: a6400_uvc_ptp_select_endpoint + session gate
# --------------------------------------------------------------------------
def _selector_cpu():
    elf = Elf32(SELECTOR_ELF)
    cpu = _new_cpu()
    elf.load(cpu)
    syms = elf.symbols()
    for name in ('a6400_uvc_ptp_select_endpoint', 'shared_endpoint', 'owner'):
        if name not in syms:
            raise ValueError(f'{SELECTOR_ELF.name}: missing symbol {name}')
    for page in (DWC, DEP, DESC, WRAP0, WRAP1, LIST, GC, SESSION):
        _map(cpu, page)
    _map(cpu, STACK, 0x8000)
    return cpu, syms


def _selector_layout(cpu, *, dep=DEP, desc_addr=DESC, enabled=1, endpoint=0x84,
                     attributes=0x02, maxpacket=(0x00, 0x02),
                     blength=7, btype=5,
                     wrappers=(WRAP0,), wrapper_raw=None, desc_present=True,
                     speed=3, gadget_present=True, owner_set=False):
    put32(cpu, DWC + 0xF4, dep)
    put32(cpu, DEP + 0x4C, enabled)
    put32(cpu, DEP + 0x1C, desc_addr if desc_present else 0)
    put8(cpu, DESC, blength)
    put8(cpu, DESC + 1, btype)
    put8(cpu, DESC + 2, endpoint)
    put8(cpu, DESC + 3, attributes)
    put8(cpu, DESC + 4, maxpacket[0])
    put8(cpu, DESC + 5, maxpacket[1])
    # gadget = dwc + 0x150; speed at gadget+0x20
    put32(cpu, GC, GADGET if gadget_present else 0)
    put32(cpu, GADGET + 0x20, speed)
    put32(cpu, SESSION + 0x14, GC)          # struct a6400_uvc_ptp_session.gc
    if owner_set:
        put32(cpu, 0x5F010000, SESSION)     # static `owner` (0x5f010000, .bss)
    for index, wrapper in enumerate(wrappers):
        put32(cpu, LIST + index * 4, wrapper)
        if wrapper:
            put32(cpu, wrapper + 0x24, dep if wrapper_raw is None else wrapper_raw)
    return len(wrappers)


def run_selector_cases():
    cases = []

    def run(name, expected_note, entry='a6400_uvc_ptp_select_endpoint', args=None,
            count=None, list_addr=LIST, **layout):
        cpu, syms = _selector_cpu()
        n = _selector_layout(cpu, owner_set=(entry == 'shared_endpoint'), **layout)
        if count is None:
            count = n
        reads = {'addresses': {DWC + 0xF4, DEP + 0x4C, DEP + 0x1C, WRAP0 + 0x24,
                               WRAP1 + 0x24}, 'reads': []}
        if entry == 'shared_endpoint':
            call_args = (count, list_addr)
            target = syms[entry][0]
        else:
            call_args = (DWC, count, list_addr) if args is None else args
            target = syms[entry][0]
        res = call_arm(cpu, target, call_args, stack=STACK + 0x8000,
                       max_insns=3000, read_log=reads)
        cases.append({'case': name, 'expect': expected_note,
                      'result': res['r0'], 'stopped': res['stopped'],
                      'error': res['error'], 'reads': reads['reads']})
        return cases[-1]

    def case(name, expect, ok, **kwargs):
        row = run(name, expect, **kwargs)
        row['pass'] = (row['result'] == ok) and row['stopped'] and row['error'] is None
        row['expected_result'] = ok
        return row

    case('expected-live-0x84-one-wrapper', 'returns wrapper (0x60103000)', WRAP0)
    case('expected-live-session-gate-speed3', 'shared_endpoint returns wrapper', WRAP0,
         entry='shared_endpoint')
    case('session-gate-speed-not-3', 'shared_endpoint returns 0', 0,
         entry='shared_endpoint', speed=2)
    case('session-gate-gadget-null', 'shared_endpoint returns 0', 0,
         entry='shared_endpoint', gadget_present=False)
    case('endpoint-0x81-rejected', 'returns 0 (composite requires 0x84)', 0, endpoint=0x81)
    case('endpoint-0x85-rejected', 'returns 0', 0, endpoint=0x85)
    case('maxpacket-64-rejected', 'returns 0 (FS/full-speed 64-byte wMaxPacketSize)', 0,
         maxpacket=(0x40, 0x00))
    case('maxpacket-low-byte-nonzero-rejected', 'returns 0 (wMaxPacketSize != 512)', 0,
         maxpacket=(0x01, 0x02))
    case('attributes-interrupt-rejected', 'returns 0', 0, attributes=0x03)
    case('attributes-iso-rejected', 'returns 0', 0, attributes=0x01)
    case('blength-9-rejected', 'returns 0 (descriptor bLength != 7)', 0, blength=9)
    case('bdescriptortype-not-5-rejected', 'returns 0', 0, btype=4)
    case('dep-disabled-flag-rejected', 'returns 0 (dep+0x4c bit0 == 0)', 0, enabled=0)
    case('dep-null-rejected', 'returns 0 (*(dwc+0xf4) == 0)', 0, dep=0)
    case('descriptor-null-rejected', 'returns 0 (*(dep+0x1c) == 0)', 0, desc_present=False)
    case('wrapper-owns-other-dep-rejected', 'returns 0', 0, wrapper_raw=DEP + 0x1000)
    case('duplicate-matching-wrappers-rejected', 'returns 0 (ambiguous ownership)', 0,
         wrappers=(WRAP0, WRAP1))
    case('null-list-slot-skipped', 'returns the single matching wrapper', WRAP0,
         wrappers=(0, WRAP0), count=2)
    case('count-0-rejected', 'returns 0', 0, count=0)
    case('count-17-rejected', 'returns 0 (count>16)', 0, count=17)
    case('list-null-rejected', 'returns 0', 0, list_addr=0)
    case('dwc-null-rejected', 'returns 0', 0,
         entry='a6400_uvc_ptp_select_endpoint', args=(0, 1, LIST))
    case('packed-count-high-bits-masked', 'returns wrapper (low byte count)', WRAP0,
         count=0xAB01)
    return cases


# --------------------------------------------------------------------------
# harness 2: bridge CLASS forwarding
# --------------------------------------------------------------------------
def _bridge_cpu():
    elf = Elf32(BRIDGE_ELF)
    cpu = _new_cpu()
    elf.load(cpu)
    syms = elf.symbols()
    for name in ('a6400_uvc_bridge_prepare', 'a6400_uvc_bridge_activate',
                 'a6400_uvc_bridge_shadow', 'a6400_uvc_bridge_size'):
        if name not in syms:
            raise ValueError(f'{BRIDGE_ELF.name}: missing symbol {name}')
    for page in (BR, REFDESC, IFACES, NAMES, RECORDER, SLOT, SETUP,
                 0x60004000, 0x60005000):
        _map(cpu, page)
    _map(cpu, STACK, 0x8000)
    # recorder: store r0..r3 at SLOT, return 0xC0DE
    code = struct.pack('<IIIII', 0xE59FC008, 0xE88C000F, 0xE59F0004, 0xE12FFF1E, SLOT)
    cpu.mem_write(RECORDER, code + struct.pack('<I', 0xC0DE))
    return cpu, syms


def _bridge_layout(cpu, *, target=RECORDER, interfaces=(1, 2)):
    put32(cpu, NAMES, 0x60004000)
    cpu.mem_write(0x60004000, b'usbg_video\x00')
    put8(cpu, IFACES, interfaces[0])
    put8(cpu, IFACES + 1, interfaces[1])
    put32(cpu, REFDESC + 0x00, 0x60004000)      # name
    put8(cpu, REFDESC + 0x04, 1)                # config
    put8(cpu, REFDESC + 0x05, interfaces[0])    # primary_interface
    put32(cpu, REFDESC + 0x08, IFACES)          # interfaces
    put8(cpu, REFDESC + 0x0C, 2)                # interface_count
    put32(cpu, REFDESC + 0x10, 0x60005000)      # private_data
    for slot in (0, 1, 7):
        put32(cpu, REFDESC + 0x18 + slot * 4, target)


def _bridge_call(cpu, syms, *, activate=True, setup=None,
                 shadow_index=1, null_class_target=False, mutate=None):
    b, r = BR, REFDESC
    res = call_arm(cpu, syms['a6400_uvc_bridge_prepare'][0], (b, r),
                   stack=STACK + 0x8000, max_insns=4000)
    steps = {'prepare': res['r0'], 'activate': None, 'shadow': None, 'thunk': None}
    if res['r0'] != 0 or not res['stopped']:
        steps['error'] = res['error']
        return steps
    if activate:
        res = call_arm(cpu, syms['a6400_uvc_bridge_activate'][0], (b, 3),
                       stack=STACK + 0x8000, max_insns=4000)
        steps['activate'] = res['r0']
        if res['r0'] != 0:
            steps['error'] = res['error']
            return steps
    res = call_arm(cpu, syms['a6400_uvc_bridge_shadow'][0], (b, shadow_index),
                   stack=STACK + 0x8000, max_insns=4000)
    shadow = res['r0']
    steps['shadow'] = hex(shadow) if res['stopped'] and res['error'] is None else None
    if not shadow:
        steps['error'] = res['error'] or 'shadow null'
        return steps
    if null_class_target:
        put32(cpu, shadow + 0x2c, 0)
    if mutate:
        for offset, value in mutate:
            put8(cpu, REFDESC + offset, value)
    thunk = get32(cpu, shadow + 0x2C)
    if not thunk:
        steps['thunk'] = 'none'
        steps['result'] = None
        return steps
    put32(cpu, SLOT, 0xEEEE0000)
    res = call_arm(cpu, thunk, (shadow, SETUP if setup is None else setup, 0, 0),
                   stack=STACK + 0x8000, max_insns=6000)
    steps['result'] = res['r0']
    steps['thunk'] = hex(thunk)
    steps['stopped'] = res['stopped']
    steps['error'] = res['error']
    steps['recorder'] = [hex(get32(cpu, SLOT + 4 * i)) for i in range(4)] \
        if get32(cpu, SLOT) != 0xEEEE0000 else []
    return steps


def _setup_packet(uc, addr, bm, bRequest, wValue, wIndex, wLength):
    uc.mem_write(addr, struct.pack('<BBHHH', bm, bRequest, wValue, wIndex, wLength))


def run_bridge_cases():
    out = []

    def run(name, bm, breq, wvalue, windex=2, wlength=34, shadow_index=1, ok_forward=True,
            **kwargs):
        cpu, syms = _bridge_cpu()
        _bridge_layout(cpu)
        _setup_packet(cpu, SETUP, bm, breq, wvalue, windex, wlength)
        steps = _bridge_call(cpu, syms, setup=SETUP, shadow_index=shadow_index, **kwargs)
        forwarded = steps.get('recorder') == [hex(REFDESC), hex(SETUP), '0x0', '0x0']
        out.append({'case': name, 'setup': {'bmRequestType': f'0x{bm:02x}',
                                            'bRequest': f'0x{breq:02x}',
                                            'wValue': f'0x{wvalue:04x}',
                                            'wIndex': f'0x{windex:04x}',
                                            'wLength': wlength},
                    'shadow_index': shadow_index, 'steps': steps,
                    'forwarded': forwarded,
                    'expect_forward': ok_forward,
                    'pass': forwarded == ok_forward and steps.get('error') is None})
        return out[-1]

    run('vs-set-cur-probe-iface2', 0x21, 0x01, 0x0100)
    run('vs-set-cur-commit-iface2', 0x21, 0x01, 0x0200)
    run('vs-get-cur-probe-iface2', 0xA1, 0x81, 0x0100)
    run('vc-get-cur-iface1-shadow0', 0xA1, 0x81, 0x0100, windex=1, shadow_index=0)
    run('mismatched-interface-iface2-on-shadow0', 0x21, 0x01, 0x0100, shadow_index=0,
        ok_forward=False)
    run('mismatched-interface-iface1-on-shadow1', 0xA1, 0x81, 0x0100, windex=1,
        shadow_index=1, ok_forward=False)
    run('endpoint-recipient-not-filtered', 0x22, 0x01, 0x0100, ok_forward=True)
    run('standard-set-interface-forwarded', 0x01, 0x0B, 0x0001, ok_forward=True)
    run('inactive-bridge-not-handled', 0x21, 0x01, 0x0100, ok_forward=False,
        activate=False)
    run('stale-snapshot-not-handled', 0x21, 0x01, 0x0100, ok_forward=False,
        mutate=[(0x04, 9)])
    run('null-class-target-not-handled', 0x21, 0x01, 0x0100, ok_forward=False,
        null_class_target=True)
    cpu, syms = _bridge_cpu()
    _bridge_layout(cpu)
    steps = _bridge_call(cpu, syms, setup=0)
    out.append({'case': 'null-setup-not-handled', 'setup': None, 'steps': steps,
                'forwarded': bool(steps.get('recorder')),
                'expect_forward': False,
                'pass': steps.get('result') == 2 and not steps.get('recorder')})
    return out


# --------------------------------------------------------------------------
# harness 3: bounded execution of the real reference class handler
# --------------------------------------------------------------------------
def _refclass_cpu():
    elf = Elf32(REFLASS_ELF)
    cpu = _new_cpu()
    elf.load(cpu)
    syms = elf.symbols()
    for name in ('core_cb_class', 'usbg_video_get_ep0_buffer', 'usbg_video_get_this',
                 'usbg_video_get_this_ex', 'usbg_video_call_user_cb', 'uvc_ep0_comp'):
        if name not in syms:
            raise ValueError(f'{REFLASS_ELF.name}: missing symbol {name}')
    bss = elf.section('.bss')
    for page in (R_CTX, R_THISEX, R_EP, R_OPS, R_REQ, R_SETUP, R_CODE, R_STUB):
        _map(cpu, page)
    _map(cpu, R_STACK, R_SP - R_STACK)
    # unused imports resolve to no-op stubs
    for off in (0x100, 0x200, 0x300, 0x400, 0x500, 0x600, 0x700, 0x800):
        _stub_return(cpu, R_STUB + off, 0)
    cpu.mem_write(R_STACK, b'\xA5' * (R_SP - R_STACK))     # poison stack
    put32(cpu, bss['addr'] + 4, R_CTX)                     # global context pointer
    put32(cpu, R_CTX + 0xBC, R_THISEX)                     # this_ex
    put32(cpu, R_EP + 8, R_OPS)                            # ep->ops
    _stub_pointer(cpu, R_CODE + 0x00, R_REQ)               # alloc_request -> request
    _stub_return(cpu, R_CODE + 0x20, 0)                    # free_request
    _stub_return(cpu, R_CODE + 0x40, 0)                    # queue -> 0
    put32(cpu, R_OPS + 0x08, R_CODE + 0x00)
    put32(cpu, R_OPS + 0x0C, R_CODE + 0x20)
    put32(cpu, R_OPS + 0x10, R_CODE + 0x40)
    _stub_return(cpu, R_STUB_EVENTQ, 0)                    # usb_event_add_queue
    cpu.mem_write(R_STUB_MEMCPY, struct.pack('<I', 0xE12FFF1E))
    return cpu, syms, bss


def _refclass_hooks(record, eventq_calls):
    def hooks(cpu):
        def code(uc, pc, size, user):
            if pc == R_STUB_MEMCPY:
                dst, src, n = (uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1),
                               uc.reg_read(UC_ARM_REG_R2))
                data = bytes(uc.mem_read(src, n))
                uc.mem_write(dst, data)
                uc.reg_write(UC_ARM_REG_R0, dst)
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
                record.append({'stub': 'memcpy', 'dst': hex(dst), 'src': hex(src), 'n': n})
            elif pc == R_STUB_EVENTQ:
                eventq_calls.append({'args': [hex(uc.reg_read(r)) for r in
                                              (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                               UC_ARM_REG_R3)]})
                uc.reg_write(UC_ARM_REG_R0, 0)
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
            elif pc == 0x5E000180:      # osal_record_pro.clone.0: logging helper
                record.append({'stub': 'osal_record_pro.clone.0'})
                uc.reg_write(UC_ARM_REG_R0, 0)
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
            elif pc == 0x5E000958:      # module log helper (printk record)
                record.append({'stub': 'log_helper_0x958'})
                uc.reg_write(UC_ARM_REG_R0, 0)
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
        cpu.hook_add(UC_HOOK_CODE, code)
    return hooks


def run_reference_class_cases():
    cases = []

    def run(name, bm, breq, wvalue, windex, wlength, max_insns=600, queue_ret=0,
            expect=0, readbuf=False):
        cpu, syms, bss = _refclass_cpu()
        _setup_packet(cpu, R_SETUP, bm, breq, wvalue, windex, wlength)
        record, eventq = [], []
        if queue_ret != 0:
            _stub_return(cpu, R_CODE + 0x40, queue_ret & 0xFF)
        res = call_arm(cpu, syms['core_cb_class'][0], (0x60000000, R_SETUP, R_EP),
                       stack=R_SP, max_insns=max_insns,
                       hooks=[_refclass_hooks(record, eventq)])
        reply = None
        if readbuf:
            try:
                reply = bytes(cpu.mem_read(R_THISEX + 0x1C, min(wlength, 48))).hex()
            except UcError:
                reply = None
        row = {'case': name,
               'setup': {'bmRequestType': f'0x{bm:02x}', 'bRequest': f'0x{breq:02x}',
                         'wValue': f'0x{wvalue:04x}', 'wIndex': f'0x{windex:04x}',
                         'wLength': wlength},
               'result': res['r0'], 'stopped': res['stopped'], 'error': res['error'],
               'stubs': record, 'usb_event_add_queue': eventq,
               'ep0_reply_hex': reply,
               'expected_result': expect,
               'pass': res['stopped'] and res['error'] is None and res['r0'] == expect}
        cases.append(row)
        return row

    run('set-cur-probe-iface2', 0x21, 0x01, 0x0100, 0x0002, 34, expect=0)
    run('set-cur-commit-iface2', 0x21, 0x01, 0x0200, 0x0002, 34, expect=0)
    run('set-cur-probe-iface1', 0x21, 0x01, 0x0100, 0x0001, 34, expect=0)
    run('set-cur-queue-failure', 0x21, 0x01, 0x0100, 0x0002, 34, expect=1, queue_ret=0xFF)
    run('get-cur-probe-34', 0xA1, 0x81, 0x0100, 0x0002, 34, expect=0, readbuf=True)
    run('get-cur-commit-26', 0xA1, 0x81, 0x0200, 0x0002, 26, expect=0, readbuf=True)
    run('get-cur-entity-windex-highbyte', 0xA1, 0x81, 0x0100, 0x0102, 34, expect=1)
    run('set-interface-standard', 0x01, 0x0B, 0x0001, 0x0002, 0, expect=2)
    run('get-len', 0xA1, 0x85, 0x0100, 0x0002, 2, expect=1)
    run('get-cur-windex0-selector1', 0xA1, 0x81, 0x0100, 0x0000, 1, expect=0, readbuf=True)
    return cases


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------
def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _file_row(path):
    p = Path(path)
    return {'path': str(p.relative_to(ROOT)).replace('\\', '/'),
            'size': p.stat().st_size, 'sha256': _sha256(p)}


def build_fixtures_script():
    return f"""#!/bin/bash
# E0351 fixture build (reproducible). Run from a host that can spawn WSL:
#   wsl -d Ubuntu -- bash "{BUILD_SCRIPT.as_posix()}"
set -e
cd "{ROOT.as_posix().replace('C:', '/mnt/c')}"
LD=arm-linux-gnueabi-ld
OUT={OUT_DEFAULT.as_posix().replace('C:', '/mnt/c')}
$LD --unresolved-symbols=ignore-all -Ttext=0x5f000000 -Tdata=0x5f010000 -o "$OUT/selector-unicorn.elf" \\
  artifacts/native/uvc-transport-e0349-fixed/uvc_ptp_adapter.o \\
  artifacts/native/uvc-transport-e0349-fixed/uvc_ptp_session.o
$LD --unresolved-symbols=ignore-all -Ttext=0x5f000000 -Tdata=0x5f010000 -o "$OUT/bridge-unicorn.elf" \\
  artifacts/native/uvc-transport-e0349-fixed/callback-bridge.o
$LD --unresolved-symbols=ignore-all -Ttext=0x5e000000 -Tdata=0x5e010000 \\
  --defsym=memcpy=0x5e100000 --defsym=usb_event_add_queue=0x5e100100 \\
  --defsym=osal_valloc_msg_wait=0x5e100200 --defsym=osal_snd_sync_direct=0x5e100300 \\
  --defsym=osal_snd_msg=0x5e100400 --defsym=osal_free_msg=0x5e100500 \\
  --defsym=snprintf=0x5e100600 --defsym=memset=0x5e100700 --defsym=printk=0x5e100800 \\
  -o "$OUT/reference-class-unicorn.elf" \\
  artifacts/native/uvc-transport-e0349-fixed/reference.rebound.o
echo built
"""


def run(out_dir=OUT_DEFAULT, rebuild=False, verbose=True):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    BUILD_SCRIPT.write_text(build_fixtures_script(), encoding='utf-8', newline='\n')
    if rebuild:
        subprocess.run(['wsl', '-d', 'Ubuntu', '--', 'bash', str(BUILD_SCRIPT)],
                       check=True, cwd=str(ROOT))
    missing = [p for p in (SELECTOR_ELF, BRIDGE_ELF, REFLASS_ELF) if not p.exists()]
    if missing:
        raise SystemExit('missing fixtures: ' + ', '.join(p.name for p in missing) +
                         f'\nrun --rebuild (needs WSL access), script: {BUILD_SCRIPT}')

    static = decode_class_handler()
    selector = run_selector_cases()
    bridge = run_bridge_cases()
    refclass = run_reference_class_cases()
    fixture_match = all(_sha256(NATIVE / name) == digest
                        for name, digest in FIXTURE_INPUT_SHA.items())

    receipts = {
        'schema': 'a6400.unicorn_uvc_e0351.v1',
        'task': ('E0351 offline decision: EP0 UVC class probe/commit vs bulk-IN '
                 'START endpoint selection'),
        'inputs': {
            'reference_module': _file_row(REF_KO),
            'shipped_module': _file_row(SHIPPED_KO),
            'objects': [_file_row(NATIVE / name) for name in
                        ('uvc_ptp_adapter.o', 'uvc_ptp_session.o', 'callback-bridge.o',
                         'reference.rebound.o', 'composite-shim.o')],
            'fixtures': [_file_row(p) for p in (SELECTOR_ELF, BRIDGE_ELF, REFLASS_ELF)],
            'fixture_build_inputs': FIXTURE_INPUT_SHA,
            'fixture_inputs_match': fixture_match,
        },
        'static_class_handler': static,
        'selector_cases': selector,
        'selector_summary': {'total': len(selector),
                             'passed': sum(1 for c in selector if c['pass']),
                             'failed': [c['case'] for c in selector if not c['pass']]},
        'bridge_cases': bridge,
        'bridge_summary': {'total': len(bridge),
                           'passed': sum(1 for c in bridge if c['pass']),
                           'failed': [c['case'] for c in bridge if not c['pass']]},
        'reference_class_cases': refclass,
        'reference_class_summary': {'total': len(refclass),
                                    'passed': sum(1 for c in refclass if c['pass']),
                                    'failed': [c['case'] for c in refclass if not c['pass']]},
        'verdict': verdict(static, selector, bridge, refclass),
        'camera_access': False, 'module_loaded': False, 'usb_access': False,
        'limitations': [
            'Synthetic kernel objects/gadgetcore wrappers; no live DWC3 register state, '
            'no real endpoint enable sequence and no real UDC completion.',
            'The reference class handler is executed with stub ep->ops functions and a '
            'stubbed OSAL record helper; its get_this/get_this_ex/context globals are synthetic.',
            'Return value 1/2 -> gadgetcore stall/handled mapping lives in vmlinux and is '
            'only referenced, not executed.',
        ],
    }
    json_path = out_dir / 'unicorn-uvc-e0351.json'
    json_path.write_text(json.dumps(receipts, indent=2) + '\n', encoding='utf-8')
    # raw dumps of the decoded handler bytes
    (out_dir / 'class_handler_0x17b0.bin').write_bytes(
        bytes.fromhex(static['raw_hex']['class_0x17b0']))
    (out_dir / 'helpers_0x11bc_0x17b0.bin').write_bytes(
        bytes.fromhex(static['raw_hex']['helper_0x11bc'] + static['raw_hex']['helper_0x1390']))
    if verbose:
        print_summary(receipts, json_path)
    return receipts


def verdict(static, selector, bridge, refclass):
    get_probe = next(c for c in refclass if c['case'] == 'get-cur-probe-34')
    reply = get_probe.get('ep0_reply_hex') or ''
    return {
        'ranking': [
            {'rank': 1, 'hypothesis': 'START endpoint selection (b)',
             'confidence': 'most likely',
             'reason': ('a6400_uvc_ptp_select_endpoint is the only composite-specific gate '
                        'that fails closed: a 0 return makes uvc_callback_bridge.c skip the '
                        'reference START callback, so usbg_cmn_make_ep_list never runs and the '
                        'bulk-IN pipe is never armed. It adds a dwc3_ep enable-flag read '
                        '(dep+0x4c bit0) that the physically validated B3 selector (E0143, '
                        '~30 FPS stream) did not perform, and every live value it needs is '
                        'unobservable in the shipped binaries.')},
            {'rank': 2, 'hypothesis': 'EP0 UVC class probe/commit (a)',
             'confidence': 'less likely',
             'reason': ('core_cb_class is byte-identical to the reference build that streamed '
                        'physically in E0143, the bridge filter passes class/interface requests '
                        'for interfaces 1 and 2, and the dynamic run accepts SET_CUR probe/commit '
                        'and answers GET_CUR. Residual EP0 defect: the GET reply is a 26-byte '
                        'template copied for the host wLength (34), so the last 8 bytes '
                        '(dwClockFrequency + version fields) come from unrelated stack.')},
            {'rank': 3, 'hypothesis': 'undecidable without live kernel logs (c)',
             'confidence': 'fallback',
             'reason': ('The selector preconditions and the gadgetcore return-code mapping are '
                        'not present in the shipped binaries; a live START trace or the original '
                        'dwc3 endpoint table would settle it.')},
        ],
        'ep0_evidence': {
            'class_handler_identical_in_shipped_build':
                static['class_handler_identical_in_shipped_build'],
            'set_cur_probe_returns_0': next(c for c in refclass
                                            if c['case'] == 'set-cur-probe-iface2')['result'],
            'set_cur_commit_returns_0': next(c for c in refclass
                                             if c['case'] == 'set-cur-commit-iface2')['result'],
            'get_cur_probe_returns_0': get_probe['result'],
            'get_cur_probe_reply_hex': reply,
            'get_cur_probe_reply_len': len(reply) // 2,
            'get_cur_probe_trailing_bytes_from_stack': reply[-16:] if len(reply) >= 16 else '',
            'bridge_forwards_vs_probe':
                next(c for c in bridge if c['case'] == 'vs-set-cur-probe-iface2')['forwarded'],
            'bridge_forwards_commit':
                next(c for c in bridge if c['case'] == 'vs-set-cur-commit-iface2')['forwarded'],
        },
        'start_evidence': {
            'expected_live_case_returns_wrapper':
                next(c for c in selector if c['case'] == 'expected-live-0x84-one-wrapper')['pass'],
            'session_gate_speed3_returns_wrapper':
                next(c for c in selector if c['case'] == 'expected-live-session-gate-speed3')['pass'],
            'live_values_required': [
                '*(u32*)(gadget-0x150+0xf4) != 0 : the 0x84 dwc3 endpoint (dep)',
                '*(u32*)(dep+0x4c) & 1 : endpoint enabled flag',
                '*(u8**)(dep+0x1c) : 7,5,0x84,(attrs&3)==2,bInterval==0,wMaxPacket==512',
                'list[i]+0x24 == dep for exactly one wrapper in the START list',
                '*(u32*)(gadget+0x20) == 3 (USB_SPEED_HIGH)',
            ],
            'failing_read_if_zero': {
                'dwc+0xf4==0': 'endpoint 0x84 not mapped/enabled yet or wrong dwc base',
                'dep+0x4c bit0==0': 'the enable flag is not what the original mapping checks',
                'dep+0x1c==0/other': 'no enabled descriptor or a non-0x84 descriptor',
                'no wrapper match': 'START list is for another interface / wrapper layout differs',
                'gadget+0x20!=3': 'gadget speed is not USB_SPEED_HIGH',
            },
        },
        'next_offline_check': (
            'Disassemble the original a6400 dwc3 gadget code around the endpoint-enable path '
            '(kernel VA 0x602ba6ec ep_ctrl_enable_ep and the dwc3_wIndex_to_dep caller) and '
            'confirm what is stored at dep+0x1c and when dep+0x4c bit0 is set at START time; '
            'if the flag/descriptor is not populated before the function-driver START callback, '
            'drop both reads from a6400_uvc_ptp_select_endpoint and accept the START list '
            'wrapper that gadgetcore already validated.'),
    }


def print_summary(receipts, json_path):
    s = receipts['static_class_handler']
    print('E0351 unicorn/uvc EP0-vs-START decision')
    print(f"  reference module sha256 {s['reference_sha256'][:16]}... "
          f"class bytes identical in shipped build: {s['class_handler_identical_in_shipped_build']}")
    print(f"  class handler .text 0x17b0 ({CLASS_SIZE} B) sha256 "
          f"{s['class_handler_sha256'][:16]}...")
    for row in s['decision_table']:
        print(f"    {row['id']:4s} {row['request'][:64]:64s} -> {row['return'][:24]}")
    for label, key in (('selector', 'selector_summary'), ('bridge', 'bridge_summary'),
                       ('reference-class', 'reference_class_summary')):
        summary = receipts[key]
        print(f"  {label} cases: {summary['passed']}/{summary['total']} pass"
              + (f"  FAILED {summary['failed']}" if summary['failed'] else ''))
    print('  verdict ranking:')
    for row in receipts['verdict']['ranking']:
        print(f"    {row['rank']}. {row['hypothesis']} ({row['confidence']})")
    if not receipts['inputs']['fixture_inputs_match']:
        print('  WARNING: objects under artifacts/native/uvc-transport-e0349-fixed/ changed '
              'since the fixtures were linked; rerun --rebuild (needs WSL access).')
    print(f"  receipt: {json_path.relative_to(ROOT).as_posix()}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, default=OUT_DEFAULT,
                        help='output directory (default: artifacts/analysis/unicorn-uvc-e0351)')
    parser.add_argument('--rebuild', action='store_true',
                        help='re-link the Unicorn fixture ELFs through WSL arm-linux-gnueabi-ld')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)
    receipts = run(args.out, rebuild=args.rebuild, verbose=not args.quiet)
    ok = (not receipts['selector_summary']['failed'] and
          not receipts['bridge_summary']['failed'] and
          not receipts['reference_class_summary']['failed'])
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())
