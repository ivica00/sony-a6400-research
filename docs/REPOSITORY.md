# Repository organization and migration

Organized on 2026-10-18. No Git initialization, commits, upstream moves, firmware modifications, or camera operations were performed.

| Original location | Implementation / data location |
| --- | --- |
| `cxd90045_hle_emulator.py` | `legacy/cxd90045_hle_emulator.py` |
| `cxd90045_gui_runner.py` | `legacy/cxd90045_gui_runner.py` |
| `sony_gui_simulator.py` | `legacy/sony_gui_simulator.py` |
| `test_authentic_screens.py` | `legacy/test_authentic_screens.py` |
| `analyze_hardware_drivers.py` | `tools/research/analyze_hardware_drivers.py` |
| `firmware_analyzer.py` | `tools/research/firmware_analyzer.py` |
| `unpack_firmware.py` | `tools/research/unpack_firmware.py` |
| `check_camera.py` | `tools/research/check_camera.py` |
| `backup_camera.py` | `tools/research/backup_camera.py` |
| Root PNG files and `temp_crops/` | `artifacts/legacy/` with original names |
| `20261015-_DSC0799 copy.jpg` | `assets/reference/20261015-_DSC0799 copy.jpg` |

The nine root Python files are compatibility entry points supporting existing root commands and imports. Run scripts through these entry points or as modules from the project root; direct execution of nested implementation files is not the supported launch path.

`project_paths.py` centralizes root, reference, and artifact locations. Firmware and upstream tool paths remain unchanged. Backup output is resolved from the project root. New icon exports use `artifacts/legacy/exported_icons/`.

At initial organization, `src/a6400/` contained only a responsibility guide and placeholder directories. It now contains a separate bounded original-interpreter probe; see [E0003](evidence/0003-original-interpreter-boundary.md). Machine/device components remain planned. Keep execution work separate from the existing behavioral simulator.

## Verification scope

Organization checks parse all 19 first-party Python files, import seven software-only root entry points, instantiate the legacy harness, load its relocated photo, and render a menu. The root screenshot-generator command is also exercised. These checks confirm path/import compatibility, not firmware or physical-camera fidelity. USB diagnostics and service-mode backup tools are not executed as part of verification.

Before first source-control import, review ignored inputs and record upstream revisions and dependency provenance as specified in Phase 0. The existing virtual environment and proprietary/local artifacts remain on disk.
