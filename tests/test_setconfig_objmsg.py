import struct
import unittest

from src.a6400.execution.mwf_objmsg import (
    build_setconfig_objmsg_image,
    SETCONFIG_CATEGORY,
    SETCONFIG_MESSAGE_ID,
    SETCONFIG_PARAM_ID,
)


class TestSetconfigObjMsgImage(unittest.TestCase):
    """E0328: emulated inbound SETCONFIG ObjMsg image (labelled experiment)."""

    def test_image_layout(self):
        obj = 0x579CE000
        image = build_setconfig_objmsg_image(obj)
        self.assertEqual(len(image), 0x80)
        self.assertEqual(int.from_bytes(image[0:4], 'little'), obj + 0x20)
        body = 0x20
        self.assertEqual(int.from_bytes(image[body + 4:body + 8], 'little'),
                         SETCONFIG_CATEGORY)
        self.assertEqual(int.from_bytes(image[body + 8:body + 12], 'little'),
                         SETCONFIG_MESSAGE_ID)
        self.assertEqual(SETCONFIG_CATEGORY, 0x6103)
        self.assertEqual(SETCONFIG_MESSAGE_ID, 0x0A4001)
        self.assertEqual(SETCONFIG_PARAM_ID, 0x1006)

    def test_body_offset_validation(self):
        with self.assertRaises(ValueError):
            build_setconfig_objmsg_image(0x1000, allocation_size=0x20,
                                         body_offset=0x20)
        with self.assertRaises(ValueError):
            build_setconfig_objmsg_image(0x1000, body_offset=0x11)
