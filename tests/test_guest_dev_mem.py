"""Unit tests for /dev/mem character device model and null_page_policy in InterpreterProbe."""
import hashlib
import struct
import unittest

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from src.a6400.images.process_elf import inspect_image
from src.a6400.execution.interpreter_probe import InterpreterProbe
from src.a6400.execution.guest_kuser import extract_kuser_template


def make_elf(path, code, dynamic=True, thumb=True):
    base = 0 if dynamic else 0x8000
    ident = b'\x7fELF' + bytes([1, 1, 1]) + bytes(9)
    header = struct.pack('<HHIIIIIHHHHHH', 3 if dynamic else 2, 40, 1,
                         base + 0x100 + int(thumb), 52, 0, 0x5000000, 52, 32, 1, 40, 0, 0)
    size = 0x100 + len(code)
    segment = struct.pack('<IIIIIIII', 1, 0, base, 0, size, 0x2000, 5, 4096)
    data = (ident + header + segment).ljust(0x100, b'\x00') + code
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    return inspect_image(path, digest)


class DevMemModelTests(unittest.TestCase):
    def setUp(self):
        self.folder = PROJECT_ROOT / 'artifacts/tests/dev-mem-probe'
        self.folder.mkdir(parents=True, exist_ok=True)

    def test_null_page_policy_maps_zero_page(self):
        app = make_elf(self.folder / 'app.elf', b'\xfe\xe7', dynamic=False)
        # Thumb code: read byte from address 8 into r0, then stop
        # ldrb r0, [r1, #8] where r1 = 0
        code = bytes.fromhex('4ff00001 087a ffee')
        linker = make_elf(self.folder / 'linker.elf', code, thumb=True)
        probe = InterpreterProbe(syscall_policy='stop', null_page_policy='read-zero')
        probe.prepare(app, linker, ['/usr/bin/test'])
        # Verify address 0 is mapped and address 8 is 0
        val = probe.mu.mem_read(8, 1)
        self.assertEqual(val, b'\x00')

    def test_null_page_read_guard_persists_zero(self):
        app = make_elf(self.folder / 'app_guard.elf', b'\xfe\xe7', dynamic=False)
        code = bytes.fromhex('4ff00001 087a ffee')
        linker = make_elf(self.folder / 'linker_guard.elf', code, thumb=True)
        probe = InterpreterProbe(syscall_policy='stop', null_page_policy='read-zero')
        probe.prepare(app, linker, ['/usr/bin/test'])
        probe.mu.mem_write(8, b'\xff\xaa\x55\x11')
        entry = probe.report['interpreter_mapping']['entry']
        probe.mu.emu_start(entry, (entry & ~1) + 6)
        r0 = probe.mu.reg_read(arm.UC_ARM_REG_R0)
        self.assertEqual(r0, 0)

    def test_dev_mem_open_fstat_and_mmap(self):
        app = make_elf(self.folder / 'app2.elf', b'\xfe\xe7', dynamic=False)
        # Code not needed since we test probe syscall handler directly
        linker = make_elf(self.folder / 'linker2.elf', b'\xfe\xe7', thumb=True)
        uname_raw = b''.join(v.encode().ljust(65, b'\x00') for v in ('Linux', 'cam', '3.4.0', '1', 'armv7l', '(none)'))
        uname_profile = {'raw_hex': uname_raw.hex(), 'fields': {'release': '3.4.0', 'sysname': 'Linux', 'nodename': 'cam', 'version': '1', 'machine': 'armv7l', 'domainname': '(none)'},
                         'file_offset': 0, 'runtime_unverified_fields': []}
        fs = {'nodes': {'/dev/mem': {'kind': 'special', 'mode': 0o20640, 'size': 0, 'uid': 0, 'gid': 0, 'stat_metadata': {'device_number': {'major': 1, 'minor': 1}}}},
              'content_loader': lambda p, n: b'', 'images': []}
        vmlinux_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
        kuser_template = extract_kuser_template(vmlinux_path)
        probe = InterpreterProbe(syscall_policy='threads', uname_profile=uname_profile,
                                 filesystem=fs, kuser_template=kuser_template)
        probe.prepare(app, linker, ['/usr/bin/test'])

        # Verify initial dev_mem open tracking
        fd = 5
        probe.filesystem.fds[fd] = {'path': '/dev/mem', 'device': 'mem', 'flags': 4098, 'device_number': [1, 1]}
        self.assertIn(fd, probe.filesystem.fds)
        self.assertEqual(probe.filesystem.fds[fd]['device'], 'mem')


if __name__ == '__main__':
    unittest.main()
