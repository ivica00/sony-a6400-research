# Validation protocol

## Run definition

Every result records: case ID, firmware/partition SHA-256, patch manifest, backend and model revision, dependency environment, initial nonvolatile state, card image, camera language/region/mode, lens/accessory state, external input source, ordered press/release events, clock policy, capture method, and output hashes.

Do not include serial numbers, calibration dumps, or private backup payloads in public reports. Refer to local hashes when needed.

## Observations and assertions

| Dimension | Required observation | Pass criteria |
| --- | --- | --- |
| Execution | Original path trace, stop reason, unsupported-event count | Intended checkpoint reached; no undeclared substitutes |
| Semantics | Screen/state transitions and enabled options | Expected ordered transitions and state values |
| Visual | Actual guest display output and camera reference | Predetermined comparison metric and tolerance appropriate to capture method |
| Persistence | State before/after reset and relevant stored data | Matches the documented camera behavior |
| Files | Content, metadata, naming and errors | Case-specific comparison against camera outputs |
| Timing | Repeated measured event intervals | Predeclared tolerance under controlled conditions |
| Patch effect | Base and patched runs with matched initial state | Intended observable effect, no unexplained divergence in covered observations |

Raw framebuffer comparison may permit exact pixel checks. Photograph comparison requires alignment, scaling, exposure, and display-response considerations; record these transformations and avoid an exact-pixel claim. Declare masks before evaluating results; do not mask unexpected differences after the fact.

## Procedure

1. Verify input hashes and reset both systems to the recorded state.
2. Repeat stock-camera observations to discover natural variation.
3. Replay the same ordered inputs in the emulator; capture trace and outputs.
4. Compare each claimed dimension separately. Locate the first divergence.
5. Repeat with an isolated, documented mutation. Validate physical patched behavior only where such a test is explicitly planned and authorized.
6. Record pass, fail, blocked, or not tested. Keep failures and limitations with the result.

## Required negative cases

- Missing imported symbol and unsupported relocation cause a clear stop.
- Unknown device access cannot silently allocate usable hardware.
- Execution fault or timeout cannot be reported as success.
- Missing guest rendering cannot leave a convincing host-generated camera UI.
- Patch preimage mismatch rejects the patch.
- Reset restores the defined volatile state and preserves only specified persistent state.

Compatibility status: **planned**, **experimental**, **validated for stated scope**, **unsupported**, or **blocked**. Existing legacy screenshots are illustrative and do not start at validated status.
