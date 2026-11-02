"""Trace original compressed-header checks without supplying storage responses."""
import hashlib
import io
import json
import struct

from elftools.elf.elffile import ELFFile
import unicorn
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input
from tools.research.storage_trace import decode_arm_range, module_relocations


def header_observation(data):
    """Decode observed words; magic alone is never full image validation."""
    if len(data) < 16:
        raise ValueError('Header observation requires at least 16 bytes')
    magic, shift, offset, size = struct.unpack_from('<4s3I', data)
    return {'first_16_bytes': data[:16].hex(), 'magic_hex': magic.hex(),
            'magic_matches_TPZL': magic == b'TPZL', 'block_shift_word': shift,
            'table_offset_word': offset, 'table_size_word': size,
            'complete_image_validated': False}


def execute_magic_comparison(section, header, start=0x5f3c, accepted=0x5f50, rejected=0x5fb8):
    """Execute the original comparison window, stopping before either successor."""
    if len(header) != 512:
        raise ValueError('Magic experiment requires one explicit 512-byte sector')
    if any(offset < 0 or offset >= len(section) or offset % 4 for offset in (start, accepted, rejected)):
        raise ValueError('Magic experiment endpoints must be ARM section offsets')
    if accepted != start + 20:
        raise ValueError('Magic experiment requires a five-instruction window')
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
    base, buffer = 0x1000000, 0x2000000
    mu.mem_map(base, (len(section) + 4095) & ~4095, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_write(base, section)
    mu.mem_map(buffer, 4096, unicorn.UC_PROT_READ)
    mu.mem_write(buffer, header)
    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
    mu.reg_write(arm.UC_ARM_REG_R4, 0)
    mu.reg_write(arm.UC_ARM_REG_R6, buffer)
    visited, boundary = [], []
    def code(uc, address, size, _):
        offset = address - base
        if offset in (accepted, rejected):
            boundary.append(offset)
            uc.emu_stop()
            return
        if not start <= offset < accepted or size != 4:
            raise ValueError('Magic experiment left its declared instruction window')
        visited.append(offset)
    mu.hook_add(unicorn.UC_HOOK_CODE, code)
    mu.emu_start(base + start, 0, timeout=500000, count=16)
    if len(boundary) != 1 or len(visited) != 5 or mu.query(unicorn.UC_QUERY_TIMEOUT):
        raise ValueError('Magic experiment did not reach exactly one declared boundary')
    return {'status': 'comparison_boundary', 'boundary_offset': boundary[0],
            'branch': 'magic_matches' if boundary[0] == accepted else 'magic_mismatch',
            'r4': mu.reg_read(arm.UC_ARM_REG_R4), 'instruction_offsets': visited,
            'instructions_executed': len(visited), 'kernel_responses_supplied': 0,
            'complete_image_validated': False,
            'assumptions': ['Caller, successful prior sector read, and uncached path are supplied initial conditions.',
                            'Provisional Cortex-A9 in ARM user mode; fixed RX code and read-only input mappings.',
                            'No storage read, cache cleanup, header remainder, registration or mount is executed.']}


def main():
    folder = PROJECT_ROOT / 'artifacts/inventory'
    expected = {row['path']: row['sha256'] for row in
                json.loads((folder / 'baseline.json').read_text(encoding='utf-8'))['inputs']}
    base = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/'
    path = base + 'nflasha3_unpacked/initrd.img_unpacked/kmod/emmc.ko'
    data = checked_input(PROJECT_ROOT, path, expected[path])
    elf = ELFFile(io.BytesIO(data))
    index = elf.get_section_index('.text')
    section = elf.get_section(index).data()
    relocations = {offset: row for (i, offset), row in module_relocations(elf).items() if i == index}
    windows = []
    for name, start, size in (('sector_read_helper', 0x5e5c, 0x7c),
                               ('preload_lzp_header', 0x5ed8, 0x118),
                               ('uz_emmc_lzp_part_size', 0x5ff0, 0x8c)):
        windows.append({'name': name, 'section': '.text', 'start': start, 'size': size,
                        'source_file_offset': elf.get_section(index)['sh_offset'] + start,
                        'rows': decode_arm_range(section, start, size, relocations)})
    observations, sources = {}, {'module': {'path': path, 'sha256': expected[path]}}
    for name in ('nflasha7', 'nflasha15'):
        image_path = base + name
        image = checked_input(PROJECT_ROOT, image_path, expected[image_path])
        header = image[:512]
        sources[name] = {'path': image_path, 'sha256': expected[image_path]}
        observations[name] = {'scope': 'preserved updater image bytes, not a physical partition dump',
                              'sector_sha256': hashlib.sha256(header).hexdigest(),
                              'header': header_observation(header),
                              'original_comparison': execute_magic_comparison(section, header)}
    # Deliberately incomplete control: a matching magic is not image validity.
    control = b'TPZL' + bytes(508)
    report = {'schema_version': 1, 'status': 'header_comparison_evidence',
              'camera_fidelity_validated': False, 'runtime_device_identity_selected': False,
              'sources': sources, 'instruction_windows': windows, 'image_observations': observations,
              'constructed_magic_only_control': {'header': header_observation(control),
                                                  'original_comparison': execute_magic_comparison(section, control)},
              'limitations': ['Updater image bytes do not establish physical compressed partition contents.',
                              'No decompression, complete header/table validation or successful mount is demonstrated.',
                              'Static helper ranges may include inline data; they are not executed control-flow traces.']}
    output = folder / 'compressed-header.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Original comparison: ' + ', '.join(
        f"{name}={item['original_comparison']['branch']}" for name, item in observations.items()))
    print(f'Report: {output}')


if __name__ == '__main__':
    main()
