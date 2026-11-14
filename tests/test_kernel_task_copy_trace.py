"""Original Sony clone-copy routines with a source-backed user register frame."""
import struct
import unittest

from tools.research.kernel_task_copy_trace import CHILD_TI, execute, execute_area_prefix, observed_task_name
from src.a6400.execution.kernel_task_identity import UnsupportedKernelBinding
from tools.research.wbi_gles_execute import load_context
from tools.research.wbi_gles_state import ROOT
from tools.research.wbi_pagewalk import read_virtual


class KernelTaskCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from project_paths import PROJECT_ROOT
        if not (PROJECT_ROOT / 'artifacts/inventory/baseline.json').is_file():
            raise unittest.SkipTest('Local inventory/firmware not present')
        cls.context = load_context()

    def test_original_frame_copy_changes_only_child_r0_and_sp(self):
        report = execute(self.context)
        self.assertEqual(report['status'], 'original_thread_notifier_boundary')
        parent = list(struct.unpack('<18I', bytes.fromhex(report['parent_frame_hex'])))
        expected = parent.copy()
        expected[0], expected[13] = 0, report['user_stack_control']
        self.assertEqual(list(struct.unpack('<18I', bytes.fromhex(report['child_frame_hex']))), expected)
        self.assertEqual(report['copied_task_pid_tgid'], [358, 152])
        self.assertFalse(report['child_pid_allocated'])
        self.assertEqual(report['service_returns_supplied'], 0)

    def test_thread_info_preserves_limit_and_rebinds_task_pointer(self):
        report = execute(self.context)
        header = bytes.fromhex(report['copied_thread_info_hex'])
        self.assertEqual(struct.unpack_from('<I', header, 8)[0], report['parent']['address_limit'])
        self.assertEqual(struct.unpack_from('<I', header, 12)[0], 0x08300000)
        source = read_virtual(self.context['memory'], ROOT, report['parent']['thread_info'], 4)
        self.assertEqual(struct.unpack_from('<I', header)[0], struct.unpack('<I', source)[0] & ~2)

    def test_settls_copies_original_parent_r3_otherwise_inherits(self):
        for flags in (0, 0x3d0f00):
            report = execute(self.context, clone_flags=flags)
            context = bytes.fromhex(report['child_context_hex'])
            parent = bytes.fromhex(report['parent_frame_hex'])
            inherited = bytes.fromhex(report['copied_thread_info_hex'])
            tls = struct.unpack_from('<I', context, 0x60-0x1c)[0]
            expected = struct.unpack_from('<I', parent, 12)[0] if flags & 0x80000 else struct.unpack_from('<I', inherited, 0x60)[0]
            self.assertEqual(tls, expected)
            self.assertEqual(context[:0x20], bytes(0x20))
            self.assertEqual(struct.unpack_from('<I', context, 0x3c-0x1c)[0], CHILD_TI+0x1fb0)

    def test_budget_cannot_be_reset_between_copy_windows(self):
        report = execute(self.context, instruction_budget=201)
        self.assertEqual(report['status'], 'instruction_budget_exhausted')
        self.assertEqual(len(report['trace']), 201)

    def test_kernel_stack_residue_is_not_a_user_register_frame(self):
        with self.assertRaisesRegex(ValueError, 'user register context'):
            execute(self.context, thread_info=0x60a1c000)

    def test_child_user_stack_outside_parent_limit_is_refused(self):
        with self.assertRaises(UnsupportedKernelBinding) as error:
            execute(self.context, user_stack=0x7ff00000)
        self.assertEqual(error.exception.details['mismatches'][0]['reason'], 'user_range_outside_task_limit')

    def test_original_area_prefix_rejects_length_above_compiled_limit(self):
        report = execute_area_prefix(self.context, length=0x5f000001)
        self.assertEqual(report['status'], 'original_area_return')
        self.assertEqual(report['returned'], (-12) & 0xffffffff)
        self.assertEqual(report['callback_responses_supplied'], 0)

    def test_original_area_rejects_low_fixed_address_but_valid_length_needs_task_mm(self):
        bad = execute_area_prefix(self.context, length=4096, address=1, flags=0x12)
        self.assertEqual(bad['status'], 'original_area_return')
        self.assertEqual(bad['returned'], (-22) & 0xffffffff)
        valid = execute_area_prefix(self.context, length=4096)
        self.assertEqual(valid['status'], 'task_mm_callback_prerequisite')
        self.assertNotIn('returned', valid)

    def test_task_358_is_thread_infra0_and_task_356_is_grm_dn_vdf_if(self):
        reader = lambda a, n: read_virtual(self.context['memory'], ROOT, a, n)
        # Task 358 comm at 0x60a4a800 + 0x1e8 is THREAD_INFRA0
        comm_358 = observed_task_name(self.context, 0x60a4a800)
        self.assertEqual(comm_358['value'], 'THREAD_INFRA0')

        # Adjacent slab slot (+0x3e0): Task 356 at 0x60a4abe0
        comm_356 = observed_task_name(self.context, 0x60a4abe0)
        self.assertEqual(comm_356['value'], 'grm_dn_vdf_if')
        self.assertEqual(comm_356['source_address'], 0x60a4a800 + 0x5c8)

        # PID, TGID, and TASK_DEAD (0x40) state
        pid_356, tgid_356 = struct.unpack('<2I', reader(0x60a4abe0 + 0x104, 8))
        self.assertEqual(pid_356, 356)
        self.assertEqual(tgid_356, 152)
        state_356 = struct.unpack('<I', reader(0x60a4abe0, 4))[0]
        self.assertEqual(state_356, 0x40)

    def test_libobj_vdf_if_port_registers_queue_and_thread_name(self):
        from project_paths import PROJECT_ROOT
        libobj_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libObj.so'
        if not libobj_path.is_file():
            self.skipTest('libObj.so not available')
        data = libobj_path.read_bytes()
        # Literal pool for queue 0x0080003b at 0x70f314
        self.assertEqual(struct.unpack_from('<I', data, 0x70f314)[0], 0x0080003b)
        # Target string at 0xfd8860 is grm_dn_vdf_if
        self.assertEqual(data[0xfd8860:0xfd8860 + 14], b'grm_dn_vdf_if\0')

