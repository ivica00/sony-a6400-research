"""RunSummary: uncapped aggregates fed through the capped logs' observer hook."""
import json
import unittest

from src.a6400.execution.guest_uipc import GuestUipc
from src.a6400.execution.interpreter_probe import InterpreterProbe


class RunSummaryTests(unittest.TestCase):
    def test_aggregates_survive_the_record_cap(self):
        probe = InterpreterProbe(syscall_policy='mmap', uname_profile={'raw_hex': bytes(390).hex()},
                                 filesystem={'nodes': {}, 'content_loader': lambda *args: b''})
        probe.uipc = GuestUipc()
        probe.filesystem.fds[7] = {'path': '/dev/foo'}
        probe.set_record_limit(2)
        log, tx = probe.report['serviced_syscalls'], probe.uipc.transactions
        probe.instructions = 100
        enoent = 0xFFFFFFFE
        log.append({'syscall': 'open', 'path': '/a', 'returned': enoent})
        probe.instructions = 200
        log.append({'syscall': 'open', 'path': '/a', 'returned': 5})
        log.append({'syscall': 'stat64', 'path': '/a', 'returned': 0})
        log.append({'syscall': 'ioctl', 'fd': 7, 'cmd': 0x80000005, 'returned': 0})
        log.append({'syscall': 'mmap2', 'arguments': [0, 4096, 3, 2, 7, 0], 'returned': 0x1000,
                    'mapping': {'path': '/lib/x.so'}})
        log.append({'syscall': 'mmap2', 'arguments': [0, 100, 3, 34, 0xFFFFFFFF, 0], 'returned': 0x9000})
        log.append({'syscall': 'munmap', 'arguments': [0x1000, 4096], 'returned': 0})
        log.append({'syscall': 'clone', 'returned': 1050})
        log.append({'syscall': 'ioctl', 'fd': 7, 'cmd': 'FIOCLEX', 'returned': 0})  # non-int cmd must not raise
        log.append({'syscall': 'mmap2', 'arguments': 'bad'})  # malformed: counted as observer error
        probe.uipc.message_queues[0x10] = [1, 2, 3]
        tx.append({'type': 'snd_msg', 'queue': 0x10, 'consumed_by': 'k.ko'})
        tx.append({'type': 'snd_sync_msg', 'target_queue': 0x10})
        tx.append({'type': 'sync_cb_delivery', 'queue': 0x20})
        tx.append({'type': 'valloc'})
        report = probe.report
        report['uipc'] = {'transactions': tx}
        probe.finalize_record_logs(report)
        s = report['summary']
        json.dumps(s)
        self.assertEqual(len(report['serviced_syscalls']), 2)  # capped list unchanged
        self.assertEqual(s['syscalls']['open'], {'count': 2, 'errnos': {'ENOENT': 1}})
        self.assertEqual(s['opens']['open /a'], {'count': 2, 'results': {'ENOENT': 1, 'fd': 1},
                                                 'first_instruction': 100, 'last_instruction': 200})
        self.assertEqual(s['opens']['stat64 /a']['results'], {'ok': 1})
        self.assertEqual(s['ioctls']['/dev/foo 0x80000005'], {'count': 1, 'results': {'ok': 1}})
        self.assertEqual(s['mmaps']['/lib/x.so'], {'count': 1, 'bytes': 4096, 'first_instruction': 200,
                                                   'munmaps': 1, 'munmap_bytes': 4096})
        self.assertEqual(s['mmaps']['[anon]']['bytes'], 100)
        self.assertEqual(s['threads']['None']['syscalls'], 10)
        self.assertEqual(s['threads']['None']['created_at'], None)
        self.assertEqual(s['uipc']['ops']['0x10 snd_msg']['count'], 1)
        self.assertEqual(s['uipc']['ops']['0x10 snd_sync_msg']['count'], 1)
        self.assertEqual(s['uipc']['ops']['- valloc']['count'], 1)
        self.assertEqual(s['uipc']['by_op']['sync_cb_delivery'], 1)
        self.assertEqual(s['uipc']['queue_max_depth'], {'0x10': 3})
        self.assertEqual(s['uipc']['kernel_consumed'], {'0x10 k.ko': 1})
        self.assertEqual(s['observer_errors'], 1)


if __name__ == '__main__':
    unittest.main()
