# E0231 — Query not published; complete receipt and cleanup

Date: 2026-11-09. User completed ordinary PCRemote→MSC return. No UVC activation or SD write. This test did not execute the SD information query.

## Physical result

E0230 collector PID929,16140bytes/SHA425711d052ec10a9bea70a40ae822962e813c476eb53c29d202a91f4a206e158, was staged READY at16:48:59 local time. User's PCRemote confirmation was processed around16:50:45, beyond the nominal60-second admission window; the actual physical switch time was not continuously observed. Windows showed native ILCE-6400 054C:0CAA/WPD StatusOK. This does not establish that timing alone caused rejection.

Recovered208-byte receipt explicitly states `SD_QUERY published=0 endpoint=4294967295`, query result0. Stdout contains repeated pre-publication `ACK_REJECTED no_write`, then `RECEIPT_VERIFIED bytes=208 captured=0 query_result=0 RAM_only`. No successful publication or native operation result. The old generic rejection message cannot identify the failed guard.

Artifacts: `artifacts/hardware/uvc-monitor-sd-query-e0230-run/` contains run.json, ready/launch, receipt.bin, stdout.bin, pre/post status/modules, helper-exit and cleanup receipts. After collection, PID149 TracerPid0/no usbg_video were checked. PID929 was verified absent. Both remote receipts were read again and compared byte-equal to host copies, then only the4run-owned RAM paths were removed and absence checked. No helper/module/hook remains from this run. Camera returned MSC normally; no freeze was reported.

## New observed boundary and correction

Post-cleanup read-only capture `artifacts/hardware/uvc-monitor-sd-query-e0231-post` observed input10/10 unchanged and output30153/17066,18641bytes, SHA63f01869e492017fb36ab045121e1036e060154b946f10699b79452d06c29d88. Those bytes include original filesystem/application diagnostics produced during the ordinary mode cycle. They are preserved without cursor acknowledgement and are not a response to our unpublished query. Their generation time/cause is not individually proven. Their presence demonstrates that the preflight-empty condition does not remain true across a mode switch; the previous collector could reject while native output accumulated. This is a plausible admission blocker, not a proven exact rejection site.

New offline collector first saves/fsyncs/readback-verifies preexisting output before acknowledging it with the input-empty admission policy. It then retries the fixed query admission. Nonempty foreign input, any failed preservation or uncertain acknowledgement is terminal, never rolled back. Total log remains bounded32768bytes, so excess background output stops instead of silently discarding evidence. Wait for manual switch is now180nominal seconds; query reply remains60seconds. No new physical deployment was performed.

The SD identity guard now records its rejection group:1mapping/code,2A-device association,3service status,4subcommand table,5namespace globals,6unique registered dispatcher;0means no SD-identity rejection was recorded (another outer guard can still fail). Same rejection conditions remain enforced. No ownership or concurrency claim is added.

Final offline build is `artifacts/native/monitor-sd-collector-e0231-final/manifest.json`; staging tool now selects this build rather than E0230. Eleven compiled identity cases still pass; eleven mocked collector cases include preserve-before-ack of background output and rejection without ack/query when preservation fails. Full regression and required interpreter receipts are `artifacts/monitor-sd-collector-e0231-*.log`. These are fixtures, not physical verification of the correction.

Next: repeat only the ordinary bounded information-query observation with the corrected collector and recover actual query result/prompt/receipt. Do not infer permission to activate configured UVC from this failed admission test. Approved SD journal still requires collision-safe creation, bounded write/flush/readback and restart survival. Status image remains E0227's latest positive physical milestone; this failed query must not increase compatibility claims.
