import io
import unittest

from tools.camera_link import (
    ARM_SYSCALL_TABLE,
    BootLogger,
    BoundaryAnalyzer,
    decode_ioctl_cmd,
    format_boundary_report,
)


class TestCameraLinkAndBootLogger(unittest.TestCase):
    def test_decode_ioctl_cmd_hdmi_and_usb(self):
        hdmi_ioc = decode_ioctl_cmd(0xc0044801)
        self.assertEqual(hdmi_ioc['macro'], '_IOWR')
        self.assertEqual(hdmi_ioc['type_char'], 'H')
        self.assertEqual(hdmi_ioc['nr'], 1)
        self.assertEqual(hdmi_ioc['size'], 4)
        self.assertEqual(hdmi_ioc['formatted'], "_IOWR('H', 0x01, 4)")

        usb_ioc = decode_ioctl_cmd(0x4024e301)
        self.assertEqual(usb_ioc['macro'], '_IOW')
        self.assertEqual(usb_ioc['type_byte'], '0xe3')
        self.assertEqual(usb_ioc['nr'], 1)
        self.assertEqual(usb_ioc['size'], 36)

    def test_boundary_analyzer_resolves_libc_and_libinfrahdmi(self):
        analyzer = BoundaryAnalyzer()
        sample_report = {
            'status': 'syscall_boundary',
            'instructions_executed': 86810403,
            'syscall_responses_supplied': 1844,
            'boundary': {
                'interrupt': 2,
                'pc': 0x50296afc,
                'instruction_address': 0x50296af8,
                'thumb': False,
                'r7': 42,
                'arguments': [0x1817055c, 0, 0, 0],
            },
            'registers': {
                'r0': 0x1817055c,
                'r7': 42,
                'lr': 0x168ff839,
                'pc': 0x50296afc,
                'cpsr': 0x60000010,
            },
            'tls_observation': {'current_tid': 1022},
            'threads': {
                '1000': {'name': 'im.elf', 'state': 'waiting'},
                '1022': {'name': 'HDMI Dev Thread', 'state': 'running'},
            },
            'mappings': [
                {'address': 0x50200000, 'length': 0x120000, 'path': '/lib/libc-2.11.2.so', 'offset': 0},
                {'address': 0x168c0000, 'length': 0x60000, 'path': '//usr/lib/libInfraHdmi.so', 'offset': 0},
            ],
        }
        analysis = analyzer.analyze_report(sample_report)
        self.assertEqual(analysis['syscall']['name'], 'pipe')
        self.assertEqual(analysis['active_thread']['tid'], 1022)
        self.assertEqual(analysis['active_thread']['name'], 'HDMI Dev Thread')
        self.assertEqual(analysis['pc_location']['guest_path'], '/lib/libc-2.11.2.so')
        self.assertEqual(analysis['pc_location']['offset'], '0x96af8')
        self.assertIn('__pipe', analysis['pc_location']['symbol'] or '')
        self.assertEqual(analysis['lr_caller']['guest_path'], '//usr/lib/libInfraHdmi.so')
        self.assertEqual(analysis['lr_caller']['offset'], '0x3f838')
        self.assertIn('DeviceThread', analysis['lr_caller']['symbol'] or '')

        formatted = format_boundary_report(analysis)
        self.assertIn('sys_pipe(int pipefd[2])', formatted)
        self.assertIn('HDMI Dev Thread', formatted)

    def test_boot_logger_captures_milestones(self):
        buf = io.StringIO()
        logger = BootLogger(log_interval=0, stream=buf)

        class DummyProbe:
            instructions = 12500000
            report = {'serviced_syscalls': []}

        probe = DummyProbe()
        logger.attach(probe)

        probe.report['serviced_syscalls'].append({
            'syscall': 'open', 'r7': 5, 'path': '/usr/lib/libInfraHdmi.so', 'returned': 15
        })
        probe.report['serviced_syscalls'].append({
            'syscall': 'init_module', 'r7': 128, 'path': '/usr/kmod/hdmi.ko', 'length': 238744, 'returned': 0
        })
        probe.report['serviced_syscalls'].append({
            'syscall': 'open', 'r7': 5, 'path': '/dev/hdmi', 'returned': 16, 'device_number': [248, 25]
        })
        probe.report['serviced_syscalls'].append({
            'syscall': 'ioctl', 'r7': 54, 'fd': 16, 'path': '/dev/hdmi', 'cmd': 0xc0044801, 'returned': 0
        })
        # Duplicate ioctl should be suppressed by BootLogger
        probe.report['serviced_syscalls'].append({
            'syscall': 'ioctl', 'r7': 54, 'fd': 16, 'path': '/dev/hdmi', 'cmd': 0xc0044801, 'returned': 0
        })

        self.assertEqual(len(logger.events), 4)
        output = buf.getvalue()
        self.assertIn('Loaded shared library /usr/lib/libInfraHdmi.so', output)
        self.assertIn('Authenticated & initialized /usr/kmod/hdmi.ko', output)
        self.assertIn('Opened device /dev/hdmi (major=248, minor=25)', output)
        self.assertIn("First /dev/hdmi ioctl 0xc0044801 (_IOWR('H', 0x01, 4))", output)


if __name__ == '__main__':
    unittest.main()
