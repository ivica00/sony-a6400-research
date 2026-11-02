# E0011 — Updater partition-image copy and write path

Date: 2026-10-18. Scope: static original updater instructions and relocations. **No updater operation, script or device write is executed.**

## Result

The original `NewFirmwareImageFile::extractImageFile` routine copies chunks from `PackedFirmwareBuffer::ReadDataWithoutCopy` to `FileHandler::WriteAll`, advances the packed buffer, and closes the output. The common library's `WriteAll` reaches the normal `write` interface and loops for partial writes. No compression call is observed in this copy loop.

That narrows the updater-to-storage question without resolving it. The packed-buffer reader delegates to a virtual method, and the receiving storage driver's write semantics are not established here. Either side must be traced before calling this an end-to-end byte-identical physical write. Existing device identity and `/etc` guards remain unchanged.

## Input identity

| Preserved updater artifact | SHA-256 |
| --- | --- |
| `updater.img_unpacked/bodylib/libupdaterbody.so` | `6daad7d8be8807e068563d09436f83b1eadb93a365248c78e6add2f15cfea01d` |
| `updater.img_unpacked/usr/lib/libupdatercommon.so` | `78ee7c1c9fbd62fdf395fe3ca9c71e440f33794d591bb37b93d77d12b62a11de` |

The tool checks both paths against the firmware boundary and their existing baseline hashes. These are updater-side libraries, not assumed interchangeable with similarly named libraries in the installed application image.

## Corrected call identification

The existing PLT recognizer matched formatted disassembler text. This updater uses ARM rotated-immediate spellings such as `#20, #20`, which the text matcher did not understand. As a result, earlier exploratory output did not name its external calls.

`plt_symbols` now recognizes the actual ARM instruction words for `add ip,pc,immediate`, `add ip,ip,immediate`, and the supported `ldr pc,[ip,offset]` variants. It decodes the immediate's rotate-right representation, includes the architectural PC offset, and requires the computed GOT slot to match an ARM jump-slot relocation. Wrong register patterns, unsupported conditions, unmatched slots, other relocation types and truncated stubs do not produce names. This resolves 301 PLT entries in the body library and 96 in the common library.

This improves static research labels. It does not execute a loader, resolve a guest import at runtime, or change a process-probe response.

## Original partition-image path

Addresses below are link-time ELF addresses; Thumb symbol values include a low ISA bit while instruction addresses are even.

`PartitionImageKeyTag::Extract` contains a substring operation that skips ten characters of the incoming name (`0x10c00`–`0x10c0c`). For the package path `part_image/dev/nflasha15`, that corresponds to `/dev/nflasha15`. This is a static path-construction observation, not a demonstrated runtime destination.

The image class's virtual table at `0x20f08` contains an ABS32 relocation at `0x20f2c` to `NewFirmwareImageFile::extractImageFile`. `extractFile` dispatches through a virtual function pointer at `0x12b12`–`0x12b14`. The report retains the table's symbol relocations; it does not fill its unrelocated zero words with guessed function addresses.

In `extractImageFile`:

| Instruction | Resolved operation | Observed role |
| --- | --- | --- |
| `0x12b94` | `FileHandler::Open(char const*, int)` | opens constructed destination with flag value 1 |
| `0x12be2` | `PackedFirmwareBuffer::ReadDataWithoutCopy` | obtains a chunk pointer/count |
| `0x12bfa` | `FileHandler::WriteAll` | writes chunk pointer and returned count |
| `0x12c3c` | `PackedFirmwareBuffer::SkipBlock` | advances input after a successful write |
| `0x12c42`–`0x12c46` | remaining-count update/branch | continues until the requested count is exhausted |
| `0x12c4a` | `FileHandler::Close` | checks completion of output close |

Failure and exception branches remain in the recorded instruction ranges. None is assumed successful.

In the common library, `FileHandler::Open` reaches `open` at `0x5f34`. `WriteAll` loads the stored descriptor, current buffer pointer and remaining length at `0x624c`–`0x6250`, then calls `write` at `0x6252`. Its `0x627a`–`0x627e` path advances the buffer and reduces the remaining length before retrying a partial write. There is no host-side execution of this path in the new tool.

## Remaining buffer indirection

`PackedFirmwareBuffer::ReadDataWithoutCopy` at `0x13160` loads an internal object, obtains a virtual function pointer at vtable offset `0x24` and calls it at `0x1316a`. Its name does not by itself prove the supplied bytes equal the preserved package-member bytes. That implementation still needs identification.

`SkipBlock` rounds a count up to a 512-byte boundary when needed (`0x13170`–`0x1317e`) and dispatches through the internal object's vtable offset `0x28`. This supports packed-record alignment, not a physical storage sector-state claim.

Downstream, a call to `write` establishes a userspace/kernel boundary, not the absence of transformation inside the device driver. The direct and decompressed device candidates from E0008–E0010 remain conditional.

## Reproduction and checks

```powershell
.\venv\Scripts\python.exe -m tools.research.updater_trace
.\venv\Scripts\python.exe -m unittest discover -s tests
```

`artifacts/inventory/updater-write-trace.json` records seven bounded original functions, source hashes, bytes, resolved call symbols, literal labels and image-class table relocations. Two fresh reports are identical. PC-referenced data is labeled separately, but linear disassembly may contain other inline data; it is not an executed control-flow trace.

The complete suite has **137 passing tests**. New checks cover rotated immediate arithmetic, both supported PLT load variants, wrong registers/conditions, relocation-slot/type mismatch and truncated stubs. Earlier decoder checks still pass. No baseline inventory or firmware bytes were overwritten.

## Next work

Identify the packed-buffer object's virtual reader/advance implementations and trace their inputs back to the original packed firmware member. Separately follow the normal storage write path in the original eMMC driver. Only after those edges are established should the updater image bytes be treated as evidence for a selected physical header format. Successful update completion, normal boot selection, mount outcomes and writable `/etc` state remain unverified.
