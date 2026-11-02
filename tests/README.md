# Tests and camera scenarios

Future automated tests belong here by responsibility: loader, architectural integration, device contracts, trace replay, and differential scenarios. Add checks when those components exist; empty folders are not implemented coverage.

Current software-only checks cover strict capability stops, ARM return/fault/limit behavior, and bounded ELF relocation/layout/inventory behavior. Run `.\venv\Scripts\python.exe -m unittest discover -s tests -v` from the project root. These checks do not claim camera equivalence.

Legacy screenshot generation lives in `legacy/test_authentic_screens.py` and is not a fidelity test.

Use `scenarios/TEMPLATE.md` for camera comparison cases. Hardware runs must be opt-in and must not be invoked during ordinary repository checks.
