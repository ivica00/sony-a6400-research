"""Optional image-backed urandom opens never fabricate entropy or broaden /dev."""
import unittest
import stat
import struct

import unicorn

from src.a6400.execution.guest_filesystem import GuestFilesystem, UnsupportedFilesystem
from src.a6400.execution.guest_uname import UnverifiedIdentityData


class UrandomTests(unittest.TestCase):
    def setUp(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.mu.mem_map(0x1000, 0x1000, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
        directory = {'kind': 'directory', 'mode': stat.S_IFDIR | 0o755, 'uid': 0, 'gid': 0}
        self.node = {'kind': 'special', 'mode': stat.S_IFCHR | 0o444, 'uid': 0, 'gid': 0,
                     'stat_metadata': {'mode': stat.S_IFCHR | 0o444,
                                       'image_sha256': 'a' * 64,
                                       'device_number': {'major': 1, 'minor': 9}}}
        self.nodes = {'/': dict(directory), '/dev': dict(directory), '/dev/urandom': self.node}
        self.fs = GuestFilesystem(self.mu, self.nodes, lambda *args: self.fail('Device must not load file bytes'),
                                  urandom_open=True)

    def request_open(self, path='/dev/urandom', flags=0):
        self.mu.mem_write(0x1000, path.encode() + b'\0')
        return self.fs.request(5, [0x1000, flags, 0])

    def test_default_policy_still_stops(self):
        self.fs.urandom_open = False
        with self.assertRaises(UnsupportedFilesystem) as caught:
            self.request_open()
        self.assertEqual(caught.exception.details['reason'], 'runtime_namespace_not_supplied')

    def test_open_read_boundary_preserves_buffer(self):
        fd = self.request_open()['returned']
        self.mu.mem_write(0x1100, b'KEEP')
        with self.assertRaises(UnsupportedFilesystem) as caught:
            self.fs.request(3, [fd, 0x1100, 4])
        self.assertEqual(caught.exception.details['reason'], 'entropy_state_not_supplied')
        self.assertEqual(caught.exception.details['bytes_supplied'], 0)
        self.assertEqual(caught.exception.details['count'], 4)
        self.assertEqual(bytes(self.mu.mem_read(0x1100, 4)), b'KEEP')

    def test_deterministic_entropy_read_supplies_bytes_and_notifies_writer(self):
        self.fs.urandom_entropy_policy = 'deterministic'
        self.fs.urandom_seed = b'\xaa\xbb\xcc\xdd'
        copied = []
        self.fs.after_write = lambda addr, sz: copied.append((addr, sz))
        fd = self.request_open()['returned']
        res = self.fs.request(3, [fd, 0x1100, 4])
        self.assertEqual(res['returned'], 4)
        self.assertEqual(res['reason'], 'deterministic_urandom_read')
        self.assertEqual(bytes(self.mu.mem_read(0x1100, 4)), b'\xaa\xbb\xcc\xdd')
        self.assertEqual(copied, [(0x1100, 4)])

    def test_other_devices_aliases_and_runtime_paths_stay_guarded(self):
        self.nodes['/alias'] = {'kind': 'symlink', 'target': '/dev/urandom'}
        for path in ('/dev/random', '/dev/null', '/alias', '/dev/../dev/urandom', '/dev/urandom/extra'):
            with self.subTest(path=path), self.assertRaises(UnsupportedFilesystem):
                self.request_open(path)
        self.assertFalse(self.fs.fds)

    def test_identity_mismatch_is_not_success(self):
        self.node['stat_metadata']['device_number']['minor'] = 8
        with self.assertRaises(UnsupportedFilesystem) as caught:
            self.request_open()
        self.assertEqual(caught.exception.details['reason'], 'urandom_image_identity_not_verified')
        self.assertFalse(self.fs.fds)

    def test_missing_provenance_and_noncharacter_node_rejected(self):
        for key, value in (('image_sha256', ''), ('mode', stat.S_IFBLK | 0o444)):
            original = self.node['stat_metadata'][key]
            self.node['stat_metadata'][key] = value
            with self.subTest(key=key), self.assertRaises(UnsupportedFilesystem):
                self.request_open()
            self.node['stat_metadata'][key] = original
        self.node['mode'] = stat.S_IFREG | 0o444
        with self.assertRaises(UnsupportedFilesystem):
            self.request_open()

    def test_only_readonly_flags_allowed(self):
        for flags in (1, 2, 0x40, 0x200):
            with self.subTest(flags=flags), self.assertRaises(UnsupportedFilesystem):
                self.request_open(flags=flags)
        self.assertFalse(self.fs.fds)

    def test_close_reuse_and_descriptor_limit(self):
        fd = self.request_open()['returned']
        self.assertEqual(self.fs.request(6, [fd, 0, 0])['returned'], 0)
        self.assertEqual(self.request_open()['returned'], fd)
        self.fs.fds.update({n: {} for n in range(3, 259)})
        with self.assertRaises(UnsupportedFilesystem) as caught:
            self.request_open()
        self.assertEqual(caught.exception.details['reason'], 'experimental_descriptor_limit')
        self.assertNotIn(None, self.fs.fds)

    def test_fstat_and_seek_do_not_invent_metadata(self):
        fd = self.request_open()['returned']
        for number in (19, 197):
            with self.subTest(number=number), self.assertRaises(UnsupportedFilesystem) as caught:
                self.fs.request(number, [fd, 0x1100, 0])
            self.assertEqual(caught.exception.details['reason'], 'urandom_operation_not_implemented')

    def test_path_provenance_cannot_be_bypassed(self):
        def guard(*args):
            raise UnverifiedIdentityData({'fields': ['machine']})
        self.fs.before_read = guard
        with self.assertRaises(UnverifiedIdentityData):
            self.request_open()
        self.assertFalse(self.fs.fds)

    def test_original_arm_syscalls_open_then_stop_before_entropy_copy(self):
        try:
            from tests.test_interpreter_probe import make_elf
        except ImportError:
            from test_interpreter_probe import make_elf
        from project_paths import PROJECT_ROOT
        from src.a6400.execution.interpreter_probe import InterpreterProbe
        folder = PROJECT_ROOT / 'artifacts/tests/urandom-arm'
        folder.mkdir(parents=True, exist_ok=True)
        # ARM open(path,0), then read(fd,stack_buffer,4). No host device is read.
        words = (0xe59f001c, 0xe3a01000, 0xe3a07005, 0xef000000,
                 0xe1a04000, 0xe59f100c, 0xe3a02004, 0xe3a07003, 0xef000000,
                 0x4000012c, 0x7fe00000)
        code = struct.pack('<11I', *words) + b'/dev/urandom\0'
        app = make_elf(folder / 'app.elf', bytes.fromhex('fee7'), dynamic=False)
        linker = make_elf(folder / 'linker.elf', code, thumb=False)
        probe = InterpreterProbe(syscall_policy='files', uname_profile={'raw_hex': bytes(390).hex()},
                                 filesystem={'nodes': self.nodes, 'content_loader': lambda *args: b'',
                                             'urandom_open': True})
        probe.prepare(app, linker, ['/test'])
        probe.mu.mem_write(0x7fe00000, b'KEEP')
        report = probe.run()
        self.assertEqual(report['status'], 'unsupported_filesystem')
        self.assertEqual(report['boundary']['reason'], 'entropy_state_not_supplied')
        self.assertEqual(report['boundary']['r7'], 3)
        self.assertEqual(report['syscall_responses_supplied'], 1)
        self.assertEqual(bytes(probe.mu.mem_read(0x7fe00000, 4)), b'KEEP')
