# Adding a Sony BIONZ X (`CXD90045`) camera

This guide is for owners of another Sony BIONZ X / `CXD90045` body — a6100, a6600,
a7 III, ZV-E10, or a model not listed yet — who want the project to know about their
camera **without inventing anything about it**.

**ILCE-6400A owners:** [E0491](evidence/0491-a6400a-offline-qualification-and-debugger-boundary.md)
qualifies the signed 1.01 package and observes Mass Storage `054C:0F0F`. The
`ilce_6400a` profile is **reference only**, not a verified execution or installation
target. Its kernel addresses and driver differ from the original a6400. Start
offline; do not run the old installer or assume a debugger is already available.

[E0492](evidence/0492-a6400a-kernel-partition-mmio-and-hook-map.md) maps the
a6400A's main/updater builds, static partition and MMIO geometry, rootfs versions
and moved execution hooks with `tools.research.bionzx_machine_map`. It explicitly
keeps live `/proc`, actual boot tags, `/setting` and physical dump facts unknown.
Package images can be shorter than partition capacity; never pad or label them
as complete camera dumps. A first-class runtime profile still needs captured
identities and per-image execution contracts, not only a registry entry.

[E0493](evidence/0493-a6400a-native-readonly-transport-and-model-info-busy.md)
records the next access boundary: a narrow native Windows inquiry works, but
normal model information remains BUSY. That does not provide `/proc` or dump
access. Keep that failed, bounded result separate from the offline machine map;
do not use generic updater/service wrappers as read-only onboarding commands.

[E0494](evidence/0494-a6400a-msc-reply-lifetime-and-verified-native-identity.md)
subsequently verifies the normal model query with one uninterrupted transaction.
Its opaque wire product code is `0032858730`; the updater model id is separately
`0x81030017`. Do not conflate those identifiers or promote a working identity API
to a first-class executable machine or debugger/dump capability.

Two ways to contribute, in increasing effort:

| Contribution | Hardware needed | What it unlocks |
| --- | --- | --- |
| **A read-only probe capture** | camera + USB | The first real facts about your body: kernel symbols, device nodes, module set, UDC state |
| **A registered `TargetProfile`** | offline work on the capture + your firmware files | Your body becomes selectable in `src/a6400/targets/` with every value traced to evidence |

Both are welcome. A partial, honest profile is far more useful than a complete guess:
`TargetProfile` **refuses to construct** a profile that carries a claim without an evidence
source, so you cannot accidentally publish an unsourced address.

---

## The evidence rules (the same ones the a6400 profile follows)

1. **Claims are per-body.** Never copy a6400 addresses, queues or PIDs into another body's
   profile. A different camera is a different kernel build even on the same SoC.
2. **Report the tier.** An offline disassembly result, a read-only `/proc` observation and
   a physically exercised capability are three different kinds of evidence. The profile
   records them as such; the status card prints each tier verbatim.
3. **Unknown stays unknown.** Leave a field out (or `None`) and list the reason in
   `boundaries`. Do not fill a gap to make a table look complete.
4. **No camera writes in the onboarding path.** Probing is read-only. Flash writes, module
   loads, USB mode switches and teardown experiments are separate, explicitly authorized
   physical workstreams — never routine onboarding steps.
5. **Keep the raw receipt.** A profile without a preserved, hash-identified capture cannot
   be reviewed, so it cannot be merged.

---

## Step 1 — Inspect your firmware offline

You need a legally acquired firmware update or a dump you already own; do not commit it.

```powershell
# Extract the container as data, without executing the updater
.\venv\Scripts\python.exe -m tools.research.sony_updater_payload firmware\Update_ILCE6400AV101.exe artifacts\analysis\NEW-CAMERA-CHECK\payload

# Inventory ELF/shared objects and kernel images found in the extracted partitions
.\venv\Scripts\python.exe -m tools.research.elf_inventory --help

# Decode the kernel kallsyms tables straight out of the extracted vmlinux.bin
.\venv\Scripts\python.exe -m tools.research.decode_kernel_kallsyms --help
```

The payload tool reports **UFU** or **CAB**. For CAB, extract only its
`FirmwareData_*.dat` member with an archive reader, then pass that data to
`fwtool.py unpack -f <payload> -o <new-output>`. For UFU, pass the extracted
container directly. Never run the updater or extracted executables. Use fresh
output directories; [E0491](evidence/0491-a6400a-offline-qualification-and-debugger-boundary.md)
records the exact a6400A cabinet/data commands. The legacy UFU-only wrapper is
not the procedure for PackMan updaters.

What to look for, and where it belongs in the profile:

| Profile field | Where it comes from |
| --- | --- |
| `firmware_version` | The update package/version you unpacked (record the hash of the input) |
| `kernel_version` | `linux_banner` / vermagic string in `vmlinux.bin`, e.g. `3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7` |
| `kallsyms.*` | `decode_kernel_kallsyms` output for `usb_gadgetcore_ioctl`, `usb_gadgetcore_register_driver`, `osal_snd_msg`, `osal_rcv_msg_tmo`, `setup_req`, `make_config_desc` and `usb_gcw_start/stop` |
| `modules.*` | `tools.research.uvc_enablement_manifest` style comparison: module size + SHA-256 + role (this is how the ZV-E10 UVC chain is pinned) |
| `usb.*` | USB descriptors in the extracted data plus the host-observed VID/PID in each mode |
| `soc_verified` | Set `True` only when you have body-specific evidence that this body is a `CXD90045`; device-tree/`/proc/cpuinfo`/kernel banner evidence counts, a forum post does not |

Static symbol addresses are exact only for the image you decoded. Say which image (hash) in
the `EvidenceRef.detail`.

---

## Step 2 — Capture a read-only runtime probe

This step assumes a debugger has already been separately qualified and installed
for your body. It is not an installer compatibility test. A stock camera without
verified access stops here; bootstrap, startup changes and even staging helpers
in camera RAM require their own explicit scope.

The `probes/` directory contains a freestanding ARMv7 reader and its build/receipt harness.
Read [`probes/README.md`](../probes/README.md) before running it: it documents the exact
bounds, exit codes and safety model.

```powershell
# Build the ARM binary and the manifest (offline; needs a WSL/ARM toolchain)
.\venv\Scripts\python.exe probes\build_probe.py

# Push it into RAM only (push is read-back verified)
.\venv\Scripts\python.exe tools\camera_debugger.py push probes\build\uvc_dma_probe_arm /tmp_bt/uvc_dma_probe
.\venv\Scripts\python.exe tools\camera_debugger.py push probes\run_probe.sh /tmp_bt/run_probe.sh
.\venv\Scripts\python.exe tools\camera_debugger.py exec "chmod +x /tmp_bt/uvc_dma_probe /tmp_bt/run_probe.sh"

# Default observational run: /proc, /sys/class/udc, /dev names, PID metadata, kallsyms
.\venv\Scripts\python.exe tools\camera_debugger.py exec "cd /tmp_bt && ./run_probe.sh"

# Retrieve the receipt (exec stdout is truncated; always read the file)
.\venv\Scripts\python.exe tools\camera_debugger.py read /tmp_bt/uvc_dma_probe.json --output artifacts\analysis\uvc-dma-probe-<model>.json
.\venv\Scripts\python.exe tools\camera_debugger.py read /tmp_bt/uvc_dma_probe.log  --output artifacts\analysis\uvc-dma-probe-<model>.log

# Remove only the helpers this run created
.\venv\Scripts\python.exe tools\camera_debugger.py exec "rm -f /tmp_bt/uvc_dma_probe /tmp_bt/run_probe.sh"
```

The probe is a **reader**. In default mode it opens nothing for I/O, never mmaps `/dev/mem`,
never issues an ioctl, and writes only its own report. Keep it that way:

* **No bulk `/dev/mem` scans.** A 16 MiB chunk read dropped the USB link and rebooted the
  a6400 (AGENTS.MD, E0454). Bounded single-page reads only, and prefer `/proc`/`/sys`.
* **No `--poll-get-jpeg`** during onboarding. That path is a camera-side transaction in the
  application's DataflowInfra namespace and needs per-attempt authorization; it is not a
  passive read.
* **No mode switch, no module load, no SD write.** If your body starts in Mass Storage, stay
  there for the probe.
* **Verify the camera afterwards**: `/proc/uptime` must be monotonic (a reset means a
  reboot), the debugger connection must still answer, and `/tmp_bt` must be back to its
  baseline.

The probe report answers the questions a profile needs:

| Report field | Profile use |
| --- | --- |
| `identity.version`, `cmdline` | Confirms the kernel/ABI baseline you decoded offline |
| `kallsyms.symbols` | Live per-symbol address, type, and `restricted` flag for masked addresses |
| `modules[]` | Loaded module set and sizes — compare with your offline inventory |
| `devnodes.listings`, `devnodes.stat` | Which `/dev/usb/*` nodes your body exposes (major:minor or errno) |
| `udc[]` | Gadget-controller state, speed, OTG flag |
| `pid149.mappings` | Library/image base addresses (per boot — never hardcode) |
| `uipc.counts` | Which OSAL queue ids appear as ASCII / little-endian in `/proc/osal/uipc` |
| `bounds`, `notes` | What was truncated or refused, and the "authored offline, not run on hardware" statement |

The JSON validator must accept your receipt:

```powershell
.\venv\Scripts\python.exe probes\test_probe_report.py artifacts\analysis\uvc-dma-probe-<model>.json
```

---

## Step 3 — Register the profile

Add (or replace the stub for) your body in `src/a6400/targets/catalog.py`:

```python
from src.a6400.targets import EvidenceRef, STATUS_VERIFIED, TargetProfile

ILCE_6100 = TargetProfile(
    target_id="ilce_6100",
    model_name="Sony ILCE-6100 (a6100)",
    status=STATUS_VERIFIED,          # only when every value below is sourced
    soc_verified=True,
    firmware_version="x.y.z",
    kernel_version="3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7",
    kallsyms={
        "usb_gadgetcore_ioctl": 0x00000000,   # from YOUR decoded/observed image
        "osal_snd_msg": 0x00000000,
        "osal_rcv_msg_tmo": 0x00000000,
        "setup_req": 0x00000000,
    },
    uipc_queues={"usb_control": 0x00000000},
    usb=UsbIdentity(vid=0x054C, pids={"mass_storage": 0x0000}, bcd_device=0x0200),
    modules={},
    sources={
        "firmware_version": (EvidenceRef("docs/evidence/NNNN-<your-record>.md", "which image/hash it came from"),),
        "kallsyms.usb_gadgetcore_ioctl": (EvidenceRef(..., "..."),),
        # ... one entry per populated field
    },
    boundaries=("What you did not verify, stated plainly.",),
    notes="Where the evidence record is.",
)
```

Then register it in `DEFAULT_REGISTRY` and run the contract checks:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_target_profiles -v
```

The tests enforce the schema and the evidence discipline: every claim has a source, every
cited path exists, stubs carry no claims, addresses are 32-bit, USB ids are 16-bit, and
duplicate `target_id`s are rejected. The failure messages tell you which field is unsourced.

If your body is only partly characterised, keep it a stub (`STATUS_UNVERIFIED`, no claims,
boundaries listed) and add claims as evidence arrives. That is a mergeable contribution too.

---

## Step 4 — Open the pull request

Include:

1. **The evidence record** `docs/evidence/NNNN-<short-title>.md` with: date, inputs (firmware
   package/partition + SHA-256, probe binary + SHA-256), exact commands, observed results,
   what you could not observe, and the remaining boundary. Copy the format used by the
   existing records.
2. **The preserved receipt** under `artifacts/analysis/` (local, not committed — artifacts are
   excluded from Git; paste the key fields and the hashes into the record instead).
3. **The profile change** plus any test updates.
4. **What you did *not* verify**, explicitly.

PR checklist:

- [ ] `python -m unittest discover -s tests -q` passes.
- [ ] `python -m unittest tests.test_target_profiles -v` passes.
- [ ] Every populated profile field has an `EvidenceRef` with a real path and detail.
- [ ] No a6400 value was copied into another body's profile.
- [ ] No firmware, module, backup or RAM dump is committed.
- [ ] No camera write, mode switch, module load or `/dev/mem` sweep is part of the onboarding path.
- [ ] The camera was left responsive in its original mode and helpers were removed.

---

## What we will not merge

* Unsourced addresses "found on the internet", forum dumps or another body's values.
* A `verified` status backed only by a model name or a forum post.
* A profile that claims execution or compatibility for a body that has never been run.
* Probe changes that add a device write, an unbounded read, a `/dev/mem` sweep, or a
  fabricated reply.
* Firmware, extracted proprietary binaries, backups or raw memory captures in the repository.

## Where the current profiles are

`src/a6400/targets/catalog.py` — original Sony ILCE-6400 (verified execution target),
ILCE-6400A, ILCE-6100, ILCE-6600 and ILCE-7M3 (sourced reference profiles), and
ZV-E10 (reference UVC chain). `src/a6400/targets/profile.py` holds the schema and
fail-closed validation. A profile is evidence metadata, not an automatic port of
every emulator or camera helper.
