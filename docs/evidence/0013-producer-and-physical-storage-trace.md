# E0013 — RingBuffer producer pipeline and physical storage write path

Date: 2026-10-18. Scope: static identified updater binaries and kernel storage driver. No updater execution, decryption routine, kernel service or hardware device write is executed.

## Findings

This analysis traces both ends left open in E0012:
1. The **producer feeding the RingBuffer** originates in `crypter.elf`. The module pipeline (`FileInputUpdaterManager` / `CryptFileInputUpdaterManager` and `DecryptorModule`) reads firmware file chunks, unscrambles 16-byte blocks using `Dec_Scramble`, and dispatches to `RingBuffer::WriteData` (table offset `+0x24`, dispatch offset `+0x1c`). In `BaseBodyLoaderModule::Execute`, `libupdaterbody.so` is loaded, `GetBody` is called to instantiate `UpdaterBody`, and `UpdaterBody::Execute(ring_buffer, callback_interface)` is invoked. `UpdaterBody` wraps the RingBuffer in `PackedFirmwareBuffer`, from which `NewFirmwareImageFile::extractImageFile` reads chunks via `ReadDataWithoutCopy` (dispatch offset `+0x24`) and issues `FileHandler::WriteAll` (`write` syscall) to `/dev/nflasha...`.
2. The **block-worker callback and physical storage-write path** in `emmc.ko`: `emmc_blk_kthread` directly calls `emmc_write` (`0xa89c`) from both direct-transfer (`0xb5a0`) and buffered-transfer (`0xba00`) branches. `emmc_write` evaluates parameter offset `+0xb4`:
   - For compressed partitions initialized by `emmc_blk_plat_probe_post` (`0x8144`), offset `+0xb4` points to `.data + 0x94`. Slot `+4` (`.data + 0x98`) holds `uz_emmc_do_compress`. Because this callback is non-null, `emmc_write` immediately returns error `R4 = -1` with **“Unsupported write on compressed partition”**.
   - For ordinary partitions initialized by `emmc_blk_plat_init` (`0x6a8`, `0x714`), offset `+0xb4` is null. Execution takes the ordinary branch to `emmc_seq_write` (`0x138b8`).
   - `emmc_seq_write` calls `write_block_retry` (`0x12ea8`), which formulates CMD24 (single-block) or CMD25 (multi-block) and invokes `exec_emmc_data_cmd` (`0xf270`).
   - `exec_emmc_data_cmd` dispatches through `handle->emmc_ops->data_cmd` (slot `+8` of registered host ops). For the SDHCI controller table (`.data + 0x30`), slot `+8` is `sdhci_emmc_exec_data_cmd` (`0x3174`).
   - `sdhci_emmc_exec_data_cmd` verifies hardware data-line busy status, maps scatter-gather DMA via `al_sg_dma_map`, and programs host controller hardware registers.

This connects the static pipeline from firmware package read to physical SDHCI programming. It confirms that compressed partition writes are explicitly blocked by the driver, while uncompressed partition writes pass to SDHCI DMA. Physical byte nonvolatile state, hardware register mappings, and runtime `/etc` contents remain unobserved. Existing process probe baselines and execution guards remain unchanged.

## RingBuffer producer pipeline

`crypter.elf` is the updater supervisor process located at `nflasha15_unpacked/bin/crypter.elf`.

1. **Buffer Allocation**: `BaseModule::Initialize` (`0xcfe0`, Thumb) allocates the `RingBuffer` (`_Znwj` with size `0x98` followed by `_ZN7Updater10RingBufferC1Ev` at `0xd00e`) and saves it at object offset `+0x24`. It retrieves buffer storage from `BufferContainer` (`0xd016`) and invokes `RingBuffer::Initialize` via vtable slot `+8` (`0xd024`).
2. **Input Reading and Decryption**: `FileInputUpdaterManager` opens the firmware file and reads chunks with `FileHandler::Read`. In encrypted firmware pipelines, `DecryptorModule::Execute` (`0xdfe0`) loops over 16-byte blocks using `memcpy` and `Dec_Scramble` (`0xe07a`), then feeds decrypted blocks to the next module's RingBuffer by calling `RingBuffer::WriteData` (`0xba42`, vtable dispatch offset `+0x1c`).
3. **Body Execution**: `BaseBodyLoaderModule::Execute` (`0xc490`, Thumb) opens `/tmp_updater/updater/bodyfs/bodylib/libupdaterbody.so` with `DllHandler::Open` (`0xc55a`). It resolves `GetBody` (`0xc564`) and `ReleaseBody` (`0xc570`). It calls `GetBody` (`0xc5ac`) to construct `UpdaterBody`, then at `0xc5ca` invokes `UpdaterBody::Execute(ring_buffer, callback_interface)` via vtable slot `+8`.
4. **PackedFirmwareBuffer Extraction**: In `libupdaterbody.so`, `UpdaterBody::Execute` (`0xf4f4`) passes the incoming RingBuffer to `PackedFirmwareBuffer::PackedFirmwareBuffer` at `0xf54c`. `PartitionImageKeyTag::Extract` invokes `NewFirmwareImageFile::extractImageFile`, which reads chunks via `PackedFirmwareBuffer::ReadDataWithoutCopy` -> `RingBuffer::ReadDataWithoutCopy` (vtable dispatch offset `+0x24`), advances with `SkipBlock`, and writes to `/dev/nflasha...` via `FileHandler::WriteAll` (`write` syscall).

## Block-worker callbacks and physical storage write

Storage offsets are relative to `.text` (or `.data` / `.init.text`) in `emmc.ko`.

1. **Worker Dispatch**: Block requests enqueued by `emmc_blk_request` wake `emmc_blk_kthread` (`0xb07c`). The thread processes direct transfers (`0xb5a0`) and buffered transfers (`0xba00`), both issuing a direct `bl` to `emmc_write` (`0xa89c`).
2. **Callback Table Guard**: `emmc_write` checks parameter offset `+0xb4`.
   - In `emmc_blk_plat_probe_post` (`0x8144`), offset `+0xb4` is assigned the relocation at `.data + 0x94`.
   - `.data + 0x94` contains `uz_emmc_do_decompress` (`0x607c`); `.data + 0x98` (+4) contains `uz_emmc_do_compress` (`0x5d58`).
   - `emmc_write` loads callback `+4` (`0xa8bc`). If non-null, it aborts write with error `R4 = -1` and reports `Unsupported write on compressed partition`.
   - In `emmc_blk_plat_init` (`0x6a8`, `0x714`), offset `+0xb4` is stored as null (`mov r5, #0`). For these uncompressed partitions, the guard check passes.
3. **Sequence Write**: On uncompressed partitions, `emmc_write` prepares sector offsets and calls `emmc_seq_write` (`0x138b8`) at `0xa900`.
4. **Retry and Command Assembly**: `emmc_seq_write` verifies sleep status (`[r8, #0xf4]`) and calls `write_block_retry` (`0x12ea8`). `write_block_retry` checks scatter-gather bounds (`al_sg_total_size`), selects CMD24 (opcode `0x18`) or CMD25, and calls `exec_emmc_data_cmd` (`0xf270`).
5. **Host Controller Dispatch**: `exec_emmc_data_cmd` calls `handle->emmc_ops->data_cmd` at `0xf310` (offset `+8` of ops). For SDHCI host operations (`.data + 0x30`), slot `+8` points to `sdhci_emmc_exec_data_cmd` (`0x3174`).
6. **Hardware Programming**: `sdhci_emmc_exec_data_cmd` polls register data-line busy status (`[r3, #0x24] & 2`), invokes `al_sg_dma_map` (`0x9128`) for DMA buffer configuration, programs host controller command and DMA registers, and awaits hardware completion.

## Inputs and reproduction

Artifacts are verified against local baseline hashes:

| Input artifact | SHA-256 |
| --- | --- |
| `0700_part_image/dev/nflasha15_unpacked/bin/crypter.elf` | `ec971fc3ae7452ff3c5a46959fdb6fa6d9a27087cb226b23cc2cce0289c84653` |
| `updater.img_unpacked/bodylib/libupdaterbody.so` | `6daad7d8be8807e068563d09436f83b1eadb93a365248c78e6add2f15cfea01d` |
| `updater.img_unpacked/usr/lib/libupdatercommon.so` | `78ee7c1c9fbd62fdf395fe3ca9c71e440f33794d591bb37b93d77d12b62a11de` |
| `nflasha3_unpacked/initrd.img_unpacked/kmod/emmc.ko` | `d60683420d1ef7af57571d4281def19254c88e47c9047da9d5098e49de848671` |

Commands:
```powershell
.\venv\Scripts\python.exe -m tools.research.producer_physical_trace
.\venv\Scripts\python.exe -m tools.research.buffer_storage_trace
.\venv\Scripts\python.exe -m unittest discover -s tests
```

Output is recorded in `artifacts/inventory/producer-physical-storage-trace.json`. The full test suite has **143 passing tests**.

## Limitations and next work

- Static instruction decoding confirms call and dispatch topologies; it does not observe physical hardware voltage/timing or completed flash writes.
- Compressed partition writes are conclusively rejected by `emmc_write`; uncompressed partitions proceed to SDHCI DMA.
- Nonvolatile partition contents on a running camera, runtime mount states, and the writable `/etc` overlay remain unresolved.
- Preserve existing process probe baselines (`brk`, `uname`, `files`, `metadata`, `--respect-runtime-mounts`); do not fabricate runtime device numbers or file content.
