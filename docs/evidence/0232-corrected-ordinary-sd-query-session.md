# E0232 — Corrected ordinary SD information query session

Date: 2026-11-09. Session pending receipt recovery at this update; no physical result is implied by elapsed monitoring. No UVC activation, module/hook installation or SD journal request.

The E0231-final collector20280bytes, SHAc29459073e5b5ea88e136034f327f67172cb9d8d51a8e642fe3d01745638b615, was uploaded byte-equal to fresh own RAM paths. PID1049 READY was captured at16:56:39local. User promptly confirmed ordinary PCRemote switch. Windows native054C:0CAA/WPD ILCE-6400 StatusOK is preserved in `artifacts/hardware/uvc-monitor-sd-query-e0232-run/pcremote-host.json`. A subsequent host debugger connection found0compatible devices during the mode transition; no command was retried through another transport.

All exact owned paths/build identity/launch/READY records are in that run directory. Query admission window180nominal seconds, response60; original services/OS IO are not subject to a proved hard deadline. Wait for user return to MSC and recover actual receipt/stdout before declaring success or failure. Do not restage based on host timing. The existing E0231 corrections preserve native output before acknowledgement and record SD guard stage1..6. These corrections are not yet physically verified by a recovered receipt.

Host cleanup is now an explicit `cleanup` phase in `run_native_monitor_sd_query`: exact4paths must share the run's timestamped `/tmp_bt/mon_sd_...` prefix; path traversal, mixed-run and extra paths are rejected. It requires previously verified collection, absent helper PID and byte-equal remote/host receipt/stdout before deleting only those4paths, then verifies absence. Ordinary unit tests cover path isolation without USB access. This workflow does not certify arbitrary concurrent ownership or permit unrelated deletion.

## Recovered physical result

User returned MSC normally. Full20013-byte RAM receipt and stdout recovered and verified. Initial18641native output bytes were preserved, fsync/readback verified, then acknowledged30153→17066; output was observed empty and input10/10. Eight subsequent attempts rejected at SD guard group2 (A/device association); samples lack per-attempt timestamps and this does not establish that A was absent throughout PCRemote. Then1117new native output bytes were preserved, but their acknowledgement was rejected (`sd_guard_stage=0`, not a filesystem-identity failure). Collector returned query_result-1 without publishing any query. No native query reply or filesystem success result.

The strict acknowledgement requires the current output producer cursor to equal the saved snapshot end and the repeated header to remain identical. Actual rejection receipt does not identify which outer check failed; appending native output is a plausible reason, not a proven exact branch. This exposed the need for a prefix-aware acknowledgement policy, treated in E0233. The collector stopped after these bounded observations rather than using the entire180s admission window; elapsed host waiting did not reveal that early stop.

Cleanup phase succeeded: helperPID1049 absent; remote receipt/stdout re-read byte-equal to host copies; exactly4owned RAM files removed and absence checked. Final PID149 TracerPid0/no usbg_video. No freeze reported, no SD write/UVC activation.620ordinary tests pass16.980s after host cleanup isolation tests; required interpreter verified.

Next: verify prefix acknowledgement offline before any corrected ordinary observation. SD journal remains unwritten and configured UVC work remains behind recoverable observation/teardown requirements.
