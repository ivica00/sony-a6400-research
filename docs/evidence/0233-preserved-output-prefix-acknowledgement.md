# E0233 — Preserved output prefix acknowledgement (offline)

Date: 2026-11-09. E0232 actual result is recorded separately. No new physical deployment, query, SD write or UVC activation in this step.

The prior strict ack deliberately required producer cursor equality with the preserved snapshot end. A native producer can append while the collector verifies its saved copy. New opt-in modes `--ack-preserved-prefix` and `--ack-probe-prefix` acknowledge only the saved prefix, leaving newer bytes pending. Existing strict modes and their original13cases remain unchanged.

Admission requires bounded saved/current cursors, the current read cursor equal to the snapshot start, and current available bytes at least as many as the saved prefix. The repeated observation must retain these conditions and may not show availability decreasing relative to that same read cursor. Background mode requires empty input and unchanged input indices between checks; query mode requires the exact published input endpoint while allowing its native reader to progress. Queue-object/GOT identity checks remain. Only the saved output read endpoint is written, never the latest producer position. Any uncertainty stops without retry or rollback.

This relies on original SPSC ring full detection keeping one slot unused: with the read cursor unchanged the producer cannot lap/overwrite the preserved prefix. It is not a multi-consumer CAS or proof excluding an external consumer completing a full ABA cycle. Sequential pre/post checks do not create exclusive ownership. Original ring replay still passes9cases (including full/wrapped-full and byte-before-index enqueue), with its original explicit division fixture. No physical concurrency proof is claimed.

Build/ARM audit: `artifacts/native/monitor-prefix-e0233/manifest.json`,21compiled admission cases (13unchanged +8prefix cases: appended/wrapped data accepted, insufficient prefix/moved consumer/foreign input/invalid prefix rejected, query reader progress accepted). Complete collector Sony-libc build: `artifacts/native/monitor-sd-collector-e0233/manifest.json`;11compiled SD identity cases and11mocked collector/receipt cases pass. Its stage tool selects this build. Second-header/live mapping/physical pwrite interleavings remain outside pure admission tests.

Validation:620tests pass17.997s (`artifacts/monitor-prefix-e0233-tests.log`); required interpreter verified, original9ring cases retained in `artifacts/monitor-prefix-e0233-original-ring.log`. A guard audit was initially invoked before asynchronous ARM build completion and reported missing binary; it was rerun after confirmed build completion and passed. No test was weakened, packages changed or incidental cleanup performed.

Status SVG/rootPNG and report copy `artifacts/reports/status_a6400-e0233.png` refreshed and visually inspected: query NOT SENT, SD NOT WRITTEN, no completion percentage or new compatibility claim.

Next: bounded ordinary MSC→PCRemote→MSC query observation using this version, recover actual result/prompt/receipt and verify cleanup. E0232 proved physical preserve-before-ack of the initial output, not the new prefix mode or successful query. Approved SD journal remains unwritten; configured UVC/sensor/PTP-control integration is still unfinished.
