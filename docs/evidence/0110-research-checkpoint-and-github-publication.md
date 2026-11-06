# E0110 — Research checkpoint and publication audit

Date: 2026-11-06. User requested documentation of remaining findings, the
live-camera/emulator workflow, and publication of the accumulated project work
to the existing GitHub repository.

## Documentation consolidated

E0084–E0109 and the native-debugger documentation had not yet been committed.
They record both successful and failed physical observations. Latest findings
are E0106 complete active-menu lookup/geometry, E0107 model/row association,
E0108 original geometric hit checks and separate selection, and E0109 guarded
activation, actual thread context and resource-management boundary.

The new [workflow](../LIVE_CAMERA_EMULATOR_WORKFLOW.md) records the full cycle:
source identity, actual state capture, original execution, explicit dependency
stop, targeted camera read, repeatable controls, prepared physical interaction,
archive-before-cleanup, evidence qualifications and publication boundaries.
README, roadmap and current assessment now point to the latest state; the older
GUI/menu plan is explicitly historical. No completed physical touch feature is
claimed. Old pending captures remain historical below newer completed statuses.

New publication metadata in
[0110-local-evidence-inventory.json](manifests/0110-local-evidence-inventory.json)
records byte lengths and SHA256 identities of23 key local captures/reports.
It contains no raw firmware or RAM. Generated snapshots, camera binaries,
sysroot, checkpoints, SD content and raw artifacts remain excluded by the
repository policy. Replays require those private local inputs; a source clone
alone is not asserted to reproduce the camera experiments.

Selected authored native debugger/observer C/assembly sources are preserved in
`tools/native_camera/`, with guarded deployment scripts included explicitly.
Their original local directory is a separate Git checkout and remains ignored;
no incomplete gitlink/submodule is published. The debugger builder uses the
canonical source copies while preserving local output paths. Compiled payloads
remain ignored.
Existing tracked emulator changes, tests and untracked authored project tools
are preserved in this checkpoint rather than silently discarded.

## Open implementation discrepancy preserved

E0097's output-backpressure evidence already identifies the manually fabricated
MonDrv output queue in `restore_checkpoint`. That block remains in the current
working implementation. Its comment says authentic, but original MonDrv/MWF
initialization has not been executed by that block. This is an acknowledged
unvalidated host workaround, not firmware compatibility or a resolved boundary.
Removing it and establishing original initialization remains follow-up work.
Publication is a record of the current research state, not a claim that every
experimental change is validated.

The separate MediaDetect/UIPC/scheduler work is described by the E0095–E0097
emulator notes alongside the hardware-menu notes with overlapping numbers.
Use the complete evidence filename, not just the numeric prefix, to distinguish
those parallel historical records.

## Validation

`python -m unittest discover -s tests -q`: **566 tests pass**,19.337s in the
successful Windows host run. The first restricted run had four errors creating
or cleaning temporary directories; the unchanged suite passed with normal host
filesystem access. No test expectation was weakened. pytest is not installed in
the inspected environments; unittest is the actual project test runner.

The preceding research continuation also reran original145-widget geometry,
252 hit checks, page binding, root selection and13 controller states. Original
activation still does not return: explicit main-thread control stops BEFORE
resource-manager write0x12abb0 at0x64c2fa8 after13,994 instructions.

This documentation/publication step makes no camera application calls, RAM
patches or SD writes and arms no observer. Further activation research is the
next task after this checkpoint.
