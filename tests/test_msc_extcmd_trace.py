import struct
import unittest

from tools.research.msc_extcmd_trace import (
    link_arm_call, linked_window, original_text, original_thumb,
)


class OriginalInputTests(unittest.TestCase):
    def test_changed_binary_is_rejected_before_module_or_library_execution(self):
        for load in (lambda: original_text(b"changed input", "0" * 64),
                     lambda: original_thumb(b"changed input", "0" * 64, "function")):
            with self.subTest(load=load), self.assertRaisesRegex(ValueError, "identity mismatch"):
                load()


class ClosedCallGraphTests(unittest.TestCase):
    def test_binding_requires_the_exact_original_relocation_target(self):
        text = struct.pack("<I", 0xEBFFFFFE)
        for relocation in ({}, {0: {"type": 2, "symbol": "known"}},
                           {0: {"type": 28, "symbol": "other"}}):
            image = {"text": text, "relocations": relocation}
            with self.subTest(relocation=relocation), self.assertRaisesRegex(ValueError, "identity"):
                linked_window(image, 0x1000000, {0: ("known", 0x1001000)})

    def test_linked_arm_call_reaches_forward_and_backward_targets(self):
        place = 0x1001000
        for target in (0x1000100, 0x1800000):
            word = link_arm_call(0xEBFFFFFE, place, target)
            displacement = (word & 0xFFFFFF) << 2
            if displacement & 0x2000000:
                displacement -= 0x4000000
            self.assertEqual(place + 8 + displacement, target)

    def test_noncall_unaligned_and_out_of_range_bindings_are_rejected(self):
        for word, place, target in ((0xE1A00000, 0x1000, 0x2000),
                                     (0xEBFFFFFE, 0x1000, 0x2001),
                                     (0xEBFFFFFE, 0x1000, 0x4000000)):
            with self.subTest(target=target), self.assertRaises(ValueError):
                link_arm_call(word, place, target)
