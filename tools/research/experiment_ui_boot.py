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
    parser.add_argument('--setting-overlay', choices=('stop', 'experimental-empty', 'observed-gps'), default='stop',
                        help='stop on /setting (default); experimental-empty provides a virtual /setting mountpoint; observed-gps also answers mkdir for the camera-observed /setting/gps directory')
    parser.add_argument('--media-service', choices=('stop', 'authentic-sd'), default='stop',
                        help='stop on MediaCommonDriver queue 0x00d9016e (default); authentic-sd provides SD presence reply')
    parser.add_argument('--kmod-service', choices=('stop', 'verified-image'), default='stop',
                        help='stop on init_module (default); verified-image allows authentic insertion of hash-matched kernel modules')
    parser.add_argument('--gpio-device', choices=('stop', 'driver-bound'), default='stop',
                        help='stop on /dev/gpio (default); driver-bound binds /dev/gpio (240:0) with verified ioctl contracts')
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
    parser.add_argument('--uipc-inject-queue', type=lambda value: int(value, 0), default=None,
                        help='verified UIPC target queue id for one scripted message (opt-in)')
    parser.add_argument('--uipc-inject-payload', default=None,
                        help='hex payload for the one scripted UIPC message')
    parser.add_argument('--uipc-pool-options', choices=('legacy-empty', 'kernel-e0300'),
                        default='legacy-empty', help='opt-in original kernel option stores; callback delivery remains a strict boundary')
    parser.add_argument('--usb-otgcore-device', choices=('stop', 'driver-bound'), default='stop',
                        help='stop on /dev/usb/otgcore (default); driver-bound binds /dev/usb/otgcore (242:2) with verified ioctl contracts')
    parser.add_argument('--usb-reply-policy', choices=('legacy-zero-stubs', 'verified-connect'),
                        default='legacy-zero-stubs',
                        help='USB buspwr/otgcore reply policy; verified-connect implements only evidence-backed replies and stops on undecoded hardware queries')
    parser.add_argument('--hdmi-device', choices=('stop', 'driver-bound'), default='stop',
                        help='stop on /dev/hdmi (default); driver-bound binds /dev/hdmi (248:25) with verified ioctl contracts')
    parser.add_argument('--cec-device', choices=('stop', 'driver-bound'), default='stop',
                        help='stop on /dev/cec (default); driver-bound binds /dev/cec (248:27) with verified ioctl contracts')
    parser.add_argument('--mmca-char-device', choices=('stop', 'driver-bound'), default='stop',
                        help='stop on /dev/mmca-char (default); driver-bound binds /dev/mmca-char (250:0..2) and /dev/ms-char (249:0)')
    parser.add_argument('--gles-device', choices=('stop', 'kernel-bound'), default='stop',
                        help='stop on /dev/dmpgles2 (default); kernel-bound binds /dev/dmpgles2 with verified TASK_SIZE 0x5f000000')
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
