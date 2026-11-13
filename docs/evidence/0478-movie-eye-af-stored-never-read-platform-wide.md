# E0478 — The `0x413b` (Movie Eye AF) value is stored and never read on every body that has it

Date: 2026-11-13. **Strictly offline.** No camera, no USB, no mode switch, no firmware write.
Inputs: the same thirteen official updaters as E0477, unpacked with `fwtool` at
`cdba742b`. Continues the `ILCE-6600` result in issue #7 and answers the two mechanisms
proposed there.

## 0. Short answer

1. **The storage-without-consumer shape is platform-wide, not an `ILCE-6600` quirk.** Ten
   of the thirteen bodies carry command `0x413b`. On all ten, the handler stores the message
   byte into one settings-cache field, and **no instruction in that same image reads the
   field back**.
2. **The field offset differs per body** (`0x5d0`, `0x5d8`, `0x5f8`, `0x6ac`, `0x6c4`,
   `0x6c8`, `0x540`), and so does the cache base. A constant copied between bodies would be
   wrong on every one of them — this is why the profile schema's "never copy an address" rule
   is correct even inside one chip family.
3. **Neither of the two proposed explanations is supported by the bytes.** The field is not
   passed by reference to another subsystem: no other module in the image holds a literal or
   a relocation anywhere near the cache field's address. It is not read through a table of
   struct offsets either: no site in the image forms the field's address by a biased base or
   a computed offset.
4. **A neighbouring control strengthens the result.** On `ILCE-6600` the handlers adjacent
   to `0x413b` (writing `+0x7ec` and `+0x7e8` of the same cache) have the identical shape and
   also no reader. Three sibling fields written and never read in one function cluster is a
   cache of values the application layer is expected to consume, not a defect in the search.

## 1. Corpus

| body | `0x413b` | handler | field offset | cache base | writes | reads |
| --- | --- | --- | --- | --- | --- | --- |
| `DSC-RX0M2` | present | `0x63af825d` | `+0x5d0` | `0x641ba4cc` | 1 | **0** |
| `ZV-E10` | present | `0x63c1b189` | `+0x6c8` | `0x6448e434` | 1 | **0** |
| `ILCE-7C` | present | `0x63c2f8d9` | `+0x6c4` | `0x644b6150` | 1 | **0** |
| `ILCE-7M3` | present | `0x63be03d9` | `+0x540` | `0x645ff774` | 30 | **0** |
| `ILCE-7RM3` | present | `0x63bc0e6d` | `+0x540` | `0x645f7ff0` | 86 | **0** |
| `ILCE-7RM4` | present | `0x63c13a8d` | `+0x6ac` | `0x644be0bc` | 1 | **0** |
| `ILCE-7RM4A` | present | `0x63c22429` | `+0x6ac` | `0x644e1c78` | 1 | **0** |
| `ILCE-9` | present | `0x63bf69b9` | `+0x5d8` | `0x644418e4` | 1 | **0** |
| `ILCE-9M2` | present | `0x63c3856d` | `+0x5f8` | `0x644ae5a8` | 1 | **0** |
| `ZV-1` | present | `0x63c304c9` | `+0x5f8` | `0x644d3424` | 1 | **0** |
| `ILCE-6600` | present | `0x63bf4cf9` | `+0x5d0` | `0x6442ab54` | 1 | **0** |
| `ILCE-6400` | **absent** | — | — | — | — | — |
| `ILCE-6100A` | **absent** | — | — | — | — | — |

The write count is the number of same-width stores to that exact `(base, field)` pair while
the base register still holds that base; the read count is the same for loads. `ILCE-7M3`
and `ILCE-7RM3` show 30 and 86 because their handler is inlined at every dispatch site, not
because the field has more logic behind it.

## 2. Method

`tools/research/av_eyeaf_field.py`. Thumb-2, no decompiler:

1. Read the table entry for `0x413b` from `av-cam.bin` (E0477's locator).
2. Disassemble a short window at the handler. The store has the shape
   `str{b,h}.w rT,[rB,#imm12]`; `imm12` is the field offset.
3. Resolve `rB` through the PIC idiom `ldr rD,[pc,#k]` ; `add rD,pc`. The absolute base is
   `literal + address_of_add + 4`, where the address is the runtime address (ORIL base
   `0x635c6000`). The literal is *measured*, never assumed.
4. Count every `ldr`/`str` in the whole image whose base register was materialised to that
   same absolute value **and** whose `imm12` equals the field offset, stopping at the point
   where the base register is overwritten. Access width must match: an 8-bit `strb.w` at
   `+0x540` and a 32-bit `str.w` at `+0x540` are different bytes of that word.

The scanner is validated against a known-good reference before use: on `ILCE-6600` it
returns field `+0x5d0`, base `0x6442ab54`, 1 write, 0 reads — identical to the result
obtained earlier by an independent manual pass (issue #7, F12).

## 3. The two proposed mechanisms, tested

The issue #7 reply asked whether the cache block is "passed by reference to another
subsystem/IPC boundary" or "indexed via a table of struct offsets rather than a hardcoded
`#0x5d0` immediate". Both are testable in the image.

**Passed by reference.** If another module received the field's address, its address would
appear there as a relocation, a literal, or a computed base. Tested on `ILCE-6600`:

- every ARM ELF file in that body's unpacked tree (461 files) was scanned for any relocation
  whose symbol value lands in `0x6442b000..0x6442c000` (the page holding `cache+0x5d0`
  = `0x6442b124`): **0 hits**;
- the cache base literal `0x6442ab54` appears only inside `av-cam.bin`; no other module
  carries it.

So no other module in the packaged image can name that field at all.

**Indexed by a table of struct offsets.** If a reader computed the field from a biased base
or a table, one of these would exist somewhere in the image:

- `add.w rD, rN, #0x5d0`: **0 sites**;
- `movw rD, #0x5d0`: **0 sites**;
- a data word equal to `0x5d0`: 3 sites, none of them inside or reachable from the cache
  arithmetic;
- any `(base materialised as cache+δ, read at imm12 = 0x5d0−δ)` pair: **0 sites**, for the
  316 distinct materialisations of the cache base and 25,271 distinct δ values.

Nothing in the image forms that address except the handler's own store.

## 4. Alternative explanations

- **"The reader is in another module, reached by IPC."** Ruled out for `ILCE-6600` above by
  the relocation sweep: no module in the image holds the address. It remains possible that a
  module *derives* the address from the cache base at runtime through a pointer the image
  does not contain statically; that would need a runtime observation to see, and this record
  does not claim otherwise.
- **"The scan misses reads because the base register is reloaded."** Tested: the counter
  walks *every* materialisation of the cache base in the image (316 of them on `ILCE-6600`)
  and counts accesses while each one is live, not only the handler's own. Widening or
  narrowing the window changed the write count, never the read count.
- **"The field is written for a purpose other than a consumer, e.g. logging."** Consistent
  with the evidence, and it does not change the conclusion: whatever the purpose, no
  instruction in that image consumes the value.

## 5. Confidence and limitations

- **Confirmed from artifacts:** the table entry, the handler address, the field offset, the
  cache base, and the read count of 0, for all ten bodies.
- **Confirmed on one body only:** the relocation sweep and the "no biased base" test were
  run on `ILCE-6600`. The same tests are runnable per body and are cheap, but this record
  does not claim they were executed for all thirteen.
- **Not examined:** whether a live camera's *application layer* reads the field through a
  pointer obtained at runtime. The packaged-image statement is a statement about the image.
- **Not a statement about the feature working.** That a body stores a value and never reads
  it says nothing about whether the UI shows the option, which is a separate question.

## 6. Dependent implementation/scenarios

- This is the strongest available negative result for the "port Movie Eye AF by copying the
  handler" idea: on every donor the handler alone is a no-op for behaviour. A port would have
  to bring a consumer, or the value stays stored and unused.
- It also explains why `ILCE-6400`/`ILCE-6100A` can lack the command while sharing a kernel
  symbol set with bodies that have it: the command lives in `av-cam.bin`, not in the kernel.

## 7. Reproduce

```bash
# one body
python3 -I tools/research/av_eyeaf_field.py \
    <unpacked>/a6600/.../nflasha3_unpacked/av-cam.bin --command 0x413b

# expected
#   command 0x413b handler 0x63bf4cf9 field +0x5d0 cache 0x6442ab54 writes 1 reads 0

# the reference validation that must pass before the sweep is trusted
python3 -I tools/research/av_eyeaf_field.py \
    <unpacked>/a6600/.../av-cam.bin --command 0x413b --expect '0x6442ab54:0x5d0:1:0'

# every body at once
python3 -I tools/research/cross_model_report.py <unpacked-root> --reference a6400 \
    --eyeaf-table
```

## 8. Next experiment

Take one body that ships UVC (`ZV-E10`, `ILCE-7C`, `ZV-1`, `DSC-RX0M2`) and run the same
"no reader anywhere" sweep for the fields its video handlers write. If the pattern repeats,
the conclusion generalises: on this platform the `av-cam` layer is a store, and consumption
happens across a boundary that a packaged image does not contain.
