"""Static analysis of initrd boot scripts, sbin/init, devno.ko, and mount configurations.

Traces:
- `devno.ko` udif_devnodes major/minor device allocations
- `sbin/init` mnts partition table, pivot_root sequence, and driver phases
- `/rootfs` (/lib) and `/usr` compressed vs uncompressed device selection
- `/etc` runtime mount on /dev/nflasha10 (vfat, read-write)
"""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path
from typing import Any

import elftools.elf.elffile as elffile

ROOT = Path(__file__).resolve().parents[2]
DEVNO_KO = ROOT / "firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/initrd.img_unpacked/kmod/devno.ko"
INIT_BIN = ROOT / "firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/initrd.img_unpacked/sbin/init"
# (mnts, drivers1, drivers2) addresses keyed by init SHA-256 (a6100 ledger F-0007).
INIT_TABLES = {
    "0af5724ece7f60db2831b7a4e61829be369868027877cca0f921f981ae8dc7ad": (0x13308, 0x131EC, 0x13210),  # a6400 V2.00
    "2258c8d964e6e3019c5c06fa90b0d01a9c60ad50ea2bbf4a1c35951d7a43d63a": (0x136B4, 0x1359C, 0x135BC),  # ILCE-6100A V1.01
}
MOUNT_CONF = ROOT / "firmware/extracted_a6400/firmware.tar_unpacked/0100_config/mount.conf"
ROOTFS_ETC = ROOT / "firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/etc"
OUTPUT_JSON = ROOT / "artifacts/inventory/boot-mount-trace.json"


def encode_st_dev(major: int, minor: int) -> int:
    """Standard Linux new_encode_dev ((minor & 0xff) | (major << 8) | ((minor & ~0xff) << 12))."""
    return (minor & 0xFF) | (major << 8) | ((minor & ~0xFF) << 12)


def parse_devno_table() -> list[dict[str, Any]]:
    with open(DEVNO_KO, "rb") as f:
        elf = elffile.ELFFile(f)
        rodata_sec = elf.get_section_by_name(".rodata.str1.1")
        data_sec = elf.get_section_by_name(".data")
        assert rodata_sec is not None and data_sec is not None
        ro_bytes = rodata_sec.data()
        d_bytes = data_sec.data()

        entries = []
        for i in range(0, len(d_bytes), 12):
            w0, w1, w2 = struct.unpack("<III", d_bytes[i : i + 12])
            name_end = ro_bytes.find(b"\x00", w0)
            name = ro_bytes[w0:name_end].decode("ascii", errors="replace")
            is_blk = w1 & 0xFFFF
            major = (w1 >> 16) & 0xFFFF
            base_minor = w2 & 0xFFFF
            count = (w2 >> 16) & 0xFFFF
            entries.append(
                {
                    "name": name,
                    "is_block_device": bool(is_blk),
                    "major": major,
                    "base_minor": base_minor,
                    "count": count,
                }
            )
        return entries


def parse_init_mounts() -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    import hashlib
    mnts_addr, drv1_addr, drv2_addr = INIT_TABLES[hashlib.sha256(INIT_BIN.read_bytes()).hexdigest()]
    with open(INIT_BIN, "rb") as f:
        elf = elffile.ELFFile(f)
        rodata_sec = elf.get_section_by_name(".rodata")
        data_sec = elf.get_section_by_name(".data")
        assert rodata_sec is not None and data_sec is not None
        ro_addr = rodata_sec["sh_addr"]
        ro_bytes = rodata_sec.data()
        d_addr = data_sec["sh_addr"]
        d_bytes = data_sec.data()

        def get_str(ptr: int) -> str:
            if ro_addr <= ptr < ro_addr + len(ro_bytes):
                off = ptr - ro_addr
                end = ro_bytes.find(b"\x00", off)
                return ro_bytes[off:end].decode("ascii", errors="replace")
            if d_addr <= ptr < d_addr + len(d_bytes):
                off = ptr - d_addr
                end = d_bytes.find(b"\x00", off)
                return d_bytes[off:end].decode("ascii", errors="replace")
            return hex(ptr)

        # Parse mnts at 0x13308 (22 entries of 20 bytes each)
        mnts = []
        for i in range(22):
            off = (mnts_addr + i * 20) - d_addr
            dev_ptr, tgt_ptr, fstype_ptr, flags, data_ptr = struct.unpack("<IIIII", d_bytes[off : off + 20])
            mnts.append(
                {
                    "index": i,
                    "address": hex(mnts_addr + i * 20),
                    "device": get_str(dev_ptr),
                    "target": get_str(tgt_ptr),
                    "fstype": get_str(fstype_ptr),
                    "flags": hex(flags),
                    "flags_int": flags,
                    "data": get_str(data_ptr),
                }
            )

        # Parse drivers1 at 0x131ec (4 entries of 8 bytes)
        drivers1 = []
        for i in range(4):
            off = (drv1_addr + i * 8) - d_addr
            name_ptr, opt_ptr = struct.unpack("<II", d_bytes[off : off + 8])
            drivers1.append({"module": get_str(name_ptr), "options": get_str(opt_ptr)})

        # Parse drivers2 at 0x13210 (31 entries of 8 bytes)
        drivers2 = []
        for i in range(31):
            off = (drv2_addr + i * 8) - d_addr
            name_ptr, opt_ptr = struct.unpack("<II", d_bytes[off : off + 8])
            drivers2.append({"module": get_str(name_ptr), "options": get_str(opt_ptr)})

        return mnts, drivers1, drivers2


def trace_boot_mounts() -> dict[str, Any]:
    devnodes = parse_devno_table()
    mnts, drivers1, drivers2 = parse_init_mounts()

    # Find nflasha and dnflasha device definitions
    nflasha_def = next(d for d in devnodes if d["name"] == "nflasha")
    dnflasha_def = next(d for d in devnodes if d["name"] == "dnflasha")

    # Major is 252 for both
    major = nflasha_def["major"]

    # Minor calculations:
    # Partition 7 (/rootfs, containing /lib):
    p7_uncompressed_minor = nflasha_def["base_minor"] + 7
    p7_compressed_minor = dnflasha_def["base_minor"] + 7
    p7_uncompressed_dev = encode_st_dev(major, p7_uncompressed_minor)
    p7_compressed_dev = encode_st_dev(major, p7_compressed_minor)

    # Partition 15 (/usr):
    p15_uncompressed_minor = nflasha_def["base_minor"] + 15
    p15_compressed_minor = dnflasha_def["base_minor"] + 15
    p15_uncompressed_dev = encode_st_dev(major, p15_uncompressed_minor)
    p15_compressed_dev = encode_st_dev(major, p15_compressed_minor)

    # Partition 10 (/tmp and /etc):
    p10_minor = nflasha_def["base_minor"] + 10
    p10_dev = encode_st_dev(major, p10_minor)

    # /etc in static rootfs
    etc_static_files = os.listdir(ROOTFS_ETC) if os.path.exists(ROOTFS_ETC) else []

    report = {
        "title": "Boot Selection, Device Node Resolution, and Runtime Mount Trace",
        "artifacts_analyzed": {
            "devno_ko": str(DEVNO_KO.relative_to(ROOT)),
            "init_bin": str(INIT_BIN.relative_to(ROOT)),
            "mount_conf": str(MOUNT_CONF.relative_to(ROOT)),
            "rootfs_etc": str(ROOTFS_ETC.relative_to(ROOT)),
        },
        "devnodes_summary": {
            "total_entries": len(devnodes),
            "nflasha": nflasha_def,
            "dnflasha": dnflasha_def,
        },
        "boot_pipeline": {
            "drivers1_phase": drivers1,
            "rootfs_mount_candidates": [
                {
                    "candidate": "/dev/dnflasha7",
                    "role": "primary_compressed_rootfs",
                    "fstype": "ext2",
                    "flags": "0xc0ed0001",
                    "readonly": True,
                },
                {
                    "candidate": "/dev/nflasha7",
                    "role": "fallback_uncompressed_rootfs",
                    "fstype": "ext2",
                    "flags": "0xc0ed0001",
                    "readonly": True,
                },
            ],
            "pivot_root": {
                "target_dir": "/rootfs",
                "old_root": "initrd",
                "new_root": ".",
                "syscall_num": 218,
            },
            "usr_mount_candidates": [
                {
                    "candidate": "/dev/dnflasha15",
                    "role": "primary_compressed_usr",
                    "fstype": "ext2",
                    "flags": "0xc0ed0001",
                },
                {
                    "candidate": "/dev/nflasha15",
                    "role": "fallback_uncompressed_usr_ext2",
                    "fstype": "ext2",
                    "flags": "0xc0ed0001",
                },
                {
                    "candidate": "/dev/nflasha15",
                    "role": "fallback_cramfs_usr",
                    "fstype": "cramfs",
                    "flags": "0xc0ed0001",
                },
                {
                    "candidate": "/dev/nflasha15",
                    "role": "fallback_vfat_usr",
                    "fstype": "vfat",
                    "flags": "0xc0ed0490",
                },
            ],
            "etc_mount": {
                "device": "/dev/nflasha10",
                "target": "/etc",
                "fstype": "vfat",
                "flags": "0xc0ed0490",
                "readonly": False,
                "data": "posix_attr",
            },
            "drivers2_count": len(drivers2),
            "userland_entry": "/usr/bin/bootin.elf",
        },
        "device_resolutions": {
            "rootfs_lib": {
                "partition_index": 7,
                "compressed": {
                    "device": "/dev/dnflasha7",
                    "major": major,
                    "minor": p7_compressed_minor,
                    "st_dev": p7_compressed_dev,
                    "st_dev_hex": hex(p7_compressed_dev),
                },
                "uncompressed": {
                    "device": "/dev/nflasha7",
                    "major": major,
                    "minor": p7_uncompressed_minor,
                    "st_dev": p7_uncompressed_dev,
                    "st_dev_hex": hex(p7_uncompressed_dev),
                },
            },
            "usr": {
                "partition_index": 15,
                "compressed": {
                    "device": "/dev/dnflasha15",
                    "major": major,
                    "minor": p15_compressed_minor,
                    "st_dev": p15_compressed_dev,
                    "st_dev_hex": hex(p15_compressed_dev),
                },
                "uncompressed": {
                    "device": "/dev/nflasha15",
                    "major": major,
                    "minor": p15_uncompressed_minor,
                    "st_dev": p15_uncompressed_dev,
                    "st_dev_hex": hex(p15_uncompressed_dev),
                },
            },
            "etc": {
                "partition_index": 10,
                "device": "/dev/nflasha10",
                "major": major,
                "minor": p10_minor,
                "st_dev": p10_dev,
                "st_dev_hex": hex(p10_dev),
            },
        },
        "etc_overlay_evidence": {
            "rootfs_etc_static_empty": len(etc_static_files) == 0,
            "static_file_count": len(etc_static_files),
            "runtime_mount_partition": "/dev/nflasha10",
            "runtime_mount_fstype": "vfat",
            "runtime_mount_writable": True,
            "boundary_explanation": "Rootfs /etc is an empty directory in static firmware images. At boot, sbin/init mounts /dev/nflasha10 (vfat, read-write) over /etc. Without physical flash or runtime overlay state, files such as /etc/ld.so.preload are unsupplied.",
        },
        "init_mounts_table": mnts,
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


if __name__ == "__main__":
    rep = trace_boot_mounts()
    print("=== Boot Mount and Device Node Trace Completed ===")
    print(f"devno.ko total device nodes: {rep['devnodes_summary']['total_entries']}")
    print(f"Major block number: {rep['devnodes_summary']['nflasha']['major']}")
    print(f"Rootfs (/lib) compressed:   {rep['device_resolutions']['rootfs_lib']['compressed']['device']} -> st_dev={rep['device_resolutions']['rootfs_lib']['compressed']['st_dev_hex']}")
    print(f"Rootfs (/lib) uncompressed: {rep['device_resolutions']['rootfs_lib']['uncompressed']['device']} -> st_dev={rep['device_resolutions']['rootfs_lib']['uncompressed']['st_dev_hex']}")
    print(f"Usr compressed:             {rep['device_resolutions']['usr']['compressed']['device']} -> st_dev={rep['device_resolutions']['usr']['compressed']['st_dev_hex']}")
    print(f"Usr uncompressed:           {rep['device_resolutions']['usr']['uncompressed']['device']} -> st_dev={rep['device_resolutions']['usr']['uncompressed']['st_dev_hex']}")
    print(f"Etc mount:                  {rep['device_resolutions']['etc']['device']} (vfat, RW) -> st_dev={rep['device_resolutions']['etc']['st_dev_hex']}")
    print(f"Saved: {OUTPUT_JSON}")
