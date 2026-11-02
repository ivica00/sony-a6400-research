# Evidence 0034: Stream device ABI and graphics allocator boundary

## Result

The optional **`--stream-device image-driver`** policy opens the original `/dev/stream` node, implements its verified offset ioctl and supports a bounded, guarded physical mapping contract. The default `stop` policy preserves the previous boundary.

Fresh `im.elf i` execution advances from **42,443,456** to **42,465,243 instructions**, supplies **659 syscall responses**, and opens `/dev/stream` twice in worker TID **1003**. It stops at syscall **268 (`tgkill`)**, arguments `(1000, 1003, 6)`, after the original application requests **SIGABRT**. Captured stderr states:

```text
im.elf: dmp_allocator.c:116: dmp_allocator_lib_init: Assertion `e == MA_ErrNone' failed.
```

**No stream ioctl or stream mmap is requested by this process run. No `/dev/fb0` open, mapping or framebuffer transaction occurs.** Those stream operations are verified through original isolated instruction windows and constructed tests, not claimed as exercised by DDS startup.

Opening the stream device does not establish successful `gl_common` initialization. The name appears in allocator messages before its required service semantics are supplied. Current generic UIPC acknowledgements do not execute the graphics allocator recipient. Ignoring the assertion, returning a fabricated allocation or ignoring SIGABRT would conceal that dependency.

## Inputs and policy

| Input | SHA-256 |
| --- | --- |
| `usr/kmod/stream.ko` | `ffc101d7ca5ed0c4417d6570352b31aa6d1e48bba3055494796afb527c6a8ff3` |
| initrd `kmod/devno.ko` | `3b36fcea8687d7f29112a7008ce61fde9229679ebc24c65ec2d21cf3af632f56` |
| `usr/kmod/grm_ma.ko` | `4bd42001061c8c6f163ede217b0cadf117f2e9f4e23723c0658ac5c3d29f163f` |
| `usr/kmod/dmm.ko` | `c5cb62579f4719bed9248b8e3dabe4d95c6fa57481e07908f10b68098e54a74f` |
| `usr/lib/libObj.so` | `60ffd2b0f31f4bc139a7c13a4f62c25cdeb6a531ad5ef35df48471e6e36e88b1` |

Inputs are checked against the preserved ELF inventory. The rootfs image's original ext2 inode **287**, mode `020777`, also encodes character device **249:7**. `devno.ko` row 35 (`.data+0x1a4`) names `stream`, character major 249, base minor 7, count 1. `stream.ko`'s cdev descriptor references this exact row, its operations table and its four-byte `.bss` offset state.

The process comparison retains the existing selected environment: `--backup-service preset-backed`, deterministic entropy, read-only image inode policies and **`--tmp-overlay experimental-empty`**. The `/tmp` overlay is invented experimental state, explicitly distinct from the real writable vfat mount on `/dev/nflasha10` described in E0033. This is not an authentic full boot or validation of actual saved settings, entropy or mount contents.

## Implemented stream subset

`GuestStream` is independent of research-tool implementations. The research launcher verifies input identities and descriptor relocations before selecting the contract. Selecting the compiled device registration/reset state remains an experimental process-environment choice; it is not observation of a camera's already-running global state.

- **Open:** accepts the observed `O_RDWR | O_DSYNC` value **4098**; no original open callback is present in the selected operations table. Other flags stop explicitly. Descriptor exhaustion returns `-EMFILE` without creating a descriptor. Guest path reads use bounds and provenance checks.
- **Ioctl `0xc0047801`:** copies exactly four bytes from the modeled module-global mapping offset. The compiled `.bss` initial value is zero. After a supported successful mapping, the value is `abs(user_virtual_start - (pgoff << 12))`, as the original ARM instructions compute. Unsupported commands return the original **`-EINVAL`**.
- **Copy limits:** the original callback ignores `copy_to_user`'s residual and returns zero even along its failed access-check path. This implementation does not invent an `-EFAULT` response or pretend a copy succeeded: an inaccessible output buffer stops before writing. Guest output writes clear only the overwritten provenance.
- **Mmap:** accepts a bounded, single `MAP_SHARED` mapping, optionally `MAP_FIXED` onto unoccupied pages, with read/write permissions and a non-overflowing ARM32 PFN range. Physical offset comes from the actual `pgoff`; it is not replaced with zero. Code execution, replacement of existing pages, physical aliases/multiple mappings, unsupported flags and excessive ranges stop explicitly.
- **Physical content:** host storage is an implementation detail, not supplied physical zeroes. Every byte starts unknown. CPU reads and the shared filesystem/UIPC/stdio host-read paths stop before accepting unwritten bytes. Successful guest writes release only those overwritten bytes. Failed stores to read-only pages do not release provenance. Device pages cannot be discarded as private anonymous memory through `MADV_DONTNEED`.
- **Other file operations:** read/write/lseek/fstat on the stream descriptor stop explicitly; close uses the existing descriptor close path. The offset belongs to the modeled device, not an individual descriptor, and is not reset by close.

The original mmap callback also changes page attributes and VMA flags around `remap_pfn_range`. These instruction observations are retained, but cache coherence, DMA, kernel remapping execution, allocation ownership and timing are not modeled or claimed. Physical initial contents remain a separate input contract.

## Original instruction checks

`python -m tools.research.stream_contract` reproduces hash-checked identity extraction and the bounded ARM windows in `artifacts/execution/stream-contract.json`:

- **15 original instructions** construct the `remap_pfn_range` call, stopping before it.
- Two explicit successful-remap controls each execute **13 original instructions** after that call, validating both signs of the virtual/physical subtraction. The supplied result is labeled a constructed control, not a successfully executed kernel remapper.
- The ioctl window follows the original command checks and callback/private-pointer indirection to the **four-byte `__copy_to_user` call boundary**. That external kernel copy is not executed in the isolated slice.

The tool also retains original symbol/relocation instruction records for the stream, GRM allocator, DMM and relevant `libObj.so` consumers. Constructed section/context/VMA/stack addresses are not camera runtime addresses.

## Why DDS does not reach fb0 yet

REA successfully analyzed `stream.ko`, `grm_ma.ko` and `dmm.ko` in separate shared WSL/Ghidra sessions. Retained manifests and structured Evidence are under `artifacts/tools/rea/stream-contract`, `stream-grm-ma` and `stream-dmm-dependency`; `stream-rea-audit.json` binds the retained query identities to their targets.

The original `grm_ma.ko:ma_init` registers synchronous recipient **`0x014c0424`** with `ma_user_sync_cb`. The callback dispatches operation **7** to name lookup, **1** to DMM-backed opening and **9** to allocation. All three request types occur in the retained process trace. Their real result structures, pointers and allocation side effects are not supplied by generic transport acknowledgements.

`ma_dmm_open_send_recv` connects allocation opening to DMM queue **`0x0061003c`** and waits for a correlated reply containing the allocation information. The current execution environment does not execute that GRM-MA/DMM exchange. The original DMP allocator consequently reaches its assertion before requesting stream mapping or framebuffer initialization. This is the next implementation dependency, not evidence that the stream ioctl needs an arbitrary constant or that SIGABRT should be ignored.

DMM analysis exposes both its configuration-loading routines and a default optional extra-file path `/setting/DmmConfigExtra.bin`. This observation does **not** establish that this file is selected or mandatory in the failed run. Continue with `dmm_module_GetConfigData`, unit `0x280` and the real opening/allocation reply contract before deciding which physical state is needed.

The full `libObj.so` REA import hit its **330-second analysis limit** and is retained as failed under `stream-dds-consumer`; no pseudocode from that failed session is claimed. Targeted original ELF/Thumb disassembly supplies the consumer evidence instead. `DDSUserInit` and `ObjDisplay_Create` are identified symbols; identification is not evidence that their initialization completed.

The preexisting framebuffer model has unverified geometry/backing defaults. Its module documentation now labels it experimental; this run does not validate or use those defaults. Reaching an eventual fb0 request will require checking the actual framebuffer driver's state and memory contract before claiming authentic mapping or pixels.

## Reproduction and verification

```powershell
.\venv\Scripts\python.exe -m tools.research.stream_contract
.\venv\Scripts\python.exe -u -m tools.research.experiment_ui_boot --argument i --stimulus none --backup-service preset-backed --urandom-open --urandom-entropy deterministic --regular-inode-rdev --readonly-image-times --tmp-overlay experimental-empty --stream-device image-driver --instructions 70000000 --timeout-us 400000000 --report artifacts/execution/stream-driver-run.json
.\venv\Scripts\python.exe -m tools.research.report_summary artifacts/execution/stream-driver-run.json --tail 10
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Preserve old reports or select a fresh report name when reproducing. The initial baseline suite had **286 passing tests** (`stream-baseline-suite.txt`). The final suite has **300 passing tests** (`stream-contract-final-suite.txt`): 14 new tests cover ioctl output extent, error/permission paths, both mapping delta directions, PFN bounds and flags, ownership, unknown-byte reads, actual ARM stores/loads/syscalls and prevention of stdout copying unwritten physical bytes. The default no-response process probe remains **1,183 instructions**, zero responses.

`stream-driver-run.json` records the first process continuation; `stream-driver-repeat.json` retains the final implementation's repetition. **Both complete reports are byte-identical**, SHA-256 `8ffea650a1d62f98d44398ff7dc748069329e3b19bfdc416612c1d31c54b7d85`. `stream-run-comparison.json` records the matching status, instruction/response counts, boundary, registers, stderr and device observations. `stream-contract.json` is reproducible without REA. The regenerated status image records the stream-open/allocator boundary and claims no camera UI. Checklist totals are unchanged.
