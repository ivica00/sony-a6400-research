"""Opt-in --syscall-record-limit: bounded syscall/UIPC logs keep exact totals and counts."""
import io
import json
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import unicorn
from unicorn import arm_const as arm

from src.a6400.execution.capped_log import CappedLog
from src.a6400.execution.guest_checkpoint import save_checkpoint
from src.a6400.execution.guest_uipc import GuestUipc
from src.a6400.execution.interpreter_probe import InterpreterProbe
from test_guest_checkpoint import MockProbe
from tools.camera_link import BootLogger


class SyscallRecordCapTests(unittest.TestCase):
    def probe(self):
        return InterpreterProbe(syscall_policy='mmap', uname_profile={'raw_hex': bytes(390).hex()},
                                filesystem={'nodes': {}, 'content_loader': lambda *args: b''})

    def test_limit_keeps_last_records_with_exact_totals_and_counts(self):
        probe = self.probe()
        probe.uipc = GuestUipc()
        probe.set_record_limit(3)
        for name in ('open', 'read', 'open', 'mmap2', 'read'):
            probe.report['serviced_syscalls'].append({'syscall': name, 'returned': 0})
        for op in ('connect', 'snd_sync_direct', 'connect', 'connect', 'snd_sync_direct'):
            probe.uipc.transactions.append({'type': op})

        log = probe.report['serviced_syscalls']
        self.assertIsInstance(log, CappedLog)
        self.assertEqual([e['syscall'] for e in log], ['open', 'mmap2', 'read'])
        self.assertEqual(log.total, 5)
        self.assertEqual(log.counts, {'open': 2, 'read': 2, 'mmap2': 1})
        self.assertEqual(probe.uipc.transactions.total, 5)
        self.assertEqual(probe.uipc.transactions.counts, {'connect': 3, 'snd_sync_direct': 2})

        report = probe.report
        report['uipc'] = {'transactions': probe.uipc.transactions}  # as _finalize_report builds it
        probe.finalize_record_logs(report)
        self.assertEqual(report['syscall_record_limit'], 3)
        self.assertEqual(report['syscalls_dropped'], 2)
        self.assertEqual(report['uipc_transactions_dropped'], 2)
        self.assertEqual(report['syscall_name_counts'], {'open': 2, 'read': 2, 'mmap2': 1})
        self.assertEqual(report['uipc_op_counts'], {'connect': 3, 'snd_sync_direct': 2})
        self.assertIsInstance(report['serviced_syscalls'], list)
        self.assertEqual(len(report['uipc']['transactions']), 3)
        json.dumps(report)  # must serialise without the deque wrapper

    def test_restored_capped_log_finalizes_without_the_flag(self):
        # A checkpoint saved under a cap, resumed without --syscall-record-limit.
        probe = self.probe()
        probe.report['serviced_syscalls'] = pickle.loads(pickle.dumps(
            CappedLog([{'syscall': 'open'}] * 4, maxlen=2, count_key='syscall')))
        report = probe.report
        report['uipc'] = {'transactions': []}
        probe.finalize_record_logs(report)
        self.assertEqual(report['syscall_record_limit'], 2)
        self.assertEqual(report['syscalls_dropped'], 2)
        json.dumps(report)

    def test_no_limit_leaves_plain_lists(self):
        probe = self.probe()
        probe.uipc = GuestUipc()
        probe.set_record_limit(None)
        self.assertIsInstance(probe.report['serviced_syscalls'], list)
        self.assertIsInstance(probe.uipc.transactions, list)

    def test_capped_log_pickle_round_trip_keeps_totals(self):
        log = CappedLog([{'type': 'a'}, {'type': 'b'}], maxlen=2, count_key='type')
        log.append({'type': 'a'})
        restored = pickle.loads(pickle.dumps(log))
        self.assertIsInstance(restored, CappedLog)
        self.assertEqual(restored.maxlen, 2)
        self.assertEqual(restored.total, 3)
        self.assertEqual(restored.counts, {'a': 2, 'b': 1})
        self.assertEqual(list(restored), [{'type': 'b'}, {'type': 'a'}])

    def test_boot_logger_attached_before_cap_still_sees_every_syscall(self):
        # build_boot_session attaches BootLogger before experiment_ui_boot sets the cap.
        probe = self.probe()
        logger = BootLogger(log_interval=0, stream=io.StringIO())
        logger._on_syscall = mock.Mock()
        logger.attach(probe)
        probe.set_record_limit(3)
        for name in ('open', 'read', 'open', 'mmap2', 'read'):
            probe.report['serviced_syscalls'].append({'syscall': name})
        self.assertEqual(logger._on_syscall.call_count, 5)
        log = probe.report['serviced_syscalls']
        self.assertEqual(len(log), 3)
        self.assertEqual(log.total, 5)

    def test_checkpoint_with_boot_logger_attached_still_pickles(self):
        # The BootLogger wrapper holds a stream and the probe; only its plain contents may be saved.
        p1 = MockProbe()
        p1.mu.mem_map(0x10000, 0x2000, unicorn.UC_PROT_ALL)
        p1.mu.reg_write(arm.UC_ARM_REG_PC, 0x10004)
        BootLogger(log_interval=0, stream=io.StringIO()).attach(p1)
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertGreater(save_checkpoint(p1, Path(tmpdir) / 'boot-logger.ckpt'), 0)

    def test_wrap_keeps_existing_totals_when_rebounded(self):
        log = CappedLog(maxlen=10, count_key='syscall')
        for name in ('x', 'y', 'x'):
            log.append({'syscall': name})
        rebounded = CappedLog.wrap(log, 1, 'syscall')
        self.assertEqual(rebounded.total, 3)
        self.assertEqual(rebounded.counts, {'x': 2, 'y': 1})
        self.assertEqual(list(rebounded), [{'syscall': 'x'}])


if __name__ == '__main__':
    unittest.main()
