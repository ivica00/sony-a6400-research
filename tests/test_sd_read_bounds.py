"""Constructed ARM code checks isolation, unknown state and bounded stops."""
import unittest
from tools.research.sd_read_bounds import execute, STATE


class SdReadBoundsTests(unittest.TestCase):
    def test_unknown_state_is_not_backing_poison(self):
        result = execute(bytes.fromhex('000090e5'), 0, 1, 1024)  # ldr r0,[r0]
        self.assertEqual(result['status'], 'unsupplied_runtime_read')
        self.assertEqual(result['boundary']['address'], STATE)

    def test_state_writes_are_forbidden(self):
        result = execute(bytes.fromhex('001080e5'), 0, 1, 1024)  # str r1,[r0]
        self.assertEqual(result['status'], 'unsupported_write')

    def test_unlinked_instructions_stop_before_execution(self):
        result = execute(bytes.fromhex('0700a0e31eff2fe1'), 0, 1, 1024, relocation_offsets=(0,))
        self.assertEqual(result['status'], 'unresolved_relocation')
        self.assertEqual(result['trace_offsets'], [])

    def test_return_and_loop_have_distinct_outcomes(self):
        result = execute(bytes.fromhex('0700a0e31eff2fe1'), 0, 1, 1024)
        self.assertEqual(result['status'], 'isolated_return')
        self.assertEqual(result['boundary']['result'], 7)
        self.assertEqual(execute(bytes.fromhex('feffffea'), 0, 1, 1024)['status'], 'instruction_limit')

    def test_extra_original_window_retains_state_and_relocation_guards(self):
        # b CODE+0x2000; external original window must not grant data state.
        branch = bytes.fromhex('fe0700ea')
        result = execute(branch, 0, 1, 1024, extra_windows=((0x2000, bytes.fromhex('000090e5'), ()),))
        self.assertEqual(result['status'], 'unsupplied_runtime_read')
        result = execute(branch, 0, 1, 1024, extra_windows=((0x2000, bytes.fromhex('0700a0e3'), (0,)),))
        self.assertEqual(result['status'], 'unresolved_relocation')
        with self.assertRaises(ValueError):
            execute(branch, 0, 1, 1024, extra_windows=((0, branch, ()),))

    def test_card_reference_supplies_pointer_and_reaches_relocation(self):
        # ldr r0, [r0]; bl target(relocated)
        code = bytes.fromhex('000090e5000000eb')
        result_without_ref = execute(code, 0, 1, 1024, relocation_offsets=(4,), card_reference=False)
        self.assertEqual(result_without_ref['status'], 'unsupplied_runtime_read')
        self.assertEqual(result_without_ref['boundary']['address'], STATE)

        result_with_ref = execute(code, 0, 1, 1024, relocation_offsets=(4,), card_reference=True)
        self.assertEqual(result_with_ref['status'], 'unresolved_relocation')
        self.assertEqual(result_with_ref['trace_offsets'], [0])

