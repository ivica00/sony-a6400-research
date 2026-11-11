# Repository layout and migration

The tree was reorganized in two steps. On 2026-10-18 implementations moved out of the
repository root; on 2026-11-11 the remaining root compatibility shims were removed and the
whole tree was reorganized as a multi-device **Sony BIONZ X (`CXD90045`) research platform**.
No Git history was rewritten, no firmware was modified and no camera operation was performed.

## Root directory

The root now holds only standard project files and core directories:

| Entry | Purpose |
| --- | --- |
| `README.md`, `LICENSE`, `CONTRIBUTING.MD`, `AGENTS.MD` | Project, licence, contributor and agent instructions |
| `pyproject.toml`, `requirements.txt` | Project metadata and the deterministic offline test/emulation dependency set |
| `project_paths.py` | Single root path-resolution module (see below) |
| `.github/`, `docs/`, `src/`, `tools/`, `tests/`, `scripts/`, `legacy/`, `probes/` | Source, tooling and documentation |
| `android/`, `android-client-ref/`, `camera-daemon/` | Track A / Track B client and camera-side work |
| `firmware/`, `backups/`, `artifacts/`, `reports/`, `scratch/` | Local preserved inputs and generated results; excluded from publication |

## Where things live

| Original location | Implementation location | Launch path |
| --- | --- | --- |
| `cxd90045_hle_emulator.py` | `legacy/cxd90045_hle_emulator.py` | `python -m legacy.cxd90045_hle_emulator` |
| `cxd90045_gui_runner.py` | `legacy/cxd90045_gui_runner.py` | `python -m legacy.cxd90045_gui_runner` |
| `sony_gui_simulator.py` | `legacy/sony_gui_simulator.py` | `python -m legacy.sony_gui_simulator` |
| `test_authentic_screens.py` | `legacy/test_authentic_screens.py` | `python -m legacy.test_authentic_screens` |
| `analyze_hardware_drivers.py` | `tools/research/analyze_hardware_drivers.py` | `python -m tools.research.analyze_hardware_drivers` |
| `firmware_analyzer.py` | `tools/research/firmware_analyzer.py` | `python -m tools.research.firmware_analyzer` |
| `unpack_firmware.py` | `tools/research/unpack_firmware.py` | `python -m tools.research.unpack_firmware` |
| `check_camera.py` | `tools/research/check_camera.py` | `python -m tools.research.check_camera` |
| `backup_camera.py` | `tools/research/backup_camera.py` | `python -m tools.research.backup_camera` |
| `launch_cinema_mpv.bat` | `scripts/launch_cinema_mpv.bat` | run the script; it resolves `%~dp0..` |
| `launch_cinemahud_android.ps1` | `scripts/launch_cinemahud_android.ps1` | run the script; it resolves the repo root from its own path |
| `launch_cinemahud_ptp.bat` | `scripts/launch_cinemahud_ptp.bat` | run the script; it changes to `%~dp0..` |
| `start_camera_shell.bat` | `scripts/start_camera_shell.bat` | run the script; it targets `%~dp0..\tools\cam_live_terminal.py` |
| `status.png`, `status_a6400.png` | `docs/images/` | written by `tools/research/generate_status_image.py` |
| `UVC_HANDOVER_PLAN.md` | `docs/UVC_HANDOVER_PLAN.md` | documentation |
| `ARCHITECTURE_UVC_MONITOR.md` | `docs/ARCHITECTURE_UVC_MONITOR.md` | documentation (hash-pinned by E0348) |
| Root PNG files and `temp_crops/` | `artifacts/legacy/` with original names | generated output |
| `20261015-_DSC0799 copy.jpg` | `assets/reference/20261015-_DSC0799 copy.jpg` | reference input |

The nine former root Python shims were deleted: their implementations had already been moved,
they were only forwarding stubs, and their documented launch paths are the module paths above.
`docs/archives/` and the dated `docs/evidence/` records keep their original root-command text as
history; they are not current instructions.

## `project_paths.py`

`project_paths.py` stays at the repository root because it is the single path-resolution module
for the codebase: `PROJECT_ROOT`, `REFERENCE_ASSETS` and `legacy_output()` are imported by more
than a hundred first-party modules under `src/`, `tools/`, `tests/` and `legacy/`. All of them
are run as modules from the repository root, so the root stays on `sys.path` and the module has
no relocated mirror.

## Verification scope

`tests/test_repository_layout.py` enforces this layout: no forwarding shims or launchers return
to the root, the moved assets live under `docs/`, and the launchers keep their `%~dp0..` /
`$PSScriptRoot`-parent resolution. `tests/test_target_profiles.py` and
`tests/test_research_status_sync.py` cover the multi-device registry and the documentation
sync. The offline suite is the primary check (`tests/README.md`); the earlier "seven
software-only root entry points" organization check no longer exists because the entry points
themselves are gone.

Two offline module audits remain available from `tools/research/`:
`python -m tools.research.probe_interpreter` writes its bounded probe report to
`artifacts/execution/`, and `python -m tools.research.audit_execution --mode research` runs the
preserved harness, records unsupported behavior (including a screen factory that returns no
instance) and exits `0`; `--mode strict` stops at the first boundary and exits `2`. Both are
optional checks: a boundary exit is not a regression and neither proves camera fidelity.

Before first source-control import, review ignored inputs and record upstream revisions and
dependency provenance as specified in Phase 0. The existing virtual environment and
proprietary/local artifacts remain on disk. USB diagnostics and service-mode backup tools are
never executed by repository validation.
