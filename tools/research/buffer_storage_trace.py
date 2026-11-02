"""Static ring-buffer and downstream storage evidence; no updater execution."""
import io
import json

from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input
from tools.research.updater_trace import inspect_functions, symbol_vtable, virtual_slot
from tools.research.storage_trace import inspect_module, module_relocations, decode_arm_range


BUFFER_FUNCTIONS = ('_ZN7Updater10RingBufferC1Ev',
                    '_ZN7Updater10RingBuffer19ReadDataWithoutCopyEPPhj',
                    '_ZN7Updater10RingBuffer8SkipDataEj',
                    '_ZN7Updater10RingBuffer14readFromBufferEPhj',
                    '_ZN7Updater10RingBuffer13writeToBufferEPKhjb',
                    '_ZN7Updater10RingBuffer9WriteDataEPKhjb',
                    '_ZN7Updater10RingBuffer10memoryCopyEPhPKhj')


def main():
    folder = PROJECT_ROOT / 'artifacts/inventory'
    expected = {row['path']: row['sha256'] for row in
                json.loads((folder / 'baseline.json').read_text(encoding='utf-8'))['inputs']}
    paths = {
        'body': 'firmware/extracted_a6400/updater.img_unpacked/bodylib/libupdaterbody.so',
        'common': 'firmware/extracted_a6400/updater.img_unpacked/usr/lib/libupdatercommon.so',
        'storage': 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/initrd.img_unpacked/kmod/emmc.ko'}
    inputs = {name: checked_input(PROJECT_ROOT, path, expected[path]) for name, path in paths.items()}
    table = symbol_vtable(inputs['common'], '_ZTVN7Updater10RingBufferE')
    storage = ELFFile(io.BytesIO(inputs['storage']))
    section_index = storage.get_section_index('.text')
    section = storage.get_section(section_index)
    relocations = {offset: row for (i, offset), row in module_relocations(storage).items()
                   if i == section_index}
    report = {'schema_version': 1, 'status': 'static_buffer_and_storage_evidence',
              'updater_executed': False, 'camera_fidelity_validated': False,
              'runtime_device_identity_selected': False,
              'sources': {name: {'path': path, 'sha256': expected[path]} for name, path in paths.items()},
              'packed_buffer_constructor': inspect_functions(inputs['body'],
                  ('_ZN7Updater20PackedFirmwareBufferC1EPNS_10RingBufferE',)),
              'ring_buffer': inspect_functions(inputs['common'], BUFFER_FUNCTIONS),
              'ring_vtable': table,
              'dispatch_candidates': {name: virtual_slot(table, 8, offset)
                                      for name, offset in (('read_without_copy', 0x24),
                                                           ('skip', 0x28), ('read', 0x20))},
              'storage_functions': inspect_module(inputs['storage'],
                  ('emmc_blk_request', 'emmc_blk_kthread', 'emmc_seq_write')),
              'storage_write_helper': {'name_basis': 'diagnostic string emmc_write, not a recovered function symbol',
                                       'section': '.text', 'start': 0xa89c, 'size': 0xa8,
                                       'source_file_offset': section['sh_offset'] + 0xa89c,
                                       'rows': decode_arm_range(section.data(), 0xa89c, 0xa8, relocations)},
              'limitations': ['Ring-buffer table candidates do not establish the producer input bytes.',
                              'No updater routine, mutex response, kernel service or hardware write is executed.',
                              'Storage ranges include indirect and unnamed local calls; they are not a complete write proof.',
                              'Successful writes, physical header representation, mounts and /etc contents remain unobserved.']}
    output = folder / 'buffer-storage-trace.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Recorded ring-buffer dispatch candidates and storage write ranges; no updater/device operations executed.')
    print(f'Report: {output}')


if __name__ == '__main__':
    main()
