"""Bounded experimental boot-event injection; no authentic producer sequence is claimed."""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import unicorn
import unicorn.arm_const as arm
from project_paths import PROJECT_ROOT
from tools.research.emulator_session import build_boot_session
from src.a6400.execution.guest_memory import cstring_preview, accessible
from src.a6400.execution.guarded_bytes import UnverifiedGuestData


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instructions', type=int, default=15000000)
    parser.add_argument('--timeout-us', type=int, default=60000000)
    parser.add_argument('--trace-library-activation', action='store_true', help='passively record original im.elf dlopen call/return arguments')
    parser.add_argument('--madvise-dontneed', action='store_true', help='discard verified private anonymous pages on MADV_DONTNEED')
    parser.add_argument('--fast-hooks', action='store_true', help='accelerate emulation using block hooks and address-filtered IT workarounds (~100x speedup)')
    parser.add_argument('--stop-worker-main-stack', action='store_true', help='diagnostic stop when a scheduled worker enters the initial main-stack mapping')
    parser.add_argument('--watch-word', action='append', type=lambda value: int(value, 0), default=[], help='record bounded passive writes to a guest diagnostic word')
    parser.add_argument('--argument', action='append', default=[], help='explicit im.elf argument; bootin phase commands use s/g/r/u/l/i/a')
    parser.add_argument('--stimulus', choices=('experimental-events', 'none'), default='experimental-events', help='none lets original startup run without injected queue messages')
    parser.add_argument('--urandom-open', action='store_true', help='open the image-backed 1:9 node; stop before unsupplied entropy bytes')
    parser.add_argument('--urandom-entropy', choices=('stop', 'deterministic'), default='stop',
                        help='stop before unsupplied entropy bytes (default); deterministic supplies explicit 4-byte stack canary entropy')
    parser.add_argument('--tmp-overlay', choices=('stop', 'experimental-empty'), default='stop', help='stop on /tmp (default); experimental-empty answers stat/access of /tmp and ENOENT below it with INVENTED metadata; not camera state')
    parser.add_argument('--stream-device', choices=('stop', 'image-driver'), default='stop',
                        help='image-driver selects verified 249:7 ABI; physical stream bytes remain guarded')
    parser.add_argument('--stream2-device', choices=('stop', 'open-only'), default='stop',
                        help='open-only accepts the observed /dev/stream2 (249:8) O_RDWR|O_DSYNC open and stops at the first ioctl/mmap')
    parser.add_argument('--nflasha4-device', choices=('stop', 'open-only', 'observed-dump'), default='stop',
                        help='stop on /dev/nflasha4 (default); open-only accepts the observed O_RDWR open and stops at the first data/ioctl/mmap; observed-dump serves reads from the hash-checked 12 MiB MPR dump and answers only the observed read-only ioctl 0x80014123 (writes/mmap/other ioctls stay boundaries)')
    parser.add_argument('--mount-service', choices=('stop', 'observed-nflasha1'), default='stop',
                        help='stop on mount(2) (default); observed-nflasha1 serves only the observed read-only mount("/dev/nflasha1","/mnt","vfat",...,"posix_attr") and materializes the hash-checked nflasha1 vfat dump as read-only guest nodes')
    parser.add_argument('--setting-service', choices=('stop', 'observed-nflasha2'), default='stop',
                        help='stop on the /setting namespace (default); observed-nflasha2 materializes the hash-checked read-only nflasha2 vfat dump under /setting (boot-mounted partition; no write path)')
    parser.add_argument('--regular-inode-rdev', action='store_true', help='supply the kernel-derived zero st_rdev for regular image files only')
    parser.add_argument('--readonly-image-times', action='store_true', help='select hash-checked ext2 image timestamps under original read-only mount records; not observed camera state')
    parser.add_argument('--backup-service', choices=('stop', 'unverified-ack', 'preset-backed'), default='stop',
                        help='stop on unsupplied backup replies (default); preset-backed services requests against authentic BK4 preset; unverified-ack reproduces historical experimental acknowledgements')
    parser.add_argument('--graphics-service', choices=('stop', 'authentic-grm'), default='stop',
                        help='stop on unsupplied graphics allocator replies (default); authentic-grm services requests against verified gl_common pool')
    parser.add_argument('--grm-pools', choices=('gl-common-only', 'captured-e0044'), default='gl-common-only',
                        help='authentic-grm pool policy: default single gl_common pool, or the captured E0044 six-pool table (opt-in)')
    parser.add_argument('--null-page', choices=('stop', 'read-zero'), default='stop',
                        help='stop on NULL pointer access (default); read-zero maps read-only zero page at 0x0 (handling MonCtrl debug print flag checks in libMWF)')
    parser.add_argument('--proc-overlay', choices=('stop', 'experimental-empty'), default='stop',
                        help='stop on /proc (default); experimental-empty provides virtual /proc directory and ENOENT for missing runtime nodes')
    parser.add_argument('--setting-overlay', choices=('stop', 'experimental-empty', 'observed-gps', 'observed-e0301'), default='stop',
                        help='stop on /setting (default); experimental-empty provides a virtual /setting mountpoint; observed-gps also answers mkdir for the camera-observed /setting/gps directory')
    parser.add_argument('--media-service', choices=('stop', 'authentic-sd'), default='stop',
                        help='stop on MediaCommonDriver queue 0x00d9016e (default); authentic-sd provides SD presence reply')
    parser.add_argument('--kmod-service', choices=('stop', 'verified-image'), default='stop',
                        help='stop on init_module (default); verified-image allows authentic insertion of hash-matched kernel modules')
    parser.add_argument('--gpio-device', choices=('stop', 'driver-bound'), default='stop',
                        help='stop on /dev/gpio (default); driver-bound binds /dev/gpio (240:0) with verified ioctl contracts')
    parser.add_argument('--kikilog-device', choices=('stop', 'open-only', 'observed-running-e0301'), default='stop',
                        help='opt-in verified kikilog open/close; stop at unsupplied logging/notification state')
    parser.add_argument('--usb-buspower-device', choices=('stop', 'driver-bound'), default='stop',
                        help='stop on /dev/usb/buspwr (default); driver-bound binds /dev/usb/buspwr (248:13) with verified ioctl contracts')
    parser.add_argument('--usb-event-device', choices=('stop', 'driver-bound'), default='stop',
                        help='stop on /dev/usb/event (default); driver-bound binds /dev/usb/event (242:0) with verified ioctl/read contracts')
    parser.add_argument('--usb-connect-event', default=None,
                        help='verified /dev/usb/event record as hex bytes (opt-in; see artifacts/analysis/e0299-usb-connect-event.md)')
    parser.add_argument('--usb-connect-event-file', type=Path, default=None,
                        help='file containing the verified /dev/usb/event record bytes')
    parser.add_argument('--usb-connect-at', type=int, default=0,
                        help='deliver the USB event only after this instruction count')
    parser.add_argument('--guest-env', action='append', default=[], metavar='KEY=VALUE',
                        help='explicit guest environment entry (repeatable); default is empty, reproducing prior runs')
    parser.add_argument('--trace-loader-lookup', action='store_true',
                        help='observe-only hook on the original ld.so _dl_lookup_symbol_x entry')
    parser.add_argument('--trace-loader-address', type=lambda value: int(value, 0),
                        default=0x4000B200,
                        help='guest address range start for loader lookup observation (default 0x4000B200)')
    parser.add_argument('--trace-loader-symbol', default='',
                        help='symbol name to capture; empty uses the Dataflow OSD mute symbol')
    parser.add_argument('--trace-address', type=lambda value: int(value, 0), default=None,
                        help='observe-only stop at one guest guest address and record the last instructions')
    parser.add_argument('--watch-write-range', default=None,
                        help='observe-only write watch on a guest range BEGIN:END (hex), bounded records')
    parser.add_argument('--allocator-audit', action='store_true',
                        help='observe-only glibc malloc/free audit (records sizes and validates free chunk headers)')
    parser.add_argument('--stop-instruction', type=lambda value: int(value, 0), default=None,
                        help='observe-only hard stop when the absolute instruction count reaches this value')
    parser.add_argument('--guest-patch-logalloc-0x50', action='store_true',
                        help='experimental modified-firmware patch: change the stella log-block malloc size 0x4C->0x50 '
                             'in the loaded libObj copy (separate output; recorded in the report)')
    parser.add_argument('--guest-inventory-dir', type=Path, default=None,
                        help='alternate inventory folder (guest-filesystem/baseline/elf-inventory) for a fidelity experiment')
    parser.add_argument('--guest-patch', action='append', default=[],
                        help='experimental modified-firmware patch SPEC = VA:EXPECTED_HEX:REPLACEMENT_HEX '
                             '(e.g. 0x5482E984:0430:0030); repeatable; verified before writing')
    parser.add_argument('--trace-when-r2', type=lambda value: int(value, 0), default=None,
                        help='with --trace-address: only record a hit whose r2 register equals this value')
    parser.add_argument('--trace-when-r0', type=lambda value: int(value, 0), default=None,
                        help='with --trace-address: only record a hit whose r0 register equals this value')
    parser.add_argument('--trace-max-hits', type=int, default=1,
                        help='with --trace-address: record this many matching hits before stopping')
    parser.add_argument('--trace-gles-bar', action='store_true',
                        help='observe-only MMIO read/write logging on the resumed dmpgles2 BAR mapping')
    parser.add_argument('--thread-timeslice', type=int, default=0,
                        help='opt-in deterministic timer preemption: switch a running thread to a '
                             'runnable peer every N guest instructions (0 keeps cooperative baseline)')
    parser.add_argument('--thread-poll-yield', action='store_true',
                        help='opt-in cooperative switch at a syscall boundary when a non-blocking '
                             'UIPC poll returns EAGAIN (lets runnable peers run safely)')
    parser.add_argument('--gles-engine-model', choices=('none', 'command-completion'), default='none',
                        help='opt-in GPES device-work model: command submitted in BAR+0xE8 header '
                             'yields the physically observed IRQ status class 0x40000000 (decoded ack; '
                             'no guest ctx completion)')
    parser.add_argument('--gles-engine-seed-observed-block', action='store_true',
                        help='seed the exact e0377-observed BAR command block (hash d38fef042304f2ae) '
                             'on resume, before running; evidence-backed device state only')
    parser.add_argument('--uipc-inject-queue', type=lambda value: int(value, 0), default=None,
                        help='verified UIPC target queue id for one scripted message (opt-in)')
    parser.add_argument('--uipc-inject-payload', default=None,
                        help='hex payload for the one scripted UIPC message')
    parser.add_argument('--uipc-inject-objmsg-setconfig-queue', type=lambda value: int(value, 0),
                        default=None,
                        help='opt-in experiment: deliver the labelled emulated inbound SETCONFIG '
                             'ObjMsg (E0323/E0324 layout; zeroed param map) to this UIPC queue')
    parser.add_argument('--uipc-inject-objmsg-wake-uaddr', type=lambda value: int(value, 0),
                        default=None,
                        help='optional futex address to wake after the emulated SETCONFIG enqueue '
                             '(e.g. the receiver OSAL condvar observed at the resumed state)')
    parser.add_argument('--uipc-pool-options', choices=('legacy-empty', 'kernel-e0300', 'kernel-e0301', 'kernel-e0303'),
                        default='legacy-empty', help='opt-in kernel options; e0300 keeps completion boundary, e0301 adds ordinary async completion, same-process sync callbacks and kernel dynamic IDs, e0303 adds generic multi-consumer/broadcast completion, sync queue 0x009c015b and allocator-driven CONNECT/dynamic IDs')
    parser.add_argument('--usb-otgcore-device', choices=('stop', 'driver-bound'), default='stop',
                        help='stop on /dev/usb/otgcore (default); driver-bound binds /dev/usb/otgcore (242:2) with verified ioctl contracts')
    parser.add_argument('--usb-reply-policy', choices=('legacy-zero-stubs', 'verified-connect'),
                        default='legacy-zero-stubs',
                        help='USB buspwr/otgcore reply policy; verified-connect implements only evidence-backed replies and stops on undecoded hardware queries')
    parser.add_argument('--usb-function-policy', choices=('legacy', 'descriptor-table'), default='legacy',
                        help='otgcore gadget function selection: default legacy keeps existing SET_CONFIG replies; descriptor-table parses the verified 64-byte layout and selects from GADGET_FUNCTION_TABLE (MSC verified; PTP/UVC stop at descriptor_unresolved)')
    parser.add_argument('--usb-configured-functions',
                        type=lambda value: tuple(part for part in value.split(',') if part),
                        default=('mass-storage',),
                        help='comma-separated GADGET_FUNCTION_TABLE rows for --usb-function-policy descriptor-table')
    parser.add_argument('--hdmi-device', choices=('stop', 'driver-bound'), default='stop',
                        help='stop on /dev/hdmi (default); driver-bound binds /dev/hdmi (248:25) with verified ioctl contracts')
    parser.add_argument('--cec-device', choices=('stop', 'driver-bound'), default='stop',
                        help='stop on /dev/cec (default); driver-bound binds /dev/cec (248:27) with verified ioctl contracts')
    parser.add_argument('--mmca-char-device', choices=('stop', 'driver-bound'), default='stop',
                        help='stop on /dev/mmca-char (default); driver-bound binds /dev/mmca-char (250:0..2) and /dev/ms-char (249:0)')
    parser.add_argument('--gles-device', choices=('stop', 'kernel-bound', 'kernel-bound-decoded'), default='stop',
                        help='stop on /dev/dmpgles2 (default); kernel-bound binds /dev/dmpgles2 with verified '
                             'TASK_SIZE 0x5f000000; kernel-bound-decoded additionally uses the grm_gles.ko-decoded '
                             'GPES ioctl semantics (E0337/E0341: 0x8004820A suspend-status, 0xC004820D wait-completion)')
    parser.add_argument('--nanosleep-policy', choices=('immediate', 'block'), default='immediate',
                        help='threads policy sleep handling: immediate return (default baseline) or block the '
                             'caller in blocked_sleep (no virtual deadline; opt-in for E0310/E0339 monitor loops)')
    parser.add_argument('--mmap-base', type=lambda x: int(x, 0), default=None,
                        help='explicit mmap allocation base; defaults to 0x04000000 when gles-device is kernel-bound')
    parser.add_argument('--log-interval', type=int, default=5000000,
                        help='real-time boot progress heartbeat interval in instructions (0 to disable periodic heartbeats)')
    parser.add_argument('--quiet-boot', action='store_true',
                        help='disable real-time BootLogger milestone streaming and automatic boundary diagnosis')
    parser.add_argument('--save-checkpoint', type=Path, default=None, help='save emulator snapshot to file upon completion')
    parser.add_argument('--load-checkpoint', type=Path, default=None, help='load emulator snapshot from file before execution')
    parser.add_argument('--display-contract', choices=('none', 'camera-e0074-e0044'), default='none',
                        help='opt-in read-only display surface extraction; camera-e0074-e0044 registers the evidence-backed OSD/Sugilite contract')
    parser.add_argument('--report', type=Path, default=PROJECT_ROOT / 'artifacts/execution/interpreter-ui-boot-test.json')
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.instructions <= 0 or args.timeout_us <= 0:
        parser.error('Execution limits must be positive')

    session = build_boot_session(args, parser)
    probe = session.probe
    probe.gles_bar_trace = bool(getattr(args, 'trace_gles_bar', False))
    if getattr(args, 'thread_timeslice', 0) > 0:
        probe.thread_timeslice = args.thread_timeslice
        probe.report['thread_timeslice'] = args.thread_timeslice
        print(f'[*] Deterministic timer preemption enabled: {args.thread_timeslice} instructions.')
    if getattr(args, 'thread_poll_yield', False):
        probe.thread_poll_yield = True
        probe.report['thread_poll_yield'] = True
        print('[*] Cooperative UIPC poll-yield enabled.')
    if getattr(args, 'gles_engine_model', 'none') != 'none':
        probe.gles.engine_model = True
        # A resumed checkpoint may already contain a submitted command and the
        # prior run's completion bookkeeping; the device state is re-evaluated
        # for this run (descriptor presence drives the completion again).
        probe.gles.engine_command_seen = False
        probe.gles.dev_a8 = 0
        probe.gles.engine_completions = 0
        probe.gles.engine_state_events = 0
        probe.gles.engine_submitted = False
        probe.report['gles_engine_model'] = args.gles_engine_model
        ranges = probe.discover_resumed_gles_bar()
        if ranges:
            print(f'[*] GPES engine model enabled: {args.gles_engine_model} '
                  f'(BAR 0x{ranges[0][0]:x}+0x{ranges[0][1]:x}; command-completion -> '
                  'observed IRQ class 0x40000000; no guest ctx completion).')
            probe.install_resumed_gles_bar_hooks()
            if getattr(args, 'gles_engine_seed_observed_block', False):
                # Exact command block recorded from the guest's own writes in
                # e0377 (ring-values hash d38fef042304f2ae): header +0xE8..+0xF0
                # then the 0x80-byte descriptor +0xF4..+0x174.
                import struct as _struct
                block = bytearray(0x8C)
                block[0x00:0x04] = _struct.pack('<I', 0x00050001)
                _struct.pack_into('<I', block, 0x04, 0xFFFFFFFF)
                _struct.pack_into('<I', block, 0x08, 0)
                _struct.pack_into('<I', block, 0x04, 0)
                words = [0x21, 0x8, 0x3E8, 0x579CF460, 0x2, 0x599F8, 0x59948,
                         0x11B7B0, 0x11B7A0, 0x1, 0, 0, 5, 0, 0, 0x579D8020,
                         0x202E8020, 0x4] + [0] * 12 + [0x99E10, 0x99E30]
                for index, value in enumerate(words):
                    _struct.pack_into('<I', block, 0x0C + index * 4, value)
                probe.mu.mem_write(ranges[0][0] + 0xE8, bytes(block))
                probe.report['gles_engine_seed'] = {
                    'source': 'e0377 observed BAR command block',
                    'bar': ranges[0][0], 'length': len(block),
                    'sha256': __import__('hashlib').sha256(bytes(block)).hexdigest()}
        else:
            print(f'[*] GPES engine model enabled: {args.gles_engine_model} '
                  '(no resumed BAR range yet; fresh mmap will bind it).')
    if getattr(args, 'trace_loader_lookup', False):
        from src.a6400.execution.loader_trace import (DEFAULT_SYMBOL,
                                                       install_loader_lookup_trace)
        install_loader_lookup_trace(probe, args.trace_loader_address,
                                    args.trace_loader_symbol or DEFAULT_SYMBOL)
        print(f'[*] Observing original loader lookup at 0x{args.trace_loader_address:08x}.')
    if getattr(args, 'trace_gles_bar', False):
        ranges = probe.install_resumed_gles_bar_hooks()
        if ranges:
            print(f'[*] Observing GPES BAR at {["0x%x+0x%x" % item for item in ranges]}.')
        else:
            print('[!] --trace-gles-bar: no resumed dmpgles2 device range found.')
    if getattr(args, 'trace_address', None) is not None:
        probe.install_trace_address(args.trace_address,
                                    when_r2=getattr(args, 'trace_when_r2', None),
                                    when_r0=getattr(args, 'trace_when_r0', None),
                                    max_hits=getattr(args, 'trace_max_hits', 1))
        print(f'[*] Observing one guest address at 0x{args.trace_address:08x}.')
    if getattr(args, 'watch_write_range', None):
        try:
            begin_text, end_text = args.watch_write_range.split(':', 1)
            watch_begin, watch_end = int(begin_text, 0), int(end_text, 0)
        except ValueError as error:
            raise SystemExit(f'--watch-write-range expects BEGIN:END (hex): {error}')
        probe.install_write_watch(watch_begin, watch_end)
        print(f'[*] Observing writes in 0x{watch_begin:08x}-0x{watch_end:08x}.')
    if getattr(args, 'allocator_audit', False):
        probe.install_allocator_audit()
        print('[*] glibc allocator audit enabled (malloc/free chunk validation).')
    if getattr(args, 'stop_instruction', None):
        probe.install_instruction_stop(args.stop_instruction)
        print(f'[*] Hard stop at absolute instruction {args.stop_instruction}.')
    for patch_spec in (getattr(args, 'guest_patch', None) or []):
        try:
            va_text, expected_text, replacement_text = patch_spec.split(':')
            patch_va = int(va_text, 0)
            expected = bytes.fromhex(expected_text)
            replacement = bytes.fromhex(replacement_text)
        except ValueError as error:
            raise SystemExit(f'--guest-patch expects VA:EXPECTED:REPLACEMENT: {error}')
        if len(expected) != len(replacement):
            raise SystemExit('--guest-patch expected and replacement lengths must match')
        try:
            current = bytes(probe.mu.mem_read(patch_va, len(expected)))
        except Exception as error:
            raise SystemExit(f'guest patch: cannot read 0x{patch_va:08x}: {error}')
        if current != expected:
            raise SystemExit(f'guest patch: unexpected bytes at 0x{patch_va:08x}: '
                             f'{current.hex()} (expected {expected.hex()})')
        probe.mu.mem_write(patch_va, replacement)
        entry = {'label': 'guest_patch_cli', 'va': patch_va,
                 'expected_hex': expected.hex(), 'replacement_hex': replacement.hex(),
                 'source': 'guest-patch CLI (modified-firmware experiment)'}
        probe.report.setdefault('guest_patches', []).append(entry)
        print(f'[*] Experimental guest patch 0x{patch_va:08x}: {expected.hex()} -> {replacement.hex()}')
    if getattr(args, 'guest_patch_logalloc_0x50', False):
        patch_va = 0x5482FE16
        expected = b'\x4c\x20'
        replacement = b'\x50\x20'
        try:
            current = bytes(probe.mu.mem_read(patch_va, 2))
        except Exception as error:
            raise SystemExit(f'guest patch: cannot read 0x{patch_va:08x}: {error}')
        if current != expected:
            raise SystemExit(f'guest patch: unexpected bytes at 0x{patch_va:08x}: '
                             f'{current.hex()} (expected {expected.hex()})')
        probe.mu.mem_write(patch_va, replacement)
        probe.report['guest_patch'] = {
            'label': 'stella_logalloc_chunksize_0x50_overlay',
            'va': patch_va, 'expected_hex': expected.hex(),
            'replacement_hex': replacement.hex(),
            'source': 'extracted libObj.so offset 0x79FE16 (movs r0,#0x4C -> #0x50)'}
        print(f'[*] Experimental guest patch applied at 0x{patch_va:08x}: '
              f'{expected.hex()} -> {replacement.hex()} (log-block malloc 0x4C->0x50).')
    manifest = session.manifest
    if session.usb_connect_event:
        probe.arm_usb_connect_event(session.usb_connect_event, session.usb_connect_at)
        print(f'[*] Armed verified USB connect event ({len(session.usb_connect_event)} bytes, at instruction {session.usb_connect_at}).')
    if session.uipc_inject_payload:
        try:
            entry = probe.inject_uipc_message(session.uipc_inject_queue,
                                              session.uipc_inject_payload, source='cli')
            print(f"[*] Injected UIPC message queue=0x{session.uipc_inject_queue:08x} "
                  f"size={entry['size']} woken={entry['woken']}.")
        except Exception as error:
            probe.report['uipc_injection_error'] = str(error)
            print(f'[!] UIPC injection failed: {error}')
    if session.uipc_setconfig_objmsg_queue is not None:
        try:
            entry = probe.inject_uipc_setconfig_objmsg(
                session.uipc_setconfig_objmsg_queue,
                wake_uaddr=session.uipc_setconfig_objmsg_wake)
            print(f"[*] Injected emulated SETCONFIG ObjMsg queue=0x"
                  f"{entry['queue']:08x} obj=0x{entry['objmsg']:08x} "
                  f"woken={entry['woken']} (labelled experiment).")
        except Exception as error:
            probe.report['uipc_objmsg_injection_error'] = str(error)
            print(f'[!] SETCONFIG ObjMsg injection failed: {error}')

    print(f"[*] Running probe (budget: {args.instructions} instructions)...")
    report = probe.run(instruction_budget=args.instructions, timeout_us=args.timeout_us)
    if args.save_checkpoint:
        print(f'[*] Saving checkpoint to: {args.save_checkpoint}...')
        from src.a6400.execution.guest_checkpoint import save_checkpoint
        sz = save_checkpoint(probe, args.save_checkpoint)
        print(f'[*] Checkpoint saved successfully ({sz:,} bytes) at instruction {probe.instructions:,}!')
    report['boot_stimulus'] = {
        'queue': '0x0094016a', 'injected': session.injected, 'deliveries': session.injection_records,
        'pending': [hex(event) for event in session.boot_events_to_inject],
        'payload': 'event ID followed by 60 zero bytes' if args.stimulus == 'experimental-events' else None,
        'mode': args.stimulus,
        'classification': ('experimental injection; identifiers from static handlers, producer ordering and payload not validated'
                           if args.stimulus == 'experimental-events' else 'no queue stimuli supplied; argv is an explicit process input'),
        'delivery': 'one event on empty Task 94 queue at receive' if args.stimulus == 'experimental-events' else 'none',
    }
    report['filesystem_sources'] = manifest['images']
    boundary = report.get('boundary', {})
    if boundary.get('r7') == 128 and boundary.get('arguments'):
        address, length, parameters = boundary['arguments'][:3]
        diagnostic = {'classification': 'post-stop diagnostic; init_module is not serviced',
                      'address': address, 'length': length, 'parameters_address': parameters,
                      'parameters_preview': cstring_preview(probe.mu, parameters)}
        if 0 < length <= 64 * 1024 * 1024 and accessible(probe.mu, address, length, unicorn.UC_PROT_READ):
            try:
                probe._before_host_read(address, length)
            except UnverifiedGuestData as error:
                diagnostic.update(payload_status='unverified_payload_bytes', details=error.details)
            else:
                payload_hash = hashlib.sha256(probe.mu.mem_read(address, length)).hexdigest()
                diagnostic.update(sha256=payload_hash, matching_verified_files=[
                    path for path, content in probe.filesystem.cache.items()
                    if len(content) == length and hashlib.sha256(content).hexdigest() == payload_hash])
        else:
            diagnostic['payload_status'] = 'outside_diagnostic_read_contract'
        report['module_load_request'] = diagnostic
    if boundary.get('r7') in (5, 33, 195) and boundary.get('arguments'):
        report['requested_path_preview'] = cstring_preview(probe.mu, boundary['arguments'][0])
    report['registers'] = {name: probe.mu.reg_read(getattr(arm, 'UC_ARM_REG_' + name.upper()))
                           for name in ('r0', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7',
                                        'r8', 'r9', 'r10', 'r11', 'r12', 'sp', 'lr', 'pc', 'cpsr')}
    report['tls_observation'] = {
        'hardware_tpidruro': probe.mu.reg_read(arm.UC_ARM_REG_C13_C0_3),
        'software_slot': int.from_bytes(probe.mu.mem_read(0xffff0ff0, 4), 'little'),
        'kuser_model': probe.kuser.tls_value,
        'current_tid': probe.threads.current_tid,
        'current_thread_tls': probe.threads.threads[probe.threads.current_tid].tls_val,
    }
    report['library_activation_calls'] = session.activation_calls
    report['watched_writes'] = session.watched_writes
    report['watched_words'] = {hex(word): (bytes(probe.mu.mem_read(word, 4)).hex()
                                           if accessible(probe.mu, word, 4, unicorn.UC_PROT_READ) else 'unreadable')
                               for word in args.watch_word}
    report['im_state_observation'] = {
        'scope': 'post-stop diagnostic of im.elf globals; not a camera-state snapshot',
        'flags_address': 0x14ee8,
        'flags': int.from_bytes(probe.mu.mem_read(0x14ee8, 4), 'little'),
        'target_pointer_address': 0x14eec,
        'target_pointer': int.from_bytes(probe.mu.mem_read(0x14eec, 4), 'little'),
    }
    report['stdout'] = b''.join(probe.stdio.stdout_log).decode('latin1')
    report['stderr'] = b''.join(probe.stdio.stderr_log).decode('latin1')
    if probe.display is None:
        report['display_validation'] = 'No camera-verified geometry, format, physical address, or submission contract supplied.'
    else:
        report['display_validation'] = ('Read-only extraction under the evidence-backed camera-e0074-e0044 display contract; '
                                        'Sugilite 16-bit format remains a hypothesis until a live camera capture confirms it.')
        frame = probe.capture_display()
        if frame is not None:
            from PIL import Image
            report['display_frame'] = frame.metadata()
            out = PROJECT_ROOT / 'artifacts/reports' / f"display-{frame.surface.name}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes('RGBA', (frame.surface.width, frame.surface.height), frame.rgba).save(out)
            print(f"[+] Display frame captured from guest memory: {frame.surface.name} ({frame.status}) -> {out}")
        else:
            print("[!] Display contract active but no mapped display surface was found.")
    out_file = args.report
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"[*] Report saved to: {out_file}")

    print(f"[*] Stopped with status: {report['status']}")
    print(f"[*] Instructions executed: {report['instructions_executed']}")
    print(f"[*] Syscalls serviced: {report['syscall_responses_supplied']}")
    print(f"[*] Injected events: {session.injected}")
    print(f"[*] Framebuffer transactions: {len(report.get('framebuffer', {}).get('transactions', []))}")
    if probe.fb.transactions and probe.fb.vram_base is not None:
        print("[!] Framebuffer transactions detail:")
        for t in probe.fb.transactions:
            print(f"    {t}")
        img = probe.fb.extract_image(probe.mu.mem_read)
        render_path = PROJECT_ROOT / 'artifacts/reports/experimental-framebuffer.png'
        render_path.parent.mkdir(parents=True, exist_ok=True)
        if img is None:
            raise ValueError('No decodable mapped framebuffer')
        img.save(render_path)
        print(f"[!] Saved experimental framebuffer diagnostic to: {render_path}")

    opens = [s for s in report.get('serviced_syscalls', []) if s.get('syscall') == 'open' and 0 <= s.get('returned', -1) < 0x80000000]
    print(f"[*] Open files count: {len(opens)}")
    for o in opens:
        print(f"    fd={o.get('returned')}: {o.get('path')}")

    if not args.quiet_boot:
        from tools.camera_link import BoundaryAnalyzer, format_boundary_report
        analyzer = BoundaryAnalyzer()
        print(format_boundary_report(analyzer.analyze_report(report)))


if __name__ == '__main__':
    main()
