"""Scaffold a draft ``TargetProfile`` module from a body's own extracted firmware.

Offline only: reads only the target body's unpacked ``vmlinux.bin`` / ``config.yaml``
(or explicit CLI flags) and emits a Python skeleton for
``src/a6400/targets/bodies/<target_id>.py``. Never copies ``a6400`` addresses.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.research.decode_kernel_kallsyms import decode as decode_kallsyms  # noqa: E402

REQUIRED_KALLSYMS = (
    "usb_gadgetcore_ioctl",
    "usb_gadgetcore_register_driver",
    "usb_gadgetcore_unregister_driver",
    "usb_gcw_start",
    "usb_gcw_stop",
    "setup_req",
    "make_config_desc",
    "ret_to_user",
    "do_page_fault",
    "do_PrefetchAbort",
)


def extract_vermagic(kernel_bytes: bytes) -> str | None:
    """Extract the Linux vermagic / banner string from a raw kernel image."""
    match = re.search(rb"3\.\d+\.\d+[^\x00\r\n]{4,80}ARMv7", kernel_bytes)
    if match:
        return match.group(0).decode("ascii", errors="replace")
    return None


def scaffold_profile_source(
    *,
    target_id: str,
    model_name: str,
    firmware_version: str | None = None,
    kernel_version: str | None = None,
    kallsyms: dict[str, int] | None = None,
    evidence_path: str = "docs/evidence/NNNN-body-onboarding.md",
    kernel_sha256: str = "<sha256>",
) -> str:
    """Render a valid ``TargetProfile`` Python module skeleton."""
    var_name = target_id.upper()
    syms = kallsyms or {}
    sym_lines = "\n".join(
        f'        "{name}": {addr:#010x},' for name, addr in sorted(syms.items())
    )
    src_lines = []
    if firmware_version is not None:
        src_lines.append(
            f'        "firmware_version": (EvidenceRef(EVIDENCE, "extracted {model_name} firmware {firmware_version}"),),'
        )
    if kernel_version is not None:
        src_lines.append(
            f'        "kernel_version": (EvidenceRef(EVIDENCE, "vermagic in vmlinux.bin {kernel_sha256[:8]}..."),),'
        )
    for name in sorted(syms):
        src_lines.append(
            f'        "kallsyms.{name}": (EvidenceRef(EVIDENCE, "decoded from vmlinux.bin {kernel_sha256[:8]}..."),),'
        )
    src_block = "\n".join(src_lines)
    status = "STATUS_REFERENCE" if syms else "STATUS_UNVERIFIED"
    soc_verified = "True" if syms else "False"
    return f'''"""{model_name} target profile (scaffolded offline)."""
from __future__ import annotations

from src.a6400.targets.profile import (
    {status},
    EvidenceRef,
    TargetProfile,
)

EVIDENCE = {evidence_path!r}

{var_name} = TargetProfile(
    target_id={target_id!r},
    model_name={model_name!r},
    status={status},
    soc_verified={soc_verified},
    firmware_version={firmware_version!r},
    kernel_version={kernel_version!r},
    kallsyms={{
{sym_lines}
    }},
    uipc_queues={{}},
    modules={{}},
    sources={{
{src_block}
    }},
    boundaries=(
        "Offline packaged firmware only: no live read-only probe has been run on this body yet.",
        "uipc_queues is empty until a read-only /proc/osal/uipc capture is recorded.",
    ),
    notes="Scaffolded offline via tools.research.scaffold_target.",
)
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-id", required=True, help="lower_snake_case target id, e.g. ilce_6500")
    parser.add_argument("--model-name", required=True, help="Human-readable name, e.g. 'Sony ILCE-6500 (a6500)'")
    parser.add_argument("--firmware-version", default=None)
    parser.add_argument("--vmlinux", type=Path, default=None, help="Path to body's extracted vmlinux.bin")
    parser.add_argument("--evidence-path", default="docs/evidence/NNNN-body-onboarding.md")
    parser.add_argument("--output", type=Path, default=None, help="Optional path to write the .py skeleton")
    args = parser.parse_args()

    kallsyms: dict[str, int] = {}
    kernel_version: str | None = None
    kernel_sha256 = "<sha256>"
    if args.vmlinux is not None:
        raw = args.vmlinux.read_bytes()
        kernel_sha256 = hashlib.sha256(raw).hexdigest()
        kernel_version = extract_vermagic(raw)
        decoded = decode_kallsyms(raw)
        sym_map = {s["name"]: s["address"] for s in decoded["symbols"]}
        for name in REQUIRED_KALLSYMS:
            if name in sym_map:
                kallsyms[name] = sym_map[name]

    code = scaffold_profile_source(
        target_id=args.target_id,
        model_name=args.model_name,
        firmware_version=args.firmware_version,
        kernel_version=kernel_version,
        kallsyms=kallsyms,
        evidence_path=args.evidence_path,
        kernel_sha256=kernel_sha256,
    )
    if args.output is not None:
        args.output.write_text(code, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
