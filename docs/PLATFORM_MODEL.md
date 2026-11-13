# The CXD90045 platform model

What thirteen official updaters establish about this camera family, how much of it is predicted
rather than described, and exactly where the boundary of the possible sits.

Every figure below carries a record ID. A figure without a record does not belong in this file.
All of it is offline: no camera, no USB, no updater executed. Where a fact needs a camera to
settle, the text says `unknown` rather than guessing.

## 1. What the platform is

Thirteen bodies, one SoC family, **nine kernels** (E0477). Sharing is proven by an identical
kernel symbol-name set, and each group says which part is actually equal:

| group | bodies | what is equal |
| --- | --- | --- |
| one kernel source, string data shifted | `ILCE-6400`, `ILCE-6600` | all 24,421 names; all 14,401 function symbols at the same address; 9,124 addresses differ and every one is data |
| three separate kernels, shared symbol list | `ILCE-6100A`, `ILCE-7M3`, `ILCE-7RM4A` | 24,351 names, but 4,033 of the 4,042 differing addresses are function symbols |
| one build, two names | `ZV-E10`, `ILCE-7C` | all 14,460 function symbols at the same address; 9 data addresses differ |
| unique | the other six | — |

The command table climbs without gaps: 285 records on the a6400, 286 on the a6600 with exactly
`0x413b` added, 337 on the ZV-E10 and a7C (E0477).

## 2. Does it predict, or only describe

A description reports what it read. A model predicts a body it never saw. Measured (E0485), with
a command-id rule fitted on four bodies and scored on three excluded from the fit:

| held-out body | command recall |
| --- | --- |
| `ILCE-6600` | 0.997 |
| `ILCE-7M3` | 0.885 |
| `ILCE-9M2` | 0.973 |

Table `docs/evidence/cross_model/prediction-scores.tsv` (E0485), scored from the packaged
images of E0477. The a6600 misses exactly one
command — `0x413b`, the one it adds — which is the correct behaviour of a conservative rule. No
rule exists yet for USB ids or device nodes, and those columns are reported as zero rather than
filled to look better.

## 3. What the application layer looks like

`libObj.so` on the a6400 is 20,860,436 bytes with SHA-256
`60ffd2b0f31f4bc139a7c13a4f62c25cdeb6a531ad5ef35df48471e6e36e88b1` (E0483), defining 1,853
code symbols at 1,851 distinct addresses; the other 1,444 of its 3,297 FUNC entries are imports.

- **29 direct IPC call sites** across `osal_snd_msg`, `osal_rcv_msg_tmo`, `osal_snd_sync_msg` and
  `ioctl`. 17 pass a constant argument, matched to the `mov`/`movw` immediate that loads it; 12
  take theirs from a register or memory and are recorded empty (E0483). Table
  `docs/evidence/cross_model/ipc-edges-a6400.tsv`, bound to the image above by SHA-256
  `60ffd2b0…e88b1`.
- **6,713 named-to-named call edges** once a call is resolved to the symbol containing it (E0484).
- **The display entry points are indirect.** `ObjDisplay_Create`, `ObjDisplay_Destroy`,
  `ObjDisplay_RegisterCommand` and `ObjDisplay_UnregisterCommand` exist on every body examined; `ObjDisplay_Start` does not exist at all,
  despite appearing in an earlier string scan. The four have **zero direct callers** and their
  addresses appear once each as data, which is the shape of a stored function pointer (E0484).

## 4. The update chain: what is checked, and what is not

The ecosystem claim that the image is AES-encrypted with per-model keys and three integrity layers
is wrong for the packaged files (E0489):

- **484 files** under the a6400 tree are ELF objects readable as-is, with working symbol tables.
- **Integrity is CRC32 and MD5**: `uc_crc32sum.elf` imports no cryptographic function, and
  `loader_writer.sh` runs `md5sum -c`. Of the updater tree's 41 files (18 scripts), none verifies a
  signature.
- **The only AES** is `libupdatertalk.so`, which decodes updater talk. Its key is the first 16
  bytes of `sha256("")`, used in ECB with no IV, and it is identical on all thirteen bodies across
  its three variants (E0489). Table `docs/evidence/cross_model/aes-key-blocks.tsv`, whose rows
  carry each library's SHA-256 and the identical key.

**What that does and does not mean.** It means the packaged image is not protected by a cipher. It
does **not** mean a modified image boots: whether the bootloader accepts a file whose CRC list was
recomputed is **unknown**, and settling it needs a camera or a preserved boot log.

## 5. Where modification is possible

Two different things, kept apart (E0486):

- **Writable at runtime, six mount points**: `/setting`, `/system`, `/tmp`, `/log`,
  `/android/data`, `/lens`. Work that stays here is reversible by deleting a file.
- **Read-only flash, three partitions**: `/` (`nflasha7`), `/usr` (`nflasha15`),
  `/android/system` (`nflasha16`). `/usr` is where the application libraries live.

A writable mount is not a modified firmware image. Persistence across a power cycle is not claimed
for any of them.

## 6. What stays unknown

Stated plainly, because a model is judged by its boundary as much as its content:

1. **Boot acceptance of a modified image is unknown** — it needs a camera (E0489 §5).
2. **The indirect route to the display** — the pointer chain from input to display is not traced;
   the next step is a data-flow search from the stored address, not a deeper call trace (E0484 §7).
3. **What consumes a queue id** — the IPC table says which constant is passed, not what the
   consumer does (E0483 §5).
4. **The other twelve bodies' layouts** — the mount layout is the a6400's; partition tables differ
   per body (E0486 §3).
5. **Persistence** — writable was measured, surviving a reboot was not (E0486 §6).

## 7. How to reproduce

```bash
python3 -m unittest tests.test_platform_model        # this document's claims
python3 -I tools/research/cross_model_report.py <roots> --reference a6400
python3 -I tools/research/update_chain.py --roots <roots> --emit-keys
python3 -I tools/research/predict_body.py --roots <roots> --hold-out a6600 ILCE-7M3 ILCE-9M2
python3 -I tools/research/ipc_edges.py <a6400>/libObj.so --tsv
```

Records behind it: E0477 (platform map), E0478 (Eye AF field), E0479 (UVC package delta), E0480
(offline kernel symbols), E0481 (changelogs), E0482 (three stubs filled), E0483 (IPC edges), E0484
(indirect display), E0485 (held-out prediction), E0486 (writable surface), E0489 (update chain).
