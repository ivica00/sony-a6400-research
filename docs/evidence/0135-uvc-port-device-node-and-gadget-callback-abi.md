# E0135: UVC port — device node and gadget callback ABI

Date: 2026-11-07. User authorized continuing toward using a6400 like the native
ZV-E10 UVC reference. Work progressed from component discovery to an offline
port candidate and original-instruction ABI checks. Physical UVC remains off.

## Camera state

Normal feature0x23 debugger PID1793 still answers. A read-only preflight confirms
`/dev/jet/pclc_msg` is248:18 and `/dev/usb/video` and `/dev/usb/audio` do not exist.
Manifest: `artifacts/hardware/uvc-port-preflight-e0135/manifest.json`.
No upload, module insertion, mode change, camera file/RAM/backup/SD write,
callback invocation or observer/hook was performed.

A single84-byte `/dev/kmem` read at the known kernel code address602b8610 failed
with-ENXIO(-6). Receipt: `artifacts/hardware/uvc-kernel-guard-read-e0135`.
This is NOT live code equality proof. No physical-address fallback or MMIO read
was attempted. Debugger identity was checked successfully afterwards.

## Confirmed device-table collision

Reference usbg_video SHA256d385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb
has exactly one udif_devnodes relocation: `.data+3c`, R_ARM_ABS32,
undefined udif_devnodes+294. Original devno entries are12 bytes.

| Offset | ZV-E10 devno | a6400 devno |
| --- | --- | --- |
| 288 |usb/audio,248:32|jet/pclc_ctr,248:17|
| 294 |usb/video,248:33|jet/pclc_msg,248:18|

The two new rows shift subsequent reference entries. Original driver loading
would bind its common character-device registration to a different a6400
device tuple; matching vermagic does not fix that reference.
The complete preserved a6400 table uses major248 minors0..31, not32/33.
This is a static allocation check, not a guarantee that no runtime driver
could reserve another range.

`tools.research.uvc_portability_audit` checks original/reference input hashes
against inventories/extraction manifests and independently resolves these
relocations and table names. Report:
`artifacts/analysis/uvc-portability-final-e0135/manifest.json`.

## Positive common-code evidence and a second mismatch

Reference video versus a6400 still-image common routines:

| Function | Non-relocated instruction bytes | Relocation target records |
| --- | --- | --- |
| usbg_cmn_reg |equal,112 bytes|equal|
| usbg_cmn_copy_probe_info |equal,352 bytes|equal|
| usbg_cmn_clear_probe_info |equal,68 bytes|equal|
| usbg_cmn_clear_ep_list |different,44 bytes|equal|

No relocation was serviced or skipped in camera execution: this is a masked
static comparison. clear_ep_list explicitly uses object+b4 in reference video
but object+a4 in a6400 still-image code. This is a real internal-layout
difference, not a successful compatibility test.

Completed REA/Ghidra12.1.4 batches:

- `uvc-driver-contract-e0135`: reference init/create/ioctl/write and instructions.
- `a6400-sicd-descriptor-e0135`: actual named sicd_core_ioctl and instructions.

The initial `a6400-gadget-descriptor-e0135` query used the wrong procedure name
usbg_sicd_core_ioctl and failed not_found; preserved as failed evidence. It is
not counted as successful analysis.

Dependency plan `uvc-video-dependency-plan-e0135` analyzes11 original functions.
The planner now accepts a separate bounded reference inventory and carries it
into generated REA commands. Default a6400 inventory is unchanged.

## Kernel callback layout — exact original guards

Hash-checked kernels:

- a6400 vmlinux.bin:12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707
- ZV-E10 vmlinux.bin:74fbef5a7c36149cf3256623950798332f9ead0fa719bf6d61dcac69397950e2

Original exported registration code gives:

| Item | a6400 | ZV-E10 |
| --- | --- | --- |
| usb_gadgetcore_register_driver |602b8610|602bcaac|
| First required callback slot |descriptor+10|descriptor+18|
| Second required callback slot |descriptor+14|descriptor+1c|

Offsets are hexadecimal. a6400 original instructions602b8644/602b8650 load+10/+14;
the reference602bcae0/602bcaec loads+18/+1c. a6400's original still-image driver
constructs start/stop in+10/+14; reference video constructs them in+18/+1c.

`tools.research.uvc_registration_guard_probe` executes the ORIGINAL a6400 guard
instructions over explicit descriptor fixtures. Native-layout callbacks pass
to the pre-allocation boundary602b865c. Reference-layout fixture, missing-start
and missing-stop controls reach rejection602b872c. No full registration,
allocator success or callback invocation is supplied. Four controls pass.

The first40 bytes of usb_gadgetcore_is_ep_alive match between the two preserved
kernels. Endpoint alignment code also has similar structure, but logs/calls/
addresses differ; it is not declared whole-function identical.

## Original dispatcher ABI and decoded kernel symbols

`tools.research.decode_kernel_kallsyms` independently recovers legacy absolute
address arrays, bounded compressed name records and256 validated token strings.
It decodes24600 a6400 symbols and24519 reference symbols with source hashes.
Reports are `a6400-kallsyms-checked.json` and `zve10-kallsyms-checked.json` in
the final audit directory. This enables exact static function boundaries without
guessing reference address deltas or executing kernels.

Comparison with retained E0133 live kallsyms uses a multimap because local names
can repeat. All decoded names occur in the live map.15441 address entries match;
9159 r/R read-only-symbol entries differ. No t/T function-address difference
occurs. This is symbol-layout corroboration, NOT equality of live kernel bytes
or authorization to use preserved read-only-data addresses on the camera.

Recovered startFuncDrv_fromIfClasses:

| Item | a6400 | ZV-E10 |
| --- | --- | --- |
| Function start |602b8e38|602bd2ec|
| Descriptor state byte written |+0c|+14|
| Start callback read |+10|+18|
| Stop before original BLX |602b8efc|602bd3b0|

Two ORIGINAL dispatch-tail controls execute the state/list writes and argument
loads on explicit prior-state fixtures, stopping BEFORE callback invocation.
Both yield r0=descriptor pointer, r1=speed fixture2, r2=interface fixture3,
r3=original incoming configuration fixture12345678, ip=callback fixture11110000.

This matters: r0 is the driver descriptor itself, NOT simply its private-data
pointer. A callback bridge must preserve/translate descriptor identity and the
state byte as well as callback offsets. Copying callback pointers into a smaller
struct would not establish a valid reference callback invocation. Probe header
fields and all stop/class/halt/lifetime paths still require verification.

## Built candidate: private video node only, NOT deployable

New explicit MOD source: `tools/native_camera/uvc_reference_node_shim.c`.
Build tool: `tools.research.build_uvc_node_candidate`.

Verified build:
`artifacts/native/uvc-node-checked-candidate-e0135/manifest.json`.
Earlier isolated build remains under `uvc-node-candidate-e0135`.

The build renames the reference module's single undefined udif_devnodes symbol
to a6400_uvc_devnodes, compiles a private ARM32 table with entry55=`usb/video`,
major248/minor33/count1, partially links and localizes that symbol. It checks
the proposed tuple against the preserved a6400 table and verifies the old
kernel-table dependency is removed. It does not edit the camera table or
replace devno.ko. The source name and tuple are explicit MOD data.

Original `.text`, `.init.text` and `.exit.text` bytes remain EXACTLY equal to
reference input. The object resolves only the node collision; it deliberately
keeps the unsupported callback layout. Output is named
`usbg_video.node-only.offline.o`, not an installable release. Manifest sets
deployable:false/deployed:false. Do not insmod this object. No physical UVC
function, descriptor registration or live JPEG producer is established by it.

## Next concrete boundary

Implement a separate descriptor/callback bridge only after matching probe
header meaning, all callback argument contracts and descriptor state ownership.
The original kernel's r0 descriptor argument requires per-registration identity
mapping and reverse translation on callbacks/unregister; no blind8-byte shift.
Then verify endpoint and DMA330 object layouts, cache and completion semantics,
unregister/cleanup/rollback and a6400 receiver01670464 before a combined staged
payload. Audio remains a separate optional port; a video-first720p target is
appropriate. Existing MSC debugger must remain recoverable through any future
USB configuration transition. No further physical action was requested.

Checks: offline node-only ARM build passes;4 original guard and2 original
dispatcher controls pass; all599 project tests pass in16.792s. New tools compile.
No guest execution behavior was replaced and no camera compatibility percentage
is increased by these static/fixture results.
