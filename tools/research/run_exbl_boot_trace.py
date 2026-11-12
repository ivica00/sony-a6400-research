"""Run the nflashaB0 EXBL loader in the bounded Unicorn harness (offline, read-only).

Default policy ``observe-zero`` collects the loader's MMIO register map as an
explicitly labelled unmodelled observation; ``--policy stop`` stops at the first
MMIO/unmapped access (fail-closed baseline).  Nothing is written to any camera
or firmware image; only a local report under artifacts/ is produced.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.a6400.execution.exbl_boot_harness import ExblBootHarness  # noqa: E402
from src.a6400.execution.exbl_image import (NFLASHA_B0_SHA256,  # noqa: E402
                                            NFLASHA_B0_SIZE, ExblImage)

DEFAULT_DUMP = ROOT / 'artifacts/dumps/a6400-nflasha-readonly/nflashaB0-4194304.bin'
OUT_DIR = ROOT / 'artifacts/analysis/e0415-nflasha-boot'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dump', type=Path, default=DEFAULT_DUMP)
    parser.add_argument('--policy', choices=('stop', 'observe-zero'), default='observe-zero')
    parser.add_argument('--limit', type=int, default=2_000_000)
    parser.add_argument('--stub', action='append', default=[], metavar='ADDRESS=VALUE',
                        help='labelled MMIO read stub (hex)')
    parser.add_argument('--counter-stub', action='append', default=[],
                        metavar='ADDRESS=STEP',
                        help='labelled MMIO read counter stub incremented per read')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not args.dump.is_file():
        print(f'boot-area dump missing: {args.dump}')
        return 2
    exbl = ExblImage.from_path(args.dump, expected_size=NFLASHA_B0_SIZE,
                               expected_sha256=NFLASHA_B0_SHA256)
    print(json.dumps({key: exbl.summary()[key] for key in
                      ('sha256', 'bytes', 'load_base', 'entry', 'extent_bytes',
                       'payload_bytes', 'mapping_consistent')}, indent=2))
    stubs = {}
    for item in args.stub:
        address, _, value = item.partition('=')
        stubs[int(address, 0)] = int(value, 0)
    counters = {}
    for item in args.counter_stub:
        address, _, value = item.partition('=')
        counters[int(address, 0)] = int(value, 0)
    harness = ExblBootHarness(exbl, mmio_policy=args.policy,
                              mmio_read_stubs=stubs or None,
                              mmio_counter_stubs=counters or None,
                              instruction_limit=args.limit)
    report = harness.run()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output = args.output or OUT_DIR / f'exbl-boot-{args.policy}.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"stop: {report['stop_reason']} at 0x{report['stop_pc']:08x}"
          if isinstance(report['stop_pc'], int) else f"stop: {report['stop_reason']}")
    print('counters:', report['counters'])
    print('mmio addresses:', report['mmio_address_count'])
    for entry in report['mmio_addresses'][:16]:
        print(f"  0x{entry['address']:08x} r={entry['reads']} w={entry['writes']}"
              + (f" last=0x{entry['last_value']:08x}" if 'last_value' in entry else ''))
    print('boot parameter reads/writes:',
          report['counters']['boot_param_reads'], report['counters']['boot_param_writes'])
    print('boot-contract reference offsets:',
          {name: values for name, values in report['boot_contract_references'].items()})
    print('report:', output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
