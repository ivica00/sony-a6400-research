"""Process-entry and boundary tests using constructed, redistributable ARM ELF."""
import hashlib
import struct
import unittest

import unicorn
from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_ARM
from unicorn import arm_const as arm
from unittest import mock

from project_paths import PROJECT_ROOT
from src.a6400.images.process_elf import inspect_image, map_image
from src.a6400.execution.process_entry import build_stack, AT_PHDR, AT_BASE, AT_ENTRY, AT_NULL
from src.a6400.execution.interpreter_probe import InterpreterProbe, summarize_loader_stop
from src.a6400.execution.guest_kuser import extract_kuser_template


def make_elf(path, code, dynamic=True, thumb=True):
    base = 0 if dynamic else 0x8000
    ident = b'\x7fELF' + bytes([1, 1, 1]) + bytes(9)
    header = struct.pack('<HHIIIIIHHHHHH', 3 if dynamic else 2, 40, 1,
                         base + 0x100 + int(thumb), 52, 0, 0x5000000, 52, 32, 1, 40, 0, 0)
    size = 0x100 + len(code)
    segment = struct.pack('<IIIIIIII', 1, 0, base, 0, size, 0x2000, 5, 4096)
    data = (ident + header + segment).ljust(0x100, b'\0') + code
    path.write_bytes(data)
    return inspect_image(path, hashlib.sha256(data).hexdigest())


class InterpreterProbeTests(unittest.TestCase):
    def setUp(self):
        self.folder = PROJECT_ROOT / 'artifacts/tests/process-probe'
        self.folder.mkdir(parents=True, exist_ok=True)

    def probe(self, code=bytes.fromhex('2d27002000df'), thumb=True, syscall_policy='stop', uname_profile=None, filesystem=None, kuser_template=None, environment=None):
        app = make_elf(self.folder / 'app.elf', b'\xfe\xe7', dynamic=False)
        interpreter = make_elf(self.folder / 'linker.elf', code, thumb=thumb)
        probe = InterpreterProbe(syscall_policy=syscall_policy, uname_profile=uname_profile, filesystem=filesystem, kuser_template=kuser_template)
        probe.prepare(app, interpreter, ['/usr/bin/test'], environment=environment)
        return probe

    def test_prepare_records_explicit_guest_environment(self):
        probe = self.probe(environment=['LD_PRELOAD=/usr/lib/x.so', 'A=B'])
        self.assertEqual(probe.report['stack']['environment'],
                         ['LD_PRELOAD=/usr/lib/x.so', 'A=B'])

    def test_prepare_default_environment_is_empty(self):
        self.assertEqual(self.probe().report['stack']['environment'], [])

    def test_thumb_syscall_stops_without_response(self):
        probe = self.probe()
        report = probe.run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 45)
        self.assertEqual(report['boundary']['arguments'][0], 0)
        self.assertEqual(report['instructions_executed'], 3)
        self.assertEqual(report['syscall_responses_supplied'], 0)

    def test_arm_syscall(self):
        code = struct.pack('<III', 0xe3a0702d, 0xe3a00000, 0xef000000)
        report = self.probe(code, thumb=False).run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertFalse(report['boundary']['thumb'])
        self.assertEqual(report['boundary']['r7'], 45)

    def test_unmapped_memory_stops_without_auto_mapping(self):
        report = self.probe(bytes.fromhex('00200068')).run()  # movs r0,#0; ldr r0,[r0]
        self.assertEqual(report['status'], 'memory_boundary')
        self.assertEqual(report['boundary']['address'], 0)

    def test_write_to_code_is_rejected(self):
        # ldr r0,literal; movs r1,#0; str r1,[r0]; literal points to RX code.
        code = bytes.fromhex('01480021016000bf') + struct.pack('<I', 0x40000100)
        report = self.probe(code).run()
        self.assertEqual(report['status'], 'memory_boundary')
        self.assertEqual(report['boundary']['address'], 0x40000100)

    def test_instruction_limit(self):
        report = self.probe(bytes.fromhex('fee7')).run(instruction_budget=10)
        self.assertEqual(report['status'], 'instruction_budget_exhausted')
        self.assertEqual(report['instructions_executed'], 10)

    def test_timeout(self):
        report = self.probe(bytes.fromhex('fee7')).run(instruction_budget=100000000, timeout_us=1000)
        self.assertEqual(report['status'], 'timeout')

    def test_exception_is_not_syscall(self):
        report = self.probe(bytes.fromhex('00de')).run()  # udf #0
        self.assertNotEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['syscall_responses_supplied'], 0)

    def test_fresh_runs_are_reproducible(self):
        first, second = self.probe().run(), self.probe().run()
        self.assertEqual(first, second)

    def test_changed_image_rejected(self):
        path = self.folder / 'changed.elf'
        image = make_elf(path, bytes.fromhex('fee7'))
        path.write_bytes(path.read_bytes() + b'changed')
        with self.assertRaises(ValueError):
            inspect_image(path, image['sha256'])

    def test_stack_pointers_auxv_and_alignment(self):
        application = {'phdr': 0x8034, 'phnum': 1, 'phent': 32, 'entry': 0x8101}
        stack = build_stack(0x70000000, 4096, ['/test', 'arg'], ['X=Y'], application, 0x40000000)
        self.assertEqual(stack['sp'] % 16, 0)
        data, index = stack['data'], stack['sp'] - 0x70000000
        words = struct.unpack_from('<7I', data, index)
        self.assertEqual(words[0], 2)
        self.assertEqual(words[3], 0)
        self.assertEqual(words[5], 0)
        self.assertEqual(data[words[1] - 0x70000000:words[1] - 0x70000000 + 6], b'/test\0')
        auxv = dict(stack['auxv'])
        self.assertEqual(auxv[AT_PHDR], 0x8034)
        self.assertEqual(auxv[AT_BASE], 0x40000000)
        self.assertEqual(auxv[AT_ENTRY], 0x8101)
        self.assertEqual(stack['auxv'][-1], (AT_NULL, 0))

    def test_stack_overflow_rejected(self):
        with self.assertRaises(ValueError):
            build_stack(0x70000000, 64, ['x' * 256], [],
                        {'phdr': 0x8034}, 0x40000000)

    def test_mapping_zero_fill_and_header_address(self):
        image = make_elf(self.folder / 'mapped.elf', b'\xfe\xe7', dynamic=False)
        mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        mapped = map_image(mu, image, 0)
        self.assertEqual(mapped['phdr'], 0x8034)
        self.assertEqual(bytes(mu.mem_read(0x9000, 4)), bytes(4))
        with self.assertRaises(UcError):
            mu.mem_read(0xa000, 1)

    def test_et_exec_bias_rejected(self):
        image = make_elf(self.folder / 'bias.elf', b'\xfe\xe7', dynamic=False)
        with self.assertRaises(ValueError):
            map_image(Uc(UC_ARCH_ARM, UC_MODE_ARM), image, 4096)

    def test_probe_cannot_be_resumed_implicitly(self):
        probe = self.probe()
        probe.run()
        with self.assertRaises(ValueError):
            probe.run()

    def test_initial_user_mode_and_stack_registers(self):
        probe = self.probe()
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_CPSR) & 0x1f, 0x10)
        sp = probe.mu.reg_read(arm.UC_ARM_REG_SP)
        words = struct.unpack('<3I', probe.mu.mem_read(sp, 12))
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R1), words[1])
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R2), words[2])

    def test_unprepared_probe_rejected(self):
        with self.assertRaises(ValueError):
            InterpreterProbe().run()

    def test_brk_contract_advances_to_next_unsupported_syscall(self):
        probe = self.probe(bytes.fromhex('2d27002000df7a2700df'), syscall_policy='brk')
        report = probe.run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 122)
        self.assertEqual(report['boundary']['arguments'][0], 0xa000)
        self.assertEqual(report['syscall_responses_supplied'], 1)
        self.assertEqual(report['serviced_syscalls'][0]['reason'], 'query')
        self.assertEqual(report['heap']['initial'], 0xa000)

    def test_unknown_syscall_policy_rejected(self):
        with self.assertRaises(ValueError):
            InterpreterProbe(syscall_policy='return_success')

    def test_uname_policy_requires_source(self):
        with self.assertRaises(ValueError):
            InterpreterProbe(syscall_policy='brk-uname')

    def test_uname_contract_then_unsupported_access(self):
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        profile = {'source_sha256': 'fixture', 'file_offset': 0, 'raw_hex': raw.hex()}
        # Reserve stack space, pass SP to uname, then request unsupported access.
        code = bytes.fromhex('ffb068467a2700df212700df')
        report = self.probe(code, syscall_policy='brk-uname', uname_profile=profile).run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 33)
        self.assertEqual(report['syscall_responses_supplied'], 1)
        self.assertEqual(report['serviced_syscalls'][0]['syscall'], 'uname')

    def test_metadata_policy_fstat_stops_at_unknown_device_read(self):
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        metadata = {'image_sha256': 'fixture', 'inode_file_offset': 128, 'inode': 2,
                    'mode': 0o100644, 'uid': 0, 'gid': 0, 'size': 3, 'nlink': 1,
                    'blocks_512': 2, 'block_size': 1024}
        filesystem = {'nodes': {'/file': {'stat_metadata': metadata}},
                      'content_loader': lambda path, node: b'ABC'}
        # fstat64(3, sp), read known mode, then read unknown st_dev.
        code = struct.pack('<7I', 0xe3a00003, 0xe1a0100d, 0xe3a070c5,
                           0xef000000, 0xe59d0010, 0xe59d0000, 0xeafffffe)
        probe = self.probe(code, thumb=False, syscall_policy='metadata',
                           uname_profile={'raw_hex': raw.hex()}, filesystem=filesystem)
        probe.filesystem.fds[3] = {'path': '/file', 'data': b'ABC', 'offset': 0, 'flags': 0}
        report = probe.run()
        self.assertEqual(report['status'], 'unverified_metadata_read')
        self.assertEqual(report['boundary']['fields'], ['st_dev'])
        self.assertEqual(report['instructions_executed'], 6)
        self.assertEqual(report['stat64_fields_read'], {'st_mode': 1, 'st_dev': 1})
        self.assertTrue(report['serviced_syscalls'][0]['partial_contract'])
        # A kernel-side overwrite clears both kinds of stale provenance.
        address = probe.mu.reg_read(arm.UC_ARM_REG_SP)
        probe._after_host_write(address, 104)
        probe._before_host_read(address, 104)

    def test_file_open_then_fstat_boundary(self):
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        profile = {'source_sha256': 'fixture', 'file_offset': 0, 'raw_hex': raw.hex()}
        filesystem = {'nodes': {'/': {'kind': 'directory', 'mode': 0o40755, 'uid': 0, 'gid': 0},
                                '/file': {'kind': 'file', 'mode': 0o100644, 'uid': 0, 'gid': 0, 'size': 3}},
                      'content_loader': lambda path, node: b'ABC'}
        code = bytes.fromhex('02480021052700dfc52700df') + struct.pack('<I', 0x40000110) + b'/file\0'
        report = self.probe(code, syscall_policy='files', uname_profile=profile, filesystem=filesystem).run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 197)
        self.assertEqual(report['boundary']['arguments'][0], 3)
        self.assertEqual(report['serviced_syscalls'][0]['syscall'], 'open')
        self.assertEqual(report['file_descriptors']['3']['path'], '/file')

    def test_unsupplied_etc_overlay_stops_before_missing_path_response(self):
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        filesystem = {'nodes': {'/': {'kind': 'directory', 'mode': 0o40755, 'uid': 0, 'gid': 0}},
                      'content_loader': lambda path, node: self.fail('Must not read host content'),
                      'unknown_roots': ('/etc',)}
        code = bytes.fromhex('02480421212700dffee700bf') + struct.pack('<I', 0x40000110) + b'/etc/ld.so.preload\0'
        report = self.probe(code, syscall_policy='files', uname_profile={'raw_hex': raw.hex()},
                            filesystem=filesystem).run()
        self.assertEqual(report['status'], 'unsupported_filesystem')
        self.assertEqual(report['boundary']['reason'], 'runtime_namespace_not_supplied')
        self.assertEqual(report['boundary']['path'], '/etc')
        self.assertEqual(report['syscall_responses_supplied'], 0)


    def test_mmap_policy_services_mmap2_and_verified_st_dev(self):
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        metadata = {'inode': 100, 'mode': 0o100755, 'nlink': 1, 'uid': 0, 'gid': 0,
                    'size': 4096, 'blocks_512': 8, 'block_size': 4096,
                    'image_sha256': 'fixture_sha', 'inode_file_offset': 0, 'st_dev': 0xfc07}
        filesystem = {'nodes': {'/file': {'stat_metadata': metadata, 'kind': 'file', 'mode': 0o100755, 'uid': 0, 'gid': 0, 'size': 4096}},
                      'content_loader': lambda path, node: b'DEVMAP_OK_' + bytes(4086)}
        # ARM instructions:
        # 1. fstat64(3, sp) -> reads st_dev (offset 0), verify no stop
        # 2. mmap2(0, 4096, PROT_READ, MAP_PRIVATE, 3, 0)
        # 3. read first word from returned address, compare with 'DEVM' (0x4d564544)
        # 4. stop at syscall exit
        code = struct.pack('<10I',
                           0xe3a00003,          # mov r0, #3
                           0xe1a0100d,          # mov r1, sp
                           0xe3a070c5,          # mov r7, #197 (fstat64)
                           0xef000000,          # svc #0
                           0xe59d8000,          # ldr r8, [sp] (read st_dev)
                           0xe3a00000,          # mov r0, #0
                           0xe3a01001, 0xe1a01601, # mov r1,#1; lsl r1,r1,#12 -> 4096
                           0xe3a02001,          # mov r2, #1 (PROT_READ)
                           0xe3a03002,          # mov r3, #2 (MAP_PRIVATE)
                           ) + struct.pack('<8I',
                           0xe3a04003,          # mov r4, #3 (fd)
                           0xe3a05000,          # mov r5, #0 (pgoff)
                           0xe3a070c0,          # mov r7, #192 (mmap2)
                           0xef000000,          # svc #0
                           0xe5906000,          # ldr r6, [r0] (read mapped word)
                           0xe3a07001,          # mov r7, #1 (exit boundary)
                           0xef000000,          # svc #0
                           0xeafffffe           # b .
                           )
        probe = self.probe(code, thumb=False, syscall_policy='mmap',
                           uname_profile={'raw_hex': raw.hex()}, filesystem=filesystem)
        probe.filesystem.fds[3] = {'path': '/file', 'data': b'DEVMAP_OK_' + bytes(4086), 'offset': 0, 'flags': 0}
        report = probe.run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 1)
        self.assertEqual(report['instructions_executed'], 17)
        self.assertEqual(report['stat64_fields_read'], {'st_dev': 1})
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R8), 0xfc07)
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R6), int.from_bytes(b'DEVM', 'little'))
        self.assertEqual(len(report['mappings']), 1)
        self.assertEqual(report['mappings'][0]['address'], 0x50000000)
        self.assertEqual(report['mappings'][0]['path'], '/file')
        self.assertEqual(report['mappings'][0]['length'], 4096)

    def test_kuser_policy_services_kuser_and_thread_syscalls(self):
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        kernel_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
        if not kernel_path.exists():
            self.skipTest('Kernel image not available')
        template = extract_kuser_template(kernel_path)
        filesystem = {'nodes': {}, 'content_loader': lambda p, n: b''}

        # ARM instructions testing:
        # 1. sys_arm_set_tls(0x503204c0) (svc 0x009f0005)
        # 2. set_tid_address(sp) (syscall 256) -> returns pid=1000 in r0
        # 3. set_robust_list(sp, 12) (syscall 338) -> returns 0 in r0
        # 4. ugetrlimit(3, sp) (syscall 191) -> writes 8MB stack limit, returns 0
        # 5. stop at syscall exit (syscall 1)
        code = struct.pack('<16I',
                           # 1. sys_arm_set_tls(0x503204c0)
                           0xe3a00205,          # mov r0, #0x50000000
                           0xe2800832,          # add r0, r0, #0x00320000
                           0xe2800c04,          # add r0, r0, #0x00000400
                           0xe28000c0,          # add r0, r0, #0x000000c0
                           0xef9f0005,          # svc 0x009f0005
                           # 2. set_tid_address(sp)
                           0xe1a0000d,          # mov r0, sp
                           0xe3a07c01,          # mov r7, #0x100 (256)
                           0xef000000,          # svc #0
                           0xe1a08000,          # mov r8, r0 (save pid 1000)
                           # 3. set_robust_list(sp, 12)
                           0xe1a0000d,          # mov r0, sp
                           0xe3a0100c,          # mov r1, #12
                           0xe2877052,          # add r7, r7, #0x52 (338)
                           0xef000000,          # svc #0
                           # 4. ugetrlimit(3, sp)
                           0xe3a00003,          # mov r0, #3 (RLIMIT_STACK)
                           0xe1a0100d,          # mov r1, sp
                           0xe3a070bf,          # mov r7, #191
                           ) + struct.pack('<5I',
                           0xef000000,          # svc #0
                           0xe59d6000,          # ldr r6, [sp] (read rlim_cur)
                           # 5. exit boundary
                           0xe3a07001,          # mov r7, #1
                           0xef000000,          # svc #0
                           0xeafffffe           # b .
                           )

        probe = self.probe(code, thumb=False, syscall_policy='kuser',
                           uname_profile={'raw_hex': raw.hex()},
                           filesystem=filesystem, kuser_template=template)
        report = probe.run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 1)
        # Check TLS in register and memory
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_C13_C0_3), 0x503204c0)
        slot_val = struct.unpack('<I', bytes(probe.mu.mem_read(0xffff0ff0, 4)))[0]
        self.assertEqual(slot_val, 0x503204c0)
        # Check pid returned from set_tid_address
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R8), 1000)
        # Check rlim_cur returned from ugetrlimit (8 MiB)
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R6), 8 * 1024 * 1024)
        # Check serviced syscalls count
        serviced_names = [s['syscall'] for s in report['serviced_syscalls']]
        self.assertIn('set_tls', serviced_names)
        self.assertIn('set_tid_address', serviced_names)
        self.assertIn('set_robust_list', serviced_names)
        self.assertIn('ugetrlimit', serviced_names)

    def test_uipc_policy_services_open_ioctl_and_mmap(self):
        filesystem = {
            'nodes': {
                '/dev/uipc': {'kind': 'cdev', 'mode': 8703, 'uid': 0, 'gid': 0, 'size': 0}
            },
            'content_loader': lambda p, n: b''
        }
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        kernel_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
        if not kernel_path.exists():
            self.skipTest('Kernel image not available')
        template = extract_kuser_template(kernel_path)

        # Code executes:
        # 1. open("/dev/uipc", O_RDWR) -> fd in r4
        # 2. fcntl64(r4, F_SETFD, 1)
        # 3. ioctl(r4, 0x80000010, &arg)
        # 4. mmap2(0, 0x100000, PROT_READ|WRITE, MAP_SHARED, r4, 0) -> pool in r5
        # 5. svc 0 (exit)
        code = struct.pack('<28I',
                           # 1. open("/dev/uipc", 2)
                           0xe28f0068,          # add r0, pc, #104 (pointer to "/dev/uipc" at end of 28 insns)
                           0xe3a01002,          # mov r1, #2 (O_RDWR)
                           0xe3a07005,          # mov r7, #5 (open)
                           0xef000000,          # svc 0
                           0xe1a04000,          # mov r4, r0 (save fd)
                           # 2. fcntl64(r4, 2, 1)
                           0xe1a00004,          # mov r0, r4
                           0xe3a01002,          # mov r1, #2 (F_SETFD)
                           0xe3a02001,          # mov r2, #1 (FD_CLOEXEC)
                           0xe3a070dd,          # mov r7, #221 (fcntl64)
                           0xef000000,          # svc 0
                           # 3. ioctl(r4, 0x80000010, sp)
                           0xe1a00004,          # mov r0, r4
                           0xe3a01102,          # mov r1, #0x80000000
                           0xe2811010,          # add r1, r1, #0x10 (0x80000010)
                           0xe1a0200d,          # mov r2, sp (arg points to [0, sp+8])
                           0xe28d3008,          # add r3, sp, #8
                           0xe58d3004,          # str r3, [sp, #4]
                           0xe3a07036,          # mov r7, #54 (ioctl)
                           0xef000000,          # svc 0
                           # 4. mmap2(0, 0x100000, 3, 1, r4, 0)
                           0xe3a00000,          # mov r0, #0
                           0xe3a01701,          # mov r1, #0x100000 (1 MiB)
                           0xe3a02003,          # mov r2, #3 (PROT_READ|PROT_WRITE)
                           0xe3a03001,          # mov r3, #1 (MAP_SHARED)
                           0xe58d4000,          # str r4, [sp] (fd on stack for ABI / Unicorn)
                           0xe3a05000,          # mov r5, #0 (pgoff)
                           0xe3a070c0,          # mov r7, #192 (mmap2)
                           0xef000000,          # svc 0
                           # 5. exit
                           0xe3a07001,          # mov r7, #1
                           0xef000000,          # svc 0
                           ) + b'/dev/uipc\x00\x00\x00'

        probe = self.probe(code, thumb=False, syscall_policy='uipc',
                           uname_profile={'raw_hex': raw.hex()},
                           filesystem=filesystem, kuser_template=template)
        report = probe.run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 1)
        self.assertIn('uipc', report)
        self.assertTrue(report['uipc']['connected'])
        self.assertIsNotNone(report['uipc']['pool_base'])
        serviced_names = [s['syscall'] for s in report['serviced_syscalls']]
        self.assertIn('open', serviced_names)
        self.assertIn('fcntl64', serviced_names)
        self.assertIn('ioctl', serviced_names)
        self.assertIn('mmap2', serviced_names)

    def test_uipc_policy_services_stdio_operations(self):
        filesystem = {
            'nodes': {},
            'content_loader': lambda p, n: b''
        }
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        kernel_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
        if not kernel_path.exists():
            self.skipTest('Kernel image not available')
        template = extract_kuser_template(kernel_path)

        # Code executes:
        # 1. fstat64(1, sp)
        # 2. ioctl(1, 0x5401, sp) -> returns -ENOTTY
        # 3. write(1, "CAM_OK", 6)
        # 4. svc 0 (exit)
        code = struct.pack('<18I',
                           # 1. fstat64(1, sp)
                           0xe3a00001,          # mov r0, #1
                           0xe1a0100d,          # mov r1, sp
                           0xe3a070c5,          # mov r7, #197 (fstat64)
                           0xef000000,          # svc 0
                           # 2. ioctl(1, 0x5401, sp)
                           0xe3a00001,          # mov r0, #1
                           0xe3051401,          # movw r1, #0x5401 (TCGETS)
                           0xe1a0200d,          # mov r2, sp
                           0xe3a07036,          # mov r7, #54 (ioctl)
                           0xef000000,          # svc 0
                           0xe1a04000,          # mov r4, r0 (save ioctl return)
                           # 3. write(1, msg, 6)
                           0xe3a00001,          # mov r0, #1
                           0xe28f1014,          # add r1, pc, #20 (pointer to "CAM_OK" at byte 72)
                           0xe3a02006,          # mov r2, #6
                           0xe3a07004,          # mov r7, #4 (write)
                           0xef000000,          # svc 0
                           # 4. exit
                           0xe3a07001,          # mov r7, #1
                           0xef000000,          # svc 0
                           0xeafffffe           # b .
                           ) + b'CAM_OK\x00\x00'

        probe = self.probe(code, thumb=False, syscall_policy='uipc',
                           uname_profile={'raw_hex': raw.hex()},
                           filesystem=filesystem, kuser_template=template)
        report = probe.run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 1)
        # ioctl returned -ENOTTY (0xffffffe7)
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R4), 0xffffffe7)
        # Check stdio logs
        self.assertIn('stdio', report)
        self.assertEqual(report['stdio']['stdout_preview'], 'CAM_OK')
        serviced_names = [s['syscall'] for s in report['serviced_syscalls']]
        self.assertIn('fstat64', serviced_names)
        self.assertIn('ioctl', serviced_names)
        self.assertIn('write', serviced_names)

    def test_uipc_policy_services_fb0_operations(self):
        filesystem = {
            'nodes': {},
            'content_loader': lambda p, n: b''
        }
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        kernel_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
        if not kernel_path.exists():
            self.skipTest('Kernel image not available')
        template = extract_kuser_template(kernel_path)

        # 33 instructions * 4 = 132 bytes. String at 132: pc = 0 + 8 = 8, 8 + 124 = 132.
        code = struct.pack('<33I',
                           # 1. open("/dev/fb0", 2)
                           0xe28f007c,          # add r0, pc, #124 (pointer to "/dev/fb0" at byte 132)
                           0xe3a01002,          # mov r1, #2 (O_RDWR)
                           0xe3a07005,          # mov r7, #5 (open)
                           0xef000000,          # svc 0
                           0xe1a04000,          # mov r4, r0 (save fd)
                           # 2. fstat64(r4, sp)
                           0xe1a00004,          # mov r0, r4
                           0xe1a0100d,          # mov r1, sp
                           0xe3a070c5,          # mov r7, #197 (fstat64)
                           0xef000000,          # svc 0
                           # 3. ioctl(r4, 0x4602, sp)
                           0xe1a00004,          # mov r0, r4
                           0xe3041602,          # movw r1, #0x4602 (FBIOGET_FSCREENINFO)
                           0xe1a0200d,          # mov r2, sp
                           0xe3a07036,          # mov r7, #54 (ioctl)
                           0xef000000,          # svc 0
                           # 4. ioctl(r4, 0x4600, sp)
                           0xe1a00004,          # mov r0, r4
                           0xe3041600,          # movw r1, #0x4600 (FBIOGET_VSCREENINFO)
                           0xe1a0200d,          # mov r2, sp
                           0xe3a07036,          # mov r7, #54 (ioctl)
                           0xef000000,          # svc 0
                           # 5. mmap2(0, 0x100000, 3, 1, r4, 0)
                           0xe3a00000,          # mov r0, #0
                           0xe3a01701,          # mov r1, #0x100000 (1 MiB)
                           0xe3a02003,          # mov r2, #3 (PROT_READ|PROT_WRITE)
                           0xe3a03001,          # mov r3, #1 (MAP_SHARED)
                           0xe58d4000,          # str r4, [sp]
                           0xe3a05000,          # mov r5, #0
                           0xe3a070c0,          # mov r7, #192 (mmap2)
                           0xef000000,          # svc 0
                           0xe1a05000,          # mov r5, r0 (save vram ptr)
                           # 6. write 0xdeadbeef to vram
                           0xe30b0eef,          # movw r0, #0xbeef
                           0xe34d0ead,          # movt r0, #0xdead
                           0xe5850000,          # str r0, [r5]
                           # 7. exit
                           0xe3a07001,          # mov r7, #1
                           0xef000000,          # svc 0
                           ) + b'/dev/fb0\x00'

        probe = self.probe(code, thumb=False, syscall_policy='uipc',
                           uname_profile={'raw_hex': raw.hex()},
                           filesystem=filesystem, kuser_template=template)
        report = probe.run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 1)
        self.assertIn('framebuffer', report)
        self.assertIsNotNone(report['framebuffer']['vram_base'])
        self.assertEqual(report['framebuffer']['width'], 960)
        self.assertEqual(report['framebuffer']['height'], 540)
        serviced_names = [s['syscall'] for s in report['serviced_syscalls']]
        self.assertIn('open', serviced_names)
        self.assertIn('fstat64', serviced_names)
        self.assertIn('ioctl', serviced_names)
        self.assertIn('mmap2', serviced_names)

        # Check vram was written with 0xdeadbeef
        vram_base = report['framebuffer']['vram_base']
        val = struct.unpack('<I', bytes(probe.mu.mem_read(vram_base, 4)))[0]
        self.assertEqual(val, 0xdeadbeef)

    def test_threads_policy_services_clone_and_multithreading(self):
        filesystem = {
            'nodes': {},
            'content_loader': lambda p, n: b''
        }
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        kernel_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
        if not kernel_path.exists():
            self.skipTest('Kernel image not available')
        template = extract_kuser_template(kernel_path)

        # 1. Setup child stack at sp - 0x1000
        #    Store fn and arg:
        #    [child_stack, #0] = 0x50085035 (fn)
        #    [child_stack, #4] = 0x50c7f460 (arg)
        # 2. sys_clone(flags=0x3d0f00, child_stack, parent_tidptr=sp, tls=0x5000, child_tidptr=sp)
        # 3. Save returned tid in r8
        # 4. sys_exit(0)
        code = struct.pack('<24I',
                           # Setup child stack
                           0xe24d1a01,          # sub r1, sp, #0x1000 (child_stack)
                           0xe3052035,          # movw r2, #0x5035
                           0xe3452008,          # movt r2, #0x5008
                           0xe5812000,          # str r2, [r1] (fn)
                           0xe30f2460,          # movw r2, #0xf460
                           0xe34520c7,          # movt r2, #0x50c7
                           0xe5812004,          # str r2, [r1, #4] (arg)
                           # Call clone
                           0xe3000f00,          # movw r0, #0x0f00
                           0xe340003d,          # movt r0, #0x003d (flags = 0x3d0f00)
                           0xe1a0200d,          # mov r2, sp (parent_tidptr)
                           0xe3003000,          # movw r3, #0
                           0xe3453000,          # movt r3, #0x5000 (tls_val)
                           0xe1a0400d,          # mov r4, sp (child_tidptr)
                           0xe3a07078,          # mov r7, #120 (clone)
                           0xef000000,          # svc 0
                           0xe1a08000,          # mov r8, r0 (save returned child TID)
                           # sys_exit(0)
                           0xe3a00000,          # mov r0, #0
                           0xe3a07001,          # mov r7, #1
                           0xef000000,          # svc 0
                           0xeafffffe,          # b .
                           0xe1a00000, 0xe1a00000, 0xe1a00000, 0xe1a00000
                           )

        probe = self.probe(code, thumb=False, syscall_policy='threads',
                           uname_profile={'raw_hex': raw.hex()},
                           filesystem=filesystem, kuser_template=template)
        report = probe.run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 1)
        # Returned TID to parent was 1001
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R8), 1001)
        # Verify parent_tidptr received 1001 in memory
        sp = probe.mu.reg_read(arm.UC_ARM_REG_SP)
        written_tid = struct.unpack('<I', probe.mu.mem_read(sp, 4))[0]
        self.assertEqual(written_tid, 1001)
        # Check threads report
        self.assertIn('threads', report)
        self.assertIn('1001', report['threads'])
        self.assertEqual(report['threads']['1001']['state'], 'runnable')
        serviced_names = [s['syscall'] for s in report['serviced_syscalls']]
        self.assertIn('clone', serviced_names)
        self.assertEqual(next(s for s in report['serviced_syscalls'] if s['syscall'] == 'clone')['flags'],
                         0x3d0f00)

    def test_threads_policy_services_nanosleep(self):
        filesystem = {
            'nodes': {},
            'content_loader': lambda p, n: b''
        }
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        kernel_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
        if not kernel_path.exists():
            self.skipTest('Kernel image not available')
        template = extract_kuser_template(kernel_path)

        # ARM instructions:
        # 1. Store timespec { tv_sec: 1, tv_nsec: 500000 } on stack
        # 2. nanosleep(sp, 0) (syscall 162)
        # 3. exit (syscall 1)
        code = struct.pack('<12I',
                           0xe3a00001,          # mov r0, #1 (tv_sec)
                           0xe58d0000,          # str r0, [sp]
                           0xe30a0120,          # movw r0, #0xa120 (lower 16 bits of 500000 = 0x7a120)
                           0xe3400007,          # movt r0, #7 (upper 16 bits of 500000)
                           0xe58d0004,          # str r0, [sp, #4]
                           0xe1a0000d,          # mov r0, sp (req)
                           0xe3a01000,          # mov r1, #0 (rem)
                           0xe3a070a2,          # mov r7, #162 (nanosleep)
                           0xef000000,          # svc 0
                           0xe3a07001,          # mov r7, #1 (exit)
                           0xef000000,          # svc 0
                           0xeafffffe           # b .
                           )

        probe = self.probe(code, thumb=False, syscall_policy='threads',
                           uname_profile={'raw_hex': raw.hex()},
                           filesystem=filesystem, kuser_template=template)
        report = probe.run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 1)
        serviced_names = [s['syscall'] for s in report['serviced_syscalls']]
        self.assertIn('nanosleep', serviced_names)
        nano_ev = next(s for s in report['serviced_syscalls'] if s['syscall'] == 'nanosleep')
        self.assertEqual(nano_ev['tv_sec'], 1)
        self.assertEqual(nano_ev['tv_nsec'], 500000)
        self.assertEqual(nano_ev['returned'], 0)

    def test_threads_policy_block_nanosleep_parks_caller(self):
        filesystem = {
            'nodes': {},
            'content_loader': lambda p, n: b''
        }
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        kernel_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
        if not kernel_path.exists():
            self.skipTest('Kernel image not available')
        template = extract_kuser_template(kernel_path)
        code = struct.pack('<8I',
                           0xe3a00001,          # mov r0, #1 (tv_sec)
                           0xe58d0000,          # str r0, [sp]
                           0xe3a00000,          # mov r0, #0 (tv_nsec)
                           0xe58d0004,          # str r0, [sp, #4]
                           0xe1a0000d,          # mov r0, sp (req)
                           0xe3a01000,          # mov r1, #0 (rem)
                           0xe3a070a2,          # mov r7, #162 (nanosleep)
                           0xef000000           # svc 0
                           )
        probe = self.probe(code, thumb=False, syscall_policy='threads',
                           uname_profile={'raw_hex': raw.hex()},
                           filesystem=filesystem, kuser_template=template)
        probe.thread_sleep_policy = 'block'
        report = probe.run()
        self.assertEqual(report['status'], 'blocked_sleep')
        self.assertEqual(report['boundary']['reason'], 'nanosleep_no_virtual_deadline')
        self.assertEqual(report['boundary']['tv_sec'], 1)
        nano_ev = next(s for s in report['serviced_syscalls'] if s['syscall'] == 'nanosleep')
        self.assertEqual(nano_ev['blocked_tid'], 1000)
        self.assertEqual(nano_ev['returned'], 0)
        self.assertEqual(report['threads']['1000']['state'], 'blocked_sleep')

    def test_threads_policy_block_nanosleep_keeps_short_sleeps_immediate(self):
        filesystem = {'nodes': {}, 'content_loader': lambda p, n: b''}
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        kernel_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
        if not kernel_path.exists():
            self.skipTest('Kernel image not available')
        template = extract_kuser_template(kernel_path)
        code = struct.pack('<10I',
                           0xe3a00000,          # mov r0, #0 (tv_sec)
                           0xe58d0000,          # str r0, [sp]
                           0xe3040240,          # movw r0, #0x4240
                           0xe340000f,          # movt r0, #0x000f -> tv_nsec = 1_000_000 (1 ms)
                           0xe58d0004,          # str r0, [sp, #4]
                           0xe1a0000d,          # mov r0, sp (req)
                           0xe3a01000,          # mov r1, #0 (rem)
                           0xe3a070a2,          # mov r7, #162 (nanosleep)
                           0xef000000,          # svc 0
                           0xe3a07001           # mov r7, #1 (exit)
                           ) + struct.pack('<2I', 0xef000000, 0xeafffffe)
        probe = self.probe(code, thumb=False, syscall_policy='threads',
                           uname_profile={'raw_hex': raw.hex()},
                           filesystem=filesystem, kuser_template=template)
        probe.thread_sleep_policy = 'block'
        report = probe.run()
        # 1 ms is a polling hint: it returns immediately instead of parking the
        # RM executor thread (E0355), so execution reaches the exit boundary.
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 1)
        nano_ev = next(s for s in report['serviced_syscalls'] if s['syscall'] == 'nanosleep')
        self.assertEqual(nano_ev['reason'], 'short_sleep_immediate')

    def test_sigill_delivery_to_registered_guest_handler(self):
        filesystem = {
            'nodes': {},
            'content_loader': lambda p, n: b''
        }
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        kernel_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
        if not kernel_path.exists():
            self.skipTest('Kernel image not available')
        template = extract_kuser_template(kernel_path)

        # Code executes:
        # 1. Store struct sigaction on stack:
        #    handler: address of handler (at offset 60, i.e. pc + 52)
        #    flags: 0, restorer: 0, mask: 0 (8 bytes)
        # 2. rt_sigaction(4, sp, 0, 8) (syscall 174)
        # 3. udf #0 (0xe7f001f0) -> triggers SIGILL hook
        # 4. Handler runs: mov r8, #42; mov r7, #1 (exit); svc 0
        code = struct.pack('<19I',
                           0xe28f4034,          # add r4, pc, #52 (handler address)
                           0xe58d4000,          # str r4, [sp]
                           0xe3a00000,          # mov r0, #0
                           0xe58d0004,          # str r0, [sp, #4]
                           0xe58d0008,          # str r0, [sp, #8]
                           0xe58d000c,          # str r0, [sp, #12]
                           0xe58d0010,          # str r0, [sp, #16]
                           0xe3a00004,          # mov r0, #4 (SIGILL)
                           0xe1a0100d,          # mov r1, sp (act)
                           0xe3a02000,          # mov r2, #0 (oldact)
                           0xe3a03008,          # mov r3, #8 (sigsetsize)
                           0xe3a070ae,          # mov r7, #174 (rt_sigaction)
                           0xef000000,          # svc 0
                           0xe7f001f0,          # udf #0 (triggers UC_HOOK_INSN_INVALID)
                           0xeafffffe,          # b .
                           # Handler (offset 60):
                           0xe3a0802a,          # mov r8, #42
                           0xe3a07001,          # mov r7, #1 (exit)
                           0xef000000,          # svc 0
                           0xeafffffe           # b .
                           )

        probe = self.probe(code, thumb=False, syscall_policy='threads',
                           uname_profile={'raw_hex': raw.hex()},
                           filesystem=filesystem, kuser_template=template)
        report = probe.run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 1)
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R8), 42)
        self.assertEqual(probe.sigill_count, 1)
        serviced_signals = [s for s in report['serviced_syscalls'] if s.get('signal') == 'SIGILL']
        self.assertEqual(len(serviced_signals), 1)
        self.assertEqual(serviced_signals[0]['signum'], 4)
        self.assertEqual(serviced_signals[0]['reason'], 'delivered_to_registered_guest_handler')

    def test_sigill_loop_bounding_fails_closed(self):
        filesystem = {
            'nodes': {},
            'content_loader': lambda p, n: b''
        }
        raw = b''.join(s.ljust(65, b'\0') for s in
                       (b'Linux', b'(none)', b'3.0.27', b'#1', b'arm', b'(none)'))
        kernel_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
        if not kernel_path.exists():
            self.skipTest('Kernel image not available')
        template = extract_kuser_template(kernel_path)

        # Code executes:
        # Register handler pointing back to udf #0 itself (infinite fault loop)
        code = struct.pack('<16I',
                           0xe28f402c,          # add r4, pc, #44 (points to udf #0 at offset 52)
                           0xe58d4000,          # str r4, [sp]
                           0xe3a00000,          # mov r0, #0
                           0xe58d0004,          # str r0, [sp, #4]
                           0xe58d0008,          # str r0, [sp, #8]
                           0xe58d000c,          # str r0, [sp, #12]
                           0xe58d0010,          # str r0, [sp, #16]
                           0xe3a00004,          # mov r0, #4 (SIGILL)
                           0xe1a0100d,          # mov r1, sp (act)
                           0xe3a02000,          # mov r2, #0 (oldact)
                           0xe3a03008,          # mov r3, #8 (sigsetsize)
                           0xe3a070ae,          # mov r7, #174 (rt_sigaction)
                           0xef000000,          # svc 0
                           0xe7f001f0,          # udf #0 (at offset 52)
                           0xeafffffe,          # b .
                           0xeafffffe           # b .
                           )

        probe = self.probe(code, thumb=False, syscall_policy='threads',
                           uname_profile={'raw_hex': raw.hex()},
                           filesystem=filesystem, kuser_template=template)
        report = probe.run()
        self.assertEqual(report['status'], 'signal_loop_boundary')
        self.assertEqual(report['boundary']['reason'], 'repeated_sigill_delivery')
        self.assertEqual(report['boundary']['deliveries'], probe.MAX_SIGILL_DELIVERIES)



class ProbeSliceAndDisplayTests(unittest.TestCase):
    """Bounded pause/resume and read-only display capture contracts."""

    def setUp(self):
        self.folder = PROJECT_ROOT / 'artifacts/tests/process-probe'
        self.folder.mkdir(parents=True, exist_ok=True)

    def probe(self, code=bytes.fromhex('00bf00bf00bf'), display_profile=None):
        app = make_elf(self.folder / 'slice-app.elf', b'\xfe\xe7', dynamic=False)
        interpreter = make_elf(self.folder / 'slice-linker.elf', code)
        probe = InterpreterProbe(syscall_policy='stop', display_profile=display_profile)
        probe.prepare(app, interpreter, ['/usr/bin/test'])
        return probe

    def test_pause_and_resume_slices(self):
        probe = self.probe(bytes.fromhex('fee7'))
        state = {'paused': False}
        probe.begin(instruction_budget=1000, timeout_us=1000000)
        probe._progress_interval = 8

        def progress(current):
            if not state['paused'] and current.instructions >= 40:
                state['paused'] = True
                current.pause()

        probe._on_progress = progress
        report = probe.run_slice(200)
        self.assertEqual(report['status'], 'paused')
        paused_at = probe.instructions
        self.assertGreaterEqual(paused_at, 40)
        self.assertLess(paused_at, 200)

        report = probe.run_slice(30)
        self.assertEqual(report['status'], 'running')
        self.assertGreaterEqual(probe.instructions, paused_at + 30)

        report = probe.finish(reason='stopped_by_user')
        self.assertEqual(report['status'], 'stopped_by_user')
        self.assertEqual(report['instructions_executed'], probe.instructions)

    def test_fresh_probe_rejects_slices_without_begin(self):
        probe = self.probe()
        with self.assertRaises(ValueError):
            probe.run_slice(10)

    def test_begin_schedules_a_woken_thread_instead_of_running_blocked_caller(self):
        from src.a6400.execution.guest_threads import GuestThreads, GuestThread
        probe = self.probe()
        probe.threads = GuestThreads()
        blocked = probe.threads.threads[1000]
        blocked.state = 'blocked_uipc'
        target = GuestThread(1001, 'proxy', state='runnable')
        target.regs = {arm.UC_ARM_REG_PC: 0x12340000, arm.UC_ARM_REG_CPSR: 0x10}
        probe.threads.threads[1001] = target
        probe.begin()
        self.assertEqual(probe.threads.current_tid, 1001)
        self.assertEqual(probe.entry, 0x12340000)
        self.assertEqual(blocked.state, 'blocked_uipc')

    def test_begin_keeps_all_blocked_threads_stopped(self):
        from src.a6400.execution.guest_threads import GuestThreads
        probe = self.probe()
        probe.threads = GuestThreads()
        probe.threads.threads[1000].state = 'blocked_uipc'
        report = probe.run()
        self.assertEqual(report['status'], 'blocked_threads')
        self.assertEqual(probe.instructions, 0)

    def test_display_capture_with_mapped_osd(self):
        from src.a6400.execution.guest_display import display_contract
        probe = self.probe(display_profile=display_contract('camera-e0074-e0044'))
        self.assertIsNotNone(probe.display)
        self.assertEqual(probe.report['display_contract'], 'camera-e0074-e0044')
        self.assertIsNone(probe.capture_display())

        probe.mu.mem_map(0x30000000, 0x200000, 5)  # UC_PROT_READ | UC_PROT_WRITE
        probe.display.register_mapping(0x30000000, 0x200000, 0x23A80000)
        probe._install_display_write_hooks()
        self.assertTrue(probe.display.installed_ranges)
        probe.display.note_write(0x30000000, 2, pc=0x401000, tid=1042, instruction=5)
        probe.mu.mem_write(0x30000000, struct.pack('<H', 0xF00F))
        frame = probe.capture_display()
        self.assertEqual(frame.surface.name, 'osd_a')
        self.assertEqual(frame.status, 'written')
        self.assertEqual(frame.rgba[0:4], bytes((255, 0, 0, 255)))
        self.assertIsNone(probe.capture_display('sugilite_color0'))
        self.assertEqual(probe._finalize_report()['display']['contract'], 'camera-e0074-e0044')


class SemtimedopDispatchTests(unittest.TestCase):
    """a6400 glibc 2.11.2 uses syscall 312 for semtimedop (301 also accepted)."""

    def _probe_with_sem(self):
        from src.a6400.execution.guest_sem import GuestSem, IPC_CREAT
        probe = InterpreterProbe(syscall_policy='stop')
        probe.syscall_policy = 'threads'
        probe.sem = GuestSem()
        probe.report['status'] = 'running'
        probe.mu.mem_map(0x1000, 0x2000, 7)
        probe.mu.mem_write(0x1000, bytes.fromhex('000000ef'))  # svc 0
        semid = probe.sem.semget(0x10020000, 1, IPC_CREAT | 0o666)
        probe.mu.mem_write(0x2000, struct.pack('<Hhh', 0, 1, 0))
        return probe, semid

    def test_semtimedop_syscall_312_is_serviced(self):
        probe, semid = self._probe_with_sem()
        probe.mu.reg_write(arm.UC_ARM_REG_R0, semid)
        probe.mu.reg_write(arm.UC_ARM_REG_R1, 0x2000)
        probe.mu.reg_write(arm.UC_ARM_REG_R2, 1)
        probe.mu.reg_write(arm.UC_ARM_REG_R3, 0)
        probe.mu.reg_write(arm.UC_ARM_REG_R7, 312)
        probe.mu.reg_write(arm.UC_ARM_REG_PC, 0x1004)
        probe.mu.reg_write(arm.UC_ARM_REG_CPSR, 0)
        probe._interrupt(probe.mu, 2, None)
        event = probe.report['serviced_syscalls'][-1]
        self.assertEqual(event['syscall'], 'semtimedop')
        self.assertEqual(event['r7'], 312)
        self.assertEqual(event['returned'], 0)
        self.assertEqual(probe.sem.sets_by_id[semid].values, [1])
        self.assertEqual(probe.report['status'], 'running')

    def test_semtimedop_syscall_301_remains_accepted(self):
        probe, semid = self._probe_with_sem()
        probe.mu.reg_write(arm.UC_ARM_REG_R0, semid)
        probe.mu.reg_write(arm.UC_ARM_REG_R1, 0x2000)
        probe.mu.reg_write(arm.UC_ARM_REG_R2, 1)
        probe.mu.reg_write(arm.UC_ARM_REG_R3, 0)
        probe.mu.reg_write(arm.UC_ARM_REG_R7, 301)
        probe.mu.reg_write(arm.UC_ARM_REG_PC, 0x1004)
        probe.mu.reg_write(arm.UC_ARM_REG_CPSR, 0)
        probe._interrupt(probe.mu, 2, None)
        event = probe.report['serviced_syscalls'][-1]
        self.assertEqual(event['r7'], 301)
        self.assertEqual(event['returned'], 0)


class UsbEventInjectionTests(unittest.TestCase):
    class FakeEvent:
        def __init__(self):
            self.owners = {}
            self.record = None

        def inject_record(self, record):
            self.record = record
            return {'accepted': True, 'reason': 'verified_record', 'bytes': len(record),
                    'sha256': hashlib.sha256(record).hexdigest()}

    class FakeThreads:
        def __init__(self):
            self.woken = []

        def handle_fd_wake(self, fd):
            self.woken.append(fd)
            return [1014]

        def handle_uipc_wake(self, queue):
            self.woken.append(queue)
            return [1001]

    def _probe(self):
        from types import SimpleNamespace
        probe = InterpreterProbe(syscall_policy='stop')
        probe.filesystem = SimpleNamespace(fds={13: {'device': 'usb_event'}})
        probe.usb_event = self.FakeEvent()
        probe.threads = self.FakeThreads()
        probe.instructions = 123
        return probe

    def test_inject_wakes_reader_and_records_provenance(self):
        probe = self._probe()
        result = probe.inject_usb_event(b'ABCD')
        self.assertTrue(result['accepted'])
        self.assertEqual(result['fd'], 13)
        self.assertEqual(result['woken'], [1014])
        self.assertEqual(probe.usb_event.record, b'ABCD')
        stored = probe.report['usb_event_injection'][-1]
        self.assertEqual(stored['bytes'], 4)
        self.assertEqual(stored['sha256'], hashlib.sha256(b'ABCD').hexdigest())

    def test_arm_waits_for_open_device_and_delivers_once(self):
        probe = self._probe()
        probe.arm_usb_connect_event(b'ABCD', at_instruction=0)
        self.assertIsNone(probe._maybe_inject_usb_connect())
        probe.usb_event.owners = {1: {}}
        result = probe._maybe_inject_usb_connect()
        self.assertTrue(result['accepted'])
        self.assertIsNone(probe._maybe_inject_usb_connect())
        self.assertEqual(probe.usb_event.record, b'ABCD')


    def test_uipc_message_injection_writes_payload_and_wakes(self):
        from src.a6400.execution.guest_uipc import GuestUipc
        probe = InterpreterProbe(syscall_policy='stop')
        probe.mu.mem_map(0x2000, 0x1000, 7)
        probe.uipc = GuestUipc(total_pool_size=0x1000)
        probe.uipc.pool_base = 0x2000
        probe.threads = self.FakeThreads()
        probe.instructions = 77
        result = probe.inject_uipc_message(0x1234, b'\x01\x02\x03', source='unit-test')
        self.assertEqual(bytes(probe.mu.mem_read(0x202c, 3)), b'\x01\x02\x03')
        self.assertEqual(bytes(probe.mu.mem_read(0x2020, 12)),
                         struct.pack('<IBBHI', 0, 0, 1, 1, 0xa5a5a5a5))
        self.assertEqual(probe.uipc.message_queues[0x1234], [0x202c])
        self.assertEqual(result['woken'], [1001])
        self.assertEqual(probe.report['uipc_injection'][-1]['queue'], 0x1234)
        self.assertEqual(probe.report['uipc_injection'][-1]['size'], 3)


class LoaderStopSummaryTests(unittest.TestCase):
    def test_summary_extracts_undefined_symbol_and_library_mappings(self):
        symbol = '_ZN29C_DataflowInfra_Entry_OsdMute11SetData_AllEPN20DataflowInfra_StdOsd12PIN_OSD_MUTEE'
        events = [
            {'syscall': 'open', 'path': '/usr/lib/libObj.so', 'returned': 6},
            {'syscall': 'mmap2', 'mapping': {'path': '/usr/lib/libObj.so', 'base': 0x54000000,
                                             'offset': 0, 'size': 20860436, 'sha256': '60ff'}},
            {'syscall': 'open', 'path': '/usr/lib/dataflowInfraFramework.so', 'returned': 6},
            {'syscall': 'mmap2', 'mapping': {'path': '/usr/lib/dataflowInfraFramework.so',
                                             'base': 0x56000000, 'offset': 0, 'size': 172192,
                                             'sha256': 'a831'}},
            {'syscall': 'mmap2', 'path': '/dev/mem', 'mapping': {'phys_addr': 0x202e0000}},
            {'syscall': 'exit_group', 'r7': 248, 'status': 127},
        ]
        stderr = '/usr/bin/im.elf: symbol lookup error: /usr/bin/im.elf: undefined symbol: ' + symbol + '\n'
        summary = summarize_loader_stop(events, stderr)
        self.assertTrue(summary['symbol_lookup_error'])
        self.assertEqual(summary['undefined_symbol'], symbol)
        self.assertEqual(summary['last_exit']['status'], 127)
        self.assertIn('/usr/lib/libObj.so', summary['libraries'])
        self.assertEqual(summary['libraries']['/usr/lib/dataflowInfraFramework.so'][-1]['size'], 172192)
        self.assertNotIn('/dev/mem', summary['libraries'])

    def test_summary_without_loader_error_is_quiet(self):
        summary = summarize_loader_stop([], '')
        self.assertFalse(summary['symbol_lookup_error'])
        self.assertIsNone(summary['undefined_symbol'])
        self.assertIsNone(summary['last_exit'])
        self.assertEqual(summary['libraries'], {})


class LoaderWorkaroundTests(unittest.TestCase):
    """E3/E4: Thumb IT-state and _dl_fixup entry workarounds.

    The 224.34M DataflowInfra abort was caused by Unicorn conditionally
    skipping _dl_fixup's unconditional `mov r4,r0` under a stale Thumb IT
    latch.  These tests exercise the pure register-level observers (fake uc;
    no firmware run) and assert the fast-hook address membership that E3
    identified, without changing or weakening the policies.
    """

    IT_ADDRESSES = (0x40004e4c, 0x50259c24, 0x50034e32, 0x50034e6a,
                    0x4000a6f4, 0x5026ebc4, 0x5026ec26)
    KNOWN_IT_MASK = (3 << 25) | (0x3f << 10)

    class _RegisterUc:
        def __init__(self, registers=None):
            self.registers = dict(registers or {})
            self.writes = []

        def reg_read(self, register):
            return self.registers[register]

        def reg_write(self, register, value):
            self.registers[register] = value
            self.writes.append((register, value))

    class _HookUc:
        """Records hook registrations instead of executing guest code."""

        def __init__(self, arch, mode):
            self.arch = arch
            self.mode = mode
            self.hooks = []

        def ctl_set_cpu_model(self, model):
            self.cpu_model = model

        def reg_write(self, register, value):
            pass

        def hook_add(self, kind, callback, **kwargs):
            self.hooks.append({'kind': kind,
                               'callback': getattr(callback, '__name__', ''),
                               'begin': kwargs.get('begin'),
                               'end': kwargs.get('end')})

    def test_ld_fixup_workaround_sets_r4_from_r0_under_threads_policy(self):
        probe = InterpreterProbe()
        probe.syscall_policy = 'threads'
        uc = self._RegisterUc({arm.UC_ARM_REG_R0: 0x1F648, arm.UC_ARM_REG_R4: 1})

        probe._ld_fixup_workaround(uc, 0x4000A6F4, 4, None)

        self.assertEqual(uc.registers[arm.UC_ARM_REG_R4], 0x1F648)
        self.assertEqual(uc.writes, [(arm.UC_ARM_REG_R4, 0x1F648)])

    def test_ld_fixup_workaround_is_gated_by_threads_policy(self):
        probe = InterpreterProbe()
        for policy in ('stop', 'brk', 'files', 'metadata'):
            with self.subTest(policy=policy):
                probe.syscall_policy = policy
                uc = self._RegisterUc({arm.UC_ARM_REG_R0: 0x1F648,
                                       arm.UC_ARM_REG_R4: 1})
                probe._ld_fixup_workaround(uc, 0x4000A6F4, 4, None)
                self.assertEqual(uc.registers[arm.UC_ARM_REG_R4], 1)
                self.assertEqual(uc.writes, [])

    def test_it_workaround_clears_it_and_jit_bits_under_supported_policy(self):
        probe = InterpreterProbe()
        probe.syscall_policy = 'threads'
        initial = 0x40000030 | self.KNOWN_IT_MASK
        uc = self._RegisterUc({arm.UC_ARM_REG_CPSR: initial})

        probe._it_workaround(uc, 0x5026EC26, 2, None)

        self.assertEqual(uc.registers[arm.UC_ARM_REG_CPSR],
                         initial & ~self.KNOWN_IT_MASK)
        self.assertEqual(len(uc.writes), 1)

    def test_it_workaround_is_unchanged_without_it_bits(self):
        probe = InterpreterProbe()
        probe.syscall_policy = 'threads'
        uc = self._RegisterUc({arm.UC_ARM_REG_CPSR: 0x30})

        probe._it_workaround(uc, 0x4000A6F4, 4, None)

        self.assertEqual(uc.registers[arm.UC_ARM_REG_CPSR], 0x30)
        self.assertEqual(uc.writes, [])

    def test_it_workaround_is_gated_by_threads_policy(self):
        probe = InterpreterProbe()
        for policy in ('stop', 'brk', 'files', 'metadata'):
            with self.subTest(policy=policy):
                probe.syscall_policy = policy
                initial = 0x30 | self.KNOWN_IT_MASK
                uc = self._RegisterUc({arm.UC_ARM_REG_CPSR: initial})
                probe._it_workaround(uc, 0x5026EBC4, 2, None)
                self.assertEqual(uc.registers[arm.UC_ARM_REG_CPSR], initial)
                self.assertEqual(uc.writes, [])

    def test_fast_mode_registers_fixup_and_pop_it_addresses(self):
        from src.a6400.execution import interpreter_probe as module
        with mock.patch.object(module.unicorn, 'Uc', self._HookUc):
            probe = InterpreterProbe(hook_mode='fast')
        hooks = probe.mu.hooks

        it_addresses = {hook['begin'] for hook in hooks
                        if hook['callback'] == '_it_workaround'}
        self.assertEqual(it_addresses, set(self.IT_ADDRESSES))
        # The two E3/E4 addresses are observed as exact single instructions.
        for address in self.IT_ADDRESSES:
            matching = [hook for hook in hooks
                        if hook['callback'] == '_it_workaround' and hook['begin'] == address]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]['end'], address)

        fixup_hooks = [hook for hook in hooks
                       if hook['callback'] == '_ld_fixup_workaround']
        self.assertEqual([(hook['begin'], hook['end']) for hook in fixup_hooks],
                         [(0x4000A6F4, 0x4000A6F4)])
        self.assertIn('_block', [hook['callback'] for hook in hooks])
        self.assertNotIn('_code', [hook['callback'] for hook in hooks])

    def test_instruction_mode_keeps_central_code_hook_without_fixup_hooks(self):
        from src.a6400.execution import interpreter_probe as module
        with mock.patch.object(module.unicorn, 'Uc', self._HookUc):
            probe = InterpreterProbe(hook_mode='instruction')
        callbacks = [hook['callback'] for hook in probe.mu.hooks]
        self.assertIn('_code', callbacks)
        self.assertNotIn('_it_workaround', callbacks)
        self.assertNotIn('_ld_fixup_workaround', callbacks)


if __name__ == '__main__':
    unittest.main()


