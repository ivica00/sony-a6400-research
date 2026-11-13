# E0490 — The platform model, and the boundary it does not cross

Date: 2026-11-13. This record is the index for the deliverable document `docs/PLATFORM_MODEL.md`.
It claims nothing new; it states what the document rests on and what it refuses to claim.

## Claim

The thirteen-body work supports a model that predicts a new body's command surface to 0.885 or
better and that locates both the modifiable surface and the limit of what this project has
measured. The model is published as `docs/PLATFORM_MODEL.md`, and its five unresolved questions are
listed there rather than left implicit.

## Status

`inferred` for the model as a whole, `verified` for each figure it quotes, each of which carries
its own record.

## Firmware hash

Every figure in the document is bound to the image that produced it. The a6400 application library
is `60ffd2b0f31f4bc139a7c13a4f62c25cdeb6a531ad5ef35df48471e6e36e88b1`; the thirteen updaters and
their hashes are in E0477; the per-body key blocks in `docs/evidence/cross_model/aes-key-blocks.tsv`
carry each library's own SHA-256.

## Source

E0477 (platform map), E0478 (Eye AF field), E0479 (UVC package delta), E0480 (offline kernel
symbols), E0481 (changelogs), E0482 (three stubs filled), E0483 (IPC edges), E0484 (indirect
display), E0485 (held-out prediction), E0486 (writable surface), E0489 (update chain).

## Method

The document is assembled from those records and checked by `tests/test_platform_model.py`, which
fails if a cited table lacks a hash or evidence id, if the integrity mechanism is not named, if the
document omits `unknown` where it should say it, or if it states a boot claim without a
qualification.

## Observation

The model answers three questions a reader can act on: which bodies share a kernel and in what way,
how well a body's command surface can be predicted before it is examined, and which mounts are
writable at runtime versus read-only on flash.

## Alternative explanations

- **"A model assembled from prior records adds nothing."** It adds the boundary: the earlier records
  each state a limit locally, and a reader could reasonably conclude from the sum that a modified
  image is now possible. The document exists to say the opposite in one place.
- **"The prediction figures are too good to be a real test."** They are a real held-out test (E0485)
  but a narrow one: recall of a command table, not capability. The document says so.

## Confidence and limitations

- **Verified:** each figure, through the record that produced it.
- **Not claimed:** anything beyond the five unresolved questions, each of which names what would
  settle it.
- **Risk of drift:** the document quotes numbers that live in other records. The test checks the
  provenance, not the values, so a future edit to a table without updating the document would not
  be caught. That is a deliberate limit: a test asserting literal figures would have to be edited
  whenever a measurement legitimately changes.

## Dependent implementation

`docs/PLATFORM_MODEL.md` and `tests/test_platform_model.py`.

## Next experiment

Nothing here; the next experiments belong to the individual records. The document should be
revisited when the indirect display route (E0484 §7) or the boot acceptance (E0489 §5) is settled,
because both would change what §6 says.
