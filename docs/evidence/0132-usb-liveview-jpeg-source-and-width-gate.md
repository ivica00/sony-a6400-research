# E0132: USB live-view discovery and original JPEG width gate

Date: 2026-11-07. User redirected work toward discovering a camera-side MJPEG
source and USB transport before building an Android monitor. Hardware support
and 1920x1080/30 delivery remain hypotheses to verify separately.

## Physical observations

Existing normal MSC debugger answered as PID1793, uid/euid/gid0, feature0x23.
No Senser/updater entry, USB reset, application-function invocation, ptrace,
camera upload, camera file write, RAM patch, configuration change or SD access
was performed. No observer/hook was armed. Existing menu work remains E0131.

`tools.research.usb_liveview_discovery` retains bounded procfs/sysfs reads,
directory names, file-descriptor links and regular ELF file windows. Final
report: `artifacts/hardware/usb-liveview-final-discovery-e0132/manifest.json`.
Initial and intermediate reports remain in `usb-liveview-discovery-e0132` and
`usb-liveview-source-discovery-e0132`; the initial guessed UDC pathname failed
and was replaced by enumeration, not treated as a device failure.

Actual `/sys/class/udc/dwc3.0` observations: current_speed `high-speed`,
maximum_speed `super-speed`, state `configured`. Maximum is a controller
attribute, NOT evidence of an available SuperSpeed physical connection.
`im.elf` PID149 already has `/dev/stream` and `/dev/stream2` open. These are
internal memory/stream devices, NOT established host video endpoints.
Both the device-name enumeration and `ls -l /proc/149/fd` exceeded the debugger
output budget (flags1); retain them as partial listings, not complete inventories.
UDC speed/state enumeration completed without truncation.

Loaded modules include `codec_drv`, `liro`, `stream`, `stream2`,
`usbg_stillimage`, `usbg_storage`, `usb_darwin` and `usb_extcmd`. Neither a
JPEG encoder contract nor UVC support follows from these names.
`libInfraStreamingServer.so` is absent from captured PID149 maps; its file
exists. Thus the discovered JPEG path is not proven active during MSC.

## Actual code and version boundary

Inventory hashes match local candidate inputs. Targeted code from
`/usr/lib/libInfraStreamingServer.so` equals retained firmware bytes for all
six functions in `artifacts/hardware/usb-liveview-path-source-e0132/manifest.json`:
pin-connect, Scalar interface, JPEG path, path packet construction, default
initialization and JPEG mapping. GetLiveViewJpeg and pubSfrGetJpeg are also
source-equal in the discovery report. This is regular-file equality, NOT
live process-memory equality or execution proof.

By contrast, fixed-address windows from local libObj and libInfraRemote
do not equal camera files. Those mismatches are preserved, not admitted as
live contracts. Bounded GNU-hash lookup of actual camera ELF exports gives:

| Function | Camera linked Thumb entry | Preserved-image entry |
| --- | --- | --- |
| ModelUsbLiveViewToInstance | 0x71a511 | 0x71a589 |
| ModelLiveViewTransferToInstance | 0x5cd7a9 | 0x5cd821 |
| MrpwDeviceManager::GetLiveViewStatus | 0xcd69 | 0xcd69 |

Addresses in this table are ELF linked values, NOT process addresses. The
two model constructors allocate0x84/0x94-byte objects. They do not establish
that either object is active or that a streaming operation is implemented.
Actual exported function bytes and bounded adjacent file windows are retained
in `artifacts/hardware/usb-liveview-symbols-e0132/`; no generic -0x78 address
translation is authorized by these two observations. The USB model's small
actions include empty return bodies; its name must not be called UVC proof.

## JPEG producer path and concrete resolution gate

Two successful, identity-checked REA/Ghidra12.1.4 batches:

- `artifacts/tools/rea/usb-liveview-jpeg-e0132`: JPEG fetch and EE consumer.
- `artifacts/tools/rea/usb-liveview-path-e0132`: six path/configuration functions.

The planner explicitly rejects ET_DYN (`usb-liveview-plan-e0132`); it returned
zero analyzed nodes. Targeted ELF mapping/disassembly and direct bounded REA
queries were used instead. Ghidra's addresses in these batches have synthetic
base0x10000 above linked addresses: e.g. linked113cc corresponds213cc, NOT a
runtime address. Preserve decompiler ABI uncertainty.

Source-equal `pvtSfrSetPathJpegPath` linked113cc does the following:

1. Reads requested width and rate at request+8/+10.
2. With `m_eevalue_force_backup==0`, accepts width320/640/1024. Other widths
   replace the requested width with `m_default_width` and set status2.
3. Converts low-byte rate by shifting8 and checks the resulting range against
   0x100..0x1e00. This is a rate encoding check, not measured frame delivery.
4. With the force-backup flag nonzero, obtains width/rate/compression/size-limit
   from default globals instead of that requested-width allowlist.
5. Passes the resulting settings to `pvtSfrSetPath` with path selector0x20.

Original source-equal Thumb instructions11420..11430 were independently executed
offline with explicit width fixtures. Widths320/640/1024 reach11432;
1920 reaches fallback11504. No external call, writable application mapping,
successful encode or physical streaming was simulated. Reproduce:

```powershell
python -m tools.research.liveview_width_gate_probe --source artifacts/hardware/usb-liveview-path-source-e0132/000113cc.bin --output artifacts/analysis/usb-liveview-static-e0132/width-gate-controls.json
```

`pvtInitEEParams` reads backup keys01710000(force),01710001(compression),
01710002(width),01710003(rate),01710004(JPEG size limit). Failure fallbacks
include width640 and rate0x1e00. The width reader only checks nonzero at this
layer. This does NOT authorize writing backup keys or prove downstream1920
acceptance. No backup value was read or changed in this investigation.

`pubSfrGetJpeg(ushort*,uint*,uint*)` constructs a0x464-byte packet with
initial halfwords2009/0100/0014/0001 and requests a dataflow response.
On the response branch it exports a16-bit handle and size shifted7. Its
interface performs ownership/transport operations; it is not a pure getter.
The EE path also uses OSAL messaging, DMM mapping, release and unmap routines.
It cannot safely be invoked as an arbitrary shell function with guessed TLS,
packet layout or buffer ownership. JPEG handle-to-bytes and release semantics
remain to be verified before any native consumer.

The two libObj REA batches (`usb-liveview-model-e0132`,
`usb-liveview-actions-e0132`) exceeded the330s initial-analysis deadline;
retain their failed manifests. No pseudocode conclusion is drawn from them.
Original file-byte disassembly remains separate evidence.

## Checks and next boundary

Both new research modules compile; 10 existing debugger protocol/locking/remote
ELF tests pass. The four source-hash-guarded original width controls pass.
Camera discovery completed repeatedly without mode changes. No emulator backend
behavior changed, and these checks are not a complete firmware regression.
The project status image was regenerated without increasing compatibility claims.

Next trace the exact lower-level path selector0x20 into its receiver/encoder,
including width/height validation, buffer-size requirements and completion/
release ownership. Separately trace an original USB image-transfer consumer
or design a bounded custom bulk transport only after source and frame lifetime
are established. First physical milestone is one complete, decoded live JPEG
with measured dimensions; then frame cadence and end-to-end USB throughput.
1920x1080 at30fps and USB video output remain UNPROVEN. No camera action from
the user is required by this checkpoint.
