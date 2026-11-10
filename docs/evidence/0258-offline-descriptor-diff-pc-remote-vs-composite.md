# E0258 — Offline descriptor diff: original PC Remote vs composite candidate

Date: 2026-11-09. Offline only: retained captures, no camera.

## Tool

`tools/research/compare_pc_remote_descriptors.py` parses the E0152 PC Remote capture and the E0210 composite capture, comparing device class, interface topology, IAD, and the PTP interface. Tests: `tests/test_descriptor_diff.py` (3 cases).

## Result

| Property | PC Remote (E0152) | Composite (E0210) |
| --- | --- | --- |
| Device class | `[0, 0, 0]` | `[0xEF, 2, 1]` |
| Interfaces | 1 | 3 |
| IAD | absent | present |
| PTP interface 0 | 6/1/1, endpoints 81/02/83, 512/512/32/interval 7 | **identical** |
| Extra interfaces | — | UVC VC 1 (14/1), VS 2 (14/2) with endpoint 84 |

Manifest: `artifacts/analysis/pc-remote-descriptor-diff-e0258/manifest.json`.

## Interpretation

The PTP interface itself is unchanged. The differences are the composite device class (`0xEF/2/1` vs `0`), the added UVC function, the interface count and the IAD. Any behavior difference in Sony's PTP liveview therefore cannot be attributed to the PTP endpoint descriptors; it must involve the device/configuration context or the app's handling of the composite topology.

## Limits

Historical captures; they show descriptor structure only, not the camera app's state machine.
