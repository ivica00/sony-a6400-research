# Experiment 0010: DMM package configuration and reservations

Question: can original DMM code derive graphics allocation state from preserved package configuration before a GRM-MA response is implemented?

Command: `.\venv\Scripts\python.exe -u -m tools.research.dmm_config_trace`.

Inputs, hashes and results: [E0035](../evidence/0035-dmm-configuration-and-boot-reservations.md).

The isolated engine uses explicit synthetic section mappings, stack and cold module BSS. It selects the preserved configuration's memory-reader branch. Each call is bounded to 3,000,000 instructions and 30 seconds; unknown imports/literals, invalid memory and reads beyond supplied configuration stop explicitly. Only byte-fill and unsigned division helpers are supplied. No host filesystem or camera operations are forwarded.

Run parser-only observation separately from full allocation-state initialization. Initialize every configured boot reservation before attempting graphics allocation/open; do not skip a failed reservation or substitute a configured parent's base address. Do not treat the package file as observed runtime state.

Observed: table parsing and allocation-state initialization return zero. First boot reservation stops on an unsupplied timer service request before graphics allocation. The report records request bytes, PC and the original instruction tail. No service reply, shared log-buffer address or timestamp is invented. The main `im.elf i` process contract is unchanged.
