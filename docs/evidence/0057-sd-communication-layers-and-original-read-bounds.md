# Evidence 0057: SD communication layers and original read bounds

## Scope and result

The user's latest instruction is to investigate **communication with the SD card and disregard injection work**. Current work follows device-path discovery, media opening, callback dispatch and the original block-read path. No card/camera writes, updater execution, payload generation or injection research occurred. Card E:\ remains the read-only source inventoried in E0056; this milestone did not need another acquisition.

Five native WSL REA batches completed **34 queries**, with original ELF/planner checks and unchanged source hashes. A separate isolated original ARM experiment verifies three rejected read controls and stops a valid request at an unimplemented helper. This is **not** a completed media mount, sector read, controller exchange or main-process/UI advance.

## Inputs and coordinate systems

All four inputs are preserved installed firmware software under `nflasha15_unpacked`:

| Input | SHA-256 |
| --- | --- |
| kmod/mmc_drv.ko | b150c666ee29567e920e156b8a5def8307d04c51b799956cdd74fcf5c55211cf |
| lib/libInfraMediaCommon.so | e03083e92240f752959449ccf7aaca185a937d14f34902eda39b9ee76850b86c |
| lib/libInfraMediaDetect.so | c983799c8a7647797c6f4072821dbe7c75aca81bcbcdfb41dd4a3ffbf46e7025 |
| lib/libInfraMediaMount.so | bec1c09e6c56ddcb51c0837ccc1d8fde33cc34f01c2d51a9f8a783ca309f84e4 |

Original init contains `/usr/kmod/mmc_drv.ko` and `/usr/kmod/ms_drv.ko` load-path strings, distinct from internal-storage `emmc.ko`. This static observation does not prove which controller/slot is live or which driver completed initialization.

The ET_REL driver uses **.text-relative offsets**; Ghidra places .text at **0x100c4** in these retained imports. Example: mmc_mem_read0x11544 -> REA0x21608; unnamed transfer helper0x16e94 -> REA0x26f58. The user libraries use synthetic bias0x10000; Thumb entry low bits must be cleared for exact Ghidra queries. These are analysis coordinates, not camera runtime addresses.

## Application side: device lookup and media opening

`InfraMediaDetectThreadBase::GetDevicePath` (ELF Thumb0xa3c5, REA0x1a3c4) constructs a0xe4-byte MWF request: word0x1000 followed by halfwords3 and0xcc. It passes the media identifier, calls `MWF::EventWrapper::SendAndRecv`, checks a returned availability byte and copies the returned path. It does not choose a host path or assume an SD device name itself. The responding subsystem and actual path remain unresolved.

`InfraMediaMountThread::Mount` (Thumb0x5a59, REA0x15a58) constructs the same request form and checks the returned availability/path. It then calls `mcmn_drv_open`, `mcmn_drv_setowner`, `mcmn_drv_getinfo` and, conditionally, power-control operations. This function name alone is **not evidence of a Linux mount syscall**. Its reconstructed path opens/manages a media-service handle and updates status.

ELF export inventory identifies `libInfraMediaCommon.so` as the provider candidate for `mcmn_drv_open` and `mcmn_drv_read`. Original `mcmn_drv_open` (Thumb0xbce9) looks up device/root descriptions, allocates and maintains control/handle objects, initializes mutexes and performs follow-up initialization. This is not simply a wrapper around Linux open.

Original `mcmn_drv_read` (Thumb0xc37d, REA0x1c37c), checked with retained instructions, locks the two root synchronization objects, starts access logging and checks the device read callback at **device-control+0xcc**. A null callback/rejected operation takes an error path. Otherwise it calls the registered callback, logs the result and unlocks. The runtime callback producer/identity and downstream userspace-to-kernel bridge remain open; no callback pointer or successful reply was supplied.

## Driver side: request routing and SD/MMCP read command setup

Dependency plans `sd-mmc-read-plan` and `sd-mmcp-plan` retain original instruction/relocation edges before new REA analysis. The first contains10 functions; the second5. Both explicitly retain unresolved/indirect edges.

`mmcd_blk_request` (.text0x3014) converts a minor to a hardware index, inspects driver state, waits if required, takes a mutex on the applicable branch and calls an internal dispatcher. That dispatcher (REA0x13008, .text0x2f44) invokes a request callback indirectly and has a retry path. Neither the live descriptor table nor callback connection to the MMCP operation is established by this static analysis.

The driver has distinct MMC and MMCP branches. The initially examined `mmc_mem_detect` programs command1; it is not sufficient evidence for SD initialization. `mmc_mmcp_detect_each` issues command2/3/9 setup and extracts CSD-related fields, with UHS-related helpers present. Names/support branches do not establish the attached camera/card's negotiated mode or speed.

Original `mmc_mmcp_read` (.text0x17070,36 bytes) sets the fifth argument to **3**, then branches to unnamed transfer helper **.text0x16e94**. The original helper:

- rejects zero counts, unsigned sector+count overflow and ranges above its capacity field at state+0x2dc;
- calls an unsupported preparation helper before command construction;
- conditionally shifts the address left9 according to stored addressing mode;
- chooses command **0x11 (17)** for one block and **0x12 (18)** for multiple blocks when selector3 is passed; the other selector branch uses24/25;
- constructs a transfer descriptor with block length **0x200 (512)** and count masked to16 bits, then dispatches further.

These observations are supported by retained original instructions and REA reconstruction. The negotiated addressing mode, actual capacity, transfer limits, preparation/locking, DMA ownership, MMIO registers, card responses and completion are **not** supplied. In particular, the16-bit count mask alone is not a verified maximum legal request size; upstream splitting/validation still needs investigation.

## Original read-bounds execution

New `tools.research.sd_read_bounds` verifies the original wrapper's branch target and executes only the original .text0x16e94..0x16fe0 window. The next named function, `mmc_mmcp_write`, establishes the window end. The first attempted run rejected an incorrect end-coordinate assumption; a second rejected unresolved relocations. Both attempts stopped before target execution. They are retained as separate empty output directories. Final execution guards each relocated word instead of treating an unlinked instruction as executable.

Isolated mapping0x01000000, constructed stack/state, capacity control **1024**, selector3 and buffer pointer are explicit research inputs. They do not describe card E:\ or current camera RAM. Only the capacity word and explicitly initialized/written stack bytes may be consumed; source code bytes are known except relocation words. Non-stack writes, unknown reads, unresolved instruction relocations and unmapped accesses stop. Limit200 instruction events/100ms. No original driver lock or card response is simulated.

| Constructed sector/count/capacity | Original events | Result |
| --- | ---: | --- |
| 0 / 0 /1024 | 14 | returns0xffffffff (-1) |
| 0xffffffff /2 /1024 | 17 | returns-1 |
| 1023 /2 /1024 | 21 | returns-1 |
| 0 /1 /1024 | 18 | reaches unsupported preparation helper .text0x16328 |

The valid control stops on instruction fetch outside the supplied window, not on a successful read. No command or physical SD access is executed by this experiment. Earlier diagnostic `sd-read-bounds-final` recorded that same fetch as an execution fault; final `sd-read-bounds-guarded` / `sd-read-bounds-repeat` retain the explicit unsupported-access boundary and are byte-identical, SHA-256 **1e21c411c21cb8a1131c0f7e535534d6a53b0ecf02ffdd55517c97f5cb75432f**.

## Reproduction, REA and validation

```
python -m tools.research.dependency_plan --target firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/mmc_drv.ko --function mmcd_blk_request --function mmc_mem_read --function mmc_mem_detect --depth 1 --max-nodes 14 --report-dir artifacts/analysis/NEW_PLAN
python -m tools.research.sd_read_bounds --report-dir artifacts/execution/NEW_BOUNDS
```

Completed REA batches: `plan-68b39dedeba2314e-0`20 queries; `sd-mmcp-read-path`6; `sd-media-mount`3; `sd-media-device-path`2; `sd-media-common-exact`3. The first `sd-media-common` batch failed on an ambiguous PLT/implementation name and is retained failed. Exact common-library entries0x1bce8/0x1c37c resolved the ambiguity. All completed manifests report unchanged input hashes; no failed batch is called completed/cache evidence.

Four constructed ARM tests verify rejection of unknown backing state, forbidden writes and unresolved relocations, and distinguish return from instruction-limit looping. Full suite **361 passing tests**, `artifacts/execution/sd-communication-suite.txt`. Status image regenerated without capability-count increases.

Next: find the MWF media-ID-to-device-path responder, register/trace the actual read callback at device-control+0xcc and follow the kernel request table to the MMCP read entry. Independently establish .text0x16328 preparation effects and host-controller/DMA completion contracts. Keep static support, isolated CPU execution and observed physical card communication distinct.
