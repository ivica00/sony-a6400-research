"""Boot the nflasha1 updater kernel on the minimal Unicorn CXD90045 machine (offline).

Uses only the E0414 read-only dumps plus the preserved firmware package: it
decompresses the updater zImage offline, reconstructs the ATAGS contract from
``boot/loadaddr.txt`` + ``boot/kemco.txt`` and runs the real kernel with a small
explicit machine model.  The captured ``ttyAM0`` serial log and every stubbed/unmapped
MMIO access are written under ``artifacts/analysis/e0416-qemu-bringup/``.

This is a bounded bring-up experiment, not a booted camera: see the run report for the
stop reason and the labelled MMIO stubs.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.a6400.execution.machine_contract import UpdaterBootContract  # noqa: E402
from src.a6400.execution.nflasha_boot_set import NflashaBootSet  # noqa: E402
from src.a6400.execution.unicorn_machine import UnicornMachine  # noqa: E402
from tools.research.decode_kernel_kallsyms import decode  # noqa: E402

OUT = ROOT / 'artifacts/analysis/e0421-ttyam0-init'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=40_000_000)
    parser.add_argument('--cmdline-extra', default='',
                        help='runner-side cmdline addition (e.g. an observed lpj=)')
    parser.add_argument('--lpj-preset', type=int, default=0,
                        help='write this lpj at calibrate_delay entry (observed 1757184)')
    parser.add_argument('--no-timer-irq', action='store_true',
                        help='disable the E0417 timer/GIC interrupt model')
    parser.add_argument('--ticks-per-instruction', type=int, default=1)
    parser.add_argument('--ticks-per-jiffy', type=int, default=0x2710)
    parser.add_argument('--timer-irq', type=int, default=153)
    parser.add_argument('--unmapped-mmio-policy', choices=('stop', 'observe-zero'),
                        default='observe-zero')
    parser.add_argument('--no-exclusive-fallback', action='store_true')
    parser.add_argument('--map-null-page', action='store_true')
    parser.add_argument('--fsr', type=lambda value: int(value, 0), default=0x5)
    parser.add_argument('--uart-base', type=lambda value: int(value, 0), default=0xF2000000)
    parser.add_argument('--probe-write-range', action='append', default=[],
                        metavar='START-END')
    parser.add_argument('--no-fixup-skip', action='store_true')
    parser.add_argument('--no-data-abort-delivery', action='store_true')
    parser.add_argument('--patch-config-cmdline', action='store_true')
    parser.add_argument('--serial-input', default='')
    parser.add_argument('--trace-user-mode', action='store_true')
    parser.add_argument('--trace-reg', action='append', default=[],
                        metavar='PC:REGS')
    parser.add_argument('--cmdline-bootparams', action='store_true')
    parser.add_argument('--sony-override', action='store_true')
    parser.add_argument('--stub', action='append', default=[],
                        metavar='ADDRESS=VALUE', help='MMIO read stub (hex)')
    parser.add_argument('--output', type=Path, default=OUT / 'nflasha1-boot-report.json')
    parser.add_argument('--serial-output', type=Path, default=OUT / 'nflasha1-ttyAM0.log')
    args = parser.parse_args()

    boot_set = NflashaBootSet.from_evidence(ROOT, 'nflasha1')
    contract = UpdaterBootContract(boot_set, cmdline_extra=args.cmdline_extra)
    verification = contract.verify()
    print(json.dumps({key: verification[key] for key in
                      ('machine', 'load_addresses', 'kernel_raw_bytes', 'initrd_bytes',
                       'memory_banks', 'atags')}, indent=2))
    symbols = {}
    try:
        decoded = decode(contract.raw_kernel)
        symbols = {symbol['name']: symbol['address'] for symbol in decoded['symbols']}
        print('symbols', len(symbols))
    except Exception as error:  # symbol naming is optional; the boot run does not need it
        print('symbol decode unavailable:', error)
        symbols = {}
    stubs = {}
    for item in args.stub:
        address, _, value = item.partition('=')
        stubs[int(address, 0)] = int(value, 0)
    boot_patches = {}
    if args.lpj_preset and 'calibrate_delay' in symbols:
        # Observed in the updater kernel disassembly: calibrate_delay reads
        # ``lpj`` at 0x6047288C and a "calibrated" flag byte at 0x60472890; a
        # non-zero lpj with flag 0 takes the preset path (no timer tick needed).
        # Unicorn mem_write() addresses are physical, so subtract the observed
        # PAGE_OFFSET 0x60000000 for these kernel data variables.
        page_offset = 0x60000000
        boot_patches[symbols['calibrate_delay']] = [
            (0x6047288C - page_offset, 4, args.lpj_preset),
            (0x60472890 - page_offset, 1, 0)]
    trace_points = {}
    if 'gic_init' in symbols:
        trace_points[symbols['gic_init']] = 'gic_init'
    if len(contract.raw_kernel) == 3581952:
        # ext_timer_setup: add r0,r0,#0x99 / bl setup_irq (updater kernel build).
        trace_points[0x6011F9FC] = 'ext_timer_setup_setup_irq'
    if (args.map_null_page and 'start_kernel' in symbols
            and 'swapper_pg_dir' in symbols):
        # Bring-up patch: map user VA 0 as a 1 MiB RW section so the ARMv7 futex
        # probe (`cmpxchg_futex_value_locked(&curval, NULL, 0, 0)`) can complete
        # instead of relying on an exception-table fixup.  Labelled, not default.
        boot_patches[symbols['start_kernel']] = [
            (symbols['swapper_pg_dir'] - 0x60000000, 4, 0x00100C0E)]
    if '__boottime_vfp_init' in symbols:
        # Sony's kernel BUG()s unless the emulated VFP reports D16 (its context
        # code assumes 16 double registers).  Unicorn's VFP model does not match
        # the board exactly, so skip the BUG branch (bne -> b) as a labelled
        # bring-up patch; the VFP context path itself is left untouched.
        vfp = symbols['__boottime_vfp_init']
        boot_patches[vfp] = [(vfp - 0x60000000 + 0x10C, 4, 0xEA000005)]
    if ('cxd900x0_fixup' in symbols and args.cmdline_extra
            and not args.no_fixup_skip):
        # The board fixup re-applies the kemco cmdline (init=/sbin/init) after the
        # ATAGS cmdline; skip it so the runner's init=/bin/ash override survives.
        fixup = symbols['cxd900x0_fixup']
        boot_patches[fixup] = [(fixup - 0x60000000, 4, 0xE12FFF1E)]  # bx lr
    if (args.patch_config_cmdline and 'start_kernel' in symbols
            and 'init=/bin/ash' in args.cmdline_extra):
        # The kernel appends its built-in CONFIG_CMDLINE (which carries
        # init=/sbin/init) after the ATAGS cmdline, so the last init= token still
        # pointed at the missing /sbin/init. Rewrite that default string in RAM
        # to init=/bin/ash (NUL padded) so execute_command resolves to the
        # updater shell.
        needle = b'init=/sbin/init'
        replacement = b'init=/bin/ash\x00\x00\x00'
        raw_kernel = contract.raw_kernel
        offset = -1
        start = 0
        while True:
            index = raw_kernel.find(needle, start)
            if index < 0:
                break
            window = raw_kernel[max(0, index - 96):index + 96]
            if b'root=/dev/ram0' in window:
                offset = index
                break
            start = index + 1
        if offset >= 0:
            base_pa = contract.load_addresses['kernel_load'] + offset
            writes = []
            for chunk in range(0, 16, 4):
                value = int.from_bytes(replacement[chunk:chunk + 4], 'little')
                writes.append((base_pa + chunk, 4, value))
            boot_patches.setdefault(symbols['start_kernel'], []).extend(writes)
    machine = UnicornMachine(
        contract.raw_kernel, contract.initrd, contract.atags,
        machine_id=contract.machine.machine_id,
        kernel_load=contract.load_addresses['kernel_load'],
        initrd_load=contract.load_addresses['initrd_load'],
        boot_params=contract.load_addresses['boot_params'],
        mmio_read_stubs=stubs or None,
        boot_patches=boot_patches,
        timer_irq_model=not args.no_timer_irq,
        timer_ticks_per_instruction=args.ticks_per_instruction,
        timer_ticks_per_jiffy=args.ticks_per_jiffy,
        timer_irq=args.timer_irq,
        unmapped_mmio_policy=args.unmapped_mmio_policy,
        exclusive_fallback=not args.no_exclusive_fallback,
        data_abort_fsr=args.fsr,
        data_abort_delivery=not args.no_data_abort_delivery,
        uart_base=args.uart_base,
        serial_input=args.serial_input.encode('latin1'),
        trace_user_mode=args.trace_user_mode,
        trace_regs={int(item.split(':')[0], 0):
                    item.split(':')[1].split(',')
                    for item in args.trace_reg},
        boot_params_payload=((contract.sony_payload
                              if args.sony_override else
                              (contract.cmdline.encode('latin1') + b'\x00'
                               if args.cmdline_bootparams else None))),
        probe_write_ranges=tuple(
            (int(item.split('-')[0], 0), int(item.split('-')[1], 0))
            for item in args.probe_write_range),
        trace_printk_at=symbols.get('printk'),
        trace_points=trace_points,
        instruction_limit=args.limit,
        symbols=symbols)
    report = machine.run()
    # E0421: locate candidate uart_port fields (mapbase/membase) in kernel data.
    uart_probe = []
    try:
        data = bytes(machine.uc.mem_read(0x00000000, 0x00800000))
    except Exception:
        data = b''
    if data:
        import struct as _struct
        patterns = (0xF2000000, 0xF2001000, 0xF2002000, 0xF2010000, 0xF2020000)
        for pattern in patterns:
            needle = _struct.pack('<I', pattern)
            start = 0
            while len(uart_probe) < 24:
                index = data.find(needle, start)
                if index < 0:
                    break
                window = data[max(0, index - 0x20):index + 0x40]
                words = [_struct.unpack_from('<I', window, offset)[0]
                         for offset in range(0, len(window) - 3, 4)]
                vas = [f'0x{word:08x}' for word in words
                       if 0xBF000000 <= word <= 0xFFFFFFFF]
                uart_probe.append({
                    'pattern': f'0x{pattern:08x}',
                    'offset': f'0x{index:08x}',
                    'nearby_va': vas[:6],
                    'words': [f'0x{word:08x}' for word in words]})
                start = index + 1
    report['uart_probe'] = uart_probe

    # E0421: the kernel's klog buffer (cmdline klog.addr=0x034A0000, size=0x20000)
    # holds the printk text; extract its readable lines as the boot log.
    klog_lines = []
    try:
        raw = bytes(machine.uc.mem_read(0x034A0000, 0x20000))
        text = ''.join(chr(byte) if 32 <= byte < 127 or byte in (9, 10, 13)
                       else '.' for byte in raw)
        import re as _re
        for line in _re.findall(r'[ -~]{16,}', text):
            klog_lines.append(line)
        (OUT / 'dmesg-klog.txt').write_text('\n'.join(klog_lines), encoding='latin1')
    except Exception:
        klog_lines = []
    report['klog_lines'] = klog_lines[-120:]

    # Scan the emulated RAM for kernel log text: without a registered console the
    # printk ring buffer is the only record of how far the boot got.
    needles = [b'Booting Linux', b'Linux version', b'Kernel command line',
               b'Calibrating delay', b'Memory:', b'GIC', b'ttyAM', b'cramfs',
               b'Freeing', b'initcall', b'sched_clock', b'console', b'timer',
               b'rootfs', b'init/sbin', b'initramfs', b'VFS', b'PID hash']
    found = []
    for base in (0x00000000, 0x80000000):
        data = b''
        try:
            data = bytes(machine.uc.mem_read(base, 0x10000000))
        except Exception:
            continue
        for needle in needles:
            start = 0
            hits = 0
            while hits < 6:
                index = data.find(needle, start)
                if index < 0:
                    break
                excerpt = data[max(0, index - 32):index + 96]
                printable = ''.join(chr(byte) if 32 <= byte < 127 else '.'
                                    for byte in excerpt)
                found.append({'ram': f'0x{base:08x}', 'offset': f'0x{index:08x}',
                              'needle': needle.decode('latin1'),
                              'excerpt': printable})
                hits += 1
                start = index + 1
    report['ram_strings'] = found
    OUT.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    args.serial_output.write_text(report['serial_text'], encoding='latin1')
    print('\nstop:', report['stop_reason'], 'pc', hex(report['stop_pc']),
          report['stop_symbol'])
    print('serial bytes:', report['serial_bytes'])
    print('stubs:', report['stub_hits'])
    print('mmio:', report['mmio_reads'][:12])
    print('hotspots:', report['hotspots'][:6])
    print('unmapped:', report['unmapped'][:3])
    report.update({'contract': {key: verification[key] for key in
                          ('machine', 'load_addresses', 'memory_banks',
                           'reserved_regions', 'cmdline', 'atags')},
                    'contract_checks': verification['checks'],
                    'kernel_sha256_zimage': boot_set.kernel_file().sha256})
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('ram strings found:', len(report['ram_strings']))
    for item in report['ram_strings'][:20]:
        print(' ', item['needle'], item['excerpt'])
    print('report:', args.output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
