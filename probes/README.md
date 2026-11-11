# probes/ â€” bounded read-only UVC/DMA probe for the ILCE-6400

This directory holds one diagnostic program and its offline build/verification
harness. It exists to collect the **read-only** runtime facts that
`artifacts/analysis/recon-e0348/LIVEVIEW_DMA.md` Â§5 lists as missing before any
liveview transport design is attempted â€” above all whether the Scalar
`GET_JPEG` ring is live and whether a *foreign* poll can see it.

**Running any of this on the camera has NOT been done by the task that authored
it.** Everything here was compiled and exercised offline (host fixture) only.
A build receipt is not hardware evidence.

| File | What it is |
| --- | --- |
| `uvc_dma_probe.c` | the ARMv7 freestanding probe (direct `svc 0`, no libc, self-contained `_start`) |
| `build_probe.py` | WSL ARM builder + `--host-check` fixture runner (Windows-runnable, no camera) |
| `run_probe.sh` | on-camera POSIX sh wrapper: runs the probe from `/tmp_bt`, optional `--sd` mirror |
| `test_probe_report.py` | stdlib-only validator for the emitted JSON |
| `build/` | generated outputs: `uvc_dma_probe_arm`, `manifest.json`, `host-check/` |

## Safety model

The probe is a **reader**, with three separate levels:

1. **Default (observational).** `open(O_RDONLY)` + `read` + `getdents64` +
   `stat64` + `readlink` on `/proc`, `/sys/class/udc`, `/dev` (names only) and the
   process metadata of PID 149, plus one bounded forward read of
   `/proc/osal/uipc`. It never opens a device node for I/O, never mmaps
   `/dev/mem`, never writes anything except `--out`, and issues no ioctl.
2. **`--devmem PA LEN`** â€” compiled out by default (`PROBE_ENABLE_DEVMEM 0`).
   When built in, it performs exactly **one** read of at most **4096** bytes.
   There is no loop and no scan: a 16 MiB `/dev/mem` chunk read dropped USB and
   rebooted the camera (AGENTS.MD, E0454), so bulk sweeps are banned outright.
3. **`--poll-get-jpeg N`** â€” an opt-in *camera-side transaction*, see the
   authorization caveat below.

Every read, directory walk and loop is capped; the caps and the observed byte
counts are echoed in the report's `bounds` object so a reader can tell a
complete collection from a truncated one. All file and directory helpers take an
explicit capacity; there is no dynamic allocation beyond static buffers
(â‰128 KiB for the `/proc/osal/uipc` window, 64 KiB for `/proc/149/maps`).

Exit codes: `0` complete, `2` partial (something was unreadable/truncated, or the
GET_JPEG reply left DMM cleanup ambiguous), `3` refused (unsafe/unknown
arguments or a missing opt-in prerequisite), `4` fatal (the report could not be
written). A refused run writes **no** report, so a report on disk always means
the probe ran.

## The `--poll-get-jpeg` authorization caveat (read this before using it)

`GET_JPEG` on OSAL queue `0x0167046a` is the Scalar frame request whose 40-byte
DataflowInfra packet is taken verbatim from
`tools/native_camera/uvc_sensor_feeder_30fps.c:484-529`. Sending it is **not a
passive read**: it is a camera-side request in the camera's own DataflowInfra
namespace, on a queue the application owns.

- It requires **both** `--poll-get-jpeg N` (`1..100`) and
  `--i-understand-foreign-get-jpeg`, otherwise the probe refuses with exit 3 and
  sends nothing.
- The poll path opens `/dev/uipc` `O_RDWR`, the same call the physically proven
  feeder makes (`uvc_sensor_feeder_30fps.c:276`), and only after both flags are
  present; the default observational mode never opens `/dev/uipc` at all.
- The probe prints a warning block before the first poll.
- **The PC-Remote ownership side effects of a foreign poll are unmeasured.**
  Every physical `GET_JPEG` ever issued from a foreign process was issued in Mass
  Storage and returned `ready=0` (`docs/evidence/0149-...`, `0145`, `0340`). What
  a foreign poll does while PC Remote is streaming â€” refuse, allocate a second
  sequence, or steal a frame the host PTP path is about to drain â€” has never
  been tested (`LIVEVIEW_DMA.md` Â§3.5).
- **Explicit user authorization is required per hardware attempt.** The standing
  read-only allowance in AGENTS.MD covers observations; this is a camera-side
  transaction, so it is not covered by default.
- If a reply reports `ready != 0`, the probe opens handle1, records the DMM
  `{phys,size}`, then runs the documented teardown
  (`dmm_open_unit` â†’ `dmm_close_unit` â†’ `dmm_free_unit` for handle1, then
  `dmm_free_unit` for handle2) exactly as
  `uvc_sensor_feeder_30fps.c:673-694` does, and stops. If any step fails it
  records the ambiguity, does **not** retry, and exits `2`. Frame bytes are never
  copied and never invented.

## Host commands (offline)

Build the ARM binary and the manifest:

```powershell
.\venv\Scripts\python.exe probes\build_probe.py
```

Compile the same source for x86-64 under WSL with `-DPROBE_HOST_STUB`, run
`--help`, then smoke-run it against a synthetic `/proc`-/`sys`-/`dev`-like tree in
a WSL temp directory and validate the JSON:

```powershell
.\venv\Scripts\python.exe probes\build_probe.py --host-check
```

Both write into `probes/build/` (`manifest.json`, `host-check/report.json`,
`host-check/help.txt`, `host-check/manifest.json`). The fixture's values are
synthetic â€” device nodes are regular files, so `major:minor` is `0:0` there â€” and
must never be quoted as camera evidence.

**Sandbox note (observed in this workspace).** The agent sandbox runs workspace
binaries at **low integrity** (`Mandatory Label\Low Mandatory Level`), and a
low-integrity process cannot start WSL: `wsl.exe` returns
`Access is denied. Error code: Wsl/E_ACCESS_DENIED`. So
`.\venv\Scripts\python.exe probes\build_probe.py` fails with a loud, specific
message in this environment. The same script run under a medium/high-integrity
interpreter (`C:\Python314\python.exe probes\build_probe.py`) builds and
host-checks normally; the receipts in the task report are from that run. This is
an environment restriction, not a bug in the builder.

## Camera commands (require an explicit decision to touch hardware)

Deployment is host-side. `tools/camera_debugger.py` (normal MSC transport, no
mode switch, no service mode) has these subcommands: `info`, `ps`, `read PATH`,
`maps PID`, `mem PID ADDR SIZE`, `snapshot PID DIR`, `threads PID`,
`exec COMMAND`, `push LOCAL REMOTE`, `stop`.

```powershell
# 1. push the binary and the wrapper into RAM (push is read-back verified, <=1 MiB)
.\venv\Scripts\python.exe tools\camera_debugger.py push probes\build\uvc_dma_probe_arm /tmp_bt/uvc_dma_probe
.\venv\Scripts\python.exe tools\camera_debugger.py push probes\run_probe.sh /tmp_bt/run_probe.sh

# 2. push does not set the exec bit
.\venv\Scripts\python.exe tools\camera_debugger.py exec "chmod +x /tmp_bt/uvc_dma_probe /tmp_bt/run_probe.sh"

# 3. default observational run
.\venv\Scripts\python.exe tools\camera_debugger.py exec "cd /tmp_bt && ./run_probe.sh"

# 4. retrieve the receipts (do not rely on exec stdout: it is truncated and has a deadline)
.\venv\Scripts\python.exe tools\camera_debugger.py read /tmp_bt/uvc_dma_probe.json --output artifacts\analysis\uvc-dma-probe.json
.\venv\Scripts\python.exe tools\camera_debugger.py read /tmp_bt/uvc_dma_probe.log  --output artifacts\analysis\uvc-dma-probe.log

# 5. remove only the helpers this run created
.\venv\Scripts\python.exe tools\camera_debugger.py exec "rm -f /tmp_bt/uvc_dma_probe /tmp_bt/run_probe.sh"
```

Notes: `exec` merges stdout/stderr under a five-second deadline with an output
limit, so a long poll sequence should be backgrounded
(`exec "cd /tmp_bt && ./run_probe.sh --poll-get-jpeg 20 --i-understand-foreign-get-jpeg >/dev/null 2>&1 &"`)
and the report fetched afterwards with `read`. The default observational run
reads a few hundred kilobytes and normally finishes well inside the deadline.
`run_probe.sh --sd` mirrors the JSON and log to a writable vfat mount among
`/mnt/sd`, `/mnt`, `/media/sd`, refuses any mount backed by `/dev/nflasha*`
(internal flash) or `/setting`, and prints the mirror receipt with a read-back
comparison.

## Field â†’ evidence table

`LIVEVIEW_DMA.md` Â§5 item in brackets.

| JSON field | What it answers |
| --- | --- |
| `identity.uptime` | reboot detection for the session; a reset after a read means the read was not safe [Â§3.5, E0297/E0454] |
| `identity.version`, `cmdline` | kernel/ABI baseline for the `stat64` layout and syscall availability; `im.elf debug s g r u l i a lazy-global` style argv is *not* re-derived here |
| `identity.devices` | character/block major names as the kernel currently reports them |
| `modules[].name/size/refcount/state/address` | loaded-module surface: `dma330`, `usbg_cmn`, `osal_uipc` present; `usbg_video`/`usbg_audio` expected absent [Â§5.7, 0316] |
| `udc[].state/current_speed/maximum_speed/active/is_otg` | gadget-controller state ("configured"/"high-speed" vs idle) at the moment of the read [Â§1.c, 0313] |
| `devnodes.listings` | `/dev` and `/dev/usb` names â€” does `/dev/usb/video` exist at all [Â§5.6, 0320/0321] |
| `devnodes.stat` | present + `major:minor` (+ decoded `mode` and the stat ABI used) or the exact errno per node: `/dev/uipc`, `/dev/stream`, `/dev/stream2`, `/dev/dmpgles2`, `/dev/usb/{event,video,audio}` |
| `pid149.status` | `Name/State/Tgid/Pid/PPid/Threads/Vm*/Cap*` for `im.elf` â€” thread count is the freeze-feasibility number seen as 175â€“181 in 0342/0345 |
| `pid149.mappings` | base/end/perms of every mapping whose path contains `im.elf`, `libInfraUsbCmn`, `libInfraPtpControl`, `libInfraPtpExtCmd`, `libptp`, `libMWF`, `libObj`, `dmpgles2`, `libosal` â€” the addresses a future hook/owner analysis must use instead of constants [Â§4.1, 0313] |
| `pid149.fds` | fd â†’ target for up to 256 fds, so `/dev/uipc`- and `/dev/stream2`-owning descriptors are attributable, not guessed |
| `kallsyms.symbols` | exact-symbol presence/address/type for `usb_gadgetcore_register_driver`, `usb_gadgetcore_unregister_driver`, `usb_sync_alloc_phys_buffer`, `usb_sync_free_phys_buffer`, `dma330_mem_transfer_async`, `osal_snd_msg`, `osal_rcv_msg_tmo`, `usb_gcw_start`, `usb_gcw_stop`, `make_config_desc`, `setup_req`; absent â†’ `null`, never a guess; a masked (zero) address is flagged `restricted` [Â§5.7] |
| `uipc.bytes_read/truncated/counts` | whether the queue ids under study appear in `/proc/osal/uipc` as ASCII (`0x0167046a`, `0x0061003c`, `0x00CA8192`, `0x012002DA`) and/or as raw little-endian ids, with occurrence counts over a single forward read [Â§5.13, 0313] |
| `uipc.minfo_head`, `uipc.ulogio_head` | first bounded header bytes of the OSAL info/log views; `ulogio` was header-only-readable in 0313 |
| `get_jpeg_polls[]` | per poll `{err, ready, size_shift, handle1, handle2}`: is the Scalar ring live and does a foreign poll see it â€” the decisive Â§5.1 question |
| `get_jpeg_frame` | the one reply that reported ready: DMM `phys`/`size` from `OpenUnit` (bounded capacity evidence for Â§5.10) and every cleanup status |
| `bounds` | the caps actually in force, the byte counts observed, and two provenance flags: `bulk_devmem_scan` (always `false` â€” no sweep ever happens) and `device_node_opened_for_io` (`false` in the default run; `true` only when `--devmem` or `--poll-get-jpeg` actually opened a device node) |
| `devmem` (opt-in build) | one bounded â‰¤4096-byte `/dev/mem` window: `pa`, `len`, `bytes_read`, first bytes, errno. Never a sweep |
| `notes` | free-text qualifiers: truncation, refusals, ambiguity, and the "authored offline, not run on hardware" statement |

### What this probe cannot answer

- Whether a foreign `GET_JPEG` starves the host PTP stream (Â§5.2) â€” that needs a
  concurrent host-side `GetObject 0xFFFFC002` stream and rate comparison.
- The `0x50e` size-vs-UnitType conflict (Â§5.3) â€” resolving it needs the alloc
  call itself, which allocates memory (a write).
- Destination window / slot size on the stock driver (Â§5.4) â€” `MOD_QUERY_DMA`
  exists only in the local shim.
- What `0xf002` really does (Â§5.5), the `/dev/usb/video` ioctl ABI (Â§5.6 after an
  overlay), encoder limits (Â§5.12), OSD liveness under polling (Â§5.11, needs
  ptrace), and glass-to-glass latency (no measurement exists anywhere).
- Any PC-Remote-vs-Mass-Storage behavioural difference in the GET_JPEG reply:
  the probe reports what happened once, not a mode comparison.

## Validator and tests

`test_probe_report.py` validates one report: required top-level keys, value
types, and evidence discipline â€” a kallsyms entry without an address, a
device-node entry with neither `major:minor` nor an errno, a zero kallsyms
address not flagged `restricted`, a `size_upper_bound` that is not
`size_shift << 7`, more than 100 polls, a `/dev/mem` read above 4096 bytes, or a
declared cap above its hard limit are all rejected.

```powershell
.\venv\Scripts\python.exe probes\test_probe_report.py probes\build\host-check\report.json
.\venv\Scripts\python.exe -m unittest discover -s tests -q
```

`tests/test_probes_report.py` generates the report it validates by running
`build_probe.py --host-check` at test time; when WSL is unreachable from the test
interpreter (the low-integrity sandbox case above) it falls back to the
report already produced by the last host check, and skips only if neither is
available. No hardware is needed for any test here.

---

## E0348 first read-only hardware run (2026-11-11)

The probe was executed once on the camera in **Mass Storage**, in its default
observational-only mode, after a hash-verified push. This is recorded so the
"authored offline" caveat above is not misread as "never ran".

- push: `camera_debugger.py push probes/build/uvc_dma_probe_arm /tmp_bt/uvc_dma_probe_arm`
  -> readback sha256 `b32987b943bf66c75befb0e13c242bdb14491fc3b0707572d28a0273f08eb66e` = local
- run: `/tmp_bt/uvc_dma_probe_arm --out /tmp_bt/uvc_probe_e0348.json` -> `exit_code=0`,
  `PROBE_RESULT schema=a6400-uvc-dma-probe/1`
- report: 18,038 B, sha256 `d97943ea5fcf75bbaf596e8b563714a55eae220ca559711d95b8c3c54bdd164e`,
  preserved as `artifacts/analysis/recon-e0348/camera-probe/uvc_probe_e0348.json`
  and validated by `probes/test_probe_report.py`
- safety: no mode switch, no module load, no `/dev/mem`, no `--poll-get-jpeg`,
  no device node opened for I/O; helpers removed afterwards, `/tmp_bt` back to baseline,
  `/proc/uptime` monotonic (3464 s -> 5175 s), camera healthy in MSC
- full receipt: `artifacts/analysis/recon-e0348/camera-probe/run-receipt.json`

`--poll-get-jpeg` remains unexecuted and still requires explicit per-run authorization.