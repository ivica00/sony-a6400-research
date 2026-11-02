"""Small original ELF windows for SD playback and updater-source investigation."""
import argparse
import io
import json

from elftools.elf.elffile import ELFFile
from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.startup_trace import decode_block, plt_symbols

BASE = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/'
TARGETS = {
    BASE + 'lib/libmpr.so': (
        '_ZN9PlayStill15GetRawMakerNoteEPN3MPR10BufferInfoE',
        '_ZN12PlayJpegThum19CopyReadStillStreamEPN3MPR14BufferAreaInfoE',
        '_ZN5MprIf23UpdateExtDeviceFirmwareEmmm',
        '_ZN15ExtDeviceFirmUp14CheckConditionEP4MMgrS1_PN3MPR12DeviceStatusEPNS2_14FirmwareStatusEPNS2_13VersionStatusE'),
    BASE + 'lib/libupdaterufp.so': ('udtr_ufp_init', 'udtr_copy2dmm'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)
    baseline = {r['path']: r['sha256'] for r in json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs']}
    report = {'method': 'Static ELF symbols, original Thumb windows, relocations and script text; no target execution.',
              'limitations': ['ET_DYN targets are outside current dependency_plan ET_REL support.',
                              'Playback wrappers are leads, not proven low-level parsers or vulnerabilities.',
                              'External-device update symbols do not establish camera-body update support.',
                              'Script MS labels do not establish SD compatibility or a boot trigger.'],
              'libraries': [], 'script_observations': []}
    for path, names in TARGETS.items():
        raw = checked_input(PROJECT_ROOT, path, baseline[path])
        elf = ELFFile(io.BytesIO(raw))
        symbols = list(elf.get_section_by_name('.dynsym').iter_symbols())
        calls = plt_symbols(elf)
        calls.update({s['st_value'] & ~1: s.name for s in symbols if s['st_shndx'] != 'SHN_UNDEF' and s['st_info']['type'] == 'STT_FUNC'})
        functions = []
        for name in names:
            matches = [s for s in symbols if s.name == name and s['st_shndx'] != 'SHN_UNDEF' and s['st_info']['type'] == 'STT_FUNC']
            if len(matches) != 1 or not 0 < matches[0]['st_size'] <= 1024:
                raise ValueError('Missing, ambiguous or oversized selected function')
            symbol = matches[0]
            functions.append({'name': name, 'value': symbol['st_value'], 'size': symbol['st_size'],
                              'instructions': decode_block(elf, raw, symbol['st_value'], symbol['st_size'], calls)})
        dynamic = elf.get_section_by_name('.dynamic')
        needed = [t.needed for t in dynamic.iter_tags() if t.entry.d_tag == 'DT_NEEDED']
        checked_input(PROJECT_ROOT, path, baseline[path])
        report['libraries'].append({'path': path, 'sha256': baseline[path], 'type': elf['e_type'], 'needed': needed, 'functions': functions})
    for path in (BASE + 'bin/common.src', 'firmware/extracted_a6400/updater.img_unpacked/config/common.src',
                 'firmware/extracted_a6400/updater.img_unpacked/bin/chkfirm.sh',
                 'firmware/extracted_a6400/updater.img_unpacked/bin/startupdate.sh'):
        raw = checked_input(PROJECT_ROOT, path, baseline[path])
        lines = [{'line': i, 'text': line} for i, line in enumerate(raw.decode('ascii').splitlines(), 1)
                 if any(s in line for s in ('DATSRC_', 'MS_MOUNT_POINT', 'MSBOOT', 'IAMLDUDWRT', 'UPDATE_TYPE=Serial'))]
        checked_input(PROJECT_ROOT, path, baseline[path])
        report['script_observations'].append({'path': path, 'sha256': baseline[path], 'lines': lines})
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(output, sum(len(l['functions']) for l in report['libraries']), 'original function windows')


if __name__ == '__main__':
    main()
