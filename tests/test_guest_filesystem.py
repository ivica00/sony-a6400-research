"""Read-only guest file behavior; fixtures never expose arbitrary host paths."""
import hashlib
from pathlib import Path
import stat
import unittest

import unicorn
from project_paths import PROJECT_ROOT
from src.a6400.execution.guest_filesystem import GuestFilesystem, UnsupportedFilesystem
from src.a6400.execution.guest_uname import UnverifiedIdentityData
from src.a6400.images.guest_paths import resolve_guest
from src.a6400.images.verified_content import VerifiedContent, ContentUnavailable


class FilesystemTests(unittest.TestCase):
    def setUp(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.mu.mem_map(0x3000, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
        self.mu.mem_map(0x5000, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
        directory = {'kind': 'directory', 'mode': stat.S_IFDIR | 0o755, 'uid': 0, 'gid': 0}
        self.nodes = {'/': dict(directory), '/lib': dict(directory),
                      '/lib/file': {'kind': 'file', 'mode': stat.S_IFREG | 0o644,
                                    'uid': 0, 'gid': 0, 'size': 6},
                      '/alias': {'kind': 'symlink', 'target': '/lib/file'}}
        self.calls = []
        def loader(path, node):
            self.calls.append(path)
            return b'ABCDEF'
        self.fs = GuestFilesystem(self.mu, self.nodes, loader)

    def path(self, value):
        self.mu.mem_write(0x3000, value.encode() + b'\0')
        return 0x3000

    def open(self, value='/lib/file', flags=0):
        return self.fs.request(5, [self.path(value), flags, 0])

    def test_absent_static_path_is_enoent(self):
        event = self.fs.request(33, [self.path('/lib/missing'), 4, 0])
        self.assertEqual(event['returned'], 0xfffffffe)
        self.assertEqual(self.calls, [])

    def test_existing_access_uses_metadata(self):
        self.assertEqual(self.fs.request(33, [self.path('/alias'), 4, 0])['returned'], 0)
        self.assertEqual(self.calls, [])

    def test_runtime_path_does_not_become_enoent(self):
        for path in ('/setting/missing', '/tmp/../lib/file', '/dev/null', '/system/no-file'):
            with self.assertRaises(UnsupportedFilesystem):
                self.fs.request(33, [self.path(path), 0, 0])

    def test_symlink_into_runtime_mount_stops(self):
        self.nodes['/runtime'] = {'kind': 'symlink', 'target': '/proc/maps'}
        with self.assertRaises(UnsupportedFilesystem):
            self.open('/runtime')

    def test_symlink_and_snapshot_hash(self):
        event = self.open('/alias')
        self.assertEqual(event['returned'], 3)
        self.assertEqual(event['resolved_path'], '/lib/file')
        self.assertEqual(event['sha256'], hashlib.sha256(b'ABCDEF').hexdigest())

    def test_read_offsets_eof_and_seek(self):
        fd = self.open()['returned']
        self.assertEqual(self.fs.request(3, [fd, 0x5000, 4])['returned'], 4)
        self.assertEqual(bytes(self.mu.mem_read(0x5000, 4)), b'ABCD')
        self.assertEqual(self.fs.request(3, [fd, 0x5000, 4])['returned'], 2)
        self.assertEqual(bytes(self.mu.mem_read(0x5000, 2)), b'EF')
        self.assertEqual(self.fs.request(3, [fd, 0, 4])['returned'], 0)
        self.assertEqual(self.fs.request(19, [fd, 0xffffffff, 2])['returned'], 5)
        self.assertEqual(self.fs.request(3, [fd, 0x5000, 1])['returned'], 1)
        self.assertEqual(bytes(self.mu.mem_read(0x5000, 1)), b'F')

    def test_bad_read_buffer_does_not_advance(self):
        fd = self.open()['returned']
        self.assertEqual(self.fs.request(3, [fd, 0, 3])['returned'], 0xfffffff2)
        self.assertEqual(self.fs.fds[fd]['offset'], 0)

    def test_read_cannot_bypass_guest_write_permissions(self):
        fd = self.open()['returned']
        self.mu.mem_protect(0x5000, 4096, unicorn.UC_PROT_READ)
        self.assertEqual(self.fs.request(3, [fd, 0x5000, 3])['returned'], 0xfffffff2)
        self.assertEqual(self.fs.fds[fd]['offset'], 0)

    def test_host_copy_notifies_provenance(self):
        copied = []
        self.fs.after_write = lambda address, size: copied.append((address, size))
        self.fs.request(3, [self.open()['returned'], 0x5000, 2])
        self.assertEqual(copied, [(0x5000, 2)])

    def test_unknown_identity_path_does_not_get_service(self):
        def guard(address, size):
            raise UnverifiedIdentityData({'fields': ['machine']})
        self.fs.before_read = guard
        with self.assertRaises(UnverifiedIdentityData):
            self.open()
        self.assertEqual(self.calls, [])

    def test_descriptor_reuse_and_independent_offsets(self):
        a, b = self.open()['returned'], self.open()['returned']
        self.fs.request(3, [a, 0x5000, 2])
        self.assertEqual(self.fs.fds[b]['offset'], 0)
        self.assertEqual(self.calls, ['/lib/file'])
        self.fs.request(6, [a, 0, 0])
        self.assertEqual(self.open()['returned'], a)

    def test_invalid_fd_and_inherited_stdio(self):
        self.assertEqual(self.fs.request(6, [99, 0, 0])['returned'], 0xfffffff7)
        with self.assertRaises(UnsupportedFilesystem):
            self.fs.request(3, [0, 0x5000, 1])

    def test_write_flags_stop_without_loader_or_fd(self):
        for flags in (1, 2, 0x40, 0x200, 0x8000):
            with self.assertRaises(UnsupportedFilesystem):
                self.open(flags=flags)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.fs.fds, {})

    def test_read_only_cloexec_and_largefile_flags(self):
        self.assertEqual(self.open(flags=0xa0000)['returned'], 3)

    def test_relative_empty_and_invalid_path_pointer(self):
        with self.assertRaises(UnsupportedFilesystem):
            self.open('lib/file')
        self.assertEqual(self.open('')['returned'], 0xfffffffe)
        self.assertEqual(self.fs.request(5, [0, 0, 0])['returned'], 0xfffffff2)

    def test_no_terminator_is_enametoolong(self):
        self.mu.mem_write(0x3000, b'x' * 4096)
        self.assertEqual(self.fs.request(5, [0x3000, 0, 0])['returned'], (-36) & 0xffffffff)

    def test_symlink_cycle_and_not_directory(self):
        self.nodes['/a'] = {'kind': 'symlink', 'target': '/b'}
        self.nodes['/b'] = {'kind': 'symlink', 'target': '/a'}
        self.assertEqual(self.open('/a')['returned'], (-40) & 0xffffffff)
        for path in ('/lib/file/child', '/lib/file/', '/alias/.'):
            self.assertEqual(self.open(path)['returned'], (-20) & 0xffffffff)

    def test_stat_absence_only_and_directory_open_stops(self):
        self.assertEqual(self.fs.request(195, [self.path('/missing'), 0x5000, 0])['returned'], (-2) & 0xffffffff)
        with self.assertRaises(UnsupportedFilesystem):
            self.fs.request(195, [self.path('/lib'), 0x5000, 0])
        with self.assertRaises(UnsupportedFilesystem):
            self.open('/lib')

    def test_permissions_are_not_inferred_from_host(self):
        self.nodes['/lib/file']['mode'] = stat.S_IFREG
        with self.assertRaises(UnsupportedFilesystem):
            self.open()
        self.fs.uid = 1000
        self.fs.gid = 1000
        self.assertEqual(self.open()['returned'], (-13) & 0xffffffff)

    def test_missing_backing_data_stops_instead_of_becoming_enoent(self):
        def unavailable(path, node):
            raise ContentUnavailable('content_hash_mismatch')
        self.fs.content_loader = unavailable
        with self.assertRaises(UnsupportedFilesystem) as caught:
            self.open()
        self.assertEqual(caught.exception.details['reason'], 'unverified_image_content')
        self.assertEqual(self.fs.fds, {})

    def test_directory_search_permissions_checked_before_absence(self):
        self.fs.uid, self.fs.gid = 1000, 1000
        self.nodes['/lib']['mode'] = stat.S_IFDIR | 0o700
        self.assertEqual(self.open('/lib/missing')['returned'], (-13) & 0xffffffff)

    def test_zero_length_read_does_not_touch_invalid_buffer(self):
        fd = self.open()['returned']
        self.assertEqual(self.fs.request(3, [fd, 0, 0])['returned'], 0)
        self.assertEqual(self.fs.fds[fd]['offset'], 0)

    def test_seek_failures_and_read_limit_do_not_advance(self):
        fd = self.open()['returned']
        self.assertEqual(self.fs.request(19, [fd, 0xffffffff, 0])['returned'], (-22) & 0xffffffff)
        self.assertEqual(self.fs.request(19, [fd, 0, 99])['returned'], (-22) & 0xffffffff)
        with self.assertRaises(UnsupportedFilesystem):
            self.fs.request(3, [fd, 0x5000, 1024 * 1024 + 1])
        self.assertEqual(self.fs.fds[fd]['offset'], 0)

    def test_tmp_overlay_stop_policy_blocks_tmp(self):
        fs = GuestFilesystem(self.mu, self.nodes, lambda p, n: b'', tmp_overlay='stop')
        with self.assertRaises(UnsupportedFilesystem):
            fs.request(33, [self.path('/tmp'), 0, 0])
        with self.assertRaises(UnsupportedFilesystem):
            fs.request(5, [self.path('/tmp/test'), 0, 0])

    def test_tmp_overlay_invalid_policy_rejected(self):
        with self.assertRaises(ValueError):
            GuestFilesystem(self.mu, self.nodes, lambda p, n: b'', tmp_overlay='invalid')

    def test_tmp_overlay_experimental_empty(self):
        fs = GuestFilesystem(self.mu, self.nodes, lambda p, n: b'', tmp_overlay='experimental-empty')
        # access('/tmp') -> 0
        ev_access = fs.request(33, [self.path('/tmp'), 0, 0])
        self.assertEqual(ev_access['returned'], 0)
        self.assertEqual(ev_access['reason'], 'experimental_tmp_access')

        # access('/tmp/nonexistent') -> ENOENT
        ev_sub_access = fs.request(33, [self.path('/tmp/nonexistent'), 0, 0])
        self.assertEqual(ev_sub_access['returned'], 0xfffffffe)
        self.assertEqual(ev_sub_access['reason'], 'ENOENT_experimental_empty_tmp')

        # open('/tmp') -> unsupported (tmp_directory_open_not_implemented)
        with self.assertRaises(UnsupportedFilesystem) as caught:
            fs.request(5, [self.path('/tmp'), 0, 0])
        self.assertEqual(caught.exception.details['reason'], 'tmp_directory_open_not_implemented')

        # open('/tmp/foo') -> ENOENT
        ev_open = fs.request(5, [self.path('/tmp/foo'), 0, 0])
        self.assertEqual(ev_open['returned'], 0xfffffffe)
        self.assertEqual(ev_open['reason'], 'ENOENT_experimental_empty_tmp')

    def test_proc_overlay_experimental_empty(self):
        fs = GuestFilesystem(self.mu, self.nodes, lambda p, n: b'', proc_overlay='experimental-empty')
        # access('/proc') -> 0
        ev_access = fs.request(33, [self.path('/proc'), 0, 0])
        self.assertEqual(ev_access['returned'], 0)
        self.assertEqual(ev_access['reason'], 'experimental_proc_access')

        # open('/proc') -> opened_experimental_proc_dir
        ev_open = fs.request(5, [self.path('/proc'), 0, 0])
        self.assertIn('returned', ev_open)
        fd = ev_open['returned']
        self.assertGreaterEqual(fd, 3)
        self.assertEqual(ev_open['reason'], 'opened_experimental_proc_dir')

        # close(fd) -> 0
        ev_close = fs.request(6, [fd, 0, 0])
        self.assertEqual(ev_close['returned'], 0)

        # open('/proc/klog') -> ENOENT
        ev_sub = fs.request(5, [self.path('/proc/klog'), 0, 0])
        self.assertEqual(ev_sub['returned'], 0xfffffffe)
        self.assertEqual(ev_sub['reason'], 'ENOENT_experimental_empty_proc')

    def test_proc_overlay_modules(self):
        class MockStatContract:
            def request(self, metadata, address):
                return {'returned': 0, 'metadata': metadata, 'address': address}

        fs = GuestFilesystem(self.mu, self.nodes, lambda p, n: b'', stat_contract=MockStatContract(), proc_overlay='experimental-empty')
        ev_access = fs.request(33, [self.path('/proc/modules'), 0, 0])
        self.assertEqual(ev_access['returned'], 0)
        self.assertEqual(ev_access['reason'], 'authentic_proc_modules_access')

        ev_stat = fs.request(195, [self.path('/proc/modules'), 0x5000, 0])
        self.assertEqual(ev_stat['returned'], 0)
        self.assertGreater(ev_stat['metadata']['size'], 0)

        ev_open = fs.request(5, [self.path('/proc/modules'), 0, 0])
        self.assertIn('returned', ev_open)
        fd = ev_open['returned']
        self.assertGreaterEqual(fd, 3)
        self.assertEqual(ev_open['reason'], 'opened_authentic_proc_modules')

        ev_fstat = fs.request(197, [fd, 0x5000, 0])
        self.assertEqual(ev_fstat['returned'], 0)

        ev_read1 = fs.request(3, [fd, 0x5000, 1024])
        self.assertEqual(ev_read1['returned'], 1024)
        ev_read2 = fs.request(3, [fd, 0x5400, 1024])
        self.assertEqual(ev_read2['returned'], 1024)
        buf = bytes(self.mu.mem_read(0x5000, 2048))
        self.assertIn(b'grm_ma ', buf)

        ev_close = fs.request(6, [fd, 0, 0])
        self.assertEqual(ev_close['returned'], 0)

    def test_setting_overlay_stop_policy_blocks_setting(self):
        fs = GuestFilesystem(self.mu, self.nodes, lambda p, n: b'', setting_overlay='stop')
        with self.assertRaises(UnsupportedFilesystem):
            fs.request(33, [self.path('/setting'), 0, 0])
        with self.assertRaises(UnsupportedFilesystem):
            fs.request(5, [self.path('/setting/test'), 0, 0])

    def test_setting_overlay_experimental_empty(self):
        fs = GuestFilesystem(self.mu, self.nodes, lambda p, n: b'', setting_overlay='experimental-empty')
        # access('/setting') -> 0
        ev_access = fs.request(33, [self.path('/setting'), 0, 0])
        self.assertEqual(ev_access['returned'], 0)
        self.assertEqual(ev_access['reason'], 'experimental_setting_access')

        # access('/setting/foo') -> ENOENT
        ev_sub_access = fs.request(33, [self.path('/setting/foo'), 0, 0])
        self.assertEqual(ev_sub_access['returned'], 0xfffffffe)
        self.assertEqual(ev_sub_access['reason'], 'ENOENT_experimental_empty_setting')

        # open('/setting') -> unsupported (setting_directory_open_not_implemented)
        with self.assertRaises(UnsupportedFilesystem) as caught:
            fs.request(5, [self.path('/setting'), 0, 0])
        self.assertEqual(caught.exception.details['reason'], 'setting_directory_open_not_implemented')

        # open('/setting/foo') -> ENOENT
        ev_open = fs.request(5, [self.path('/setting/foo'), 0, 0])
        self.assertEqual(ev_open['returned'], 0xfffffffe)
        self.assertEqual(ev_open['reason'], 'ENOENT_experimental_empty_setting')



class ContentTests(unittest.TestCase):
    def setUp(self):
        self.root = PROJECT_ROOT / 'artifacts/tests/content-provider'
        self.allowed = self.root / 'images'
        self.allowed.mkdir(parents=True, exist_ok=True)
        self.path = self.allowed / 'file.bin'
        self.path.write_bytes(b'ABCDEF')
        self.provider = VerifiedContent(self.root, self.allowed,
                                        {'images/file.bin': hashlib.sha256(b'ABCDEF').hexdigest()})

    def test_verified_bytes(self):
        self.assertEqual(self.provider('/file', {'extracted_path': 'images/file.bin'}), b'ABCDEF')

    def test_changed_missing_and_non_allowlisted_content(self):
        self.path.write_bytes(b'changed')
        with self.assertRaises(ContentUnavailable):
            self.provider('/file', {'extracted_path': 'images/file.bin'})
        for name in ('images/unknown.bin', '../outside'):
            with self.assertRaises(ContentUnavailable):
                self.provider('/file', {'extracted_path': name})

    def test_allowlist_cannot_escape_confinement(self):
        provider = VerifiedContent(self.root, self.allowed, {'../outside': '0' * 64})
        with self.assertRaises(ContentUnavailable):
            provider('/file', {'extracted_path': '../outside'})
