# E0302 — clone-derived GLES identity, `/dev/stream2` and the next memory boundary

Date: 2026-11-10. Offline firmware execution only; the camera was used only for
read-only `/proc`/`/etc`/`maps` evidence by a teammate. No physical write, mode
switch, `/dev/stream` open or SD write. **No emulator GUI frame is established.**

## Team findings used here

* **U1/E1:** the DataflowInfra symbol is referenced only by `libObj.so`
  (`R_ARM_JUMP_SLOT` at `0x136B0A8`) and defined only by
  `dataflowInfraFramework.so`; at the `e0302-cont` stop it is in libObj's
  42-entry searchlist and the 73-entry global list, the provider GNU hash finds
  it (bucket 972 -> 974), and the GOT slot is still the PLT0 lazy stub. UIPC is
  not the cause (the last transaction is the received DMM completion). The
  stop is guest ld.so `writev` + `exit_group(127)`.
* **C1:** camera PID149 argv is the full `im.elf debug s g r u l i a lazy-global`;
  its environment has **no `LD_*`**; `/etc/ld.so.preload` contains only the two
  authorized `/setting` debug payloads. `/dev/dmpgles2` is an 8 KiB `rw-s`
  mapping; OSD A/B map `/dev/stream` at `0x23a80`/`0x23b16`. The camera libObj
  build differs from the extracted image (first LOAD +0x940), so camera GOT
  offsets are not an identity-matched binding reference.
* **G1:** `C_DataflowInfra_Entry_OsdMute::SetData_All` is a 16-byte OSD-mute
  data setter (not a renderer) on the VDF/OSD control path; the OSD A/B writer
  is the mcmn/DMPNative window path and GPU composition is most strongly
  supported; no CPU frame writer was found.
* **R1:** GRM telemetry records only 5 requests before the loader gate (one
  `gl_common` findbyname, four DMM unit `0x0E1700` requests); no OSD/"empty"
  pool request. `unit 0x4092E` is the unexecuted OSD-pool watch candidate.
* **G2:** the fresh-run GLES stop is a stale fixed fixture: the kernel task
  record was hard-coded `pid=1003`, while the fresh clone-order opener is
  `1011`. The guard itself was correct.

## Verified change: per-thread kernel task observation

`KernelTaskIdentityTable` registers a task record at each emulated `clone`
(`pid=child_tid`, `tgid=process_id`, evidence-backed thread_info/task backlink
and `0x5F000000` address limit). `GlesBinding` resolves the record for the
actual caller; an unobserved caller is still rejected. The stale constant is
removed; the backlink/limit/range checks and `require_caller` are unchanged.
The checkpoint path rebuilds the table from its recorded 51 TIDs (opener 1003
still passes); the fresh run registers 54 TIDs (opener 1011 passes).

## Bounded runs

| Run | Result |
| --- | --- |
| `e0302-cont` (from `boot-e0301-live-receiver.ckpt`) | 224,338,158; `exit_group(127)` after the DataflowInfra symbol lookup; 51 threads |
| `e0302-bindnow` (fresh, `LD_BIND_NOW=1`) | labelled experiment; THREAD_INFRA0 library-load loop, 9 threads; not a fix |
| `e0302-preload` (fresh, `LD_PRELOAD=dataflowInfraFramework.so`) | labelled experiment; early malloc abort; rejected |
| `e0302-fresh-lazy` (fresh, no env) | 146,035,171; `/dev/dmpgles2` identity stop (guest 1011 vs fixture 1003) |
| `e0302-gles-table` (fresh, per-thread table) | **GLES open accepted**; 185,358,896 / 54 threads; `/dev/stream2` open flags `0x1002` stops at the read-only filesystem gate |
| `e0302-stream2` (resume, `--stream2-device open-only`) | `/dev/stream2` (249:8) open accepted at fd 29; 185,772,548; next stop is a `memory_boundary` write at `0x5034...` (PC libc `0x5026ec2c`) |

The GLES stop is gone and the fresh path now starts the app/UI infrastructure
threads (`THREAD_INFRA1/2`, `UsbControl`, `UsbBusPower`, HDMI/CEC, `IFsys`,
`IMM`, ...). OSD A/B remain unmapped; `viewUnified2` has not loaded.

## `/dev/stream2`

The original 249:8 character node is in the image. `--stream2-device open-only`
accepts exactly `O_RDWR|O_DSYNC` (`0x1002`/`0x21002`), records the fd, and stops
at the first ioctl/mmap/file operation with an explicit
`stream2_*_not_supplied` boundary. This is an observation policy, not a
modelled stream ABI; physical bytes remain unspecified.

## Next boundary

The resume at 185,772,548 stops on an unmapped write in libc
(`0x5026ec2c`, `strb` to `0x5034...`, value 3). It is after the stream2 open
and before any stream2 ioctl/mmap, so the missing contract is either the
buffer/ownership around the stream2 fd or an unrelated app pointer. The next
step is an observation-only memory/stream trace at that PC, then the stream2
ABI; the checkpoint-path lazy symbol remains separate. Do not load the provider
earlier, force `RTLD_GLOBAL`, patch the GOT or host-inject a task.

## Update: the Dataflow symbol gate is resolved at the emulator CPU contract

E3 captured the failing loader lookup: the provider is in scope, but
`_dl_fixup`'s unconditional `mov r4,r0` at ld `0x4000A6F8` was skipped after a
Thumb-2 IT block, leaving `r4=1`; the lookup then searched `undef_map=1`,
`scope=0`, and the undefined-symbol fatal path used the `rtld_progname`
fallback. The fix is the same emulator IT-state workaround family: clear the
CPSR IT/JIT bits at `_dl_fixup` entry `0x4000A6F4` **and** make the intended
`r4=r0` explicit before the skipped move. With that workaround the checkpoint
path resolves the symbol and advances from 224,338,158 to **231,909,376**
(55 threads), opening `/dev/dmpgles2` (fd 27) and `/dev/stream2` (fd 29) and
reaching the media path. This is an emulator CPU-contract repair, not a symbol
injection, preload, RTLD change or GOT patch.

The next stop is `open("/dev/nflasha4", O_RDWR)` under the read-only filesystem
policy: the app's media initialisation now needs the internal-flash block
device. The project boundary is read-only/observation only; the
`/dev/nflasha4` role, partition image and first ioctl/read are the next
evidence-based contract. Do not enable writable internal flash.

The 185.77M libc `tzset` stop was also a CPU-state/branch defect: U3 proved
`0x5026EC2C` is a literal-pool address, U3b showed the Thumb function's
`pop {r4,r5,r6,pc}` at `0x5026EC26` delivered execution into its own literal
pool, and the same IT-state workaround family was extended to that function.
The checkpoint path did not re-hit it; the fresh path must be re-verified.

The restored `GrmMaService` now defaults `telemetry_policy`/`telemetry` in
`__setstate__`, so pre-E0302 checkpoints continue without reply changes.

## Round 5: `/dev/nflasha4` MPR boundary

The fixed checkpoint path reaches **231,909,376 / 55 threads** and opens
`/dev/dmpgles2`, `/dev/stream2`, then `/dev/nflasha4` O_RDWR (fd 31). U4/C4
verified the node is block `252:4`, the raw 12 MiB internal-flash **MPR
partition** (`mount.conf`: `none raw 12582912`, no mount point, `ro=0`), opened
by the original `libmpr` `DFA::OpenDriver` and also held O_RDWR|O_LARGEFILE by
the real camera PID149 (fd 29, pos 81920). The updater erases it
(`ERROR_MPR_ERASE`); there is no nflasha4 image in the preserved firmware, so
the read-only policy is observation-only, not fidelity.

The explicit `--nflasha4-device open-only` policy accepts the observed open,
answers `lseek(SEEK_END)` from the verified 12,582,912-byte size, and stops at
the first flash operation: **ioctl `0x80014123`** (`_IOR('A',0x23,1)`,
`emmc_seq_get_erased_mem_cont` + `__put_user_1`), a read-only erased-state
query. The emulator correctly does not fabricate the one-byte result. A VBUS
UIPC injection at this state woke the four UIPC proxies but the MPR init on
THREAD_INFRA1 still blocks the startup sequence; no OSD/view. G4 classifies
nflasha4 as a side media path, not the OSD critical path, but the app's startup
order still waits on it.

All five teammates were employed this round: U4 (MPR role/policy), E4 (IT/GRM
tests), G4 (view/OSD after media), R4 (GRM telemetry after nflasha4; no new
GRM/DMM requests), C4 (camera read-only nflasha4 evidence). The
`unsupported_nflasha4_contract` status is now retry-safe in checkpoint
metadata. Full suite: **854 tests OK** (18.1 s) after the E0303 USB/UIPC/
otgcore contracts. See the short readiness note
[E0303](0303-usb-uipc-otgcore-uvc-ptp-readiness.md).

Next: an authorized read-only MPR content dump is required before the read-only
ioctl/read path can be served truthfully; writes/erase/fdatasync to internal
flash remain forbidden. Alternatively continue the USB/view lane, but the
current app thread is blocked on MPR.

## Checks

Full suite: **854 tests OK** (18.1 s). New focused tests cover the per-thread
table (registered/unobserved caller, tgid/range rejection, clone registration,
pickle round-trip), the guest environment field, the loader-stop summary and
the existing stream/GLES contracts. Earlier team runs: E1 819 tests OK (its
UIPC/checkpoint test included), R1 43 focused GRM tests.
