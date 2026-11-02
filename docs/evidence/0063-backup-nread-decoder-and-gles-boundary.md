# Evidence 0063: Backup reads, reply queue wakes and original GLES prerequisites

Date: 2026-10-24

## Result

The process now services backup operation 30 (`Backup_nread`) under the existing
explicit `preset-backed` policy. Two process experiments with a 150,000,000
instruction budget stop at **80,739,451 instructions**, opening `/dev/dmpgles2`
with flags 2 (`O_RDWR`). The prior unsupported operation-30 boundary was
80,737,298 instructions. The new boundary is reported as `unsupported_filesystem`,
reason `open_flags_not_read_only_subset`; this is an unsupported GPU device,
not an instruction to enable general filesystem writes.

There are **zero framebuffer transactions**, no mapped framebuffer VRAM and no
`gui_first_frame.png`. No display, GPU rendering, full kernel or camera fidelity
milestone is claimed. No card/camera writes, updater execution or injected queue
messages were used.

## Input identities and retained analysis

| Input | SHA-256 |
| --- | --- |
| `backup.ko` | `63c69e991a8da77e301a7090c8ba6e4dcced43921e88415e3591cf0e96dbb2c6` |
| selected `CX62600_UC2.bin` preset | `241c8521035bc9ff1edbe66cf3d42d81879a4bef8ff9e21cbfb84530a1446154` |
| `grm_gles.ko` | `a8d1dbe8c66be365d32371b13f35a0e7d598c415c0ff17f2c8f544084ccc6882` |
| rootfs `devno.ko` | `3b36fcea8687d7f29112a7008ce61fde9229679ebc24c65ec2d21cf3af632f56` |

Dependency plans are in `artifacts/analysis/backup-nread-plan` and
`artifacts/analysis/gles-open-plan`. The backup plan's 12-node cap is recorded as
truncation, not missing firmware. Targeted WSL REA/Ghidra 12.1.4 analysis and
hash/profile-checked retained evidence are preserved in:

- `artifacts/tools/rea/backup-nread-followup`
- `artifacts/tools/rea/backup-nread-core-followup`
- `artifacts/tools/rea/backup-nread-errors-followup`
- `artifacts/tools/rea/backup-next-contracts-followup`
- `artifacts/tools/rea/backup-data-pointers-followup`
- `artifacts/tools/rea/gles-open-followup`

Static decompilation is corroborated by original instruction listings and the
bounded original getter/open/setup execution described below. Reused decompilation
retains its provenance and is not called fresh execution.

## Implemented and corrected backup contracts

Original `backup_osal_call_func` dispatches operation `0x1e` to
`Backup_nread(words[6], words[7], words[8])`: unit, destination and signed capacity.
`Backup_nread` calls the common helper at Ghidra address `0x10a88` with its fourth
argument set to one. `Backup_read` uses the same helper without the capacity check.

The helper returns `0xffffffff` for an absent unit. Otherwise it obtains the
unit's actual size, compares sizes **signed**, copies the entire unit and returns
that size. It does not truncate to capacity. Insufficient capacity calls the
`backup size err` diagnostic and error-service path (`0x109e4`, `0x10a08`). The
model stops before that unsupported path with `backup_nread_capacity_assertion`
and no output mutation; this stop is not an emulated fatal-service completion.

Operations 0 and 2 now expose original `Backup_get_datasize` and
`Backup_get_attribute`: actual descriptor values, or `-1` for an absent unit.
Original `Backup_read_4Byte` returns a word only when the size is exactly four;
it returns zero for absent units and other sizes. The prior implementation
incorrectly stopped on absent units and returned the first word of larger units.
These return contracts are now corrected. Strict `backup-service stop` remains
independent and unchanged.

The request decoder previously unconditionally unpacked nine words. Valid
one-argument and two-argument requests fit 28/32 bytes and could therefore fail
with a host unpacking error. It now reads the six-word header and only requires
the argument words used by each supported operation. Truncated requests stop
explicitly before writes. The compact-message changes are covered independently
by regression tests; the process experiments reached GLES before needing them.

### Preset descriptor offset correction

Original `Data_GetDataPt` always uses the **preset start** plus the descriptor's
low 24 bits. For encoding 0 it skips a four-byte size/vmax header; for encoding
255 it skips a two-byte size header. The previous model added the payload-area
offset again for those two encodings, selecting incorrect sizes and bytes.

`tools.research.backup_read_contract_trace` executes original `Data_init`,
`Data_SearchId`, `Data_GetSize`, `Data_GetDataPt`, `Data_GetVmaxSize` and
`Data_GetAttr` over the hash-checked selected preset, using the earlier bounded
module relocation machinery. The corrected model matches the original results:

| Encoding | Unit | Data file offset | Size | Vmax |
| --- | --- | --- | --- | --- |
| size in descriptor | `0x00020000` | `0x2b6a0` | 4 | 0 |
| extended size (`255`) | `0x00020008` | `0x2b6c4` | 1024 | 0 |
| variable size (`0`) | `0x003e0014` | `0x66b40` | 1 | 4 |

These are explicit package preset contents, not observed current camera settings.
Trace: `artifacts/execution/backup-read-contract-trace.json`, SHA-256
`9d2d240a3da5de35d03d384c32fd2f8d1f22f216c712721e0a0d422c9e267596`.

## Anticipated reply-queue scheduling defect reproduced and fixed

An asynchronous request may cause an existing service model to enqueue its
completion on a different queue. Waking only the request destination leaves a
receiver blocked despite an available completion. A constructed two-thread ARM
fixture using the existing DMM completion path reproduced the missing wake.

After a successful UIPC ioctl, the interpreter also checks queues with blocked
receivers and wakes them when an actual message is queued. It supplies no message
or service success itself. The fixture now observes the original receiver repeat
its SVC and dequeue the completion pointer. Existing direct-send ARM and Thumb
retry tests continue to pass. This proves scheduler integration, not DMM hardware
or GPU fidelity.

## Original GLES device prerequisites and expected next boundaries

The preserved `devno.ko` table identifies `dmpgles2` at table offset `0x318`,
character device **248:29**, count one. `grm_gles.ko` provides the real
`sugilite_open`, `sugilite_ioctl`, `sugilite_register_init` and interrupt handler.

`tools.research.gles_contract_trace` executes five original ARM instructions in
`sugilite_open` (`.text+0x43c`) using explicitly constructed inode/file storage.
It verifies the inode's private device pointer at `+0x190` is written to the
file at `+0xa8`, then stops before `__migrate_disable` at `.text+0x450`. It does
not return a descriptor or supply a kernel lock result.

Static original open code subsequently requires spinlocks, an atomic open count,
the preallocated device area at `device+0xac`, privileged VA/PA translation,
DMA cache maintenance, the current kernel task identifier and an allocated
per-process completion/list record. These cannot be replaced by `open -> 0`.

Original `sugilite_dev_init` assigns register base `0xf1000000`, size `0x4000`,
and allocates a `0x20000`-byte vmalloc area. Character registration requests IRQ
`0x4c` before calling `sugilite_register_init`. Those compiled assignments and
requested resources do not establish completed kernel initialization.

The bounded register-setup experiment runs 17 original instructions and reaches
the first `sugilite_iowrite32` with value `0xffffffff`, destination `0xf10010c0`.
It stops before reading the unsupplied **`outer_cache+0x1c` runtime callback** at
`.text+0x13fc`. No cache callback or MMIO write is executed. The unresolved import
address is an explicitly constructed control binding, not a recovered kernel VA.

Later expected boundaries, supported by static original ioctl code but **not
reached by the process**, include device-private state/queries, mapped register
and buffer ownership, submission/wait paths, IRQ/completion signaling and the
actual GPU command/rendering contract. The driver includes waits and status
consumption; returning generic success or an invented interrupt would not make
them correct. Backup callback registration and multi-read were also inspected;
callback allocation/registration and multi-read side effects remain unsupported,
not speculative successes added to this change.

Trace: `artifacts/execution/gles-contract-trace.json`, SHA-256
`e0e6208dc015187dd09d2fadeb6b9d439f734fa17285aa867f7df3f330df7aca`.

## Process experiments and regression validation

Same selected process policies and argv as experiment 0005; `--stimulus none`,
150,000,000 instruction budget, timeout 3,600,000,000 microseconds. No resumable
80.8M checkpoint was available, so both start from original process entry.

- First read-contract run: `artifacts/execution/ui-boot-backup-nread-150m.json`.
- Repeat after descriptor/read/wake fixes:
  `artifacts/execution/ui-boot-backup-read-final-150m.json`, SHA-256
  `0d38eade5adbda2adfe94210da312ff7b33ef50874468dac68da5c3526b2d110`.
- Both stop opening `/dev/dmpgles2` at **80,739,451** instructions, flags 2,
  syscall 5, PC `1342749796` (`0x5008bc64`).
- Graphic thread remains waiting on UIPC; no drawing commands or framebuffer
  writes are claimed. The selected existing graphics service name
  `authentic-grm` remains a model policy, not independent proof of full fidelity.
- All **411 tests pass**:
  `artifacts/execution/backup-read-gles-final-suite.txt`.

The suite covers bounded/capacity/missing-unit behavior, unmodified destination
tails and preset bytes, all three descriptor encodings against original ARM,
short/truncated requests, reply-queue wake delivery, and both original GLES
prerequisite stops. The new research tools preserve existing reports rather
than overwriting them on CLI rerun. They supply no camera operations.

Next work is original GLES kernel-object initialization and cache/DMA ownership,
then the actual GPU command and completion contract. Existing read-only SD sector
support remains independent; this run does not establish SD-to-renderer routing.
