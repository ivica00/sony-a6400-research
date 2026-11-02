"""Identify original GLES module/state in package WBI with an explicit page root."""
import argparse
import hashlib
import io
import json
import struct

from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.dmm_runtime_trace import KERNEL, KERNEL_BASE
from tools.research.gles_contract_trace import MODULE
from tools.research.mount_evidence import checked_input
from tools.research.storage_trace import module_relocations
from tools.research.wbi_logging_trace import PackageMemory
from tools.research.wbi_memory import IMAGE, decode_section
from tools.research.wbi_pagewalk import read_virtual, translate

ROOT = 0x104000


def owner_context_candidates(memory, owners, extra_groups=(), include_all_tasks=False):
    """Structural task/stack backlinks, not discovery of an active CPU task."""
    if any(not 0 <= group <= 0xffffffff for group in extra_groups):
        raise ValueError('Additional TGIDs must be ARM32 values')
    groups = {owner['tgid'] for owner in owners} | set(extra_groups)
    candidates = []
    for section in memory.sections:
        data = decode_section(memory.raw, section)[0]
        first = (section['physical'] + 8191) & ~8191
        for physical in range(first, section['physical'] + len(data) - 23, 8192):
            offset = physical - section['physical']
            task = struct.unpack_from('<I', data, offset + 12)[0]
            if not 0x60000000 <= task < 0xa0000000 or task & 3:
                continue
            thread_info = physical + 0x60000000
            try:
                task_data = read_virtual(memory, ROOT, task, 0x10c)
                header = read_virtual(memory, ROOT, thread_info, 24)
            except ValueError:
                continue
            # Original sugilite_ioctl follows current_task+8 to thread_info
            # before reading its flags (not the generic assumed task+4 layout).
            stack = struct.unpack_from('<I', task_data, 8)[0]
            pid, tgid = struct.unpack_from('<2I', task_data, 0x104)
            if stack == thread_info and (tgid in groups or include_all_tasks) and header == data[offset:offset + 24]:
                candidates.append({'task': task, 'thread_info': thread_info, 'pid': pid, 'tgid': tgid,
                                   'thread_info_words': list(struct.unpack_from('<4I', header)),
                                   'cpu': struct.unpack_from('<I', header, 20)[0],
                                   'migration_depth': struct.unpack_from('<I', task_data, 0xa8)[0]})
    return candidates


def inspect(memory, module, kernel, extra_groups=(), include_all_tasks=False):
    elf = ELFFile(io.BytesIO(module))
    index = next(i for i, section in enumerate(elf.iter_sections()) if section.name == '.text')
    code = elf.get_section(index).data()
    relocs = module_relocations(elf)
    if kernel[0x54:0x58] != struct.pack('<I', 0xe3a04941):
        raise ValueError('Original kernel selected-root instruction changed')
    needle = code[0x43c:0x450]
    if any(i == index and 0x43c <= off < 0x450 for i, off in relocs):
        raise ValueError('Module identity prefix contains relocations')
    hits = []
    for section in memory.sections:
        data = decode_section(memory.raw, section)[0]
        start = 0
        while (offset := data.find(needle, start)) >= 0:
            if offset % 4 == 0:
                hits.append(section['physical'] + offset)
            start = offset + 1
    pages = {address & ~4095 for address in hits}
    candidates = set()
    for virtual in range(0x5f000000, 0x60000000, 4096):
        try:
            physical, _ = translate(memory, ROOT, virtual)
        except ValueError:
            continue
        if physical in pages:
            candidates.update(virtual + (hit & 4095) - 0x43c for hit in hits if hit & ~4095 == physical)
    excluded = {off for (i, off) in relocs if i == index}
    matches = []
    for virtual in sorted(candidates):
        try:
            captured = read_virtual(memory, ROOT, virtual, len(code))
        except ValueError:
            continue
        compared = 0
        for offset in range(0, len(code), 4):
            if offset in excluded:
                continue
            if captured[offset:offset + 4] != code[offset:offset + 4]:
                break
            compared += len(code[offset:offset + 4])
        else:
            matches.append((virtual, captured, compared))
    if len(matches) != 1:
        raise ValueError(f'Expected one original GLES text mapping; hits={hits}, matches={len(matches)}')
    base, captured, compared = matches[0]
    if (relocs[(index, 0x1414)]['symbol'] != 'outer_cache'
            or relocs[(index, 0x1734)]['symbol_section'] != '.bss'
            or relocs[(index, 0x1734)]['target_offset'] != 0x78):
        raise ValueError('Original cache/device state anchors changed')
    outer = struct.unpack_from('<I', captured, 0x1414)[0]
    cache_table = read_virtual(memory, ROOT, outer, 32)
    sync = struct.unpack_from('<I', cache_table, 28)[0]
    callback = {'address': sync}
    if sync:
        if sync & 3 or not KERNEL_BASE <= sync <= KERNEL_BASE + len(kernel) - 128:
            raise ValueError('Captured cache callback is not aligned preserved kernel code')
        original = kernel[sync - KERNEL_BASE:sync - KERNEL_BASE + 128]
        captured_callback = read_virtual(memory, ROOT, sync, 128)
        if captured_callback != original:
            raise ValueError('Captured cache callback differs from preserved kernel')
        callback.update(verified_bytes=128, code_hex=original.hex(), sha256=hashlib.sha256(original).hexdigest())
    device_slot = struct.unpack_from('<I', captured, 0x1734)[0]
    device = struct.unpack('<I', read_virtual(memory, ROOT, device_slot, 4))[0]
    if not device:
        raise ValueError('Captured GLES device pointer is NULL')
    state = read_virtual(memory, ROOT, device, 0x10c)
    fields = {name: struct.unpack_from('<I', state, offset)[0] for name, offset in (
        ('open_count', 0x40), ('event_status', 0x44), ('suspend_status', 0x48),
        ('hardware_status', 0xa8), ('shared_area', 0xac), ('device_kind', 0xec),
        ('configuration', 0xf0), ('register_pointer', 0xf8), ('bar0', 0x100),
        ('bar1', 0x104), ('bar_size', 0x108))}
    if fields['register_pointer'] != 0xf1000000 or fields['bar_size'] != 0x4000 or fields['device_kind'] != 2:
        raise ValueError('Captured device metadata disagrees with compiled initialization')
    head = device_slot - 0x78
    first, last = struct.unpack('<2I', read_virtual(memory, ROOT, head, 8))
    current, previous, owners = first, head, []
    while current != head:
        if len(owners) >= 64 or any(owner['address'] == current for owner in owners):
            raise ValueError('Captured GLES owner list is cyclic/excessive')
        words = struct.unpack('<6I', read_virtual(memory, ROOT, current, 24))
        if words[1] != previous:
            raise ValueError('Captured GLES owner links are not reciprocal')
        owners.append({'address': current, 'next': words[0], 'previous': words[1],
                       'tgid': words[2], 'references': words[3],
                       'pending_event': words[4], 'completion': words[5]})
        previous, current = current, words[0]
    if previous != last:
        raise ValueError('Captured GLES owner-list tail differs')
    contexts = owner_context_candidates(memory, owners, extra_groups, include_all_tasks)
    owner_groups = {owner['tgid'] for owner in owners}
    return {'status': 'identified_captured_gles_state', 'selected_root': ROOT,
            'identity_prefix_physical_hits': hits, 'code_virtual': base,
            'code_mapping': translate(memory, ROOT, base)[1], 'nonrelocated_bytes_verified': compared,
            'relocation_words_excluded': len(excluded), 'outer_cache': outer,
            'outer_cache_words': list(struct.unpack('<8I', cache_table)), 'cache_sync': callback,
            'device_pointer_slot': device_slot, 'device_virtual': device,
            'device_mapping': translate(memory, ROOT, device)[1], 'device_fields': fields,
            'owner_list_head': head, 'captured_owners': owners,
            'owner_context_candidates': [item for item in contexts if item['tgid'] in owner_groups],
            'additional_context_candidates': [item for item in contexts if item['tgid'] not in owner_groups],
            'requested_additional_tgids': list(extra_groups),
            'include_all_tasks': include_all_tasks,
            'limitations': ['Explicit selected package-WBI page root; active TTBR/cold-start ownership not established.',
                            'Captured runtime objects are not current camera state or main-process initialization.',
                            'No driver open, cache success, GPU MMIO reply, interrupt or render result supplied.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    parser.add_argument('--include-tgid', action='append', type=lambda value: int(value, 0), default=[])
    parser.add_argument('--all-tasks', action='store_true')
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Report must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)
    entries = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs']
    hashes = {entry['path']: entry['sha256'] for entry in entries}
    originals = {path: checked_input(PROJECT_ROOT, path, hashes[path]) for path in (IMAGE, MODULE, KERNEL)}
    report = inspect(PackageMemory(originals[IMAGE]), originals[MODULE], originals[KERNEL],
                     args.include_tgid, args.all_tasks)
    report['inputs'] = {path: hashes[path] for path in originals}
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output / 'report.json')
    print('module', hex(report['code_virtual']), 'cache sync', hex(report['cache_sync']['address']))
    print('device fields', {key: hex(value) for key, value in report['device_fields'].items()})


if __name__ == '__main__':
    main()
