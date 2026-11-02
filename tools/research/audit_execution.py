"""Run the preserved harness with explicit capability and execution reporting."""
import argparse
from pathlib import Path

from legacy.cxd90045_hle_emulator import CXD90045_HLE_Emulator, LIB_DIR
from legacy.execution_audit import UnsupportedBehavior
from project_paths import PROJECT_ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('research', 'strict'), default='strict')
    parser.add_argument('--report', type=Path,
                        default=PROJECT_ROOT / 'artifacts/execution/latest.json')
    args = parser.parse_args()
    emu = CXD90045_HLE_Emulator(mode=args.mode)
    try:
        emu.load_elf_module(str(Path(LIB_DIR) / 'libObj.so'), 0x30000000)
        emu.load_elf_module(str(Path(LIB_DIR) / 'viewUnified2.so'), 0x32000000)
        emu.setup_sony_subsystems()
        emu.instantiate_all_screens()
        print('Research setup completed; camera fidelity is not validated.')
        return 0
    except UnsupportedBehavior as error:
        print(f'Stopped at unsupported behavior: {error}')
        return 2
    finally:
        emu.write_execution_report(args.report)
        print(f'Execution report: {args.report}')


if __name__ == '__main__':
    raise SystemExit(main())
