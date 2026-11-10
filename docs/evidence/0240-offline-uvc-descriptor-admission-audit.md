# E0240 — Offline UVC/PTP descriptor and endpoint-admission audit

Date: 2026-11-09. Offline only: no camera access, no module load, no UVC activation. This is step P2 of the UVC/PTP critical path.

## Purpose

Verify the current candidate descriptor matrix and the original native SET_CONFIGURATION directionless endpoint rule behind the earlier Windows Code 10, and confirm that the endpoint-84 move resolves it.

## Inputs

- `tools/native_camera/uvc_ptp_descriptors.c`, SHA-256 `5600bd72d5a5efd5c7e733820b55868c533914bd014defbbf8ace3c8b978eb3b`.
- `tools/research/probe_uvc_ptp_config_endpoints.py`: executes the original Sony SET_CONFIGURATION admission loop with explicit descriptor/stack/context fixtures (service doubles), stopping at the conflict branch or completed scan.
- New `tools/research/probe_uvc_ptp_descriptor_matrix.py`: static source audit of the candidate matrix.
- The latest built module (`artifacts/native/uvc-ptp-module-e0212`) is enumeration-only: video START is suppressed and UPDATE/ENABLE/WAIT are rejected, so descriptor acceptance is not streaming.

## Results

Original endpoint scan, 4/4 cases:

| UVC video endpoint | Native scan outcome |
| --- | --- |
| `0x82` | **conflict** (directionless address `0x02` already owned by PTP OUT) |
| `0x84` | **accepted** (scan completes) |
| `0x81` | conflict |
| `0x83` | conflict |

Static descriptor matrix, 18/18 checks:

- Interfaces: `0` PTP class 6/1/1 with bulk IN `0x81`, bulk OUT `0x02`, interrupt IN `0x83`; `1` UVC VideoControl class 14/1 with no endpoints; `2` VideoStreaming class 14/2 with bulk IN `0x84`.
- IAD `{8,11,1,2,14,3,0,0}`: length 8, type 11, first interface 1, interface count 2, function class 14, subclass 3; VC `baInterfaceNr=2`.
- Directionless endpoint addresses `{1,2,3,4}` are unique; the old `0x82` would collide with PTP OUT `0x02`.
- HS max packets `512/512/32/512`; FS PTP packets `64/64` (third inherits 32); FS interrupt interval 10.

## Interpretation

The E0208/E0209 Windows parent Code 10 is consistent with the native directionless collision; moving shared UVC video to `0x84` completes the original endpoint scan, and E0210 physically enumerated parent + PTP + UVC children with Code 0. The E0210 freeze/teardown failure remains open: descriptor acceptance is not Windows binding proof, endpoint allocation, a PTP transaction or streaming. No sensor frame is involved.

## Limits

Static source audit plus original-scan fixtures, not the live serializer, SET_CONFIGURATION, hardware allocation or Windows driver binding. No camera was touched in this step.

## Next

P3: producer admission — source span, decoded dimensions (E0239 parser), WAIT before reuse and per-slot frame lengths — wired behind an opt-in compile flag and ARM-audited. P0 (PC Remote reboot isolation) still gates P4 enumeration/teardown reruns.
