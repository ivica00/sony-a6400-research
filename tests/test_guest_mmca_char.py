import struct
import unittest

from src.a6400.execution.guest_mmca_char import (
    GuestMmcChar,
    MMC_CHAR_IOCTL_GET_CARD_TYPE,
    MMC_CHAR_IOCTL_GET_TRC_AREA,
    MMC_CHAR_IOCTL_MOUNT,
    MMC_CHAR_IOCTL_SET_TRC_AREA,
    MMC_CHAR_IOCTL_UNMOUNT,
    MS_CHAR_IOCTL_MOUNT,
    MS_CHAR_IOCTL_SET_ERRLOG_AREA,
    UnsupportedMmcChar,
    minor_to_hwid,
)


class TestGuestMmcChar(unittest.TestCase):
    def test_minor_to_hwid_mapping(self):
        self.assertEqual(minor_to_hwid(0), 0)
        self.assertEqual(minor_to_hwid(10), 0)
        self.assertEqual(minor_to_hwid(29), 0)
        self.assertEqual(minor_to_hwid(1), 1)
        self.assertEqual(minor_to_hwid(30), 1)
        self.assertEqual(minor_to_hwid(2), 2)
        self.assertEqual(minor_to_hwid(50), 2)
        self.assertEqual(minor_to_hwid(99), 0)

    def test_open_and_close_mmc_and_ms_nodes(self):
        drv = GuestMmcChar()
        h0 = drv.open(flags=0xa0002, pid=1004, tgid=1000, path='/dev/mmca-char')
        self.assertEqual((h0['major'], h0['minor'], h0['hwid']), (250, 0, 0))
        self.assertEqual(drv.close(h0['owner_id']), 0)

        h1 = drv.open(flags=0xa0002, pid=1004, tgid=1000, path='/dev/mmcb-char')
        self.assertEqual((h1['major'], h1['minor'], h1['hwid']), (250, 1, 1))
        self.assertEqual(drv.close(h1['owner_id']), 0)

        h2 = drv.open(flags=0xa0002, pid=1004, tgid=1000, path='/dev/mmcc-char')
        self.assertEqual((h2['major'], h2['minor'], h2['hwid']), (250, 2, 2))
        self.assertEqual(drv.close(h2['owner_id']), 0)

        hms = drv.open(flags=0xa0002, pid=1004, tgid=1000, path='/dev/ms-char')
        self.assertEqual((hms['major'], hms['minor']), (249, 0))
        self.assertEqual(drv.close(hms['owner_id']), 0)

    def test_mmc_trc_set_and_get_area_contract(self):
        drv = GuestMmcChar()
        oid = drv.open(flags=0xa0002, pid=1004, tgid=1000, path='/dev/mmca-char')['owner_id']
        mem = bytearray(256)

        def reader(addr, sz):
            return bytes(mem[addr:addr + sz])

        def writer(addr, data):
            mem[addr:addr + len(data)] = data

        # Valid 64-byte aligned trace area: phys=0x20030800, size=0x400
        struct.pack_into('<iii', mem, 0x20, -1, 0x20030800, 0x400)
        self.assertEqual(drv.ioctl(oid, MMC_CHAR_IOCTL_SET_TRC_AREA, 0x20, reader, writer), 0)
        status, phys, size = struct.unpack_from('<iii', mem, 0x20)
        self.assertEqual((status, phys, size), (0, 0x20030800, 0x400))
        self.assertEqual(drv.trc_areas[0], {'phys_addr': 0x20030800, 'size': 0x400})

        # Read back via MMC_CHAR_IOCTL_GET_TRC_AREA (0x03)
        struct.pack_into('<II', mem, 0x40, 0, 0)
        self.assertEqual(drv.ioctl(oid, MMC_CHAR_IOCTL_GET_TRC_AREA, 0x40, reader, writer), 0)
        self.assertEqual(struct.unpack_from('<II', mem, 0x40), (0x20030800, 0x400))

        # Unaligned size ((size & 0x3f) != 0) writes status = -3 (0xfffffffd)
        struct.pack_into('<iii', mem, 0x60, 0, 0x20030800, 0x120)
        self.assertEqual(drv.ioctl(oid, MMC_CHAR_IOCTL_SET_TRC_AREA, 0x60, reader, writer), 0)
        bad_status, _, _ = struct.unpack_from('<iii', mem, 0x60)
        self.assertEqual(bad_status, -3)

    def test_mmc_mount_unmount_and_card_type(self):
        drv = GuestMmcChar(card_present=True)
        oid = drv.open(flags=2, pid=1004, tgid=1000, path='/dev/mmca-char')['owner_id']
        mem = bytearray(128)

        def reader(addr, sz):
            return bytes(mem[addr:addr + sz])

        def writer(addr, data):
            mem[addr:addr + len(data)] = data

        self.assertEqual(drv.ioctl(oid, MMC_CHAR_IOCTL_MOUNT, 0x10, reader, writer), 0)
        self.assertTrue(drv.mounted[0])
        self.assertEqual(struct.unpack_from('<i', mem, 0x10)[0], 0)

        self.assertEqual(drv.ioctl(oid, MMC_CHAR_IOCTL_GET_CARD_TYPE, 0x20, reader, writer), 0)
        self.assertEqual(mem[0x20], 0)

        self.assertEqual(drv.ioctl(oid, MMC_CHAR_IOCTL_UNMOUNT, 0x10, reader, writer), 0)
        self.assertFalse(drv.mounted[0])

    def test_ms_char_errlog_area_and_mount(self):
        drv = GuestMmcChar()
        oid = drv.open(flags=0xa0002, pid=1004, tgid=1000, path='/dev/ms-char')['owner_id']
        mem = bytearray(128)

        def reader(addr, sz):
            return bytes(mem[addr:addr + sz])

        def writer(addr, data):
            mem[addr:addr + len(data)] = data

        struct.pack_into('<iii', mem, 0x10, -1, 0x20030400, 0x400)
        self.assertEqual(drv.ioctl(oid, MS_CHAR_IOCTL_SET_ERRLOG_AREA, 0x10, reader, writer), 0)
        self.assertEqual(struct.unpack_from('<i', mem, 0x10)[0], 0)
        self.assertEqual(drv.ms_errlog_area, {'phys_addr': 0x20030400, 'size': 0x400})

        self.assertEqual(drv.ioctl(oid, MS_CHAR_IOCTL_MOUNT, 0x30, reader, writer), 0)
        self.assertEqual(struct.unpack_from('<I', mem, 0x30)[0], 0xfffffff7)

    def test_unknown_ioctl_raises(self):
        drv = GuestMmcChar()
        oid = drv.open(flags=2, pid=1004, tgid=1000, path='/dev/mmca-char')['owner_id']
        with self.assertRaises(UnsupportedMmcChar):
            drv.ioctl(oid, 0xdeadbeef, 0x10, lambda a, s: b'\x00' * s, lambda a, d: None)


if __name__ == '__main__':
    unittest.main()
