"""chdir(2) (ARM nr 12) against the image namespace: 0 / -ENOENT / -ENOTDIR, cwd stored."""
import stat
import unittest

import unicorn
from project_paths import PROJECT_ROOT  # noqa: F401 (sets sys.path like neighbouring tests)
from src.a6400.execution.guest_filesystem import GuestFilesystem


class ChdirTests(unittest.TestCase):
    def setUp(self):
        mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        mu.mem_map(0x3000, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
        d = {'kind': 'directory', 'mode': stat.S_IFDIR | 0o755, 'uid': 0, 'gid': 0}
        nodes = {'/': dict(d), '/usr': dict(d), '/usr/share': dict(d),
                 '/lib/file': {'kind': 'file', 'mode': stat.S_IFREG | 0o644, 'uid': 0, 'gid': 0, 'size': 1}}
        nodes['/lib'] = dict(d)
        self.mu, self.fs = mu, GuestFilesystem(mu, nodes, lambda path, node: b'x')

    def chdir(self, value):
        self.mu.mem_write(0x3000, value.encode() + b'\0')
        return self.fs.request(12, [0x3000, 0, 0])['returned']

    def test_chdir(self):
        self.assertEqual(self.chdir('/usr/share/'), 0)
        self.assertEqual(self.fs.cwd, '/usr/share')
        self.assertEqual(self.chdir('/usr/missing'), 0xfffffffe)
        self.assertEqual(self.chdir('/lib/file'), 0xffffffec)
        self.assertEqual(self.fs.cwd, '/usr/share')  # failures leave cwd alone

    def test_relative_open_resolves_against_chdir_cwd(self):
        self.assertEqual(self.chdir('/lib'), 0)
        self.mu.mem_write(0x3000, b'file\0')
        opened = self.fs.request(5, [0x3000, 0, 0])
        self.assertIn(opened['returned'], self.fs.fds)
        self.assertEqual(opened['path'], '/lib/file')
        self.assertEqual(self.fs.fds[opened['returned']]['path'], '/lib/file')


if __name__ == '__main__':
    unittest.main()
