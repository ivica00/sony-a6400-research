"""Sensor configuration table mapping and bounded emulation for BIONZ X (CXD90045).

Covers:
* ``sabin/`` Signal Accelerator (SA), DCV PSF, Spica/Musashi tap-filter, and IDT/SSBOOT binaries
* ``dfe_app.bin`` Data Front-End (DFE) XDMAC/padding helper linked at ``0xFE1ED000``
* ``av-cam.bin`` ORIL-mapped ``Camera::Imager::IMX284`` mode/geometry and MMIO register tables
"""
from .dfe_app import DfeAppInfo, DfeAppModel, DfeError, parse_dfe_app
from .imager_tables import (
    ImagerMmioBank,
    ImagerTableError,
    ImagerTableSummary,
    MmioWrite,
    SensorGeometry,
    analyze_avcam_imager,
)
from .sabin import (
    DcvPsfHeader,
    IdtSsbootHeader,
    SaModuleHeader,
    SabinInventory,
    SpicaMusashiEntry,
    parse_dcv_psf,
    parse_idt_ssboot,
    parse_sa_module,
    scan_sabin_tree,
)

__all__ = [
    "DcvPsfHeader",
    "DfeAppInfo",
    "DfeAppModel",
    "DfeError",
    "IdtSsbootHeader",
    "ImagerMmioBank",
    "ImagerTableError",
    "ImagerTableSummary",
    "MmioWrite",
    "SaModuleHeader",
    "SabinInventory",
    "SensorGeometry",
    "SpicaMusashiEntry",
    "analyze_avcam_imager",
    "parse_dcv_psf",
    "parse_dfe_app",
    "parse_idt_ssboot",
    "parse_sa_module",
    "scan_sabin_tree",
]
