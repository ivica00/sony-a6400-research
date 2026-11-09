"""Execute only the original, source-equal JPEG-path width gate offline."""
import argparse
import hashlib
import json
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_PROT_READ, UC_PROT_EXEC
from unicorn.arm_const import UC_ARM_REG_R5, UC_ARM_REG_PC

SOURCE_SHA256 = 'fbef6c78a1c0c25900a4c014529e6297d38b146098e08bc0a852eb543a4e0aec'


def probe(data):
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError('Expected exact E0132 source-equal function bytes')
    results = []
    for width in (320, 640, 1024, 1920):
        cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        cpu.mem_map(0x11000, 0x1000)
        cpu.mem_write(0x113cc, data)
        cpu.mem_protect(0x11000, 0x1000, UC_PROT_READ | UC_PROT_EXEC)
        cpu.reg_write(UC_ARM_REG_R5, width)
        trace = []

        def code_hook(machine, pc, size, context):
            trace.append(pc)
            if pc in (0x11432, 0x11504):
                machine.emu_stop()

        cpu.hook_add(UC_HOOK_CODE, code_hook)
        cpu.emu_start(0x11421, 0x11600, count=12)
        stop = cpu.reg_read(UC_ARM_REG_PC)
        if stop not in (0x11432, 0x11504):
            raise RuntimeError('Unexpected original-code boundary')
        accepted = stop == 0x11432
        if accepted != (width in (320, 640, 1024)):
            raise RuntimeError('Original-code width result changed')
        results.append({'width': width, 'stop_pc': hex(stop),
            'width_gate_accepted': accepted, 'trace': [hex(pc) for pc in trace]})
    return {'source_sha256': SOURCE_SHA256, 'controls': results,
        'scope': 'Original Thumb width-gate instructions only on explicit register fixtures; '
                 'no complete streaming path, camera execution or encoder validation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = probe(args.source.read_bytes())
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('4 original width-gate controls passed; 1920 rejected by normal path')


if __name__ == '__main__':
    main()
