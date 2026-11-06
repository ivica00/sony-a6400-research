"""Unsupplied backup replies and bounded host-side UIPC memory operations."""
import struct
import unittest

import unicorn
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from src.a6400.execution.guest_uipc import GuestUipc, UnsupportedUipc, BACKUP_SERVICE_QUEUE, UIPC_CMD_SND_SYNC_MSG
from src.a6400.execution.guarded_bytes import UnverifiedGuestData
from src.a6400.execution.interpreter_probe import InterpreterProbe
from test_interpreter_probe import make_elf


class UipcServiceGuardTests(unittest.TestCase):
    def test_blocked_receive_retries_svc_after_sender_wakes_it(self):
        self.check_blocked_receive(False)

    def test_thumb_blocked_receive_retries_two_byte_svc(self):
        self.check_blocked_receive(True)

    def test_service_reply_wakes_receiver_on_reply_queue(self):
        self.check_blocked_receive(False, service_reply=True)

    def check_blocked_receive(self, thumb, service_reply=False):
        from src.a6400.execution.guest_threads import GuestThreads, GuestThread, REGISTER_LIST
        folder = PROJECT_ROOT / 'artifacts/tests/uipc-wait-wake'
        folder.mkdir(parents=True, exist_ok=True)
        # ioctl; exit. Both threads execute the same original-instruction fixture.
        code = (bytes.fromhex('362700df012700dffee7') if thumb else
                struct.pack('<5I', 0xe3a07036, 0xef000000, 0xe3a07001, 0xef000000, 0xeafffffe))
        interp = make_elf(folder / 'interpreter.elf', code, thumb=thumb)
        app = make_elf(folder / 'app.elf', bytes.fromhex('fee7'), dynamic=False)
        probe = self.probe()
        probe.prepare(app, interp, ['/queue-fixture'])
        probe.syscall_policy = 'threads'
        probe.uipc = GuestUipc()
        probe.threads = GuestThreads()
        probe.filesystem.fds[3] = {'device': 'uipc', 'path': '/dev/uipc'}
        base, queue = 0x50000000, 0x1234
        probe.mu.mem_map(base, 4096)
        probe.mu.mem_write(base, struct.pack('<4I', queue, base + 64, 0, 0xffffffff))
        probe.mu.mem_write(base + 16, struct.pack('<2I', queue, base + 128))
        expected_message = base + 128
        if service_reply:
            from src.a6400.execution.guest_uipc import DMM_SERVICE_QUEUE
            probe.uipc = GuestUipc(graphics_service_policy='authentic-grm')
            probe.uipc.pool_base = base + 512
            probe.mu.mem_write(base + 16, struct.pack('<2I', DMM_SERVICE_QUEUE, base + 128))
            probe.mu.mem_write(base + 128, struct.pack('<6I', 1, 0x280, 0, 0, queue, 7))
            expected_message = probe.uipc.pool_base + probe.uipc.next_offset + 12
        for register, value in ((arm.UC_ARM_REG_R0, 3), (arm.UC_ARM_REG_R1, 0x80000007),
                                (arm.UC_ARM_REG_R2, base)):
            probe.mu.reg_write(register, value)
        child = GuestThread(1001, 'sender', 'runnable')
        child.regs = {r: probe.mu.reg_read(r) for r in REGISTER_LIST}
        child.regs[arm.UC_ARM_REG_PC] = probe.entry
        if thumb:
            child.regs[arm.UC_ARM_REG_CPSR] |= 0x20
        child.regs[arm.UC_ARM_REG_R1] = 0x80000004
        child.regs[arm.UC_ARM_REG_R2] = base + 16
        probe.threads.threads[1001] = child
        report = probe.run(instruction_budget=100)
        self.assertEqual(struct.unpack('<I', probe.mu.mem_read(base + 64, 4))[0], expected_message)
        sends = [e for e in report['serviced_syscalls'] if e.get('cmd') == 0x80000004]
        self.assertEqual(sends[0]['woken_tids'], [1000])
        receives = [e for e in report['serviced_syscalls'] if e.get('cmd') == 0x80000007]
        self.assertEqual(len(receives), 1)
        self.assertEqual(receives[0]['returned'], 0)
        self.assertEqual(probe.threads.uipc_waiters, {})

    def memory(self, queue=BACKUP_SERVICE_QUEUE):
        data = bytearray(256)
        struct.pack_into('<2I', data, 0, queue, 16)
        struct.pack_into('<3I', data, 16, 64, 0, 0)
        struct.pack_into('<8I', data, 64, 3, 0, 2, queue, 0, 0, 0xfa007c, 0x12345678)
        return data

    def test_unsupplied_backup_reply_stops_before_acknowledgement_or_mutation(self):
        data = self.memory()
        before = bytes(data)
        service = GuestUipc()
        service.allocated_msgs[64] = 64
        with self.assertRaises(UnsupportedUipc) as caught:
            service.handle_snd_sync_msg(lambda address, size: bytes(data[address:address + size]), 0)
        self.assertEqual(caught.exception.details['reason'], 'backup_service_reply_not_supplied')
        self.assertEqual(caught.exception.details['request_words'][:4], [3, 0, 2, BACKUP_SERVICE_QUEUE])
        self.assertEqual(caught.exception.details['replies_supplied'], 0)
        self.assertEqual(bytes(data), before)
        self.assertEqual(service.transactions, [])
        self.assertEqual(service.allocated_msgs, {64: 64})

    def test_historical_acknowledgement_requires_explicit_selection_and_is_labeled(self):
        data = self.memory()
        service = GuestUipc(backup_service_policy='unverified-ack')
        self.assertEqual(service.handle_snd_sync_msg(lambda address, size: bytes(data[address:address + size]), 0), 0)
        self.assertIn('unverified', service.transactions[-1]['classification'])
        self.assertEqual(struct.unpack_from('<I', data, 68)[0], 0)

    def test_unreadable_message_is_not_swallowed_as_success(self):
        data = self.memory()
        service = GuestUipc()
        def read(address, size):
            if address == 64:
                raise UnsupportedUipc('fixture_unreadable_payload')
            return bytes(data[address:address + size])
        with self.assertRaises(UnsupportedUipc):
            service.handle_snd_sync_msg(read, 0)
        self.assertEqual(service.transactions, [])

    def test_unknown_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            GuestUipc(backup_service_policy='success')

    def probe(self):
        return InterpreterProbe(syscall_policy='mmap', uname_profile={'raw_hex': bytes(390).hex()},
                                filesystem={'nodes': {}, 'content_loader': lambda *args: b''})

    def test_gles_open_stops_without_kernel_process_binding(self):
        from src.a6400.execution.guest_threads import GuestThreads
        folder = PROJECT_ROOT / 'artifacts/tests/gles-binding'
        folder.mkdir(parents=True, exist_ok=True)
        interp = make_elf(folder / 'interpreter.elf', struct.pack('<2I', 0xe3a07005, 0xef000000), thumb=False)
        app = make_elf(folder / 'app.elf', bytes.fromhex('fee7'), dynamic=False)
        probe = self.probe()
        probe.prepare(app, interp, ['/gles-fixture'])
        probe.syscall_policy = 'threads'
        probe.uipc = GuestUipc()
        probe.threads = GuestThreads()
        address = probe.mu.reg_read(arm.UC_ARM_REG_SP) - 64
        probe.mu.mem_write(address, b'/dev/dmpgles2\0')
        probe.mu.reg_write(arm.UC_ARM_REG_R0, address)
        probe.mu.reg_write(arm.UC_ARM_REG_R1, 2)
        report = probe.run(instruction_budget=10)
        self.assertEqual(report['status'], 'unsupported_gles_contract')
        self.assertEqual(report['boundary']['reason'], 'gles_kernel_process_binding_not_supplied')
        self.assertEqual(report['boundary']['guest_tgid'], 1000)
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R0), address)
        self.assertFalse(any(fd.get('path') == '/dev/dmpgles2' for fd in probe.filesystem.fds.values()))

    def test_gles_binding_services_open_when_bound_and_rejects_high_stack(self):
        from src.a6400.execution.guest_threads import GuestThreads
        from src.a6400.execution.guest_gles import GuestGles, GlesBinding
        from src.a6400.execution.kernel_task_identity import KernelTaskObservation
        folder = PROJECT_ROOT / 'artifacts/tests/gles-binding'
        folder.mkdir(parents=True, exist_ok=True)
        interp = make_elf(folder / 'interpreter.elf', struct.pack('<2I', 0xe3a07005, 0xef000000), thumb=False)
        app = make_elf(folder / 'app.elf', bytes.fromhex('fee7'), dynamic=False)

        # 1. Reject when stack is at high default 0x7fe00000 (> 0x5f000000)
        header = struct.pack('<6I', 0, 1, 0x5f000000, 0x8000, 0, 0)
        task_bytes = bytearray(0x10c)
        struct.pack_into('<I', task_bytes, 8, 0x2000)
        struct.pack_into('<2I', task_bytes, 0x104, 1000, 1000)
        task_obs = KernelTaskObservation.read(lambda a, s: header if a == 0x2000 else task_bytes, 0x2000)
        binding = GlesBinding(task_obs)

        probe_high = self.probe()
        probe_high.prepare(app, interp, ['/gles-fixture'], stack_bottom=0x7fe00000)
        probe_high.syscall_policy = 'threads'
        probe_high.uipc = GuestUipc()
        probe_high.threads = GuestThreads()
        probe_high.gles = GuestGles(binding)
        addr = probe_high.mu.reg_read(arm.UC_ARM_REG_SP) - 64
        probe_high.mu.mem_write(addr, b'/dev/dmpgles2\0')
        probe_high.mu.reg_write(arm.UC_ARM_REG_R0, addr)
        probe_high.mu.reg_write(arm.UC_ARM_REG_R1, 2)
        rep_high = probe_high.run(instruction_budget=10)
        self.assertEqual(rep_high['status'], 'unsupported_gles_contract')
        self.assertEqual(rep_high['boundary']['mismatches'][0]['reason'], 'user_range_outside_task_limit')

        # 2. Succeed open and ioctl (GLES_GET_VERSION) when stack is within task size (< 0x5f000000)
        code_open_ioctl = struct.pack('<8I',
            0xe3a07005,  # mov r7, #5 (open)
            0xef000000,  # svc 0
            0xe3081200,  # movw r1, #0x8200
            0xe3481004,  # movt r1, #0x8004 (0x80048200)
            0xe1a0200d,  # mov r2, sp (arg buffer)
            0xe3a07036,  # mov r7, #54 (ioctl)
            0xef000000,  # svc 0
            0xeafffffe   # b .
        )
        interp_ioctl = make_elf(folder / 'interp_ioctl.elf', code_open_ioctl, thumb=False)
        probe_ok = self.probe()
        probe_ok.prepare(app, interp_ioctl, ['/gles-fixture'], stack_bottom=0x5eb80000, stack_size=0x10000)
        probe_ok.syscall_policy = 'threads'
        probe_ok.uipc = GuestUipc()
        probe_ok.threads = GuestThreads()
        probe_ok.gles = GuestGles(binding)
        addr2 = probe_ok.mu.reg_read(arm.UC_ARM_REG_SP) - 64
        probe_ok.mu.mem_write(addr2, b'/dev/dmpgles2\0')
        probe_ok.mu.reg_write(arm.UC_ARM_REG_R0, addr2)
        probe_ok.mu.reg_write(arm.UC_ARM_REG_R1, 2)
        rep_ok = probe_ok.run(instruction_budget=8)
        self.assertIn(3, probe_ok.filesystem.fds)
        self.assertEqual(probe_ok.filesystem.fds[3]['path'], '/dev/dmpgles2')
        # Check that both open (r7=5) and ioctl (r7=54) succeeded
        serviced = [s for s in rep_ok['serviced_syscalls'] if s.get('r7') in (5, 54)]
        self.assertEqual(len(serviced), 2)
        self.assertEqual(serviced[0]['r7'], 5)
        self.assertEqual(serviced[0]['returned'], 3)
        self.assertEqual(serviced[1]['r7'], 54)
        self.assertEqual(serviced[1]['returned'], 0)
        self.assertEqual(serviced[1]['device'], 'dmpgles2')
        sp_val = probe_ok.mu.reg_read(arm.UC_ARM_REG_SP)
        ver = int.from_bytes(probe_ok.mu.mem_read(sp_val, 4), 'little')
        self.assertEqual(ver, 2)

    def test_host_read_respects_provenance_and_host_write_respects_page_permissions(self):
        probe = self.probe()
        probe.mu.mem_map(0x1000, 4096)
        probe.mu.mem_map(0x3000, 4096, unicorn.UC_PROT_READ)
        probe.mu.mem_write(0x3000, b'KEEP')
        metadata = {'inode': 1, 'mode': 0o100644, 'nlink': 1, 'uid': 0, 'gid': 0,
                    'size': 4, 'block_size': 4096, 'blocks_512': 8}
        probe.stat64.request(metadata, 0x1000)
        # st_rdev remains unknown in this policy, even though host reads can bypass CPU hooks.
        with self.assertRaises(UnverifiedGuestData):
            probe._uipc_read(0x1020, 4)
        with self.assertRaises(UnsupportedUipc):
            probe._uipc_write(0x3000, b'LOST')
        self.assertEqual(bytes(probe.mu.mem_read(0x3000, 4)), b'KEEP')
        with self.assertRaises(UnsupportedUipc):
            probe._uipc_read(0x9000, 4)
        probe._uipc_write(0x1020, b'NEW!')
        self.assertEqual(probe._uipc_read(0x1020, 4), b'NEW!')
        with self.assertRaises(UnverifiedGuestData):
            probe._uipc_read(0x1024, 4)

    def test_arm_ioctl_stops_without_returning_success_to_guest(self):
        folder = PROJECT_ROOT / 'artifacts/tests/uipc-service-guard'
        folder.mkdir(parents=True, exist_ok=True)
        code = struct.pack('<3I', 0xe3a07036, 0xef000000, 0xeafffffe)
        interp = make_elf(folder / 'interpreter.elf', code, thumb=False)
        app = make_elf(folder / 'app.elf', bytes.fromhex('fee7'), dynamic=False)
        probe = self.probe()
        probe.prepare(app, interp, ['/guard-fixture'])
        probe.syscall_policy = 'uipc'
        probe.uipc = GuestUipc()
        probe.filesystem.fds[3] = {'device': 'uipc', 'path': '/dev/uipc'}
        base = 0x50000000
        data = self.memory()
        struct.pack_into('<2I', data, 0, BACKUP_SERVICE_QUEUE, base + 16)
        struct.pack_into('<3I', data, 16, base + 64, 0, 0)
        probe.mu.mem_map(base, 4096)
        probe.mu.mem_write(base, bytes(data))
        for register, value in ((arm.UC_ARM_REG_R0, 3), (arm.UC_ARM_REG_R1, UIPC_CMD_SND_SYNC_MSG),
                                (arm.UC_ARM_REG_R2, base)):
            probe.mu.reg_write(register, value)
        report = probe.run()
        self.assertEqual(report['status'], 'unsupported_uipc_contract')
        self.assertEqual(report['syscall_responses_supplied'], 0)
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R0), 3)
        self.assertEqual(bytes(probe.mu.mem_read(base, len(data))), bytes(data))
        self.assertEqual(probe.uipc.transactions, [])
