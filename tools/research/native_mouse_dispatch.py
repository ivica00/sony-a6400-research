"""Retain live/file-verified mouse dispatch instructions; no calls or writes."""
import json
from datetime import datetime
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from tools.camera_debugger import connect
from tools.research.remote_elf import RemoteElf32, debugger_reader

ROOT = Path(__file__).resolve().parents[2]
NAMES = [
    '_ZN2ux6wgtsys12WidgetSystem13postMouseMoveEhssNS_4core8MsecTimeE',
    '_ZN2ux6wgtsys12WidgetSystem14postMousePressEhhNS_4core8MsecTimeE',
    '_ZN2ux6wgtsys12WidgetSystem16postMouseReleaseEhhNS_4core8MsecTimeE',
    '_ZN2ux6wgtsys6Widget16setPassiveRegionEb',
    '_ZN2ux6wgtsys10WidgetBase17setMouseEventHookEb',
]


def main():
    report = {'read_only': True, 'remote_calls': False, 'functions': {}}
    decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    with connect() as debugger:
        maps, _ = debugger.read_all('/proc/149/maps')
        bases = [int(line.split('-')[0], 16) for line in maps.decode().splitlines()
                 if line.endswith('/libObj.so') and 'r-xp 00000000 ' in line]
        if len(bases) != 1:
            raise ValueError('Ambiguous libObj mapping')
        base = bases[0]
        elf = RemoteElf32(debugger_reader(debugger, '/usr/lib/libObj.so'))
        queue = []
        for name in NAMES:
            symbol = elf.resolve(name)
            queue.append((base + (symbol['value'] & ~1), min(symbol['size'], 2048), name, 0))
        seen = set()
        while queue and len(seen) < 32:
            address, size, name, depth = queue.pop(0)
            if address in seen:
                continue
            if size <= 0 or not base <= address < base + 0x1000000:
                raise ValueError('Code outside bounded library')
            seen.add(address)
            code = debugger.memory(149, address, size)
            if code != elf.virtual(address - base, size):
                raise ValueError('Live/file mismatch at ' + hex(address))
            instructions = []
            for ins in decoder.disasm(code, address):
                instructions.append({'address': hex(ins.address), 'bytes': ins.bytes.hex(),
                                     'instruction': ins.mnemonic + ' ' + ins.op_str})
                if depth < 2 and ins.mnemonic in ('bl', 'b.w') and ins.op_str.startswith('#0x'):
                    target = int(ins.op_str[1:], 16)
                    if base + 0x100000 <= target < base + 0x1000000:
                        queue.append((target, 512, 'direct target of ' + hex(ins.address), depth + 1))
            report['functions'][hex(address)] = {'name': name, 'depth': depth,
                                                'code': code.hex(), 'instructions': instructions}
    destination = ROOT / 'artifacts/hardware' / ('native-mouse-dispatch-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(destination)


if __name__ == '__main__':
    main()
