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
    uipc_setconfig_objmsg_queue: Optional[int] = None
    uipc_setconfig_objmsg_wake: Optional[int] = None
    uipc_local_post_object: Optional[int] = None
    uipc_local_post_waiter: Optional[int] = None
    uipc_local_post_guest_alloc: bool = False
    uipc_local_post_libosal_base: Optional[int] = None
    uipc_local_post_libmwf_base: Optional[int] = None



class _ObservedSettingTree:
    """Minimal walk()/read_file() source for mount_vfat: the evidence-recorded /setting members."""
    image_sha256 = None
    _files = {'updater/dat4': bytes.fromhex('0002')}

    class _Entry:
        def __init__(self, path, is_dir):
            self.path, self.is_dir = path, is_dir

    def walk(self):
        for directory in ('gps', 'updater'):
            yield directory, self._Entry(directory, True)
        for path in self._files:
            yield path, self._Entry(path, False)

    def read_file(self, entry):
        return self._files[entry.path]

def usb_otgcore_options(args):
    """Resolve the opt-in otgcore gadget-function policy from session args.

    The default keeps ``function_policy='legacy'`` (byte-identical SET_CONFIG
    replies); ``descriptor-table`` parses the verified 64-byte layout and
    selects from ``GADGET_FUNCTION_TABLE`` (MSC verified, PTP/UVC explicit
    ``descriptor_unresolved`` boundaries).  No guest reply is fabricated for
    an unresolved function.
    """
    return {
        'reply_policy': getattr(args, 'usb_reply_policy', 'legacy-zero-stubs'),
        'function_policy': getattr(args, 'usb_function_policy', 'legacy'),
        'configured_functions': getattr(args, 'usb_configured_functions', None),
    }


def live_uipc_receiver(probe):
    """Resolve the current transport at call time, including after restore.

    A bound method captured before restore would keep reading an abandoned
    empty GuestUipc instance instead of the checkpoint's queues.
    """
    def receive(memory_reader, memory_writer, arg_ptr):
        device = probe.uipc
        return type(device).handle_rcv_msg_tmo(device, memory_reader, memory_writer, arg_ptr)
    return receive


def build_boot_session(args, parser=None) -> BootSession:
    """Build the prepared probe and its explicit experimental state.

    This performs the same hash/namespace checks as the CLI.  It does not run
    the guest and does not contact the camera.
    """
    inventory_dir = getattr(args, 'guest_inventory_dir', None)
    folder = (PROJECT_ROOT / inventory_dir) if inventory_dir else (PROJECT_ROOT / 'artifacts/inventory')
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
    gles_kernel_bound = getattr(args, 'gles_device', 'stop').startswith('kernel-bound')
    gles_decoded = getattr(args, 'gles_device', 'stop') == 'kernel-bound-decoded'
    mmap_search_low = 0x10000000 if gles_kernel_bound else None
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
                             grm_pool_policy=getattr(args, 'grm_pools', 'gl-common-only'),
                             mmap_eof_policy=getattr(args, 'mmap_eof', 'zero-fill'))
    probe.thread_sleep_policy = getattr(args, 'nanosleep_policy', 'immediate')
    stack_bottom = 0x5e390000 if gles_kernel_bound else 0x7fe00000
    stack_size = 0x800000 if gles_kernel_bound else 0x100000
    probe.prepare(app, interp, ['/usr/bin/im.elf', *args.argument],
                  stack_bottom=stack_bottom, stack_size=stack_size,
                  environment=getattr(args, 'guest_env', None))
    if gles_kernel_bound:
        from src.a6400.execution.guest_gles import GuestGles, GlesBinding
        from src.a6400.execution.kernel_task_identity import KernelTaskIdentityTable
        kernel_table = KernelTaskIdentityTable(address_limit=0x5f000000)
        if getattr(probe, 'threads', None) is not None:
            for thread_id in probe.threads.threads:
                kernel_table.register(thread_id, probe.threads.process_id)
            probe.threads.on_clone = kernel_table.register
        probe.kernel_tasks = kernel_table
        probe.gles = GuestGles(GlesBinding(table=kernel_table))
    if args.gpio_device == 'driver-bound':
        from src.a6400.execution.guest_gpio import GuestGpio
        probe.gpio = GuestGpio()
    if getattr(args, 'kikilog_device', 'stop') != 'stop':
        from src.a6400.execution.guest_kikilog import GuestKikilog
        target = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/kikilog.ko'
        identity = next(item['sha256'] for item in inventory if item['path'] == target)
        checked_input(PROJECT_ROOT, target, identity)
        probe.kikilog = GuestKikilog(identity, policy=args.kikilog_device)
    if args.usb_buspower_device == 'driver-bound':
        from src.a6400.execution.guest_usb_buspower import GuestUsbBusPower
        probe.usb_buspower = GuestUsbBusPower(
            reply_policy=getattr(args, 'usb_reply_policy', 'legacy-zero-stubs'))
    if args.usb_event_device == 'driver-bound':
        from src.a6400.execution.guest_usb_event import GuestUsbEvent
        probe.usb_event = GuestUsbEvent()
    if args.usb_otgcore_device == 'driver-bound':
        from src.a6400.execution.guest_usb_otgcore import GuestUsbOtgCore
        options = usb_otgcore_options(args)
        probe.usb_otgcore = GuestUsbOtgCore(**options)
        probe.report['usb_otgcore_function_policy'] = {
            'reply_policy': options['reply_policy'],
            'function_policy': options['function_policy'],
            'configured_functions': list(options['configured_functions'] or ()),
        }
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

    original_rcv = live_uipc_receiver(probe)
    boot_events_to_inject = ((getattr(args, 'stimulus_events', None)
                              or [0x00940007, 0x0092014b, 0x00940036, 0x00940038, 0x00920152])
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
    probe.uipc.sync_callback_delivery_policy = getattr(
        args, 'uipc_sync_callback_delivery', 'unmodelled')
    probe.uipc.model_info_reply = getattr(args, 'model_info_reply', None)
    probe.uipc.capid_table_reply = getattr(args, 'capid_table_reply', None)
    probe.uipc.upm_boot_key = getattr(args, 'upm_boot_key', None)
    if probe.uipc.upm_boot_key is not None:
        probe.report['upm_boot_key'] = probe.uipc.upm_boot_key
    if args.load_checkpoint and not args.load_checkpoint.exists():
        # A missing checkpoint previously fell through silently and cold-booted,
        # which produced misleading "continuation" experiments.
        raise SystemExit(f'load-checkpoint not found: {args.load_checkpoint}')
    if args.load_checkpoint:
        print(f'[*] Restoring checkpoint from: {args.load_checkpoint}...')
        restore_checkpoint(probe, args.load_checkpoint,
                           exact=getattr(args, 'uipc_pool_options', '') in ('kernel-e0301', 'kernel-e0303'))
        requested_uipc = getattr(args, 'uipc_pool_options', 'legacy-empty')
        if requested_uipc in ('kernel-e0300', 'kernel-e0301', 'kernel-e0303') and not probe.uipc.kernel_pool_options:
            raise ValueError('Kernel UIPC options require a fresh boot or a checkpoint created with a kernel policy; old startup cannot be repaired retroactively')
        if requested_uipc in ('kernel-e0301', 'kernel-e0303'):
            if (getattr(probe.uipc, 'kernel_contract_revision', None) != 1
                    or getattr(probe.uipc, 'pool_options_policy', '') != requested_uipc):
                raise ValueError('kernel-e0301/e0303 contract requires a fresh boot or a matching revision checkpoint')
            probe.uipc.pool_options_policy = requested_uipc
        probe.uipc.handle_rcv_msg_tmo = patched_rcv_msg_tmo
        # Restore replaces the whole UIPC subsystem, so re-apply the opt-in
        # sync-callback delivery policy after checkpoint restoration.
        probe.uipc.sync_callback_delivery_policy = getattr(
            args, 'uipc_sync_callback_delivery', 'unmodelled')
        probe.uipc.upm_boot_key = getattr(args, 'upm_boot_key', None)  # restore replaced UIPC
        probe.uipc.model_info_reply = getattr(args, 'model_info_reply', None)
        probe.uipc.capid_table_reply = getattr(args, 'capid_table_reply', None)
        probe.uipc.deliver_model_info_reply(lambda a_, d_: probe.mu.mem_write(a_, bytes(d_)))  # callback registered before the checkpoint
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
    if (gles_kernel_bound
            and getattr(probe, 'gles', None) is not None):
        from src.a6400.execution.guest_gles import GlesBinding
        from src.a6400.execution.kernel_task_identity import KernelTaskIdentityTable
        kernel_table = getattr(probe, 'kernel_tasks', None)
        if kernel_table is None:
            kernel_table = KernelTaskIdentityTable(address_limit=0x5f000000)
        if getattr(probe, 'threads', None) is not None:
            for thread_id in probe.threads.threads:
                kernel_table.register(thread_id, probe.threads.process_id)
            probe.threads.on_clone = kernel_table.register
        probe.kernel_tasks = kernel_table
        probe.gles.binding = GlesBinding(table=kernel_table)
        probe.gles.decoded_semantics = gles_decoded
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
    uipc_setconfig_objmsg_queue = getattr(args, 'uipc_inject_objmsg_setconfig_queue', None)
    uipc_setconfig_objmsg_wake = getattr(args, 'uipc_inject_objmsg_wake_uaddr', None)
    uipc_local_post_object = getattr(args, 'uipc_local_post_setconfig_object', None)
    uipc_local_post_waiter = getattr(args, 'uipc_local_post_waiter', None)
    uipc_local_post_guest_alloc = getattr(args, 'uipc_local_post_guest_alloc', False)
    uipc_local_post_libosal_base = getattr(args, 'uipc_local_post_libosal_base', None)
    uipc_local_post_libmwf_base = getattr(args, 'uipc_local_post_libmwf_base', None)

    probe.stream2_device_policy = getattr(args, 'stream2_device', 'stop')
    probe.ldec_device_policy = getattr(args, 'ldec_device', 'stop')
    probe.nflasha4_device_policy = getattr(args, 'nflasha4_device', 'stop')
    nflasha4_file = dict(getattr(args, 'nflasha_image', None) or []).get(4)
    if nflasha4_file and probe.nflasha4_device_policy in ('stop', 'open-only'):
        probe.nflasha4_device_policy = 'synthetic-erased'  # a supplied image implies the writable in-memory policy
    probe.nflasha4_dump = None
    probe.nflash_dumps = {}
    if dict(getattr(args, 'nflasha_image', None) or []).get(23):  # writable in-memory 2 MB partition, host file read-only
        from src.a6400.execution.guest_nflasha4 import Nflasha4Dump
        probe.nflash_dumps[23] = Nflasha4Dump.synthetic(0xff, dict(args.nflasha_image)[23], expected_size=2097152)
    if probe.nflasha4_device_policy == 'synthetic-erased':
        # Not observed content unless --nflasha-image 4=<dump> is given: else an erased MPR partition
        # (0xFF fill like the live one; ioctl byte 0x00, E0305 B=00).
        # Served through the observed-dump paths so reads/ioctl/flush keep the same contracts.
        from src.a6400.execution.guest_nflasha4 import PARTITION_SIZE, Nflasha4Dump
        probe.nflasha4_device_policy = 'observed-dump'
        probe.nflasha4_dump = Nflasha4Dump.synthetic(0xff, nflasha4_file)
        probe.report['nflasha4_dump_policy'] = {'policy': 'synthetic-erased', 'size': PARTITION_SIZE,
                                                'erased_state_byte': 0,
                                                'initial_image': nflasha4_file or 'fill 0xFF',
                                                'initial_sha256': probe.nflasha4_dump.image_sha256}
    elif probe.nflasha4_device_policy == 'observed-dump':
        from src.a6400.execution.guest_nflasha4 import Nflasha4Dump
        probe.nflasha4_dump = Nflasha4Dump.from_evidence(PROJECT_ROOT)
        probe.report['nflasha4_dump_policy'] = {
            'policy': 'observed-dump',
            'image_sha256': probe.nflasha4_dump.image_sha256,
            'size': probe.nflasha4_dump.size,
            'erased_state_byte': probe.nflasha4_dump.erased_state_byte,
            'evidence': probe.nflasha4_dump.evidence,
        }
    probe.mount_service_policy = getattr(args, 'mount_service', 'stop')
    probe.vfat_image = None
    if probe.mount_service_policy == 'observed-nflasha1':
        from src.a6400.execution.guest_vfat import VfatImage
        probe.vfat_image = VfatImage.from_evidence(PROJECT_ROOT)
        probe.report['mount_service_policy'] = {
            'policy': 'observed-nflasha1',
            'image_sha256': probe.vfat_image.image_sha256,
            'size': len(probe.vfat_image.image),
            'fat_type': probe.vfat_image.fat_type,
            'evidence': probe.vfat_image.evidence,
        }
    probe.setting_service_policy = getattr(args, 'setting_service', 'stop')
    if probe.setting_service_policy == 'observed-dat4':
        # Not a partition image: only the /setting members the evidence records with content
        # (E0307: updater/dat4 = 2 B, sha256 fcf0a6c7...c5177f = 00 02 per E0413). Everything else is ENOENT.
        mounted = probe.filesystem.mount_vfat('/setting', _ObservedSettingTree())
        probe.filesystem.vfat_mounts['/setting']['source'] = 'observed-dat4 (E0307/E0413), not nflasha2'
        probe.report['setting_service_policy'] = {'policy': 'observed-dat4', 'mounted': mounted,
                                                  'camera_fidelity_validated': False}
    elif probe.setting_service_policy == 'observed-nflasha2':
        from src.a6400.execution.guest_vfat import VfatImage
        setting_image = VfatImage.from_evidence(
            PROJECT_ROOT,
            manifest_relative='artifacts/hardware/nflasha2-readonly/manifest.json',
            image_relative='artifacts/hardware/nflasha2-readonly/nflasha2-20971520.bin',
            expected_size=20971520)
        mounted = probe.filesystem.mount_vfat('/setting', setting_image)
        probe.report['setting_service_policy'] = {
            'policy': 'observed-nflasha2',
            'image_sha256': setting_image.image_sha256,
            'size': len(setting_image.image),
            'fat_type': setting_image.fat_type,
            'evidence': setting_image.evidence,
            'mounted': mounted,
        }

    return BootSession(probe=probe, manifest=manifest, filesystem=filesystem,
                       boot_events_to_inject=boot_events_to_inject,
                       injected=injected, injection_records=injection_records,
                       activation_calls=activation_calls, watched_writes=watched_writes,
                       readonly_mounts=readonly_mounts, display_contract=contract_name,
                       usb_connect_event=usb_connect_event, usb_connect_at=usb_connect_at,
                       uipc_inject_queue=uipc_inject_queue,
                       uipc_inject_payload=uipc_inject_payload,
                       uipc_setconfig_objmsg_queue=uipc_setconfig_objmsg_queue,
                       uipc_setconfig_objmsg_wake=uipc_setconfig_objmsg_wake,
                       uipc_local_post_object=uipc_local_post_object,
                       uipc_local_post_waiter=uipc_local_post_waiter,
                       uipc_local_post_guest_alloc=uipc_local_post_guest_alloc,
                       uipc_local_post_libosal_base=uipc_local_post_libosal_base,
                       uipc_local_post_libmwf_base=uipc_local_post_libmwf_base)
