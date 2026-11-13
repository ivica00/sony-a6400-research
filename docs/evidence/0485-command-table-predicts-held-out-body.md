# E0485 — The command table predicts a held-out body's surface; USB and device nodes do not

Date: 2026-11-13. Offline only: seven unpacked bodies, no camera, no execution.

A description lists what was read. This record tests whether the work produced a *model*: a rule
fitted on four bodies, scored on three it never saw. The answer is uneven, and the unevenness is
the result.

## 0. Short answer

1. **The command-table rule predicts a new body well.** Fitted on a6400, a6100A, ZV-E10 and ZV-1,
   it recalls **0.997** of the a6600's commands, **0.885** of the a7 III's and **0.973** of the
   a9 II's. The plan's bar was recall ≥ 0.9 on at least two of three held-out bodies; three of
   three are at 0.885 or above, two clear the bar.
2. **The USB rule and the device-node rule predict nothing, and are reported as zero.** They are
   not fitted at all — the fitted rule carries only command ids — so scoring them 0 is honest
   rather than a failure of prediction: there is no rule to fail.
3. **The a7 III is the body the rule does worst on**, at 0.885, and that is the body whose USB id
   set diverges from the others (E0487). Prediction quality tracks shared lineage, which is what
   a model built on a family should show.
4. **An empty prediction scores 0, not 1.** A rule that predicts nothing has nothing wrong with it
   and everything missing; the test pins that so the metric cannot be gamed.

## 1. The experiment

```bash
python3 -I tools/research/predict_body.py \
  --roots <a6400> <a6600> <a6100a> <zve10> <ILCE-7M3> <ILCE-9M2> <ZV-1> \
  --hold-out a6600 ILCE-7M3 ILCE-9M2 --emit-tsv \
  > docs/evidence/cross_model/prediction-scores.tsv
```

The rule is deliberately conservative: **a command id is expected on a new body when every
training body has it**. Sony's tables form a ladder (E0477), so the intersection is the part a
body is unlikely to drop. The union would score better on recall and predict nothing useful —
"this body has all 337 commands" is not a prediction.

| held-out body | command_recall | usb_match | devno_match |
| --- | --- | --- | --- |
| `ILCE-6600` | 0.997 | 0.000 | 0.000 |
| `ILCE-7M3` | 0.885 | 0.000 | 0.000 |
| `ILCE-9M2` | 0.973 | 0.000 | 0.000 |

## 2. Reading the numbers

**Command recall.** The a6600 has 286 records; the rule predicts 285 of them. That is exactly the
one-command difference E0477 measured: the a6600 adds `0x413b` over the a6400, and a rule fitted
across bodies cannot know about a command only the a6600 has. Missing exactly the one command that
distinguishes the body is the correct behaviour of a conservative rule, and it is visible in the
0.003 shortfall rather than hidden.

The a7 III's 0.885 means 37 of its 322 records were not predicted. Those are the ids the ZV-line
bodies do not share, which is consistent with the a7 III being the body whose USB set also diverges.

**USB and device nodes are 0 by construction.** `fit()` returns only `command_ids`, so `score()`
compares an empty set against a real one. That is not a prediction problem — it is the honest
statement that no rule was derived for those two surfaces. A rule for the USB set would have to
explain why the a6400's six pairs are a subset of the a6600's ten and a subset of the a6100A's
twelve while the a7 III shares four and adds four of its own (E0487); that is a lineage question,
not a counting one, and inventing a rule to make the column look better would be exactly the
fabrication this record's metric is designed to expose.

## 3. Alternative explanations

- **"The recall is high because the rule saw those bodies."** No: `score_held_out` fits on the
  four bodies not named in `--hold-out` and reports only the three that are. The test
  `test_scores_are_reported_only_for_the_named_bodies` fails if a fitted body appears.
- **"The rule is trivial: almost all commands are shared, so any body scores high."** True for the
  A6xxx/ZV line and false in general: the ZV-1 at 294 records and the a9 II at 293 are bodies
  where the ladder differs, and the a7 III's 0.885 is the case that shows the rule can miss.
- **"0.000 for USB means the prediction was wrong."** It means no prediction was made. Reporting
  it as a failure would be clearer; reporting it as a success would be false. The record says
  which, and the column is left visible rather than dropped.

## 4. Confidence and limitations

- **Verified:** the three recall figures, from the command tables measured in E0477 and the rule
  in `predict_body.fit`; the absence of a USB or device-node rule in that function.
- **Not verified:** that a body outside the CXD90045 family would score anything. The rule is
  fitted on one family and makes no claim beyond it.
- **Not verified:** that recall predicts anything a user cares about. It measures agreement
  between tables, not capability.

## 5. Dependent implementation

`tools/research/predict_body.py`, 6 tests in `tests/test_predict_body.py`. The tests pin the two
properties that make the metric meaningful: an empty prediction scores 0, and a fitted body never
appears in the held-out output.

## 6. Next experiment

Derive a USB rule from lineage rather than counting: group bodies by shared kernel symbol set
(E0477's nine kernels) and test whether the USB pair set is a function of that group. If it is,
the a7 III's divergence becomes predictable and the `usb_match` column stops being zero.
