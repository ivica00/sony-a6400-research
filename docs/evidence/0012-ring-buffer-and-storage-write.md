# E0012 — Ring-buffer dispatch and storage write guard

Date: 2026-10-18. Scope: static identified updater and storage instructions. No updater, synchronization service, kernel request or hardware write is executed.

## Findings

The virtual reader left open in E0011 maps to the updater common library's `RingBuffer::ReadDataWithoutCopy` for the recovered RingBuffer table. This method returns a pointer into buffered data; producer-side `writeToBuffer` calls `memcpy`, including a wraparound case. No compression call is observed in those routines.

The downstream helper identified by its `emmc_write` diagnostic has a separate guard: a non-null callback at offset +4 of its compression-operations object takes an **“Unsupported write on compressed partition”** error path. The other branch calls `emmc_seq_write`.

Together these narrow the transformation question. They do not prove the producer supplied unchanged firmware-member bytes, establish which runtime object/table was used, connect every block-worker dispatch, or observe completed writes. The deeper physical representation, mount outcomes and writable `/etc` state remain unresolved. Existing execution guards and process policies are unchanged.

## Original buffer-object connection

`PackedFirmwareBuffer`'s constructor at `0xf37c` stores its incoming RingBuffer pointer at object offset +4 (`0xf388`). E0011's reader loads that same pointer and dispatches through its vtable offset +0x24. Its skip wrapper uses offset +0x28.

The common library's RingBuffer table starts at `0x10768`, size 60. It has ARM ABS32 symbol relocations at these full-table offsets:

| Table offset | Candidate target | Dispatch offset with address point +8 |
| --- | --- | --- |
| +0x28 | `RingBuffer::ReadData` | +0x20 |
| +0x2c | `RingBuffer::ReadDataWithoutCopy` | +0x24 |
| +0x30 | `RingBuffer::SkipData` | +0x28 |

The constructor at `0x6ec8` obtains its vtable pointer through a GOT load, adds eight at `0x6eda`, and stores it into the object at `0x6ede`. The calculated GOT slot `0x10b20` has a relocation to `_ZTVN7Updater10RingBufferE`. This supports the address point used above. The report retains table relocations and explicitly marks each resolution as a candidate with `runtime_dispatch_observed: false`; it does not invent a loaded vtable or execute a virtual dispatch.

## Buffer contents and advancement

`ReadDataWithoutCopy` (`0x6d8c`) contains synchronization and wait paths. At `0x6df0`–`0x6df2`, it loads the current buffer pointer from object offset +0xc and stores it through the output-pointer argument. It bounds the returned count using buffered-data and requested/contiguous sizes. It does not copy, decompress or rewrite the returned chunk in that path.

`writeToBuffer` (`0x6f20`) uses `memcpy` at `0x6f40`, or the split-copy calls at `0x6f54` and `0x6f60` when the buffer wraps. It updates write position/data count and signals waiting readers. This establishes copying within the ring; it does not identify the source of bytes passed to the producer's public API.

`SkipData` (`0x6cac`) passes a null destination to the virtual read method at offset +0x20, allowing advancement through the read path. `memoryCopy` checks for a null destination before the copy branch. The report includes these functions and the relevant constructor. Synchronization, scheduling, stop/end flags and concurrent lifetime rules are not implemented by this static tool.

## Storage-side branch

Storage offsets are relative to `.text` in the original relocatable `emmc.ko`, not kernel virtual addresses. The bounded helper begins with a prologue at `0xa89c`; its diagnostic identifies it as `emmc_write`, but no matching function symbol was recovered. This naming basis is explicit in the report.

At `0xa8ac`, the helper loads block parameters through its input object. It obtains a callback-table pointer at parameter offset +0xb4 (`0xa8b0`). If that pointer is non-null, it loads the callback at +4 (`0xa8bc`); a non-null callback leads to R4 = -1 and the unsupported-compressed-write diagnostic through `0xa8c8`–`0xa8dc` and `0xa920`–`0xa924`.

When either check permits the ordinary branch, `0xa8e0`–`0xa8fc` prepares arguments, including adding a parameter-derived sector offset, and calls relocated `emmc_seq_write` at `0xa900`. The return value is checked; failure is not assumed away.

The new report also retains the original `emmc_blk_request`, `emmc_blk_kthread` and `emmc_seq_write` functions. The worker uses indirect calls and unnamed local helpers; the sequence routine invokes additional local routines. These ranges are evidence for further tracing, **not a completed connection from userspace write to physical eMMC programming**. No successful request, automatic compression or physical byte identity is claimed.

## Inputs and reproduction

The updater body/common identities are unchanged from E0011. Storage source `nflasha3_unpacked/initrd.img_unpacked/kmod/emmc.ko` retains SHA-256 `d60683420d1ef7af57571d4281def19254c88e47c9047da9d5098e49de848671`. Every input is confined to firmware paths and checked against the existing baseline.

```powershell
.\venv\Scripts\python.exe -m tools.research.buffer_storage_trace
.\venv\Scripts\python.exe -m unittest discover -s tests
```

`artifacts/inventory/buffer-storage-trace.json` contains source identities, eight updater constructor/buffer functions, table relocations, three storage functions and the bounded diagnostic-named helper. Two fresh complete reports are identical. The earlier E0011 updater report remains byte-identical after sharing its table-reading implementation.

The complete suite has **140 passing tests**. New checks cover explicit vtable address-point arithmetic, bounds/alignment, missing or duplicate slots, wrong relocation types and adjusted targets. The resolver never promotes a static candidate to an observed runtime dispatch.

## Next work

Trace the producer feeding the RingBuffer and the block worker's callback-table assignments, rather than infer physical bytes from class names. Complete the normal-write edge into the sector/DMA programming path, or obtain an identified read-only physical snapshot. Preserve the conditional device-number candidates and both process baselines; do not remove guards based on these static findings alone.
