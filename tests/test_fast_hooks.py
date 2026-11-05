import unittest
from src.a6400.execution.interpreter_probe import InterpreterProbe


class TestFastHooks(unittest.TestCase):
    def test_probe_initializes_with_fast_hook_mode(self):
        probe = InterpreterProbe(syscall_policy='stop', hook_mode='fast')
        self.assertEqual(probe.hook_mode, 'fast')

    def test_probe_invalid_hook_mode_raises(self):
        with self.assertRaises(ValueError):
            InterpreterProbe(syscall_policy='stop', hook_mode='invalid_mode')


if __name__ == '__main__':
    unittest.main()
