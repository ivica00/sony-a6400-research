# Legacy research prototypes

The HLE harness executes selected ARM routines but supplies application behavior and display pixels in Python. The standalone simulator and screen generator are visual research tools. None is a validated firmware compatibility backend.

Launch the prototypes as modules from the repository root (for example `python -m legacy.cxd90045_gui_runner`); the former root forwarding stubs were removed in the 2026-11-11 reorganization. Shared path setup in `project_paths.py` keeps firmware and upstream dependencies at their existing locations; generated images go to `artifacts/legacy/`.
