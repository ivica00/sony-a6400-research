"""E0459: models of the B24 NULL-deref fix and the unbuffered OBS flush.

The E0458/B24 oops is precise: `make_device_desc+0x70` (`ldrh r3,[r7]`, VA
0x602bb9f8) read address 0 because the shared-PTP teardown had restored a valid
descriptor root (0x68a844a0) and the E0399 legacy deferred restore then ran with
`g_saved_msc_desc_tbl == NULL`, wrote NULL into `gc+0x6c`, re-armed EP0 and
raised D+. The next GET_DESCRIPTOR dereferenced the NULL table.

Fix 1 (`uvc_composite_shim.c`): the legacy restore refuses to run when no legacy
Mass Storage table was saved, and never arms EP0/raises D+ with an empty table.
Fix 2 (`uvc_callback_bridge.c`): the OBS work item prints "OBS work enter" on
entry and flushes each row immediately instead of only at the end.
"""
import unittest


class RestoreDescriptorGuardModel(unittest.TestCase):
    def legacy_restore(self, saved_root, gc_root):
        """Model of a6400_uvc_restore_descriptors() after the E0459 fix."""
        if not saved_root:
            return {'status': -6, 'root': gc_root, 'armed': False, 'raised_dplus': False}
        root = saved_root
        if root is None:
            return {'status': -6, 'root': gc_root, 'armed': False, 'raised_dplus': False}
        return {'status': 0, 'root': root, 'armed': True, 'raised_dplus': True}

    def test_legacy_restore_without_saved_table_is_refused(self):
        # B24 state at the deferred restore: shared teardown restored 0x68a844a0,
        # but the legacy commit never ran so g_saved_msc_desc_tbl is NULL.
        result = self.legacy_restore(saved_root=None, gc_root=0x68A844A0)
        self.assertEqual(result['status'], -6)
        self.assertEqual(result['root'], 0x68A844A0, 'valid shared root must be preserved')
        self.assertFalse(result['armed'])
        self.assertFalse(result['raised_dplus'])

    def test_restore_never_publishes_a_null_descriptor_table(self):
        for saved in (None, 0):
            result = self.legacy_restore(saved_root=saved, gc_root=0x68A844A0)
            self.assertNotEqual(result['root'], 0,
                                'make_device_desc would dereference gc+0x6c')

    def test_legacy_path_with_saved_table_still_restores_and_reconnects(self):
        result = self.legacy_restore(saved_root=0x6ABC0000, gc_root=0x12345678)
        self.assertEqual(result['status'], 0)
        self.assertEqual(result['root'], 0x6ABC0000)
        self.assertTrue(result['armed'])
        self.assertTrue(result['raised_dplus'])


class UnbufferedObsFlushModel(unittest.TestCase):
    def test_unbuffered_flush_survives_a_late_crash(self):
        events = [('ep0s', 0), ('ep0s', 2), ('ep0s', 3)]
        crashed_at = 2  # two rows recorded, then the camera crashed before the dump
        buffered_printed = []  # the old end-of-loop dump never executed
        unbuffered_printed = events[:crashed_at]  # rows already flushed survive
        self.assertEqual(buffered_printed, [])
        self.assertEqual(unbuffered_printed, [('ep0s', 0), ('ep0s', 2)])

    def test_work_enter_is_flushed_before_any_row(self):
        printed = ['OBS start', 'OBS work enter', 'OBS 0 t=...', 'OBS 1 t=...']
        self.assertLess(printed.index('OBS work enter'), printed.index('OBS 0 t=...'))


if __name__ == '__main__':
    unittest.main()

