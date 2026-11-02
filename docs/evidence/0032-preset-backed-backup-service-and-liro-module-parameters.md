# Evidence 0032: Preset-backed backup service, verified RAM mutations, and authentic LIRO module parameters

## Result and scope

A dedicated, evidence-backed backup service implementation (`src/a6400/execution/backup_service.py`) now replaces unverified acknowledgements with authentic BK4 preset state and memory mutation contracts.

Key findings and milestones:
1. **Authentic BK4 Decoding and Mutable RAM**: `BK4PresetState` validates the preserved packaging preset `CX62600_UC2.bin` (691 subsystems, 28,900 properties, data offset `0x2b6a0`). It implements the exact lookup algorithm of original `Data_SearchId`, resolving property descriptors, attributes, sizes, and direct payload offsets.
2. **Preset-backed UIPC Synchronous Dispatch**: `PresetBackedBackupService` handles synchronous messages on queue `0x003e014d`:
   - **Operation 8 (`Backup_write`)**: Enforces subsystem matching (`unit >> 16 == subsystem`), resolves unit descriptors, reads guest memory, updates the preset RAM buffer, and writes status `0` to message word 1.
   - **Operation 3 (`Backup_read`)**: Resolves unit descriptors, copies authentic preset bytes to the guest destination buffer, and writes read byte count to message word 1.
   - **Strict Fail-Closed Boundaries**: Any request for an unindexed unit or unsupported operation raises `UnsupportedUipc`.
3. **Authentic LIRO Module Parameter Generation (`im.elf l`)**:
   - `im.elf l` executes 2,226,832 instructions (advancing past the 2,107,833 backup service boundary).
   - At `0xb314`, `Backup_read(0xfa, 0x00fa007c, &adr)` receives `0x035c6000` from preset offset `0xb4de0`.
   - Original `im.elf` code formats the authentic module argument string:
     ```text
     adr=0x35c6000
     ```
     (replacing the broken `adr=0x0` produced when backup replies were unserviced).
   - `im.elf` opens `/usr/kmod/liro.ko` and reaches `sys_init_module` (syscall 128) with `uargs = " adr=0x35c6000  "`.
4. **Task 94 Progression and Worker Thread Activation (`im.elf i`)**:
   - Authentically services `Backup_write(0x3e, 0x003e000b, &val=1)` at preset offset `0x66b2c` and `Backup_write(0x94, 0x00940003, &val=0)` at preset offset `0x860b0`.
   - Progresses through Task 94 Phase 0, creates worker thread TID 1001 via `sys_clone`, which sets its thread name via `prctl(PR_SET_NAME, "THREAD_INFRA0")`.
   - `THREAD_INFRA0` loads and relocates over 30 original infrastructure shared libraries (including `libObj.so`, `libInfraFsys.so`, `libmintx.so`, `libssp.so`, `libexpat.so`), executing over 8,000,000 instructions.

**The default fail-closed boundary remains unchanged.** `--backup-service stop` remains the default probe policy; the authentic capability is explicitly selected via `--backup-service preset-backed`.

## Inputs and identity

| Input | SHA-256 |
| --- | --- |
| Preset `CX62600_UC2.bin` | `241c8521035bc9ff1edbe66cf3d42d81879a4bef8ff9e21cbfb84530a1446154` |
| `usr/bin/im.elf` | `866729eb0bc1e6f5aba04d8bf8e45491985afe89a078ccb106a1ce2476865225` |
| `usr/kmod/liro.ko` | `ce9f8c679a7850a5814125b29f0e1376fa2e3e5c9b6db94eecbb7d827f311c97` |
| `usr/kmod/backup.ko` | `63c69e991a8da77e301a7090c8ba6e4dcced43921e88415e3591cf0e96dbb2c6` |
| `usr/lib/libbackup.so` | `ab3ad7b492a1654bfa3f1468106785f933539fffcbe709f808af8dc2c59bbc15` |

All inputs match preserved inventory hashes. No files or camera memory were modified.

## Unit resolution and memory mapping

In `BK4PresetState`, descriptor lookup for verified units resolves as follows:

| Unit | Subsystem | Prop Index | Attribute | Size | File Offset | Initial Value | Mutated By |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `0x003e000b` | `0x3e` | `0x0b` | `0x0000` | 1 byte | `0x66b2c` | `0x01` | `im.elf` Task 94 Phase 0 write (`0x01`) |
| `0x00940003` | `0x94` | `0x03` | `0x000a` | 1 byte | `0x860b0` | `0x00` | `im.elf` Task 94 Phase 0 write (`0x00`) |
| `0x00fa007c` | `0xfa` | `0x7c` | `0x0000` | 4 bytes | `0xb4de0` | `0x035c6000` | Read-only in `im.elf l` |
| `0x00fa0076` | `0xfa` | `0x76` | `0x0000` | 4 bytes | `0xb4dc8` | `0x035c6000` | Read-only fallback |

## Reproduction and verification

```powershell
.\venv\Scripts\python.exe -m unittest tests/test_backup_service.py -v
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --backup-service preset-backed --argument l --instructions 5000000 --urandom-open --regular-inode-rdev --readonly-image-times
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --backup-service preset-backed --argument i --instructions 8000000 --urandom-open --regular-inode-rdev --readonly-image-times
```

All **280 tests pass**, including 10 new unit tests covering BK4 preflight checks, descriptor indexing, unit read/write mutations, UIPC dispatcher contracts, and subsystem validation.
