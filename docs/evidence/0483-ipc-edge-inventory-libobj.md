# E0483 — The IPC edge table: 29 call sites, 17 with a constant argument

Date: 2026-11-13. Offline only: the a6400 packaged image, no camera, no execution.

The camera's application layer talks over OSAL messages, and a queue id is what links a producer
to a consumer. This record is the first table of that layer produced from the shipped binary
rather than from a live read: every call site of `osal_snd_msg`, `osal_rcv_msg_tmo`,
`osal_snd_sync_msg` and `ioctl` in `libObj.so`, with the argument when it is a constant.

## 0. Short answer

1. **`libObj.so` contains 29 direct IPC call sites**, of which 17 pass a constant argument and 12
   take theirs from a register or memory.
2. **The table is honest about the 12.** An argument that is not an immediate is written as an
   empty field, never as a zero, because `0` is a real queue id and a fabricated one would be
   indistinguishable from a measured one.
3. **Two fabricated numbers were found and removed during this work.** The first version of the
   tool reported `0x4604490f` for a call whose argument is loaded from memory: it read the
   instruction bytes as if they were the literal pool. A second version missed `movw` entirely.
   Both are recorded in §4 rather than quietly fixed.
4. **The image is `libObj.so`, 20,860,436 bytes, SHA-256 `60ffd2b0…e88b1`** — the table is
   exact for that file and no other.

## 1. Inputs

| input | detail |
| --- | --- |
| body | `ILCE-6400` (a6400) |
| library | `.../nflasha15_unpacked/lib/libObj.so`, 20,860,436 bytes, SHA-256 `60ffd2b0f31f4bc139a7c13a4f62c25cdeb6a531ad5ef35df48471e6e36e88b1` |
| code section | `.text` at `0x104910`, 13,849,456 bytes |
| defined code symbols | 1,853 addresses among 3,297 FUNC entries (1,444 are imports with address 0); they collapse to 1,851 distinct addresses |
| PLT stubs | 2,547, mapped to import names through `.rel.plt` |

## 2. The table

`docs/evidence/cross_model/ipc-edges-a6400.tsv`, header `caller`, `callee`, `site`,
`queue_or_cmd`. Six representative rows:

| caller | callee | site | queue_or_cmd |
| --- | --- | --- | --- |
| `InfraAdjMedia_Exit` | `ioctl` | `0x1871c6` | `0xe002` |
| `ObjMedia_UnregisterCommand` | `ioctl` | `0xa21a70` | `0xc` |
| `ObjCamera_Destroy` | `ioctl` | `0xa731fa` | `0xc006` |
| `ObjCamera_Destroy` | `ioctl` | `0xaa5b3a` | `0x16` |
| `ObjEffect_UnregisterCommand` | `ioctl` | `0xe2e974` | `0x2022` |
| `compass_res` | `osal_snd_msg` | `0x81144a` | *(unknown)* |

The last row is the important one as a shape: the tool found the call and could not find a
constant, so it says so.

## 3. Method

```bash
python3 -I tools/research/ipc_edges.py <tree>/libObj.so --tsv \
  > docs/evidence/cross_model/ipc-edges-a6400.tsv
```

Four steps, each with an independent check:

1. **Find calls.** `callgraph.direct_calls` decodes candidate `bl`/`blx` sites from the
   instruction encoding, then *confirms each one with capstone*, requiring a 4-byte branch as
   the first decoded instruction. The confirmation is not decoration: without it 28 of 29 sites
   were literal-pool bytes that happened to share the `bl` encoding bits.
2. **Name the callee.** A call to an import lands on a PLT stub, not on the import's address
   (which is 0), so `.rel.plt` maps the n-th 12-byte stub to the n-th relocation. Without this
   step `named_edges` was 0 — every call read as `sub_XXXXXXXX`.
3. **Find the argument.** Walk back at most `0x40` bytes for an immediate written to `r0`
   (`r1` for `ioctl`). A register copied from another register, loaded from memory, or formed by
   `add rX, pc` yields no value.
4. **Verify.** Every site in the table was disassembled and confirmed to be a 4-byte branch, and
   every constant id was confirmed by finding the corresponding `mov`/`movw` immediate in the
   32 bytes before the call:

```text
real calls: 29, bogus: 0
verified ids: 17, unverified: 0
```

## 4. Alternative explanations, and the errors this table survived

- **"The 12 unknown arguments could be recovered from the literal pool."** Not by this method:
  the pool holds a *pointer* or a value the relocation layer fills, and following it statically
  is a different technique from reading an immediate. Left as unknown deliberately.
- **"A call site could be a tail call or an indirect call."** Indirect calls (`blx r3`) are not
  counted here at all; the table is direct calls only, which is why its count is small and its
  rows are trustworthy rather than exhaustive.
- **The first version was wrong, twice.** It reported 28 bogus sites because the branch
  confirmation compared the decoded instruction without checking its size, so a 2-byte opcode
  sharing the encoding bits passed. It then fabricated arguments (`0x4604490f`, `0x44784811`)
  because the literal-pool fallback read `data[site:site+4]` — the instruction bytes — instead
  of the pool. Both were caught by disassembling the claims rather than trusting the tool, which
  is why §3 step 4 exists.

## 5. Confidence and limitations

- **Verified:** 29 call sites, each disassembled; 17 constant arguments, each matched to its
  `mov`/`movw` immediate; the PLT mapping resolves 2,547 stubs.
- **Bound only to one image:** these addresses are exact for the a6400 `libObj.so` named in
  §1. Another body's library has a different layout; the a6100a build, for instance, contains no
  direct `osal_snd_msg` call site at all, so a table copied to it would be wrong.
- **Not claimed:** that the 29 are all the IPC traffic. Wrappers, indirect dispatch and calls
  into other libraries are outside this table.
- **Not claimed:** any runtime behaviour of a queue id. The table says which constant is passed,
  not what the consumer does with it.

## 6. Dependent implementation

`tools/research/ipc_edges.py` and `tools/research/callgraph.py`, with 15 tests between them.
`tests/test_ipc_edges.py` pins the one distinction that makes the table usable: an unknown
argument must appear as an empty field, never as `0x0`.

## 7. Next experiment

Take the two `osal_snd_msg` rows and find the receiver of their queue ids in the same image with
`capability_path.path_between`. If a receiver exists, the producer-consumer pair becomes a traced
capability; if not, it is another write-only path like the Eye AF field in E0478, and the pattern
generalises.
