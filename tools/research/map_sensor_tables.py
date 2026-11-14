"""Map and run bounded emulation over BIONZ X sensor configuration tables.

Covers ``sabin/``, ``dfe_app.bin``, and ``av-cam.bin`` (``Camera::Imager``).
Strictly offline: reads unpacked firmware files only.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from project_paths import PROJECT_ROOT
from src.a6400.sensor import (
    DfeAppModel,
    ImagerMmioBank,
    analyze_avcam_imager,
    scan_sabin_tree,
)
from src.a6400.sensor.dfe_app import DfeXdmacDescriptor


DEFAULT_A6400_DEV = (
    PROJECT_ROOT
    / "firmware"
    / "extracted_a6400"
    / "firmware.tar_unpacked"
    / "0700_part_image"
    / "dev"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Map & emulate BIONZ X sensor tables")
    parser.add_argument(
        "--dev-dir",
        type=Path,
        default=DEFAULT_A6400_DEV,
        help="Path to unpacked dev/ directory containing nflasha3_unpacked and nflasha15_unpacked",
    )
    args = parser.parse_args()

    nflasha3 = args.dev_dir / "nflasha3_unpacked"
    nflasha15 = args.dev_dir / "nflasha15_unpacked"

    # 1. sabin/
    inv = scan_sabin_tree([nflasha3 / "sabin", nflasha15 / "sabin"])
    print(f"=== sabin/ inventory ({inv.total_files} files) ===")
    print(f"  SA modules:     {len(inv.sa_modules)}")
    print(f"  DCV PSF tables: {len(inv.dcv_tables)}")
    for dcv in inv.dcv_tables:
        print(f"    - {dcv.filename}: {dcv.generator_tag} ({dcv.timestamp}) payload={dcv.payload_size} B")
    print(f"  IDT/SSBOOT:     {len(inv.idt_ssboot)}")
    for idt in inv.idt_ssboot:
        print(f"    - {idt.filename}: size={idt.declared_size} code_off={idt.code_offset:#x} flags={idt.flags:#x}")
    spica_modes = sorted({s.mode for s in inv.spica_tables})
    print(f"  Spica/Musashi:  {len(inv.spica_tables)} tables across modes: {spica_modes}")
    print(f"  Other files:    {[f[0] for f in inv.other_files]}")

    # 2. dfe_app.bin
    dfe_path = nflasha3 / "dfe_app.bin"
    dfe_model = DfeAppModel.from_bytes(dfe_path.read_bytes())
    print("\n=== dfe_app.bin ===")
    print(f"  size={dfe_model.info.size} B  link={dfe_model.info.link_base:#x}..{dfe_model.info.link_end:#x}")
    print(f"  SRAM regions: {[hex(x) for x in dfe_model.info.sram_regions]}")
    print(f"  entrypoints:  {[hex(x) for x in dfe_model.info.entrypoints]}")
    print(f"  error gates:  {list(dfe_model.info.error_strings)}")
    staged = dfe_model.create_list([DfeXdmacDescriptor(src_addr=0x10000000, dst_addr=0x20000000, byte_count=4096)])
    xfer = dfe_model.run_xdmac()
    print(f"  emulation smoke: staged={staged} descriptor(s), transferred={xfer} B")

    # 3. av-cam.bin
    avcam_path = nflasha3 / "av-cam.bin"
    summary = analyze_avcam_imager(avcam_path.read_bytes())
    print("\n=== av-cam.bin (Camera::Imager) ===")
    print(f"  ORIL v{summary.oril_version} entry={summary.oril_entry:#x} size={summary.size} B")
    print(f"  IMX identifiers: {list(summary.imx_identifiers)}")
    print(f"  Imager classes ({len(summary.imager_classes)}):")
    for cls, vts in summary.imager_classes.items():
        print(f"    - {cls}: vtables={[hex(v) for v in vts]}")
    print(f"  Sensor geometries ({len(summary.geometries)}):")
    for g in summary.geometries:
        print(
            f"    - {g.va:#x}: raw={g.raw_w}x{g.raw_h} eff={g.eff_w}x{g.eff_h} "
            f"active={g.active_w}x{g.active_h} off=({g.off_x},{g.off_y}) crop=({g.crop_x},{g.crop_y})"
        )

    # Replay MMIO tables into ImagerMmioBank
    bank = ImagerMmioBank()
    total_writes = sum(bank.apply_table(writes) for writes in summary.mmio_tables.values())
    print(
        f"  Imager MMIO tables: {len(summary.mmio_tables)} tables, "
        f"{total_writes} writes -> {len(bank.regs)} unique registers in 0xFC09xxxx..0xFC0Axxxx"
    )

    # Diff /usr/sabin/ references vs on-disk sabin/
    on_disk = {p.name for p in (nflasha15 / "sabin").iterdir()} if (nflasha15 / "sabin").exists() else set()
    on_disk |= {p.name for p in (nflasha3 / "sabin").iterdir()} if (nflasha3 / "sabin").exists() else set()
    missing = [ref for ref in summary.sabin_refs if Path(ref).name not in on_disk]
    print(f"  /usr/sabin/ refs in av-cam.bin: {len(summary.sabin_refs)} (absent on disk: {[Path(m).name for m in missing]})")
    print(f"  Video mode strings ({len(summary.video_mode_strings)}): {list(summary.video_mode_strings)}")
    print(f"  Timing entries ({len(summary.timing_entries)}):")
    for t in summary.timing_entries[:12]:
        print(f"    - {t.va:#x}: flags={t.flags:#010x} h={t.h_param} v={t.v_param}")
    print(f"  Active encoder engines: {list(summary.active_encoder_engines)}")
    print(f"  Enum-only encoders (1-hit debug table): {list(summary.enum_only_encoders)}")
    print(f"  Codec strings ({len(summary.codec_strings)}): {list(summary.codec_strings)}")


if __name__ == "__main__":
    main()
