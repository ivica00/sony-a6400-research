import hashlib
import struct
import unittest
from pathlib import Path

from src.a6400.debug import tree_deepcopy_model as model

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tools/native_camera/a6400_dbg_tree.c'
MANIFEST = ROOT / 'artifacts/native/e0407b1-tree/manifest.json'
MODULE = ROOT / 'artifacts/native/e0407b1-tree/final/a6400_dbg_tree.ko'

_ENGINE = None


def engine():
    global _ENGINE
    if _ENGINE is None:
        try:
            _ENGINE = model.TreeEngine()
        except Exception as exc:  # pragma: no cover - environment guard
            raise unittest.SkipTest(f'tree Unicorn engine unavailable: {exc}')
    return _ENGINE


def descriptors(data):
    found = []
    offset = 0
    while offset + 2 <= len(data):
        length = data[offset]
        if length < 2:
            break
        found.append((offset, length, data[offset + 1]))
        offset += length
    return found


class TreeStaticTests(unittest.TestCase):
    def test_payload_matches_current_source(self):
        if not model.PAYLOAD_PATH.is_file():
            self.skipTest(f'Local payload not present: {model.PAYLOAD_PATH}')
        self.assertTrue(model.PAYLOAD_PATH.is_file(), model.PAYLOAD_PATH)
        payload = model.payload()
        self.assertEqual(payload['source_sha256'], model.source_sha256(),
                         'regenerate tree_test_payload.json after editing the C source')
        for name in ('init_module', 'cleanup_module', 'tree_deepcopy',
                     'tree_append_vendor_interface', 'tree_free', 'tree_validate',
                     'tree_apply_patches', 'tree_restore_patches', 'tree_quiesce',
                     'tree_install_root', 'tree_restore_root', 'tree_unload'):
            self.assertIn(name, payload['symbols'])

    def test_source_keeps_corrected_speed_mapping_and_three_record_free(self):
        source = SOURCE.read_text(encoding='utf-8')
        # Corrected mapping: HIGH -> root+0x00, SUPER -> root+0x20, else +0x10.
        self.assertIn('speed == 5u ? 0x20u : (speed == 3u ? 0x00u : 0x10u)', source)
        self.assertNotIn('speed == 3u ? 0x10u', source)
        self.assertNotIn('speed == 5u ? 0x20u : (speed == 3u ? 0x10u', source)
        # Module-owned free must visit all three records (native omits +0x20).
        self.assertIn('free_record(root + 0x00u);', source)
        self.assertIn('free_record(root + 0x10u);', source)
        self.assertIn('free_record(root + 0x20u);', source)
        # Bounded counts, fail-closed range checks and the three patch targets.
        for token in ('A6400_MAX_INTERFACES', 'A6400_MAX_ENDPOINTS',
                      'A6400_MAX_LANGS', 'range_ok(', 'probe_kernel_write',
                      'A6400_OS_CRC_STOCK', 'tree_restore_patches',
                      'state->saved_os', 'A6400TREE LEAK', 'license=GPL',
                      '__kmalloc'):
            self.assertIn(token, source)

    def test_module_receipt_is_audited(self):
        if not MANIFEST.is_file() or not MODULE.is_file():
            self.skipTest(f'Local built module receipt not present: {MANIFEST}')
        self.assertTrue(MANIFEST.is_file(), MANIFEST)
        self.assertTrue(MODULE.is_file(), MODULE)
        import json
        receipt = json.loads(MANIFEST.read_text(encoding='utf-8'))
        self.assertEqual(receipt['audit'], 'ok')
        self.assertEqual(receipt['tree_audit'], 'ok')
        self.assertEqual(receipt['module_sha256'],
                         hashlib.sha256(MODULE.read_bytes()).hexdigest())
        self.assertEqual(receipt['vermagic'],
                         'vermagic=3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7 ')
        self.assertEqual(receipt['tree_source_sha256'],
                         hashlib.sha256(SOURCE.read_bytes()).hexdigest())
        for name in ('__kmalloc', 'kfree', 'memcpy', 'memset', 'printk',
                     'probe_kernel_read', 'probe_kernel_write'):
            self.assertIn(name, receipt['undefined_symbols'])
        self.assertLessEqual(set(receipt['tree_added_imports']),
                             {'printk', 'probe_kernel_read', 'probe_kernel_write'})


class UnicornTreeTests(unittest.TestCase):
    def setUp(self):
        self.e = engine()
        self.e.prepare()

    # -- pure tree logic --------------------------------------------
    def test_deepcopy_is_byte_identical_and_shares_no_pointer(self):
        e = self.e
        out_slot = 0x60000400
        rc = model.TreeEngine._signed(e.call('tree_deepcopy', model.ROOT, out_slot))
        self.assertEqual(rc, 0)
        clone = e.read_u32(out_slot)
        self.assertNotEqual(clone, model.ROOT)
        self.assertEqual(e.tree_view(clone), e.tree_view(model.ROOT))
        shared = e.tree_pointers(model.ROOT) & e.tree_pointers(clone)
        self.assertEqual(shared, set())
        for pointer in e.tree_pointers(clone):
            self.assertGreaterEqual(pointer, model.ALLOC_START)
            self.assertLess(pointer, model.ALLOC_END)
        self.assertEqual(len(e.alloc_order), 23)
        self.assertEqual(e.call('tree_validate', clone), 0)
        e.call('tree_free', clone)
        self.assertTrue(e.clean)
        self.assertEqual(len(e.frees), 23)
        self.assertEqual(len(e.allocs), 0)

    def test_deepcopy_rejects_corrupt_counts_without_leaks(self):
        e = self.e
        e.write_u8(model.ROOT + 0x05, 9)  # bNumConfigurations > A6400_MAX_CONFIGS
        out_slot = 0x60000400
        rc = model.TreeEngine._signed(e.call('tree_deepcopy', model.ROOT, out_slot))
        self.assertEqual(rc, -34)
        self.assertEqual(e.read_u32(out_slot), 0)
        self.assertTrue(e.clean)
        # Invalid serial pointer is refused before any allocation.
        e.prepare()
        e.write_u32(model.ROOT + 0x44, 0x1000)
        rc = model.TreeEngine._signed(e.call('tree_deepcopy', model.ROOT, out_slot))
        self.assertEqual(rc, -14)
        self.assertEqual(len(e.alloc_order), 0)

    def test_append_adds_vendor_interface_to_every_record(self):
        e = self.e
        out_slot = 0x60000400
        self.assertEqual(e.call('tree_deepcopy', model.ROOT, out_slot), 0)
        clone = e.read_u32(out_slot)
        self.assertEqual(len(e.alloc_order), 23)
        self.assertEqual(e.call('tree_append_vendor_interface', clone), 0)
        self.assertEqual(len(e.alloc_order), 29)   # 3 new arrays + 3 new alts
        self.assertEqual(len(e.frees), 3)          # 3 replaced interface arrays
        view = e.tree_view(clone)
        for slot in (0x00, 0x10, 0x20):
            config = view['records'][slot]['configs'][0]
            self.assertEqual(config['num_ifaces'], 2)
            self.assertEqual([item['number'] for item in config['interfaces']], [0, 1])
            vendor = config['interfaces'][1]
            self.assertEqual(len(vendor['alts']), 1)
            alt = vendor['alts'][0]
            self.assertEqual((alt['alt'], alt['ep_count'], alt['class'], alt['sub'],
                              alt['proto'], alt['iInterface'], alt['extra'],
                              alt['endpoints']), (0, 0, 0xFF, 0xDB, 0x01, 0, b'', []))
        self.assertEqual(e.call('tree_validate', clone), 0)
        # The source tree is untouched.
        self.assertEqual([cfg['num_ifaces'] for cfg in
                          e.tree_view(model.ROOT)['records'][0x00]['configs']], [1])
        e.call('tree_free', clone)
        self.assertTrue(e.clean)
        self.assertEqual(len(e.frees), 29)

    def test_append_rejects_used_interface_number(self):
        e = self.e
        e.write_u8(model.IFACE[0x00], 1)   # interface count 1, number 1
        rc = e.start()
        self.assertEqual(rc, -22)
        self.assertTrue(e.clean)
        self.assertEqual(e.installed_root(), model.ROOT)
        self.assertEqual(e.os_crc(), model.OS_CRC_STOCK)
        self.assertEqual(e.read_u8(e.gc + 0x84), 0)
        self.assertEqual(len(e.allocs), 0)

    # -- patches and swap ------------------------------------------
    def test_three_patches_apply_and_restore_exact_bytes(self):
        e = self.e
        stock = e.os_bytes()
        self.assertEqual(stock, model.OS_STRING_STOCK)
        self.assertEqual(e.os_crc(), model.OS_CRC_STOCK)
        self.assertEqual(e.read_u16(model.ROOT), 0x0200)
        self.assertEqual(e.start(), 0)
        clone = e.installed_root()
        self.assertNotEqual(clone, model.ROOT)
        self.assertEqual(e.installed_root(), clone)
        self.assertEqual(e.os_bytes(), model.OS_STRING_OS20)
        self.assertEqual(e.os_crc(), model.OS_CRC_OS20)
        self.assertEqual(e.read_u8(e.gc + 0x84), 1)
        self.assertEqual(e.read_u16(clone + 0x00), 0x0210)
        self.assertEqual(e.read_u16(clone + 0x10), 0x0110)
        self.assertEqual(e.read_u16(clone + 0x20), 0x0320)
        # The original kernel-owned tree is not modified at all.
        self.assertEqual(e.read_u16(model.ROOT + 0x00), 0x0200)
        self.assertEqual(e.run_cleanup(), 0)
        self.assertEqual(e.installed_root(), model.ROOT)
        self.assertEqual(e.os_bytes(), stock)
        self.assertEqual(e.os_crc(), model.OS_CRC_STOCK)
        self.assertEqual(e.read_u8(e.gc + 0x84), 0)
        self.assertEqual(e.read_u16(model.ROOT + 0x00), 0x0200)
        # The module clone was restored before it was freed.
        self.assertEqual(e.read_u16(clone + 0x00), 0x0200)
        self.assertTrue(e.clean)
        self.assertEqual(len(e.allocs), 0)

    def test_patch_prechecks_reject_nonstock_state(self):
        e = self.e
        e.prepare(mode=1)
        self.assertEqual(e.start(), -16)
        self.assertTrue(e.clean)
        self.assertEqual(e.installed_root(), model.ROOT)
        e.prepare(os_string=b'X' * 18)
        self.assertEqual(e.start(), -5)
        self.assertEqual(e.os_bytes(), b'X' * 18)
        self.assertEqual(len(e.alloc_order), 0)
        e.prepare(bcdusb=0x0210)
        self.assertEqual(e.start(), -22)
        self.assertEqual(e.read_u16(model.ROOT), 0x0210)
        self.assertEqual(len(e.alloc_order), 0)

    def test_patch_record_selection_follows_runtime_speed(self):
        e = self.e
        # FULL speed (2): builder selects root+0x10.
        e.prepare(speed=2)
        e.write_u16(model.ROOT + 0x10, 0x0200)
        self.assertEqual(e.start(), 0)
        clone = e.installed_root()
        self.assertEqual(clone + 0x10, e.state_u32(12))
        self.assertEqual(e.read_u16(clone + 0x10), 0x0210)
        self.assertEqual(e.read_u16(clone + 0x00), 0x0200)
        _, dev = e.run_device_desc(speed=2)
        self.assertEqual(struct.unpack_from('<H', dev, 2)[0], 0x0210)
        _, dev_hs = e.run_device_desc(speed=3)
        self.assertEqual(struct.unpack_from('<H', dev_hs, 2)[0], 0x0200)
        self.assertEqual(e.run_cleanup(), 0)
        # SUPER speed (5): builder selects root+0x20.
        e.prepare(speed=5)
        e.write_u16(model.ROOT + 0x20, 0x0200)
        self.assertEqual(e.start(), 0)
        clone = e.installed_root()
        self.assertEqual(clone + 0x20, e.state_u32(12))
        _, dev = e.run_device_desc(speed=5)
        self.assertEqual(struct.unpack_from('<H', dev, 2)[0], 0x0210)
        self.assertEqual(e.run_cleanup(), 0)
        self.assertTrue(e.clean)

    def test_root_swap_state_and_restore(self):
        e = self.e
        self.assertEqual(e.start(), 0)
        clone = e.installed_root()
        bss = e.bss_address()
        self.assertEqual(e.state_u32(0), e.gc)
        self.assertEqual(e.state_u32(4), model.ROOT)
        self.assertEqual(e.state_u32(8), clone)
        self.assertEqual(e.state_u32(12), clone + 0x00)
        self.assertEqual(e.state_u32(16), model.OS_CRC_STOCK)
        self.assertEqual(e.state_u16(20), 0x0200)
        self.assertEqual(e.state_u8(22), 3)
        self.assertEqual(e.state_u8(23), 0)
        self.assertEqual([e.state_u8(offset) for offset in (24, 25, 26, 27, 28)],
                         [1, 1, 1, 1, 1])
        self.assertEqual(e.read(bss + 32, 18), model.OS_STRING_STOCK)
        self.assertEqual(e.run_cleanup(), 0)
        self.assertEqual(e.state_u32(8), 0)
        self.assertEqual(e.state_u8(27), 0)
        self.assertEqual([e.state_u8(offset) for offset in (24, 25, 26)], [0, 0, 0])

    def test_restore_root_does_not_overwrite_app_tree(self):
        e = self.e
        self.assertEqual(e.start(), 0)
        self.assertNotEqual(e.installed_root(), model.ROOT)
        # The app's stop+start replaces gc+0x6c with its own tree.
        e.write_u32(e.gc + 0x6c, model.ROOT)
        self.assertEqual(e.run_cleanup(), 0)
        self.assertEqual(e.installed_root(), model.ROOT)
        self.assertEqual(e.os_crc(), model.OS_CRC_STOCK)
        self.assertTrue(e.clean)
        # The native stop ioctl can only free a tree after it cleared the
        # started bit itself; our install leaves bit 2 clear, so an app stop is
        # an early-return no-op and our clone is never kfree'd by native code.
        # Simulate a later app start+stop that leaves gc+0x6c == 0: the module
        # must free its detached clone and must not resurrect the old root.
        self.assertEqual(e.start(), 0)
        self.assertNotEqual(e.installed_root(), model.ROOT)
        e.write_u32(e.gc + 0x6c, 0)
        self.assertEqual(e.run_cleanup(), 0)
        self.assertEqual(e.installed_root(), 0)
        self.assertEqual(e.os_crc(), model.OS_CRC_STOCK)
        self.assertEqual(e.read_u8(e.gc + 0x84), 0)
        self.assertTrue(e.clean)
        self.assertEqual(len(e.allocs), 0)

    # -- quiesce ----------------------------------------------------
    def test_quiesce_order_and_gate_clear(self):
        e = self.e
        e.prepare(started=1, configured=1)
        self.assertEqual(e.read_u32(e.gc + 0x68) & 4, 4)
        self.assertEqual(e.read_u8(e.gc + 0x74), 1)
        self.assertEqual(e.start(), 0)
        self.assertEqual([call[0] for call in e.service_calls],
                         ['pullup', 'stop_disconnect', 'gcw_stop'])
        self.assertEqual(e.service_calls[0], ('pullup', model.GADGET, 0))
        self.assertEqual(e.service_calls[1], ('stop_disconnect', model.GC))
        self.assertEqual(e.read_u32(e.gc + 0x68) & 4, 0)
        self.assertEqual(e.read_u8(e.gc + 0x74), 0)
        self.assertEqual(e.read_u16(e.installed_root()), 0x0210)
        self.assertEqual(e.run_cleanup(), 0)
        self.assertTrue(e.clean)
        self.assertEqual(e.installed_root(), model.ROOT)

    def test_quiesce_failure_aborts_before_install(self):
        e = self.e
        e.prepare(started=1, configured=1, pullup_result=-5,
                  stop_disconnect_clears_config=False)
        self.assertEqual(e.start(), -5)
        self.assertEqual([call[0] for call in e.service_calls],
                         ['pullup', 'stop_disconnect', 'gcw_stop'])
        self.assertEqual(e.read_u32(e.gc + 0x68) & 4, 0)
        self.assertEqual(e.installed_root(), model.ROOT)
        self.assertEqual(e.os_crc(), model.OS_CRC_STOCK)
        self.assertEqual(e.read_u8(e.gc + 0x84), 0)
        self.assertEqual(len(e.allocs), 0)
        self.assertTrue(e.clean)

    # -- failure injection -----------------------------------------
    def test_allocation_failure_at_every_step_unwinds(self):
        e = self.e
        e.prepare()
        self.assertEqual(e.start(), 0)
        total = e.alloc_attempts
        self.assertEqual(total, 29)
        e.run_cleanup()
        for index in range(1, total + 1):
            rc = e.run_init(fail_at_alloc=index)
            self.assertLess(rc, 0, f'allocation {index} did not fail the module')
            self.assertTrue(e.clean, f'allocation {index} leaked {e.leaks}')
            self.assertEqual(e.installed_root(), model.ROOT, index)
            self.assertEqual(e.os_crc(), model.OS_CRC_STOCK, index)
            self.assertEqual(e.read_u8(e.gc + 0x84), 0, index)

    def test_write_failure_at_every_copy_and_patch_step_unwinds(self):
        e = self.e
        e.prepare()
        self.assertEqual(e.start(), 0)
        total = e.write_attempts
        self.assertGreaterEqual(total, 3)
        e.run_cleanup()
        for index in range(1, total + 1):
            rc = e.run_init(fail_at_write=index)
            self.assertLess(rc, 0, f'write {index} did not fail the module')
            self.assertTrue(e.clean, f'write {index} leaked {e.leaks}')
            self.assertEqual(e.installed_root(), model.ROOT, index)
            self.assertEqual(e.os_crc(), model.OS_CRC_STOCK, index)
            self.assertEqual(e.read_u8(e.gc + 0x84), 0, index)

    def test_double_init_and_double_cleanup_are_safe(self):
        e = self.e
        self.assertEqual(e.start(), 0)
        clone = e.installed_root()
        self.assertEqual(e.start(), -16)
        self.assertEqual(e.installed_root(), clone)
        self.assertEqual(e.run_cleanup(), 0)
        self.assertEqual(e.installed_root(), model.ROOT)
        frees = len(e.frees)
        self.assertEqual(e.run_cleanup(), 0)
        self.assertEqual(len(e.frees), frees)
        self.assertTrue(e.clean)

    def test_unsafe_unload_leaks_instead_of_freeing(self):
        e = self.e
        self.assertEqual(e.start(), 0)
        clone = e.installed_root()
        live = len(e.leaks)
        self.assertEqual(live, 26)
        # Host/app restarted the UDC and the pull-down cannot be proven.
        e.write_u32(e.gc + 0x68, 4)
        e.write_u8(e.gc + 0x74, 1)
        e.pullup_result = -5
        e.stop_disconnect_clears_config = False
        self.assertEqual(e.run_cleanup(), 0)
        self.assertEqual(e.installed_root(), clone)
        self.assertEqual(len(e.leaks), live)
        self.assertEqual(e.os_crc(), model.OS_CRC_STOCK)
        self.assertEqual(e.read_u8(e.gc + 0x84), 0)
        self.assertTrue(any('LEAK' in line for line in e.logs))

    # -- original serializer execution -----------------------------
    def test_served_device_descriptor_uses_corrected_record(self):
        e = self.e
        _, baseline = e.run_device_desc(speed=3)
        self.assertEqual(struct.unpack_from('<H', baseline, 2)[0], 0x0200)
        e.prepare()
        self.assertEqual(e.start(), 0)
        e.write_u8(e.gadget + 0x20, 3)
        length, device = e.run_device_desc(speed=3)
        self.assertEqual(length, 18)
        self.assertEqual(len(device), 18)
        self.assertEqual(struct.unpack_from('<H', device, 2)[0], 0x0210)
        self.assertEqual(device[4:7], bytes([0x00, 0x00, 0x00]))
        self.assertEqual(struct.unpack_from('<HH', device, 8), (0x054C, 0x0CAA))
        # The unpatched FULL/SUPER records still serve their own values.
        _, full = e.run_device_desc(speed=2)
        self.assertEqual(struct.unpack_from('<H', full, 2)[0], 0x0110)
        self.assertEqual(full[4:7], bytes([0xEF, 0x02, 0x01]))
        _, super_speed = e.run_device_desc(speed=5)
        self.assertEqual(struct.unpack_from('<H', super_speed, 2)[0], 0x0320)

    def test_served_config_grows_by_exactly_nine(self):
        e = self.e
        base_ret, base = e.run_config_desc(speed=3)
        self.assertEqual(base_ret, 32)
        self.assertEqual(base[4], 1)
        self.assertEqual(struct.unpack_from('<H', base, 2)[0], 32)
        e.prepare()
        self.assertEqual(e.start(), 0)
        ret, merged = e.run_config_desc(speed=3)
        self.assertEqual(ret, 41)
        self.assertEqual(struct.unpack_from('<H', merged, 2)[0], 41)
        self.assertEqual(merged[4], 2)
        self.assertEqual(merged[1], 2)
        self.assertEqual(merged[5], 1)
        self.assertEqual(ret - base_ret, 9)
        self.assertEqual(merged[9:32], base[9:32])       # interface 0 + endpoints
        self.assertEqual(merged[32:41], bytes([9, 4, 1, 0, 0, 0xFF, 0xDB, 0x01, 0]))
        kinds = [kind for _offset, _length, kind in descriptors(merged[:ret])]
        self.assertEqual(kinds, [2, 4, 5, 5, 4])
        vendor_offset = descriptors(merged[:ret])[4][0]
        self.assertEqual(vendor_offset + 9, ret)        # zero endpoints after it

    def test_string_descriptors_preserved_and_ms_os_gate(self):
        e = self.e
        base_ret, base = e.run_string_desc(index=1)
        base3_ret, base3 = e.run_string_desc(index=3)
        self.assertEqual(base_ret, 6)
        self.assertEqual(base[:6], bytes([6, 3, 0x41, 0, 0x42, 0]))
        # Before the mode patch the 0xEE string is refused (-ENODEV path).
        refused, _ = e.run_string_desc(index=0xEE)
        self.assertEqual(refused, -22)
        e.prepare()
        self.assertEqual(e.start(), 0)
        ret, string1 = e.run_string_desc(index=1)
        ret3, string3 = e.run_string_desc(index=3)
        self.assertEqual((ret, string1[:ret]), (base_ret, base[:base_ret]))
        self.assertEqual((ret3, string3[:ret3]), (base3_ret, base3[:base3_ret]))
        gate_ret, gate = e.run_string_desc(index=0xEE)
        self.assertEqual(gate_ret, 18)
        self.assertEqual(gate[:18], model.OS_STRING_OS20)


if __name__ == '__main__':
    unittest.main()
