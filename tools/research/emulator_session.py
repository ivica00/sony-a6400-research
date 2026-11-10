"""Reusable bounded boot-session construction for the CLI and the emulator GUI.

The setup below is the verified experiment used by
``tools.research.experiment_ui_boot``.  It is factored here so the GUI can
reuse exactly the same inputs, guards and device policies instead of growing a
second boot harness.  Construction has no side effects on the camera; it reads
only hash-checked local inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional

import unicorn
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from tools.research.probe_interpreter import load_guest_image
from tools.research.mount_evidence import checked_input, inspect_init
from tools.research.inventory import digest
from src.a6400.execution.interpreter_probe import InterpreterProbe
from src.a6400.execution.guest_display import display_contract
from src.a6400.execution.guest_kuser import extract_kuser_template
from src.a6400.execution.guest_memory import accessible, cstring_preview
from src.a6400.execution.guest_uname import extract_kernel_uts
from src.a6400.execution.guarded_bytes import UnverifiedGuestData
from src.a6400.images.ext2_metadata import Ext2Metadata
from src.a6400.images.verified_content import VerifiedContent


@dataclass
class BootSession:
    probe: InterpreterProbe
    manifest: Dict[str, Any]
    filesystem: Dict[str, Any]
    boot_events_to_inject: List[int] = field(default_factory=list)
    injected: List[str] = field(default_factory=list)
    injection_records: List[Dict[str, Any]] = field(default_factory=list)
    activation_calls: List[Dict[str, Any]] = field(default_factory=list)
    watched_writes: List[Dict[str, Any]] = field(default_factory=list)
    readonly_mounts: List[Dict[str, Any]] = field(default_factory=list)
    display_contract: str = 'none'
    usb_connect_event: Optional[bytes] = None
    usb_connect_at: int = 0
    uipc_inject_queue: Optional[int] = None
    uipc_inject_payload: Optional[bytes] = None


def build_boot_session(args, parser=None) -> BootSession:
    """Build the prepared probe and its explicit experimental state.

    This performs the same hash/namespace checks as the CLI.  It does not run
    the guest and does not contact the camera.
    """
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

    kernel = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
    kernel_sha = expected_inputs[kernel]
    uname_profile = extract_kernel_uts(PROJECT_ROOT / kernel, kernel_sha)
    kuser_template = extract_kuser_template(PROJECT_ROOT / kernel, kernel_sha)

    content_loader = VerifiedContent(PROJECT_ROOT, PROJECT_ROOT / 'firmware', expected_inputs)
    filesystem = {
        'nodes': manifest['nodes'], 'content_loader': content_loader,
        'urandom_open': args.urandom_open,
        'urandom_entropy_policy': args.urandom_entropy,
        'regular_inode_rdev': args.regular_inode_rdev,
        'tmp_overlay': args.tmp_overlay, 'proc_overlay': args.proc_overlay,
        'setting_overlay': args.setting_overlay,
        'readonly_image_times': args.readonly_image_times,
    }
    if args.stream_device == 'image-driver':
        from tools.research.stream_contract import load_stream_profile
        stream_profile = load_stream_profile()
        if args.media_service == 'authentic-sd':
            from tools.research.wbi_memory import IMAGE as WBI_IMAGE, parse_sections, decode_section
            wbi_raw = checked_input(PROJECT_ROOT, WBI_IMAGE, expected_inputs[WBI_IMAGE])
            _, wbi_secs = parse_sections(wbi_raw)
            s555, _, _ = decode_section(wbi_raw, wbi_secs[555])
            stream_profile['backed_physical_ranges'] = {
                (0x20030000, 0x68000): s555[0x8000:0x70000]
            }
        filesystem['stream_profile'] = stream_profile
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

    contract_name = getattr(args, 'display_contract', 'none')
    display_profile = None if contract_name in (None, '', 'none') else display_contract(contract_name)

    mmap_base = args.mmap_base
    mmap_search_low = 0x10000000 if args.gles_device == 'kernel-bound' else None
    probe = InterpreterProbe(syscall_policy='threads', uname_profile=uname_profile,
                             filesystem=filesystem, kuser_template=kuser_template,
                             madvise_policy='private-anonymous-dontneed' if args.madvise_dontneed else 'stop',
                             backup_service_policy=args.backup_service,
                             graphics_service_policy=args.graphics_service,
                             null_page_policy=args.null_page,
                             hook_mode='fast' if args.fast_hooks else 'instruction',
                             kmod_service_policy=args.kmod_service,
                             media_service_policy=args.media_service,
                             mmap_base=mmap_base,
                             mmap_search_low=mmap_search_low,
                             display_profile=display_profile,
                             grm_pool_policy=getattr(args, 'grm_pools', 'gl-common-only'))
    stack_bottom = 0x5e390000 if args.gles_device == 'kernel-bound' else 0x7fe00000
    stack_size = 0x800000 if args.gles_device == 'kernel-bound' else 0x100000
    probe.prepare(app, interp, ['/usr/bin/im.elf', *args.argument],
                  stack_bottom=stack_bottom, stack_size=stack_size)
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
        probe.usb_buspower = GuestUsbBusPower(
            reply_policy=getattr(args, 'usb_reply_policy', 'legacy-zero-stubs'))
    if args.usb_event_device == 'driver-bound':
        from src.a6400.execution.guest_usb_event import GuestUsbEvent
        probe.usb_event = GuestUsbEvent()
    if args.usb_otgcore_device == 'driver-bound':
        from src.a6400.execution.guest_usb_otgcore import GuestUsbOtgCore
        probe.usb_otgcore = GuestUsbOtgCore(
            reply_policy=getattr(args, 'usb_reply_policy', 'legacy-zero-stubs'))
    if args.hdmi_device == 'driver-bound':
        from src.a6400.execution.guest_hdmi import GuestHdmi
        probe.hdmi = GuestHdmi()
    if args.cec_device == 'driver-bound':
        from src.a6400.execution.guest_cec import GuestCec
        probe.cec = GuestCec()
    if args.mmca_char_device == 'driver-bound':
        from src.a6400.execution.guest_mmca_char import GuestMmcChar
        probe.mmca_char = GuestMmcChar()
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
            if parser is not None:
                parser.error('Watched words must be aligned ARM32 addresses')
            raise ValueError('Watched words must be aligned ARM32 addresses')
        probe.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, watch_write, begin=word - 15, end=word + 3)

    original_rcv = probe.uipc.handle_rcv_msg_tmo
    boot_events_to_inject = ([0x00940007, 0x0092014b, 0x00940036, 0x00940038, 0x00920152]
                             if args.stimulus == 'experimental-events' else [])
    injected = []
    injection_records = []

    def patched_rcv_msg_tmo(memory_reader, memory_writer, arg_ptr: int) -> int:
        raw_arg = memory_reader(arg_ptr, 16)
        queue, p_out_msg, out_msg, timeout = struct.unpack('<IIII', raw_arg)
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

    if not args.quiet_boot:
        from tools.camera_link import BootLogger
        BootLogger(log_interval=args.log_interval).attach(probe)

    from src.a6400.execution.guest_checkpoint import restore_checkpoint
    probe.uipc.pool_options_policy = getattr(args, 'uipc_pool_options', 'legacy-empty')
    if args.load_checkpoint and args.load_checkpoint.exists():
        print(f'[*] Restoring checkpoint from: {args.load_checkpoint}...')
        restore_checkpoint(probe, args.load_checkpoint)
        if (getattr(args, 'uipc_pool_options', 'legacy-empty') == 'kernel-e0300'
                and getattr(probe.uipc, 'pool_options_policy', 'legacy-empty') != 'kernel-e0300'):
            raise ValueError('kernel-e0300 requires a fresh boot or a checkpoint created with that policy; old startup cannot be repaired retroactively')
        probe.uipc.handle_rcv_msg_tmo = patched_rcv_msg_tmo
        active_tid = probe.threads.current_tid if hasattr(probe, 'threads') else 1000
        print(f'[*] Checkpoint restored! Resuming at instruction {probe.instructions:,} (active TID {active_tid}).')
        if hasattr(probe, 'threads') and 1004 in probe.threads.threads:
            t1004 = probe.threads.threads[1004]
            if t1004.state == 'blocked_uipc' and t1004.blocked_uaddr == 0x8000103a:
                reply_queue = 0x8000103a
                notify_queue = 0x8000103b
                subcmd_payload = 1 | (4 << 16)
                reply_ptr = probe.uipc.allocate_message(32)
                reply_data = struct.pack('<IIIIIIII', 3, subcmd_payload, reply_queue, 0, 0, 0, notify_queue, 0)
                probe.mu.mem_write(reply_ptr, reply_data)
                probe.uipc.enqueue_message(reply_queue, reply_ptr)
                probe.threads.handle_uipc_wake(reply_queue)
                print(f"[+] Re-serviced authentic mcmn SetOsalIdForMediaNotify reply on queue 0x{reply_queue:08x}; TID 1004 is now runnable!")
    usb_reply_policy = getattr(args, 'usb_reply_policy', 'legacy-zero-stubs')
    for device_attr in ('usb_buspower', 'usb_otgcore'):
        device = getattr(probe, device_attr, None)
        if device is not None:
            # Restored checkpoint devices predate the policy field; apply it
            # without reinitializing their captured state.
            device.reply_policy = usb_reply_policy
    print('[*] Prepared InterpreterProbe with threads policy.')

    usb_connect_event = None
    usb_connect_file = getattr(args, 'usb_connect_event_file', None)
    if usb_connect_file:
        usb_connect_event = Path(usb_connect_file).read_bytes()
    elif getattr(args, 'usb_connect_event', None):
        try:
            usb_connect_event = bytes.fromhex(args.usb_connect_event.replace(' ', ''))
        except ValueError as error:
            raise ValueError('USB connect event must be hex bytes') from error
    if usb_connect_event is not None and not usb_connect_event:
        raise ValueError('USB connect event file is empty')
    usb_connect_at = int(getattr(args, 'usb_connect_at', 0))
    if usb_connect_at < 0:
        raise ValueError('USB connect instruction must not be negative')

    uipc_inject_queue = getattr(args, 'uipc_inject_queue', None)
    uipc_inject_payload = None
    if getattr(args, 'uipc_inject_payload', None):
        try:
            uipc_inject_payload = bytes.fromhex(args.uipc_inject_payload.replace(' ', ''))
        except ValueError as error:
            raise ValueError('UIPC injection payload must be hex bytes') from error
        if not uipc_inject_payload:
            raise ValueError('UIPC injection payload is empty')
    if (uipc_inject_queue is None) != (uipc_inject_payload is None):
        raise ValueError('UIPC injection requires both --uipc-inject-queue and --uipc-inject-payload')

    return BootSession(probe=probe, manifest=manifest, filesystem=filesystem,
                       boot_events_to_inject=boot_events_to_inject,
                       injected=injected, injection_records=injection_records,
                       activation_calls=activation_calls, watched_writes=watched_writes,
                       readonly_mounts=readonly_mounts, display_contract=contract_name,
                       usb_connect_event=usb_connect_event, usb_connect_at=usb_connect_at,
                       uipc_inject_queue=uipc_inject_queue,
                       uipc_inject_payload=uipc_inject_payload)
