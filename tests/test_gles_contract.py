"""Original GLES prefixes stop before unsupplied kernel and cache effects."""
import unittest

from tools.research.gles_contract_trace import run


class GlesContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from project_paths import PROJECT_ROOT
        if not (PROJECT_ROOT / 'artifacts/inventory/elf-inventory.json').is_file():
            raise unittest.SkipTest('Local inventory/firmware not present')
        cls.report = run()

    def test_device_identity_and_original_open_prefix(self):
        identity = self.report['device_identity']
        self.assertEqual((identity['major'], identity['minor'], identity['count']), (248, 29, 1))
        opened = self.report['open_prefix']
        self.assertEqual(opened['status'], 'kernel_migrate_disable_boundary')
        self.assertEqual(len(opened['trace']), 5)
        self.assertEqual(opened['kernel_responses_supplied'], 0)

    def test_setup_stops_before_runtime_cache_callback_or_register_write(self):
        setup = self.report['register_setup_prefix']
        self.assertEqual(setup['status'], 'outer_cache_runtime_callback_boundary')
        self.assertEqual(setup['registers']['r4'], 0xffffffff)
        self.assertEqual(setup['registers']['r1'], 0xf10010c0)
        self.assertEqual(setup['kernel_responses_supplied'], 0)
        self.assertEqual(self.report['register_writes_executed'], 0)


if __name__ == '__main__':
    unittest.main()
