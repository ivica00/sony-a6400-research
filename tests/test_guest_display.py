import struct
import unittest

from src.a6400.execution.guest_display import (
    ARGB8888, DEFAULT_SURFACE_ORDER, DISPLAY_SURFACES, DisplayModel,
    argb8888_to_rgba, decode_surface, display_contract, rgb565_to_rgba,
    rgba4444_to_rgba,
)


class TestDisplayDecoders(unittest.TestCase):
    def test_rgba4444_known_pixels(self):
        raw = struct.pack('<4H', 0xF00F, 0x0FFF, 0x0000, 0x1234)
        rgba = rgba4444_to_rgba(raw, 4, 1)
        self.assertEqual(rgba[0:4], bytes((255, 0, 0, 255)))
        self.assertEqual(rgba[4:8], bytes((0, 255, 255, 255)))
        self.assertEqual(rgba[8:12], bytes((0, 0, 0, 0)))
        self.assertEqual(rgba[12:16], bytes((17, 34, 51, 68)))

    def test_rgba4444_is_little_endian(self):
        # 0x0F00 little-endian is 00 0F; red nibble = 0, green = 15.
        self.assertEqual(rgba4444_to_rgba(b'\x00\x0f', 1, 1), bytes((0, 255, 0, 0)))

    def test_rgb565_known_pixels(self):
        raw = struct.pack('<4H', 0xF800, 0x07E0, 0x001F, 0xFFFF)
        rgba = rgb565_to_rgba(raw, 4, 1)
        self.assertEqual(rgba[0:4], bytes((255, 0, 0, 255)))
        self.assertEqual(rgba[4:8], bytes((0, 255, 0, 255)))
        self.assertEqual(rgba[8:12], bytes((0, 0, 255, 255)))
        self.assertEqual(rgba[12:16], bytes((255, 255, 255, 255)))

    def test_argb8888_memory_order(self):
        raw = bytes((0x33, 0x22, 0x11, 0x44))
        self.assertEqual(argb8888_to_rgba(raw, 1, 1), bytes((0x11, 0x22, 0x33, 0x44)))

    def test_rejects_short_and_long_buffers(self):
        with self.assertRaises(ValueError):
            rgba4444_to_rgba(b'\x00\x00', 2, 1)
        with self.assertRaises(ValueError):
            rgba4444_to_rgba(b'\x00\x00\x00\x00\x00\x00', 1, 1)
        with self.assertRaises(ValueError):
            decode_surface(DISPLAY_SURFACES['osd_a'], b'')

    def test_contract_names_surfaces_and_marks_hypothesis(self):
        contract = display_contract('camera-e0074-e0044')
        self.assertEqual(set(contract['surfaces']), {'osd_a', 'osd_b', 'sugilite_color0'})
        self.assertEqual(contract['surfaces']['osd_a']['format_source'], 'camera-documented')
        self.assertEqual(contract['surfaces']['osd_a']['role'], 'display')
        self.assertEqual(contract['surfaces']['sugilite_color0']['format_source'], 'evidence-hypothesis')
        self.assertEqual(contract['surfaces']['sugilite_color0']['role'], 'internal')
        with self.assertRaises(ValueError):
            display_contract('made-up-contract')
        self.assertEqual(display_contract('none')['surfaces'], {})


class TestDisplayModel(unittest.TestCase):
    def setUp(self):
        self.model = DisplayModel(display_contract('camera-e0074-e0044'))
        # gl_common mapped at a guest-chosen VA: the internal Sugilite buffer is
        # inside, the OSD display pools are not.
        self.ranges = self.model.register_mapping(
            0x50000000, 0x02000000, 0x202E0000, device='stream')

    def test_mapping_exposes_only_contained_surfaces(self):
        self.assertEqual([(start, end - start) for start, end in self.ranges],
                         [(0x50001000, DISPLAY_SURFACES['sugilite_color0'].byte_size)])
        mapped = {key for key, _, _ in self.model.mapped_surfaces()}
        self.assertEqual(mapped, {'sugilite_color0'})
        self.assertEqual(self.model.display_mapped(), [])
        self.assertIsNone(self.model.select())
        self.assertIsNone(self.model.surface_for_address(0x50000000))
        self.assertEqual(self.model.surface_for_address(0x50001000), 'sugilite_color0')

    def test_osd_display_surface_is_selected_and_has_provenance(self):
        model = DisplayModel(display_contract('camera-e0074-e0044'))
        model.register_mapping(0x40000000, 0x96000, 0x23A80000, device='stream')
        self.assertEqual(model.select()[0], 'osd_a')
        self.assertEqual(model.note_write(0x40000000, 4, pc=0x1234, tid=1042,
                                          instruction=99), 'osd_a')
        state = model.states['osd_a']
        self.assertEqual(state.count, 1)
        self.assertEqual(state.first_pc, 0x1234)
        self.assertEqual(state.last_tid, 1042)
        self.assertEqual(state.first_instruction, 99)

    def test_internal_buffer_is_not_a_display(self):
        surface = DISPLAY_SURFACES['sugilite_color0']
        raw = bytearray(surface.byte_size)
        struct.pack_into('<H', raw, 0, 0xF00F)
        self.model.note_write(0x50001000, 2, pc=0x2000, tid=1008, instruction=7)
        self.assertIsNone(self.model.select())
        self.assertIsNone(self.model.read_frame(lambda a, s: bytes(raw)))
        frame = self.model.read_frame(lambda a, s: bytes(raw), key='sugilite_color0')
        self.assertEqual(frame.surface.name, 'sugilite_color0')
        self.assertEqual(frame.surface.role, 'internal')
        self.assertEqual(frame.rgba[0:4], bytes((255, 0, 0, 255)))

    def test_read_frame_reports_written_content(self):
        model = DisplayModel(display_contract('camera-e0074-e0044'))
        model.register_mapping(0x40000000, 0x96000, 0x23A80000, device='stream')
        surface = DISPLAY_SURFACES['osd_a']
        raw = bytearray(surface.byte_size)
        struct.pack_into('<H', raw, 0, 0xF00F)
        model.note_write(0x40000000, 2, pc=0x2000, tid=1042, instruction=7)
        frame = model.read_frame(lambda address, size: bytes(raw), instruction=7)
        self.assertEqual(frame.status, 'written')
        self.assertEqual(frame.rgba[0:4], bytes((255, 0, 0, 255)))
        self.assertEqual(frame.provenance['first_pc'], 0x2000)
        self.assertEqual(frame.metadata()['surface'], 'osd_a')

    def test_unwritten_and_short_read(self):
        surface = DISPLAY_SURFACES['sugilite_color0']
        frame = self.model.read_frame(lambda a, s: bytes(surface.byte_size), key='sugilite_color0')
        self.assertEqual(frame.status, 'unwritten')
        with self.assertRaises(ValueError):
            self.model.read_frame(lambda a, s: b'\x00' * 4, key='sugilite_color0')

    def test_unmapped_model_returns_no_frame(self):
        model = DisplayModel(display_contract('camera-e0074-e0044'))
        self.assertIsNone(model.select())
        self.assertIsNone(model.read_frame(lambda a, s: b''))
        self.assertEqual(model.report()['mappings'], [])

    def test_checkpoint_state_round_trip(self):
        self.model.note_write(0x50001000, 2, pc=0x2000, tid=1008, instruction=7)
        state = self.model.to_state()
        restored = DisplayModel(display_contract('camera-e0074-e0044'))
        restored.from_state(state)
        self.assertEqual(restored.mappings[0].physical_start, 0x202E0000)
        self.assertEqual(restored.states['sugilite_color0'].count, 1)
        self.assertEqual(restored.states['sugilite_color0'].last_pc, 0x2000)

    def test_surface_order_default(self):
        self.assertEqual(DEFAULT_SURFACE_ORDER, ('osd_a', 'osd_b'))
        self.assertEqual(self.model.presentation_order, DEFAULT_SURFACE_ORDER)


if __name__ == '__main__':
    unittest.main()
