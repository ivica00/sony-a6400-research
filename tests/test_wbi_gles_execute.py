"""Original captured GLES query returns and guarded kernel/hardware boundaries."""
import struct
import unittest

from tools.research.wbi_gles_execute import CAPTURED_GRAPHICS_THREAD_INFO, OUTPUT, execute, load_context
from tools.research.wbi_gles_state import ROOT
from tools.research.wbi_pagewalk import read_virtual


class CapturedGlesExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from project_paths import PROJECT_ROOT
        if not (PROJECT_ROOT / 'artifacts/inventory/baseline.json').is_file():
            raise unittest.SkipTest('Local inventory/firmware not present')
        cls.context = load_context()

    def test_original_queries_and_kernel_copy_return_captured_values(self):
        context = self.context
        device = context['device']
        for command, offset in ((0x80048200, 0xec), (0x80048205, 0x104),
                                (0x80048206, 0x108), (0x8004820a, 0x48)):
            with self.subTest(command=hex(command)):
                expected = struct.unpack('<I', read_virtual(context['memory'], ROOT, device + offset, 4))[0]
                report = execute(context, command)
                self.assertEqual(report['status'], 'original_ioctl_return')
                self.assertEqual(report['return_register'], 0)
                self.assertEqual(report['output_word'], expected)
                self.assertEqual(report['writes'][0]['value'], expected)
                self.assertEqual(report['writes'][0]['pc'], context['putter'] + 12)
                self.assertEqual(report['service_returns_supplied'], 0)

    def test_original_address_limit_check_returns_efault_without_output_write(self):
        report = execute(self.context, 0x80048200, address_limit=OUTPUT + 3)
        self.assertEqual(report['status'], 'original_ioctl_return')
        self.assertEqual(report['return_register'], (-14) & 0xffffffff)
        self.assertEqual(report['output_word'], 0xa5a5a5a5)
        self.assertEqual(report['writes'], [])

    def test_original_noop_and_unknown_ioctl_return_without_touching_output(self):
        for command, expected in ((0x40048204, 0), (0, (-515) & 0xffffffff)):
            with self.subTest(command=hex(command)):
                report = execute(self.context, command)
                self.assertEqual(report['status'], 'original_ioctl_return')
                self.assertEqual(report['return_register'], expected)
                self.assertEqual(report['output_word'], 0xa5a5a5a5)
                self.assertEqual(report['writes'], [])

    def test_register_setup_executes_real_cache_callback_then_stops_at_hardware(self):
        report = execute(self.context)
        self.assertEqual(report['status'], 'unsupported_device_or_snapshot_write')
        self.assertEqual(report['boundary'], {'pc': 0x6011a5e8, 'address': 0xf8002730,
                                               'size': 4, 'value': 0})
        self.assertTrue(any(event['pc'] == self.context['sync'] for event in report['trace']))
        self.assertEqual(report['hardware_responses_supplied'], 0)
        self.assertEqual(report['writes'], [])

    def test_indexed_queries_execute_original_get_user_and_put_user(self):
        for command, index, expected in ((0xc0048201, 0, 0), (0xc0048201, 1, 0x4000),
                                          (0xc0048202, 0, 0x80000000), (0xc0048202, 1, 0xf1000000)):
            with self.subTest(command=hex(command), index=index):
                report = execute(self.context, command, input_word=index)
                self.assertEqual(report['status'], 'original_ioctl_return')
                self.assertEqual(report['return_register'], 0)
                self.assertEqual(report['output_word'], expected)
                self.assertTrue(any(event['pc'] == self.context['getter'] for event in report['trace']))

    def test_original_get_user_rejects_short_address_range(self):
        report = execute(self.context, 0xc0048202, input_word=1, address_limit=OUTPUT + 3)
        self.assertEqual(report['status'], 'original_ioctl_return')
        self.assertEqual(report['return_register'], (-14) & 0xffffffff)
        self.assertEqual(report['output_word'], 1)
        self.assertEqual(report['writes'], [])

    def test_submission_stops_before_consuming_unknown_current_kernel_task(self):
        report = execute(self.context, 0xc0048203, input_word=0x40000000)
        self.assertEqual(report['status'], 'unsupplied_kernel_stack_state')
        self.assertEqual(report['boundary']['address'], 0x0800000c)
        self.assertEqual(report['hardware_responses_supplied'], 0)
        self.assertEqual(report['writes'], [])

    def test_original_owner_lookup_matches_captured_list_and_absent_control(self):
        context = self.context
        node = struct.unpack('<I', read_virtual(context['memory'], ROOT, context['owner_head'], 4))[0]
        tgid = struct.unpack('<I', read_virtual(context['memory'], ROOT, node + 8, 4))[0]
        for selected, expected in ((tgid, node), (0xffffffff, 0)):
            with self.subTest(tgid=selected):
                report = execute(context, owner_tgid=selected)
                self.assertEqual(report['status'], 'original_owner_lookup_return')
                self.assertEqual(report['return_register'], expected)
                self.assertEqual(report['writes'], [])

    def test_user_input_padding_is_not_accepted_as_zero(self):
        report = execute(self.context, 0xc0048202, argument=OUTPUT + 4)
        self.assertEqual(report['status'], 'constructed_output_padding_read')
        self.assertEqual(report['writes'], [])

    def test_captured_open_runs_original_migration_before_lock_boundary(self):
        report = execute(self.context, open_thread_info=CAPTURED_GRAPHICS_THREAD_INFO)
        self.assertEqual(report['status'], 'unsupported_kernel_import')
        self.assertEqual(report['boundary']['symbol'], 'rt_spin_lock')
        self.assertTrue(any(event['pc'] == self.context['migrate'] for event in report['trace']))
        self.assertEqual(report['captured_task_control']['tgid'], 152)
        self.assertEqual(report['address_limit_control'], 0x5f000000)

    def test_original_captured_open_returns_with_retain_mutations_and_restored_locks(self):
        context = self.context
        report = execute(context, open_thread_info=CAPTURED_GRAPHICS_THREAD_INFO, follow_kernel_locks=True)
        self.assertEqual(report['status'], 'original_driver_open_return')
        self.assertEqual(report['return_register'], 0)
        self.assertEqual(report['file_private_word'], context['device'])
        self.assertEqual(report['service_returns_supplied'], 0)
        mutations = {item['start']: item for item in report['snapshot_mutations']}
        count = mutations[context['device'] + 0x40]
        self.assertEqual(struct.unpack_from('<I', bytes.fromhex(count['before_hex']))[0], 1)
        self.assertEqual(struct.unpack_from('<I', bytes.fromhex(count['after_hex']))[0], 2)
        owner = mutations[report['captured_task_control']['owner_entry'] + 12]
        self.assertEqual(owner['before_hex'], '01000000')
        self.assertEqual(owner['after_hex'], '02000000')
        for start, _ in context['lock_ranges']:
            self.assertEqual(mutations[start]['before_hex'], mutations[start]['after_hex'])
        # The source snapshot is immutable; mutations belong to this CPU instance.
        self.assertEqual(struct.unpack('<I', read_virtual(context['memory'], ROOT,
                                                          context['device'] + 0x40, 4))[0], 1)

    def test_captured_thread_info_must_be_aligned(self):
        with self.assertRaises(ValueError):
            execute(self.context, open_thread_info=CAPTURED_GRAPHICS_THREAD_INFO + 4)

    def test_nonowner_requires_explicit_allocation_policy(self):
        with self.assertRaises(ValueError):
            execute(self.context, open_thread_info=0x60a1c000)

    def test_new_owner_lifecycle_restores_allocator_and_list(self):
        from tools.research.wbi_gles_execute import new_owner_options
        report = execute(self.context, **new_owner_options(0x60a1c000), owner_lifecycle=True)
        self.assertEqual(report['status'], 'original_driver_release_return')
        self.assertEqual([c['operation'] for c in report['calls']], ['open', 'query', 'release'])
        self.assertEqual([c['returned'] for c in report['calls']], [0, 0, 0])
        self.assertEqual(report['calls'][1]['output_word'], 2)
        opened = {m['start']: bytes.fromhex(m['hex']) for m in report['calls'][0]['mutation_state']}
        self.assertEqual(struct.unpack('<I', opened[0x6940f000])[0], 65)
        self.assertEqual(struct.unpack_from('<2I', opened[0x68ad25a0], 8), (97, 1))
        self.assertEqual(report['service_returns_supplied'], 0)
        self.assertEqual(report['hardware_responses_supplied'], 0)
        mutations = {m['start']: m for m in report['snapshot_mutations']}
        for address in (self.context['device'] + 0x40, self.context['owner_head'], 0x6940f000):
            self.assertEqual(mutations[address]['before_hex'], mutations[address]['after_hex'])
        peer = mutations[0x68abdda0 + 0x14]
        self.assertEqual(peer['before_hex'][:8], '00000000')
        self.assertEqual(peer['after_hex'][:8], 'ffffff7f')

    def test_lifecycle_budget_stays_bounded(self):
        from tools.research.wbi_gles_execute import new_owner_options
        options = new_owner_options(0x60a1c000)
        options['instruction_budget'] = 1107
        report = execute(self.context, **options, owner_lifecycle=True)
        self.assertEqual(report['status'], 'instruction_budget_exhausted')
        self.assertLessEqual(len(report['trace']), 1107)


if __name__ == '__main__':
    unittest.main()
