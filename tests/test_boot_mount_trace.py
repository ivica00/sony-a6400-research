"""Tests for boot mount selection and device node resolution."""
import unittest

from tools.research.boot_mount_trace import (
    encode_st_dev,
    parse_devno_table,
    parse_init_mounts,
    trace_boot_mounts,
)


class TestBootMountTrace(unittest.TestCase):
    def test_encode_st_dev(self):
        # Linux new_encode_dev: (minor & 0xff) | (major << 8) | ((minor & ~0xff) << 12)
        self.assertEqual(encode_st_dev(252, 7), 0xFC07)
        self.assertEqual(encode_st_dev(252, 135), 0xFC87)
        self.assertEqual(encode_st_dev(252, 10), 0xFC0A)
        self.assertEqual(encode_st_dev(252, 15), 0xFC0F)
        self.assertEqual(encode_st_dev(252, 143), 0xFC8F)

    def test_parse_devno_table(self):
        nodes = parse_devno_table()
        self.assertEqual(len(nodes), 88)

        nflasha = next(n for n in nodes if n["name"] == "nflasha")
        self.assertTrue(nflasha["is_block_device"])
        self.assertEqual(nflasha["major"], 252)
        self.assertEqual(nflasha["base_minor"], 0)
        self.assertEqual(nflasha["count"], 32)

        dnflasha = next(n for n in nodes if n["name"] == "dnflasha")
        self.assertTrue(dnflasha["is_block_device"])
        self.assertEqual(dnflasha["major"], 252)
        self.assertEqual(dnflasha["base_minor"], 128)
        self.assertEqual(dnflasha["count"], 32)

    def test_parse_init_mounts(self):
        mnts, drivers1, drivers2 = parse_init_mounts()
        self.assertEqual(len(mnts), 22)
        self.assertEqual(len(drivers1), 4)
        self.assertEqual(len(drivers2), 31)

        # Drivers1 sequence
        self.assertEqual(drivers1[0]["module"], "/kmod/devno.ko")
        self.assertEqual(drivers1[1]["module"], "/kmod/dmac.ko")
        self.assertEqual(drivers1[2]["module"], "/kmod/ldec.ko")
        self.assertEqual(drivers1[3]["module"], "/kmod/emmc.ko")
        self.assertIn("tbl=0x80000000", drivers1[3]["options"])

        # Rootfs entries: entry 18 is compressed dnflasha7, entry 19 is uncompressed fallback
        self.assertEqual(mnts[18]["device"], "/dev/dnflasha7")
        self.assertEqual(mnts[18]["target"], "/rootfs")
        self.assertEqual(mnts[18]["fstype"], "ext2")
        self.assertEqual(mnts[18]["flags"], "0xc0ed0001")

        self.assertEqual(mnts[19]["device"], "/dev/nflasha7")
        self.assertEqual(mnts[19]["target"], "/rootfs")
        self.assertEqual(mnts[19]["fstype"], "ext2")

        # Etc entry: entry 21 is nflasha10 on /etc, vfat, read-write
        self.assertEqual(mnts[21]["device"], "/dev/nflasha10")
        self.assertEqual(mnts[21]["target"], "/etc")
        self.assertEqual(mnts[21]["fstype"], "vfat")
        self.assertEqual(mnts[21]["flags"], "0xc0ed0490")
        self.assertEqual(mnts[21]["data"], "posix_attr")

    def test_trace_boot_mounts_resolution(self):
        rep = trace_boot_mounts()
        res = rep["device_resolutions"]

        # Rootfs (/lib) partition 7
        self.assertEqual(res["rootfs_lib"]["compressed"]["st_dev"], 64647)
        self.assertEqual(res["rootfs_lib"]["compressed"]["st_dev_hex"], "0xfc87")
        self.assertEqual(res["rootfs_lib"]["uncompressed"]["st_dev"], 64519)
        self.assertEqual(res["rootfs_lib"]["uncompressed"]["st_dev_hex"], "0xfc07")

        # Usr partition 15
        self.assertEqual(res["usr"]["compressed"]["st_dev"], 64655)
        self.assertEqual(res["usr"]["compressed"]["st_dev_hex"], "0xfc8f")
        self.assertEqual(res["usr"]["uncompressed"]["st_dev"], 64527)
        self.assertEqual(res["usr"]["uncompressed"]["st_dev_hex"], "0xfc0f")

        # Etc partition 10
        self.assertEqual(res["etc"]["st_dev"], 64522)
        self.assertEqual(res["etc"]["st_dev_hex"], "0xfc0a")

        # /etc overlay facts
        self.assertTrue(rep["etc_overlay_evidence"]["rootfs_etc_static_empty"])
        self.assertTrue(rep["etc_overlay_evidence"]["runtime_mount_writable"])


if __name__ == "__main__":
    unittest.main()
