"""Hash-checked stream device identity and bounded original ARM driver windows."""
import io
import json
import struct

import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input
from tools.research.storage_trace import module_relocations, inspect_module
from tools.research.liro_startup_trace import BASE, STATE, run_slice
from tools.research.startup_trace import analyze

STREAM = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/stream.ko'
DEVNO = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/initrd.img_unpacked/kmod/devno.ko'


def load_stream_profile():
    inventory = json.loads((PROJECT_ROOT / 'artifacts/inventory/elf-inventory.json').read_text(encoding='utf-8'))
    expected = {row['path']: row['sha256'] for row in inventory['entries']}
    raw = checked_input(PROJECT_ROOT, STREAM, expected[STREAM])
    devno = ELFFile(io.BytesIO(checked_input(PROJECT_ROOT, DEVNO, expected[DEVNO])))
    table = devno.get_section_by_name('.data').data()
    pointer, kind, numbers = struct.unpack_from('<3I', table, 0x1a4)
    names = devno.get_section_by_name('.rodata.str1.1').data()
    name = names[pointer:names.index(0, pointer)].decode('ascii')
    if (name, kind & 0xffff, kind >> 16, numbers & 0xffff, numbers >> 16) != ('stream', 0, 249, 7, 1):
        raise ValueError('Original devno stream identity differs')
    elf = ELFFile(io.BytesIO(raw))
    reloc = module_relocations(elf)
    data_index = next(i for i, s in enumerate(elf.iter_sections()) if s.name == '.data')
    for offset, section, target in ((0, 'SHN_UNDEF', 0x1a4), (4, '.data', 0xcc), (8, '.bss', 0),
                                     (0xd4, '.text', 0x80), (0xe4, '.text', 0)):
        r = reloc[(data_index, offset)]
        if r['type'] != 2 or r['symbol_section'] != section or r['target_offset'] != target:
            raise ValueError('Stream descriptor/operations relocation differs')
    if (elf.get_section_by_name('.bss')['sh_size'] != 4
            or elf.get_section_by_name('.bss')['sh_type'] != 'SHT_NOBITS'
            or struct.unpack_from('<I', elf.get_section_by_name('.data').data(), 0xcc)[0] != 0):
        raise ValueError('Stream offset initializer extent differs')
    return {'major': 249, 'minor': 7, 'initial_offset': 0,
            'module_sha256': expected[STREAM], 'devno_sha256': expected[DEVNO],
            'classification': 'selected compiled driver registration/reset; not observed camera runtime state'}


def main():
    profile = load_stream_profile()
    raw = checked_input(PROJECT_ROOT, STREAM, profile['module_sha256'])
    elf = ELFFile(io.BytesIO(raw))
    code = bytearray(elf.get_section_by_name('.text').data())
    struct.pack_into('<I', code, 0x7c, STATE + 0x100)
    cases = []
    for virtual, pgoff in ((0x50000000, 0x2000), (0x10000000, 0x50000)):
        state = bytearray(4096)
        struct.pack_into('<2I', state, 4, virtual, virtual + 4096)
        struct.pack_into('<I', state, 0x18, 0x4400)
        struct.pack_into('<I', state, 0x48, pgoff)
        regions = [(STATE, bytes(state), unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)]
        before, _ = run_slice(bytes(code), 0, [(0, 0x3c)], {0x3c: 'remap_pfn_range_boundary'},
                               {arm.UC_ARM_REG_R1: STATE}, regions)
        # Explicit remap-result controls, not an executed kernel remapper.
        after, mu = run_slice(bytes(code), 0x40, [(0x40, 0x74)], {0x74: 'mapping_epilogue_boundary'},
                               {arm.UC_ARM_REG_R0: 0, arm.UC_ARM_REG_R4: STATE,
                                arm.UC_ARM_REG_R5: pgoff}, regions)
        offset = struct.unpack('<I', mu.mem_read(STATE + 0x100, 4))[0]
        if (before['status'] != 'remap_pfn_range_boundary' or after['status'] != 'mapping_epilogue_boundary'
                or offset != abs(virtual - pgoff * 4096)):
            raise ValueError('Original stream mapping controls differed')
        cases.append({'virtual': virtual, 'pgoff': pgoff, 'before_remap': before,
                      'supplied_remap_result': 0, 'after_remap': after, 'offset': offset})
    state = bytearray(4096)
    # Construct the UDIF callback context/private-pointer indirection and a
    # bounded kernel thread-info addr_limit solely for this instruction slice.
    struct.pack_into('<I', state, 4, STATE + 0x100)
    struct.pack_into('<I', state, 0x100, STATE + 0x200)
    struct.pack_into('<I', state, 0x200, 0x12345678)
    struct.pack_into('<2I', state, 0x300, 0xc0047801, STATE + 0x400)
    stack_info = bytearray(8192)
    struct.pack_into('<I', stack_info, 8, 0x80000000)
    ioctl, _ = run_slice(bytes(code), 0x80, [(0x80, 0xe0)], {0xe0: 'copy_to_user_boundary'},
                                 {arm.UC_ARM_REG_R0: STATE, arm.UC_ARM_REG_R1: STATE + 0x300,
                                  arm.UC_ARM_REG_SP: 0x61000},
                                 [(STATE, bytes(state), unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE),
                                  (0x60000, bytes(stack_info), unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)])
    if (ioctl['status'] != 'copy_to_user_boundary'
            or [ioctl['registers'][r] for r in ('r0', 'r1', 'r2')] != [STATE + 0x400, STATE + 0x200, 4]):
        raise ValueError('Original ioctl did not reach the selected four-byte source copy')
    inventory = json.loads((PROJECT_ROOT / 'artifacts/inventory/elf-inventory.json').read_text(encoding='utf-8'))
    expected = {r['path']: r['sha256'] for r in inventory['entries']}
    allocator_evidence = []
    for module, names in [('grm_ma.ko', ['ma_init', 'ma_user_sync_cb', 'ma_dmm_open_impl', 'ma_dmm_open_send_recv']),
                          ('dmm.ko', ['dmm_module_GetConfigData', 'dmm_module_LoadConfigBuf', 'dmm_ctrl_OpenUnitHdlr'])]:
        path = STREAM.rsplit('/', 1)[0] + '/' + module
        content = checked_input(PROJECT_ROOT, path, expected[path])
        allocator_evidence.append({'path': path, 'sha256': expected[path], 'functions': inspect_module(content, names)})
    consumer = STREAM.replace('kmod/stream.ko', 'lib/libObj.so')
    checked_input(PROJECT_ROOT, consumer, expected[consumer])
    consumers = analyze(PROJECT_ROOT / consumer, [],
                        named_functions=['DDSUserInit', 'ObjDisplay_Create', 'dmp_allocator_lib_init'],
                        explicit_blocks=[('MA client initialization', 0x71f409, 0x80),
                                         ('MA create request', 0x720621, 0xac)])
    output = PROJECT_ROOT / 'artifacts/execution/stream-contract.json'
    output.write_text(json.dumps({'profile': profile, 'mapping_controls': cases, 'ioctl_copy_window': ioctl,
                                 'allocator_evidence': allocator_evidence, 'consumer_evidence': consumers,
                                 'original_functions': inspect_module(raw, ['stream_ioctl', 'stream_mmap', 'stream_init']),
                                 'limitations': 'Constructed state and successful-remap control only; no kernel, DMA or physical bytes supplied.'}, indent=2), encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
