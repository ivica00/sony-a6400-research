# E0481 — Published firmware changelogs give a target for every binary diff

Date: 2026-11-13. **Read-only web reading**, no camera, no firmware execution. Source: the
thirteen official Sony support pages that host the updaters of E0477. This record exists
because a binary diff needs a question to answer, and Sony publishes the questions.

## 0. Short answer

1. **Where Sony publishes a per-version history, it is rich.** The a7 III page lists eleven
   versions from `1.01` (2018-04-18) to `4.04` (2026-04-15), and every one of the ten earlier
   entries expands to its own text. The a7R IVA page expands three.
2. **Most pages do not expose a per-version history at all.** Of the nine pages read, only
   `ILCE-7M3` (10 expanded entries) and `ILCE-7RM4A` (3) do. The other seven show a single
   flat list under "The following benefits and improvements are also included in this update",
   with no version and no date per item, and their "View previous benefits and improvements"
   control is a `javascript:void(0)` link that reveals nothing further.
3. **Where it exists, the text is specific enough to aim a diff.** `Ver. 4.00 (2021-03-10)` —
   "Adds new features of FTP transfer … allows you to register up to nine FTP servers
   (previous was up to 3)".
4. **It is not a code map.** "Adds FTP transfer" is tens of kilobytes across several modules.
   The changelog supplies the *version boundary* and the *name* of the change; the diff
   supplies the addresses.
5. **One entry names a feature this project already tracks.** The `ILCE-7C` page (flat list)
   says "Makes the Eye AF feature compatible with animals when recording a movie" — the same
   capability as command `0x413b` (Movie Eye AF), which E0478 examines on ten bodies.

## 1. What was read, and what each page actually exposed

| model | versions listed | entries that expand to text |
| --- | --- | --- |
| `ILCE-7M3` | 10 | 10 |
| `ILCE-7RM4A` | 3 | 3 |
| `ILCE-7C`, `ILCE-7RM3`, `ILCE-7RM4`, `ILCE-9`, `ILCE-9M2`, `ZV-1`, `DSC-RX0M2` | 0 | 0 (flat list only) |

The a7 III version list, verbatim:

| version | date |
| --- | --- |
| 1.01 | 2018-04-18 |
| 2.00 | 2018-10-10 |
| 2.10 | 2018-12-18 |
| 3.00 | 2019-04-11 |
| 3.01 | 2019-05-16 |
| 3.10 | 2019-12-17 |
| 4.00 | 2021-03-10 |
| 4.01 | 2021-06-17 |
| 4.02 | 2025-04-16 |
| 4.03 | 2025-09-04 |
| 4.04 | 2026-04-15 |

The extracted text for every page read is in `docs/evidence/cross_model/patch-notes.json`,
with `versions_expanded` and `history_available` recording what that page actually produced.

## 2. Where the changelog helps and where it does not

**Helps — on the two pages that expose it.** It answers "which version introduced X", which is
the question a two-image diff needs. If a feature appears at `4.00` and not at `3.10`, then every behavioural difference
between those two images is a candidate, and the changelog says what to look for. Without it,
a diff between two builds is a list of thousands of changed bytes with no priority.

**Does not help.** It gives no symbol, no module and no size. It also describes user-visible
changes only: a build that fixes an internal fault without changing behaviour produces an
entry like "Improves the operational stability of the camera", which is true and useless for
aiming a diff.

**A concrete example of the help.** The a7 III `4.04` page lists `4.03` and `4.02` as also
included, both dated 2025, after a four-year gap from `4.01` (2021). A body whose packaged
build is older than 2025 therefore cannot contain whatever those two entries describe, which
tells a diff which side is newer without trusting a version string inside the image.

## 3. The limit that matters: older files are gone

The changelog survives; the files do not. Queried directly:

| request | result |
| --- | --- |
| `Update_ILCE7M3V400.exe` | HTTP 404 |
| `Update_ILCE7M3V403.exe` | HTTP 404 |
| `Update_ILCE7M3V402.exe` | HTTP 404 |
| `Update_ILCE7M3V310.exe` | HTTP 404 |
| `Update_ILCE7M3V300.exe` | HTTP 404 |
| archived copy of `Update_ILCE7M3V400.exe` | no snapshot |

Sony keeps only the current file per model, and the old version pages do not carry a live
link to their own file. So a version-to-version diff **within one model** is not obtainable
from official sources, and this record does not claim otherwise.

What remains available, and is what E0477 uses:

- **build-to-build across models** — nine kernels across thirteen bodies, all current;
- **model-to-model at the same build** — `ILCE-6100A`/`ILCE-7M3`/`ILCE-7RM4A` share a symbol
  set, so a diff between them isolates body-specific code from shared code;
- **the application layer per body**, where the command tables already differ by 0–52 entries.

## 4. Alternative explanations

- **"A changelog entry may cover several versions."** It does: the page presents the entries
  of previous versions as "also included in this update". The version a feature *arrived* in
  is the earliest entry that mentions it, not the page it appears on.
- **"The dates may be regional."** Possible; the pages read are the US support pages, and a
  regional page could differ. The dates are recorded as read, not as a Sony-wide timeline.
- **"An older file might be reachable under a different path."** Not tested exhaustively, and
  not claimed. The five probed names are the ones the page's own version list implies.

## 5. Confidence and limitations

- **Confirmed:** the version list and dates for the a7 III; the presence of the same section
  on the other twelve pages; the five 404s and the empty archive query on 2026-11-13.
- **Not confirmed:** that no official mirror anywhere holds an older file; the internal
  content of any pre-current version.
- **Snapshot risk:** these pages change. The extracted text is committed as
  `patch-notes.json` so a later reader can see what was read on this date.

## 6. Dependent implementation/scenarios

- Any future "which build changed this" question starts from `patch-notes.json`, then confirms
  in the binary. The changelog is a hypothesis generator, never evidence of behaviour.
- The "FTP transfer at 4.00" and "animal Eye AF" entries are concrete targets for a diff
  against a donor body that predates them.

## 7. Reproduce

The pages are read-only and public. The committed extract was produced by walking each model's
`.../downloads` page, opening its Windows firmware page, expanding
"Previous Benefits and Improvements", and storing the resulting text:

```bash
python3 -I tools/research/patch_notes.py --pages docs/evidence/cross_model/patch-pages.tsv \
    --out patch-notes.json
```

(The crawler uses an attached browser because the support pages return 403 to a plain HTTP
client; nothing is posted or logged in to.)

## 8. Next experiment

Take the one changelog entry that names a command this project already tracks — the `ILCE-7C`'s
"animal Eye AF in movie" — and compare `ILCE-7C` against a body whose changelog lacks it at the
same kernel build. If the only difference is the `0x413b` chain in `av-cam.bin`, the changelog
becomes a usable index into the binary; if it is broader, the changelog's granularity is
established as feature-level, not command-level.
