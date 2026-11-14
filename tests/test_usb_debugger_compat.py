"""Tests for per-body native USB debugger compatibility registry and checks."""
from pathlib import Path
import unittest

from src.a6400.targets.usb_debugger_compat import (
    get_debugger_target,
    list_debugger_targets,
    load_reference_usb_extcmd,
    verify_camera_debugger_compatibility,
)

ROOT = Path(__file__).resolve().parents[1]
ILCE_7C_PULL = ROOT / "artifacts/hardware/ilce-7c-2.00-pull"


class TestUsbDebuggerCompat(unittest.TestCase):
    def test_registry_lists_qualified_targets(self):
        targets = list_debugger_targets()
        self.assertIn("ilce_6400", targets)
        self.assertIn("ilce_7c", targets)
        self.assertEqual(get_debugger_target("ILCE-7C").target_id, "ilce_7c")

    def test_unknown_target_raises(self):
        with self.assertRaises(KeyError):
            get_debugger_target("ilce_9999")

    @unittest.skipUnless(
        (ILCE_7C_PULL / "usb_extcmd.ko").is_file()
        and (ILCE_7C_PULL / "libusbcmd.so").is_file(),
        "ILCE-7C 2.00 pull fixtures not present",
    )
    def test_ilce_7c_live_pull_is_compatible_and_rejects_mutations(self):
        spec = get_debugger_target("ilce_7c")
        actual_ko = (ILCE_7C_PULL / "usb_extcmd.ko").read_bytes()
        actual_lib = (ILCE_7C_PULL / "libusbcmd.so").read_bytes()
        _, ref_ko = load_reference_usb_extcmd(spec, ROOT)

        ok = verify_camera_debugger_compatibility(spec, actual_ko, actual_lib, ref_ko)
        self.assertTrue(ok["compatible"], ok)
        self.assertTrue(ok["libusbcmd_match"])
        self.assertTrue(ok["usb_extcmd_match"])
        self.assertTrue(ok["exact_usb_extcmd_match"])
        self.assertIsNone(ok["reason"])

        # Also works without a local reference file (e.g. fresh clone without proprietary pulls)
        ok_no_ref = verify_camera_debugger_compatibility(spec, actual_ko, actual_lib, None)
        self.assertTrue(ok_no_ref["compatible"], ok_no_ref)

        # Mutate a libusbcmd.so byte -> must fail
        bad_lib = bytearray(actual_lib)
        bad_lib[0] ^= 0xFF
        fail_lib = verify_camera_debugger_compatibility(spec, actual_ko, bytes(bad_lib), ref_ko)
        self.assertFalse(fail_lib["compatible"])
        self.assertFalse(fail_lib["libusbcmd_match"])
        self.assertIn("libusbcmd.so mismatch", fail_lib["reason"])

        # Mutate a code/header byte in usb_extcmd.ko -> must fail
        bad_ko = bytearray(actual_ko)
        bad_ko[100] ^= 0xFF
        fail_ko = verify_camera_debugger_compatibility(spec, bytes(bad_ko), actual_lib, ref_ko)
        self.assertFalse(fail_ko["compatible"])
        self.assertFalse(fail_ko["usb_extcmd_match"])
        self.assertIn("usb_extcmd.ko mismatch", fail_ko["reason"])


if __name__ == "__main__":
    unittest.main()
