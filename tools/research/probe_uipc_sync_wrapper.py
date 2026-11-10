"""Execute the original OSAL sync wrapper against a constructed callback.

The wrapper owns both callback invocation and completion. The ioctl import is
the explicitly tested transport contract, not a host call of the callback.
"""
import hashlib
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from src.a6400.execution.guest_uipc import GuestUipc


def run_control():
    source = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libosal_uipc.so'
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    if sha != 'b6ded35add9582413b401cf4db78ec2c9a201b632e78c2731d6bbb379249b3eb':
        raise ValueError('OSAL identity changed')
    mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    base, fixture, stop = 0x100000, 0x200000, 0x300000
    mu.mem_map(base, 0x20000)
    mu.mem_map(fixture, 0x4000)
    mu.mem_map(stop, 0x1000)
    with source.open('rb') as stream:
        elf = ELFFile(stream)
        for segment in elf.iter_segments():
            if segment['p_type'] == 'PT_LOAD':
                mu.mem_write(base + segment['p_vaddr'], segment.data())
        dyn = elf.get_section_by_name('.dynsym')
        for relocation in elf.get_section_by_name('.rel.dyn').iter_relocations():
            kind = relocation['r_info_type']
            address = base + relocation['r_offset']
            old = struct.unpack('<I', mu.mem_read(address, 4))[0]
            symbol = dyn.get_symbol(relocation['r_info_sym'])
            if kind == 23:  # R_ARM_RELATIVE
                value = base + old
            elif kind in (2, 21) and symbol['st_shndx'] != 'SHN_UNDEF':
                value = base + symbol['st_value'] + (old if kind == 2 else 0)
            else:
                continue  # Unused imports remain unsupplied, not fake exports.
            mu.mem_write(address, struct.pack('<I', value))
    uipc = GuestUipc()
    uipc.pool_options_policy = 'kernel-e0301'
    uipc.pool_base = fixture
    message = uipc.allocate_message(16, memory_writer=mu.mem_write)
    callback = fixture + 0x1001
    mu.mem_write(callback & ~1, bytes.fromhex('422202607047'))  # movs r2,#66; str r2,[r0]; bx lr
    mu.mem_write(base + 0xef80, struct.pack('<I', 3))  # fixture uconf.fd
    uipc.callbacks[1] = dict(queue=0xca01a4, callback=callback, user_data=0xabcdef, flags=1)
    calls = []

    def read(address, size):
        return bytes(mu.mem_read(address, size))

    def on_code(uc, address, size, _):
        if address == base + 0x17f8:  # Original wrapper's ioctl PLT import.
            cmd = uc.reg_read(arm.UC_ARM_REG_R1)
            if cmd != 0x80000005:
                raise RuntimeError('Unexpected original ioctl')
            result = uipc.handle_ioctl(read, mu.mem_write, cmd, uc.reg_read(arm.UC_ARM_REG_R2), tid=1000)
            if result != 0:
                raise RuntimeError('Unexpected transport response')
            calls.append('ioctl')
            uc.reg_write(arm.UC_ARM_REG_R0, result)
            uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR))
        elif address == callback & ~1:
            calls.append('guest_callback')

    mu.hook_add(UC_HOOK_CODE, on_code)
    mu.reg_write(arm.UC_ARM_REG_SP, fixture + 0x3800)
    mu.reg_write(arm.UC_ARM_REG_LR, stop)
    mu.reg_write(arm.UC_ARM_REG_R0, 0xca01a4)
    mu.reg_write(arm.UC_ARM_REG_R1, message)
    mu.emu_start(base + 0x2605, stop, count=512)
    if (mu.reg_read(arm.UC_ARM_REG_PC) != stop or calls != ['ioctl', 'guest_callback', 'ioctl']
            or read(message, 4) != b'\x42\x00\x00\x00' or read(message - 7, 1) != b'\x01'
            or uipc.sync_callback_inflight):
        raise AssertionError('Original wrapper control failed')
    return {'source': str(source.relative_to(PROJECT_ROOT)), 'sha256': sha,
            'scope': 'original OSAL wrapper with constructed callback and modeled ioctl',
            'calls': calls, 'message_after': read(message, 4).hex(),
            'header_flags_after': read(message - 7, 1).hex(), 'transactions': uipc.transactions}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Use a new report path')
    result = run_control()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('Original OSAL wrapper invoked and completed the constructed guest callback')
