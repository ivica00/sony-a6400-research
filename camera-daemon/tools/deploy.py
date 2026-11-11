#!/usr/bin/env python3
"""Host-side deploy helper for camera-daemon.

This tool is documentation-with-checks. It:

  (a) verifies the built ARM daemon binary against build/manifest.json
      (size + SHA-256) and, optionally, a module against an expected hash;
  (b) prints the exact, copy-pasteable deploy / run / teardown command plan
      built on tools/camera_debugger.py push|exec;
  (c) refuses to execute anything itself.

It imports no process-spawning module and has no code path that talks to a
camera. Running it does not touch hardware. The plan it prints must still be
reviewed by a human and is only valid with explicit authorization for a
camera-module session (see camera-daemon/README.md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DAEMON_DIR = ROOT / "camera-daemon"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--daemon-dir", type=Path, default=DEFAULT_DAEMON_DIR)
    parser.add_argument("--binary", type=Path, default=None,
                        help="default <daemon-dir>/build/a6400-lived")
    parser.add_argument("--manifest", type=Path, default=None,
                        help="default <daemon-dir>/build/manifest.json")
    parser.add_argument("--module", type=Path, default=None,
                        help="optional composite .ko to include in the plan")
    parser.add_argument("--module-sha256", default=None,
                        help="expected SHA-256 of --module (from the offline audit)")
    parser.add_argument("--python", default=str(ROOT / "venv" / "Scripts" / "python.exe"))
    parser.add_argument("--debugger", default=str(ROOT / "tools" / "camera_debugger.py"))
    parser.add_argument("--duration", type=int, default=30,
                        help="daemon run duration in seconds (self-terminating)")
    parser.add_argument("--execute", action="store_true",
                        help="refused: this tool never runs camera commands")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fail(message: str) -> int:
    print(f"REFUSED: {message}")
    return 2


def main() -> int:
    args = parse_args()

    if args.execute:
        return fail("this tool never executes anything; copy the printed commands and "
                    "run them yourself after reviewing them")

    daemon_dir = args.daemon_dir.resolve()
    binary = (args.binary or daemon_dir / "build" / "a6400-lived").resolve()
    manifest_path = (args.manifest or daemon_dir / "build" / "manifest.json").resolve()

    print("camera-daemon deploy plan (DOCUMENTATION ONLY; nothing is executed)")
    print("=" * 72)

    # ---- (a) identity checks ------------------------------------------------
    if not binary.is_file():
        return fail(f"binary not found: {binary} (run build.sh first)")
    if not manifest_path.is_file():
        return fail(f"manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_size = binary.stat().st_size
    actual_sha = sha256_file(binary)

    print(f"binary          : {binary}")
    print(f"bytes           : {actual_size}")
    print(f"sha256          : {actual_sha}")
    print(f"manifest status : {manifest.get('status')}")
    print(f"manifest sha256 : {manifest.get('sha256')}")
    print(f"manifest bytes  : {manifest.get('bytes')}")

    if manifest.get("status") != "built_not_deployed":
        return fail("manifest status is not 'built_not_deployed'; refusing to plan a deploy")
    if manifest.get("camera_access"):
        return fail("manifest claims camera access; refusing")
    if int(manifest.get("bytes", -1)) != actual_size:
        return fail("binary size does not match the manifest")
    if manifest.get("sha256") != actual_sha:
        return fail("binary SHA-256 does not match the manifest")

    module_sha = None
    if args.module:
        module = args.module.resolve()
        if not module.is_file():
            return fail(f"module not found: {module}")
        module_sha = sha256_file(module)
        print(f"module          : {module}")
        print(f"module sha256   : {module_sha}")
        if args.module_sha256 and args.module_sha256.lower() != module_sha:
            return fail("module SHA-256 does not match --module-sha256")
        if not args.module_sha256:
            print("module note     : no --module-sha256 supplied; the plan records the "
                  "observed hash but cannot confirm it matches an audit report")
    print("identity        : OK")
    print()

    # ---- (b) the plan -------------------------------------------------------
    py = args.python
    dbg = args.debugger
    remote_bin = "/tmp_bt/a6400-lived"
    remote_module = "/tmp_bt/a6400_uvc_composite.ko"
    duration = max(1, args.duration)

    def call(description: str, command: str) -> None:
        print(f"# {description}")
        print(f'"{py}" "{dbg}" exec "{command}"')
        print()

    def push(description: str, local: Path, remote: str) -> None:
        print(f"# {description}")
        print(f'"{py}" "{dbg}" push "{local}" "{remote}"')
        print()

    print("PHYSICAL PLAN (review every precondition; do not automate the stop)")
    print("-" * 72)
    print("Preconditions")
    print("  P0  Explicit user authorization for a camera-module session exists.")
    print("  P1  The module is a transport build (--shared-ptp-enumeration-candidate")
    print("      --composite-transport) and boundaries B3 and B5 are understood:")
    print("      today's audit tool refuses transport builds, and the START bridge")
    print("      matches only EP 0x81 while the descriptor advertises 0x84.")
    print("  P2  /tmp_bt is empty; camera is in PC Remote; /proc/uptime recorded.")
    print("  P3  Recovery is known: battery pull wipes /tmp_bt, so read receipts first.")
    print()

    print("1. Read-only preflight")
    call("uptime + module set + node presence (expect no usbg_video yet)",
         "cat /proc/uptime; grep -E 'usbg_video|usbg_cmn|osal_uipc' /proc/modules; ls -l /tmp_bt")
    print("2. Push the daemon and the module")
    push("static ARM daemon (hash pinned by the manifest)", binary, remote_bin)
    if args.module:
        push("composite transport module", args.module.resolve(), remote_module)
    print("3. Verify the pushed bytes before executing anything")
    call("hash check; must equal the manifest sha256 printed above",
         f"sha256sum {remote_bin}")
    print("4. Create the device node if absent (major 248 minor 33)")
    call("idempotent: skip when /tmp_bt/video already exists",
         "test -c /tmp_bt/video || mknod /tmp_bt/video c 248 33")
    print("5. Load the module (RAM only; never from SD or internal flash)")
    if args.module:
        call("insmod from /tmp_bt; refused if the module hash differs from the audit",
             f"insmod {remote_module}")
    else:
        print("# (no --module supplied: skip insmod; a stock camera cannot provide the node)")
        print()
    print("6. Discovery only: no freeze, no INIT, no UPDATE")
    call("dry run; expect device_open + usb_identity + dma_window + dry_run_complete",
         f"{remote_bin} --dry-run --wait-pcremote --timeout 60 --verbose")
    print("7. Armed session (destructive; --arm-transport is required)")
    print("#   Launch detached if the debugger's exec cannot be interrupted: a failed")
    print("#   stop attestation parks the daemon (after writing the receipt) instead of")
    print("#   retrying cleanup. SIGINT/SIGTERM releases the park.")
    call(f"self-terminating {duration}s run; use --dma-phys/--dma-size only if step 6 "
         f"reported ENOTTY",
         f"{remote_bin} --arm-transport --wait-pcremote --timeout 60 --duration {duration} "
         "--stats-interval 5 --verbose")
    print("8. Read the receipts BEFORE any mode change (a reboot wipes /tmp_bt)")
    call("log tail", "cat /tmp_bt/a6400_lived.jsonl")
    call("receipt", "cat /tmp_bt/a6400_lived_receipt.json")
    print("9. Teardown")
    call("confirm the daemon exited with 0/2/3/4 and stop_verified=1 in the receipt",
         "cat /tmp_bt/a6400_lived_receipt.json")
    print("# If the receipt is missing or stop_verified is not 1, PARK: do not rmmod,")
    print("# do not retry cleanup, do not change USB mode. Battery pull is the only")
    print("# guaranteed reset and it destroys the evidence in /tmp_bt.")
    print()
    if args.module:
        call("rmmod ONLY with a verified stop receipt", "rmmod a6400_uvc_composite")
    print("10. Post-check")
    call("uptime must be monotonic (no reboot); module list restored; node gone",
         "cat /proc/uptime; grep -E 'usbg_video|usbg_cmn' /proc/modules || true; ls -l /tmp_bt")

    print("=" * 72)
    print("NOTHING ABOVE WAS EXECUTED. This tool has no camera code path.")
    print("Module prerequisite summary: camera-daemon/module/README.md")
    print("Physical test plan and success criteria: camera-daemon/README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
