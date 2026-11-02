# Evidence 0058: Registered SD read ioctl and original preparation state

## Result and scope

The emulation contract is now more precise: the installed MMC media adapter assigns its read callbacks, and its selected low-level read uses **ioctl0x10f**, not the library's generic `lseek64/read` implementation. Original kernel dispatch recognizes that same ioctl and its16-byte/status layout. A bounded original ARM continuation now reaches the first unknown card/host reference in preparation, after **23 original instruction events** for the valid control.

The user reaffirmed correct firmware emulation as the objective. This work implements/researches explicit contracts and initialization dependencies; it performs no injection, vulnerability investigation, camera operation, updater execution, host SD ioctl or card write. Card E:\ was not accessed again. Main process/UI and physical SD communication remain unadvanced; none of the static callbacks is installed as a fabricated successful process service.

## Original registered callback chain

Inputs are the same hash-checked installed `libInfraMediaCommon.so` and `mmc_drv.ko` from E0057. Source identities are retained in every report and rechecked after analysis. New `sd_callback_profile` verifies original PC-relative pointer calculations and exact following stores in `mcmn_drv_mmc_open`:

| Device-control field | Original Thumb function pointer | Ghidra exact instruction entry |
| --- | --- | --- |
| +0xcc | 0x12869 | 0x22868 |
| +0xd0 | 0x117d1 | 0x217d0 |

Original pointer producers at0x134e0/0x134e4 produce these values; stores at0x134e6/0x134ec put them into fields+0xcc/+0xd0. This is source-backed setup on the successful open path, **not evidence that a live device finished opening**. `mcmn_drv_mmc_open` first opens a device-description path with original flag value0x90002, stores its descriptor at device-control+0x40, and sets block size+0x58 to512. The actual description/path, fd and media state remain unknown.

The resulting original call topology is:

```
mcmn_drv_read
  -> registered +0xcc wrapper (0x12869)
     -> media readiness/preparation helper
     -> mcmn_drv_default_read (0xeb81)
        -> registered +0xd0 implementation (0x117d1)
           -> ioctl(fd, 0x10f, request)
```

`mcmn_drv_default_read` checks media flags/block size and buffer alignment, can split requests according to configured limits, and has an intermediate-buffer/copy path for unaligned destinations. Its called callback is the configured+0xd0 field. **Do not substitute `mcmn_drv_default_read_impl` (0xed89)**: that separate generic implementation uses `lseek64/read`, but it is not the pointer assigned here. An early commentary observation in this turn described that generic path; subsequent original assignment/registered-function verification resolves the distinction.

The selected0x117d1 implementation logs, builds the following stack request and calls ioctl0x10f. It checks both syscall result and the returned status word; a transport return alone is not a successful read.

| Request byte offset | Original field |
| --- | --- |
| 0 | status, initially zero before ioctl; driver writes result |
| 4 | destination buffer pointer |
| 8 | starting logical sector |
| 12 | number of sectors |

`mcmn_drv_mmc_mount4sd` separately uses ioctl0x10e, checks its returned status and copies0x6c bytes of returned information. These requests were not sent to either the host reader or an emulated device.

## Matching kernel descriptor and dispatch

The preserved driver's unique aligned `.data+0x138` descriptor contains original words **[0x10f,16,0]**: command, request size, status offset. `sd_callback_profile` checks its uniqueness. REA's descriptor lookup helper (Ghidra0x123d8 / .text0x2314) searches25 twelve-byte descriptors. This independently supports the user wrapper's16-byte request layout.

Original `mmcd_blk_ioctl` (.text0x3fa0) takes the applicable mutex, resolves the descriptor, allocates/copies the request under kernel user-address rules, checks card/driver state and dispatches0x10f with direction selector0 to the internal range/serialized-transfer helper (Ghidra0x13500 / .text0x343c). It copies the response back and cleans up. Thread address limits, waits, allocation, callback state and locks remain unsupplied runtime dependencies.

That helper checks LBA against the summed configured extent length and count against remaining length, then invokes the next transfer helper. On a rejected range it writes **-3 into the request status** and returns0 from the ioctl handler path. This is a static original-code observation, not a supplied emulated result. It establishes why ioctl return0 must not replace device status. Further serialized-transfer/callback wiring to MMCP still needs validation.

User-library strings include `/dev/mmca`, related partition-style paths and `-char` paths. Their existence does not select the live slot or authorize assigning a path/major/minor to the process probe. The MWF media-ID/path responder remains unresolved.

## Original preparation continuation

E0057's valid control stopped before original .text0x16328. REA verifies its actual prerequisites: read the card-state object's first word, call `mmc_hw_wrapper_lock_sem`, compare card-selection state through+0x278/+0x290, and conditionally configure width/clock/select-card state before returning. The semaphore call result and those state fields cannot be replaced with assumed success/current state.

`sd_read_bounds --preparation-prefix` adds only the original .text0x16328..0x163d8 window to the bounded CPU experiment. All selected source bytes and relocation words retain provenance guards. The original direct helper branch reaches this window without a synthetic return or redirected branch.

- Three invalid controls still return-1 after14/17/21 original events.
- Valid constructed sector0/count1/capacity1024 now executes **23 events** and stops at original **PC0x16338**, `ldr r0,[r0]`.
- The unknown address is the first word of the **constructed** state object0x08200000. No host/card reference is placed there. Semaphore execution has not begun.

Capacity1024 remains a research control, not E:\ capacity. Original stack stores are allowed; other state writes, unknown reads, unmapped accesses, unresolved relocations and unsupported code still stop. Additional code windows cannot overlap or escape the isolated code region, and mapped page padding is not accepted as instruction bytes. There is no supplied clock, DMA state, hardware register response or read result.

Default mode still produces E0057's byte-identical report hash **1e21c411c21cb8a1131c0f7e535534d6a53b0ecf02ffdd55517c97f5cb75432f** (`sd-read-bounds-regression`). Preparation reports `sd-read-preparation-first` / `sd-read-preparation-repeat` are byte-identical, SHA-256 **5be6a98c4d74ff937e321567229a4e312f0444f133fdfc8c8d2a2721048d4d34**. Callback profiles `sd-callback-profile-verified` / repeat are byte-identical, SHA-256 **338a1198956f906e761a6fdc382e3a32d758169d6f4021df26da800720ec2673**.

## Reproduction and validation

```
python -m tools.research.sd_callback_profile --report-dir artifacts/analysis/NEW_CALLBACK_PROFILE
python -m tools.research.sd_read_bounds --preparation-prefix --report-dir artifacts/execution/NEW_PREPARATION
```

New completed native WSL REA batches total **18 queries**: `sd-callback-provider`6, `sd-read-preparation`2, `sd-mmc-registered-read`3, `sd-read-ioctl-dispatch`3, `sd-read-ioctl-contract`4. Exact library entries use Ghidra bias0x10000; driver .text uses base0x100c4. All completed manifests preserve unchanged hashes. Planner cannot identify an unnamed containing function for .text0x16328; `sd-preparation-plan` was rejected rather than inventing a graph. `sd-ioctl-plan` retains three named ioctl functions, original instructions and unresolved dependencies before the new queries.

One new constructed ARM test verifies additional code windows retain unknown-state/relocation guards and reject overlap. Existing tests and invalid/default controls remain unchanged. Full suite **362 passing tests**, `artifacts/execution/sd-callback-final-suite.txt`; status image regenerated with unchanged capability counts.

Next for emulation: trace the serialized ioctl transfer to the selected card operations table, establish the producer of the card-state first word and semaphore/control state, and resolve the MWF device-path response. Only after those prerequisites are known should a selected SD contract supply sectors/completion to original firmware. This is a contract-completeness boundary, not a security-review block.
