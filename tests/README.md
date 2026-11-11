# Tests and camera scenarios

The offline suite is the project's primary regression check: bounded contracts for guest
execution, kernel/syscall/device responses, USB/UIPC decoding, the UVC/PTP transport work,
plus the repository-structure, target-profile and documentation-sync contracts. No camera
is required and no test may touch USB or the device.

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -q
```

```bash
python3 -m unittest discover -s tests -q
```

Structure/target/docs contracts on their own (also what CI runs):

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_repository_layout tests.test_target_profiles tests.test_research_status_sync -v
```

These checks do not claim camera equivalence. Legacy screenshot generation lives in
`legacy/test_authentic_screens.py` and is not a fidelity test. Use `scenarios/TEMPLATE.md`
for camera comparison cases: hardware runs must be opt-in and must not be invoked during
ordinary repository checks.