"""Bounded experimental boot-event injection; no authentic producer sequence is claimed."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
import unicorn
import unicorn.arm_const as arm
from project_paths import PROJECT_ROOT
from tools.research.probe_interpreter import load_guest_image
from src.a6400.execution.interpreter_probe import InterpreterProbe
from tools.research.guest_layout import resolve_guest
from tools.research.inventory import digest
from src.a6400.execution.guest_uname import extract_kernel_uts
from src.a6400.images.verified_content import VerifiedContent
from src.a6400.images.ext2_metadata import Ext2Metadata
from src.a6400.execution.guest_kuser import extract_kuser_template
from src.a6400.execution.guest_memory import cstring_preview, accessible
from src.a6400.execution.guarded_bytes import UnverifiedGuestData
from tools.research.mount_evidence import checked_input, inspect_init

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instructions', type=int, default=15000000)
    parser.add_argument('--timeout-us', type=int, default=60000000)
    parser.add_argument('--trace-library-activation', action='store_true', help='passively record original im.elf dlopen call/return arguments')
    parser.add_argument('--madvise-dontneed', action='store_true', help='discard verified private anonymous pages on MADV_DONTNEED')
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
    parser.add_argument('--null-page', choices=('stop', 'read-zero'), default='stop',
                        help='stop on NULL pointer access (default); read-zero maps read-only zero page at 0x0 (handling MonCtrl debug print flag checks in libMWF)')
    parser.add_argument('--proc-overlay', choices=('stop', 'experimental-empty'), default='stop',
                        help='stop on /proc (default); experimental-empty provides virtual /proc directory and ENOENT for missing runtime nodes')
    parser.add_argument('--setting-overlay', choices=('stop', 'experimental-empty'), default='stop',
                        help='stop on /setting (default); experimental-empty provides virtual /setting mountpoint directory')
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
    parser.add_argument('--gles-device', choices=('stop', 'kernel-bound'), default='stop',
                        help='stop on /dev/dmpgles2 (default); kernel-bound binds /dev/dmpgles2 with verified TASK_SIZE 0x5f000000')
    parser.add_argument('--mmap-base', type=lambda x: int(x, 0), default=None,
                        help='explicit mmap allocation base; defaults to 0x04000000 when gles-device is kernel-bound')
    parser.add_argument('--report', type=Path, default=PROJECT_ROOT / 'artifacts/execution/interpreter-ui-boot-test.json')
    args = parser.parse_args()
    if args.instructions <= 0 or args.timeout_us <= 0:
        parser.error('Execution limits must be positive')
    folder = PROJECT_ROOT / 'artifacts/inventory'
    manifest = json.loads((folder / 'guest-filesystem.json').read_text(encoding='utf-8'))
    inventory = json.loads((folder / 'elf-inventory.json').read_text(encoding='utf-8'))['entries']
    baseline = json.loads((folder / 'baseline.json').read_text(encoding='utf-8'))
    expected_inputs = {item['path']: item['sha256'] for item in baseline['inputs']}
    
    for image in manifest['images']:
        local = (PROJECT_ROOT / image['path']).resolve()
        if not local.is_relative_to((PROJECT_ROOT / 'firmware').resolve()) or digest(local) != image['sha256']:
            raise ValueError('Original filesystem image path/hash mismatch')
    app = load_guest_image(manifest, inventory, '/usr/bin/im.elf')
    interp = load_guest_image(manifest, inventory, app['interpreter'])

    # Kernel uname and kuser
    kernel = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
    kernel_sha = expected_inputs[kernel]
    uname_profile = extract_kernel_uts(PROJECT_ROOT / kernel, kernel_sha)
    kuser_template = extract_kuser_template(PROJECT_ROOT / kernel, kernel_sha)

    # Content loader & filesystem
    content_loader = VerifiedContent(PROJECT_ROOT, PROJECT_ROOT / 'firmware', expected_inputs)
    filesystem = {'nodes': manifest['nodes'], 'content_loader': content_loader, 'urandom_open': args.urandom_open,
                  'urandom_entropy_policy': args.urandom_entropy,
                  'regular_inode_rdev': args.regular_inode_rdev, 'tmp_overlay': args.tmp_overlay, 'proc_overlay': args.proc_overlay, 'setting_overlay': args.setting_overlay,
                  'readonly_image_times': args.readonly_image_times}
    if args.stream_device == 'image-driver':
        from tools.research.stream_contract import load_stream_profile
        filesystem['stream_profile'] = load_stream_profile()
        stream_node = manifest['nodes'].get('/dev/stream', {})
        if stream_node.get('kind') != 'special' or stream_node.get('mode', 0) & 0o170000 != 0o020000:
            raise ValueError('Expected original stream character node')
    readonly_mounts = []
    if args.readonly_image_times:
        init_path = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/sbin/init'
        init_hash = expected_inputs[init_path]
        mount_rows = inspect_init(checked_input(PROJECT_ROOT, init_path, init_hash))['mounts']
        for image in manifest['images']:
            target = '/rootfs' if image['planned_mount'] == '/' else image['planned_mount']
            candidates = [row for row in mount_rows if row['target'] == target and row['filesystem'] == 'ext2'
                          and row['source'] in ('/dev/' + Path(image['path']).name,
                                                '/dev/d' + Path(image['path']).name)]
            if not candidates or any(not row['flags'] & 1 for row in candidates):
                raise ValueError('Read-only ext2 mount selection is not established for image')
            readonly_mounts.append({'image_sha256': image['sha256'], 'target': target, 'filesystem': 'ext2',
                                    'flags': candidates[0]['flags'], 'init_sha256': init_hash,
                                    'candidate_records': candidates})

    boot_mount_data = json.loads((folder / 'boot-mount-trace.json').read_text(encoding='utf-8'))
    major = boot_mount_data['devnodes_summary']['nflasha']['major']
    for image in manifest['images']:
        source = Ext2Metadata(PROJECT_ROOT / image['path'], image['sha256'])
        indexed = source.index()
        for node in filesystem['nodes'].values():
            if node.get('image') != Path(image['path']).name:
                continue
            metadata = indexed[node['archive_path'] or '/']
            node_stat = {**metadata, 'image_sha256': image['sha256']}
            part_num = 7 if 'nflasha7' in image['path'] else 15
            node_stat['st_dev'] = (major << 8) | part_num
            if args.readonly_image_times:
                node_stat['readonly_image_mount'] = next(row for row in readonly_mounts
                                                        if row['image_sha256'] == image['sha256'])
            node['stat_metadata'] = node_stat

    if args.stream_device == 'image-driver':
        stream_metadata = filesystem['nodes']['/dev/stream']['stat_metadata']
        if stream_metadata.get('device_number') != {'major': 249, 'minor': 7}:
            raise ValueError('Original ext2 stream node does not match verified devno identity')

    mmap_base = args.mmap_base
    mmap_search_low = 0x10000000 if args.gles_device == 'kernel-bound' else None
    probe = InterpreterProbe(syscall_policy='threads', uname_profile=uname_profile,
                             filesystem=filesystem, kuser_template=kuser_template,
                             madvise_policy='private-anonymous-dontneed' if args.madvise_dontneed else 'stop',
                             backup_service_policy=args.backup_service,
                             graphics_service_policy=args.graphics_service,
                             null_page_policy=args.null_page,
                             kmod_service_policy=args.kmod_service,
                             media_service_policy=args.media_service,
                             mmap_base=mmap_base,
                             mmap_search_low=mmap_search_low)
    stack_bottom = 0x5e390000 if args.gles_device == 'kernel-bound' else 0x7fe00000
    stack_size = 0x800000 if args.gles_device == 'kernel-bound' else 0x100000
    probe.prepare(app, interp, ['/usr/bin/im.elf', *args.argument], stack_bottom=stack_bottom, stack_size=stack_size)
    if args.gles_device == 'kernel-bound':
        from src.a6400.execution.guest_gles import GuestGles, GlesBinding
        from src.a6400.execution.kernel_task_identity import KernelTaskObservation
        header = struct.pack('<6I', 0, 1, 0x5f000000, 0x8000, 0, 0)
        task_bytes = bytearray(0x10c)
        struct.pack_into('<I', task_bytes, 8, 0x2000)
        struct.pack_into('<2I', task_bytes, 0x104, 1003, 1000)
        task_obs = KernelTaskObservation.read(lambda a, s: header if a == 0x2000 else task_bytes, 0x2000)
        probe.gles = GuestGles(GlesBinding(task_obs))
    if args.gpio_device == 'driver-bound':
        from src.a6400.execution.guest_gpio import GuestGpio
        probe.gpio = GuestGpio()
    if args.usb_buspower_device == 'driver-bound':
        from src.a6400.execution.guest_usb_buspower import GuestUsbBusPower
        probe.usb_buspower = GuestUsbBusPower()
    if args.usb_event_device == 'driver-bound':
        from src.a6400.execution.guest_usb_event import GuestUsbEvent
        probe.usb_event = GuestUsbEvent()
    if args.readonly_image_times:
        probe.report['readonly_image_mount_selection'] = readonly_mounts

    if args.stop_worker_main_stack:
        def check_worker_stack(mu, address, size, _):
            sp = mu.reg_read(arm.UC_ARM_REG_SP)
            stack = probe.report['stack']
            if probe.threads.current_tid != 1000 and stack['bottom'] <= sp < stack['bottom'] + stack['size']:
                probe.report.update(status='diagnostic_thread_stack_boundary',
                                    boundary={'reason': 'scheduled_worker_in_initial_main_stack',
                                              'tid': probe.threads.current_tid, 'pc': address, 'sp': sp})
                mu.emu_stop()
        probe.mu.hook_add(unicorn.UC_HOOK_CODE, check_worker_stack)

    activation_calls = []
    if args.trace_library_activation:
        def observe_activation(mu, address, size, _):
            if address == 0xb21c and len(activation_calls) < 64:
                activation_calls.append({'call_pc': address, 'instruction': probe.instructions,
                                          'tid': probe.threads.current_tid,
                                          'name': cstring_preview(mu, mu.reg_read(arm.UC_ARM_REG_R0)),
                                          'mode': mu.reg_read(arm.UC_ARM_REG_R1)})
            elif address == 0xb220 and activation_calls:
                activation_calls[-1]['returned_handle'] = mu.reg_read(arm.UC_ARM_REG_R0)
        probe.mu.hook_add(unicorn.UC_HOOK_CODE, observe_activation, begin=0xb21c, end=0xb220)

    watched_writes = []
    def watch_write(mu, access, address, size, value, _):
        for word in args.watch_word:
            if address < word + 4 and word < address + size and len(watched_writes) < 128:
                watched_writes.append({'word': word, 'address': address, 'size': size, 'value': value,
                                       'pc': mu.reg_read(arm.UC_ARM_REG_PC),
                                       'sp': mu.reg_read(arm.UC_ARM_REG_SP),
                                       'tid': probe.threads.current_tid, 'instruction': probe.instructions})
    for word in args.watch_word:
        if not 16 <= word <= 0xfffffffc or word % 4:
            parser.error('Watched words must be aligned ARM32 addresses')
        probe.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, watch_write, begin=word - 15, end=word + 3)

    # Static handler identifiers; ordering and zero-filled bodies are experimental inputs.
    print("[*] Prepared InterpreterProbe with threads policy.")

    original_rcv = probe.uipc.handle_rcv_msg_tmo
    boot_events_to_inject = ([0x00940007, 0x0092014b, 0x00940036, 0x00940038, 0x00920152]
                             if args.stimulus == 'experimental-events' else [])
    injected = []
    injection_records = []

    def patched_rcv_msg_tmo(memory_reader, memory_writer, arg_ptr: int) -> int:
        raw_arg = memory_reader(arg_ptr, 16)
        queue, p_out_msg, out_msg, timeout = struct.unpack('<IIII', raw_arg)
        
        # If Task 94's queue is empty and we have boot events, inject the next one
        if queue == 0x0094016a and not probe.uipc.message_queues.get(queue, []) and boot_events_to_inject:
            if probe.uipc.pool_base is not None:
                try:
                    event_id = boot_events_to_inject[0]
                    msg_addr = probe.uipc.allocate_message(64)
                    payload = struct.pack('<I60s', event_id, b'\x00' * 60)
                    probe.mu.mem_write(msg_addr, payload)
                    probe.uipc.enqueue_message(queue, msg_addr)
                    boot_events_to_inject.pop(0)
                    injected.append(hex(event_id))
                    injection_records.append({'event': hex(event_id), 'message': msg_addr,
                                              'instruction': probe.instructions,
                                              'pc': probe.mu.reg_read(arm.UC_ARM_REG_PC)})
                    print(f"[+] Injected experimental boot event {hex(event_id)} on queue 0x0094016a (msg @ {hex(msg_addr)})")
                except Exception as ex:
                    probe.report.update(status='stimulus_error', boundary={'error': str(ex), 'event': hex(event_id)})
                    probe.mu.emu_stop()
                    return -1

        return original_rcv(memory_reader, memory_writer, arg_ptr)

    probe.uipc.handle_rcv_msg_tmo = patched_rcv_msg_tmo

    print(f"[*] Running probe (budget: {args.instructions} instructions)...")
    report = probe.run(instruction_budget=args.instructions, timeout_us=args.timeout_us)
    report['boot_stimulus'] = {
        'queue': '0x0094016a', 'injected': injected, 'deliveries': injection_records,
        'pending': [hex(event) for event in boot_events_to_inject],
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
    report['library_activation_calls'] = activation_calls
    report['watched_writes'] = watched_writes
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
    report['display_validation'] = 'No camera-verified geometry, format, physical address, or submission contract supplied.'
    out_file = args.report
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"[*] Report saved to: {out_file}")

    print(f"[*] Stopped with status: {report['status']}")
    print(f"[*] Instructions executed: {report['instructions_executed']}")
    print(f"[*] Syscalls serviced: {report['syscall_responses_supplied']}")
    print(f"[*] Injected events: {injected}")
    print(f"[*] Framebuffer transactions: {len(report.get('framebuffer', {}).get('transactions', []))}")
    if probe.fb.transactions and probe.fb.vram_base is not None:
        print("[!] Framebuffer transactions detail:")
        for t in probe.fb.transactions:
            print(f"    {t}")
        # Diagnostic extraction only; ioctl activity does not prove rendering.
        img = probe.fb.extract_image(probe.mu.mem_read)
        render_path = PROJECT_ROOT / 'artifacts/reports/experimental-framebuffer.png'
        render_path.parent.mkdir(parents=True, exist_ok=True)
        if img is None:
            raise ValueError('No decodable mapped framebuffer')
        img.save(render_path)
        print(f"[!] Saved experimental framebuffer diagnostic to: {render_path}")
            
    # Check open files / libraries
    opens = [s for s in report.get('serviced_syscalls', []) if s.get('syscall') == 'open' and 0 <= s.get('returned', -1) < 0x80000000]
    print(f"[*] Open files count: {len(opens)}")
    for o in opens:
        print(f"    fd={o.get('returned')}: {o.get('path')}")


if __name__ == '__main__':
    main()

