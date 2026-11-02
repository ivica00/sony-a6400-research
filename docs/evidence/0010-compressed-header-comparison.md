# E0010 — Original compressed-header comparison

Date: 2026-10-18. Scope: preserved firmware bytes, static driver evidence and isolated original ARM execution. No physical storage read, kernel boot or camera operation.

## Result

The original driver's compressed-header path compares the first four header bytes with **`TPZL`**. Executing that five-instruction comparison against the first 512 bytes of each preserved updater filesystem image, `nflasha7` and `nflasha15`, takes the mismatch branch and sets R4 to `0xffffffea` (-22).

A constructed sector containing `TPZL` followed by zeros takes the matching branch. This control is deliberately incomplete: matching the magic does not validate a complete compressed image, table, block geometry or runtime registration.

Both preserved images begin with sixteen zero bytes and contain the ext2 structures recorded in E0007. **This experiment does not establish the bytes stored at the corresponding physical partition addresses.** It therefore does not select the direct-device fallback, remove the `st_dev` guard or resolve the `/etc` overlay boundary. Process execution policies are unchanged.

## Original read and comparison path

Offsets below refer to `.text` in the identified `emmc.ko`, not loaded kernel addresses.

In the cold-header path at `0x5ed8`, the routine saves its input partition pointer. If it differs from the cached pointer, instructions at `0x5f00`–`0x5f10` load the partition's first word, shift it right by nine, request a 512-byte read, and pass the cached header-buffer pointer to the helper at `0x5e5c`.

That helper sets up a buffer through relocated `uz_emmc_buf_to_sg` at `0x5e80`, then calls relocated `emmc_seq_read` at `0x5e94`. This establishes a dependency on original storage-read behavior; the new experiment supplies no implementation or fabricated response for either call. A negative helper result follows a separate error path.

After a successful read, instructions at `0x5f3c`–`0x5f4c` load the constant from section offset `0x5fe8`, load the header's first word through R6, compare them, conditionally set R4 to -22 and branch to cleanup on mismatch. The constant's little-endian bytes are `TPZL`. Cleanup at `0x5fb8` clears the cached partition pointer; the later exit moves R4 into R0.

For matching magic, later static instructions read header words at offsets 4, 8 and 12. The word at +8 is used to derive how many eight-byte entries fit in the initial sector when that offset is below 512. At `0x5fa0`–`0x5fb0`, the +4 word is used as an ARM register shift count to form a block-size value. `uz_emmc_lzp_part_size` subsequently shifts the +12 word right by three and multiplies by that block-size value. These observations support block-shift/table-offset/table-size interpretations; they are not proof of sufficient validation or safe geometry for arbitrary headers.

The bundled `fwtool.py/fwtool/archive/lzpt.py` independently uses the same magic and names the four words magic, blockSize, tocOffset and tocSize. This is corroborating extraction-tool interpretation, not proof that host decoding reproduces the Sony driver. It is not used as a replacement runtime validator.

## Bounded execution method

`tools/research/compressed_header.py` checks the original module and image hashes against the existing baseline before analysis or execution. It maps the original `.text` RX, supplies one 512-byte read-only sector, initializes R6 to that sector and R4 to zero, and starts at `0x5f3c`. It stops **before** either successor executes: matching boundary `0x5f50`, mismatch boundary `0x5fb8`.

Each completed run must reach exactly one declared boundary after five instruction callbacks. Conditional instructions count as callbacks even when their condition fails. Unexpected branches, loops, timeouts, memory faults and input writes cannot become comparison results. The routine's earlier storage read, cache state, cleanup, remaining header processing and return are not executed.

As in E0009, provisional Cortex-A9, ARM user mode, fixed mappings and supplied caller registers are experiment inputs. There are zero supplied kernel responses. This isolates one original decision; it does not validate privileged execution or complete storage behavior.

The report preserves source identities, raw header words, sector hashes, original instruction windows, branch offsets, R4 and assumptions. Both magic matches and mismatches explicitly report `complete_image_validated: false`.

## Inputs, reproduction and checks

Module SHA-256: `d60683420d1ef7af57571d4281def19254c88e47c9047da9d5098e49de848671`.

Image SHA-256 values remain `305e289ecc1d768544af71c83d58ce23ec4d232be1e7572d9d4f68f0f12188cc` (`nflasha7`) and `0e9b19144b021d8b1b1908554a7ac9cdc6f8b9599eeeb1d53118b8832a296e56` (`nflasha15`). No expected identity or original input was changed.

```powershell
.\venv\Scripts\python.exe -m tools.research.compressed_header
.\venv\Scripts\python.exe -m unittest discover -s tests
```

Output: `artifacts/inventory/compressed-header.json`. Two fresh complete reports are identical. The complete suite has **133 passing tests**. New constructed ARM checks cover matching/mismatching/byte-reversed magic, incomplete matching headers, extreme observed words without host allocation, short input, invalid endpoints, looping/unexpected branches and read-only input enforcement.

## Next work

Trace the updater's write/compression path to determine whether it stores these extracted image bytes directly or constructs a compressed physical representation. Identify any missing partition header/table state needed to reproduce the original read. Until that relationship or an identified read-only physical snapshot is established, keep both device-registration outcomes conditional. The writable `/etc` state remains a separate required input.
