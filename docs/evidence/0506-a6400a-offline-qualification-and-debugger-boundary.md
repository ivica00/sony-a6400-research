# E0506 - ILCE-6400A 1.01 qualification and native debugger boundary

Date: 2026-11-13. Offline official firmware analysis plus **read-only Windows USB
device metadata**. The owner confirmed ILCE-6400A, displayed firmware 1.01 and
Mass Storage, connecting USB without changing settings. No camera protocol
command, updater execution, bootstrap, module load, driver replacement,
filesystem access, SD change or flash write was performed.

## 0. Verdict

PR integration note (2026-11-14): the a6400A records were renumbered after
upstream allocated their original IDs. Local receipt directories and the
original observations below are unchanged.

**A valid BIONZ X research candidate, not a verified drop-in execution or deployment
target.** The signed package identifies the modeled SoC family and ARM machine,
the existing parsers accept its boot sets, and original USB packing code executes
correctly. Its kernel and application images are different inputs. Old addresses,
checkpoints, overlays and the original a6400 installer cannot be assumed safe.

The new `ilce_6400a` profile is **reference**, not `verified`. Registering evidence
does not automatically retarget the emulator or qualify a debugger installation.

| Area | Observation | Qualification |
| --- | --- | --- |
| Official input | Sony-signed 1.01 updater, exact published size | Passed input checks |
| SoC / ISA | Package `CXD90045`; ELF32 little-endian ARM EABI5; `ARM-CXD900X0`, machine ID `0xDA9` | Offline family match, not a live silicon read |
| Main kernel | 24,351 decoded symbol names, seven USB addresses independently resolved | Different image and addresses |
| Camera command table | Same 285 command IDs as original a6400, no additions/removals | Table membership only, not behavioral equality |
| Native USB API | Original 26-byte Thumb packing function passes on explicit buffers | Bounded original-code execution |
| Updater kernel | 3,001 original instructions, then unmapped UART write | Prefix only; not a kernel boot |
| Physical USB | `054C:0F0F`, revision `0200`, USBSTOR, status OK/error 0 | Host enumeration only |
| Installed debugger / live OS | Not queried | Unknown; no partition-dump access claimed |

## 1. Input identity and extraction

Official source: [Sony ILCE-6400A Windows firmware 1.01](https://www.sony.co.uk/electronics/support/software/00405394),
published 2026-06-30. The owner downloaded the file without running it.

| Input | Bytes | SHA-256 |
| --- | --- | --- |
| `Update_ILCE6400AV101.exe` | 324,175,032 | `fd6ae50755a9202a8b506b6b77aa27ab41ae717e96f05a0d4e2ad699b40d9ad1` |
| Main `vmlinux.bin` | 4,117,760 | `9d51ab60df8246f10cb2afb12fb504d7f148fae437ee404f5b9837cc3b8f85ca` |
| Packaged updater `nflasha1` | 8,323,072 | `c9040270ad886214c5656894b90fb1e839a3ab942cb65726633d8f1f1221c093` |
| Decompressed updater kernel | 3,590,400 | `0616ca7036567c9e6c1869fe47ece2debeebaecacad550aabbb3055d308cacd8` |
| Updater cramfs initrd | 4,943,872 | `040a7d7666aa93f6abeade2caf153fd346c42dd90931de37bd656ae63d615d8d` |

Windows Authenticode returned **Valid**, signer **Sony Corporation**, with a
DigiCert timestamp. The SHA-256 above identifies the retained download; it is
not represented as a separately published Sony digest.

`sony_updater_payload` recognized an inverted PackMan cabinet at `0x71A2C`.
Its restored cabinet is 323,698,894 bytes. Windows `expand.exe` listed the
cabinet, then extracted **only** `FirmwareData_ILCE6400AV101.dat`. No contained
Windows executable was extracted or run. The existing `fwtool.py` decrypted and
unpacked that data into a new local directory.

Selected configuration: `dat.crypterName=CXD90045`, `fdat.version=1.01`,
`fdat.model=0x81030017`. The main kernel reports Sony CE Linux **8.2.7.6**.
The inspected module vermagic is
`3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7`.

The reference is the preserved original-a6400 2.00 package, build 8.2.5.7.
It is **not** the original camera's later live 8.2.6.0 snapshot. Its updater
partition is not present locally: the first qualification script stopped
explicitly at that missing input; the corrected receipt records the comparison
as unperformed rather than assuming byte identity or reusing old address hooks.

## 2. Kernel, application and device contracts

The same bounded kallsyms decoder and kernel-backing verifier accept the a6400A
main image: the banner pointer agrees with its file offset and the text range
lies inside the image. Relative to the original package, 359 non-literal symbol
names are added and 439 removed. This is not the same kernel.

| Symbol | Original package | a6400A 1.01 package |
| --- | --- | --- |
| `usb_gadgetcore_ioctl` | `0x602B8844` | `0x602BC864` |
| `usb_gadgetcore_register_driver` | `0x602B8610` | `0x602BC630` |
| `usb_gadgetcore_unregister_driver` | `0x602B8560` | `0x602BC584` |
| `usb_gcw_start` | `0x602BD7F8` | `0x602C1818` |
| `usb_gcw_stop` | `0x602BD834` | `0x602C1854` |
| `setup_req` | `0x602B94A4` | `0x602BD4C4` |
| `make_config_desc` | `0x602BBC54` | `0x602BFC74` |

All seven addresses moved. The short start/stop instruction spans match, while
the other five compared prefixes differ. No relocated-call or object-layout
equivalence follows from this comparison.

The inspected application, loader and libraries are ELF32 ARM EABI5.
`im.elf` is ET_EXEC with entry `0x92B1` and interpreter
`//lib/ld-linux.so.3`. Its bytes, `libObj.so`, libc and ld.so differ from the
reference. Existing application offsets and checkpoints are not portable proof.

The relocation-aware device-table parser finds **88 rows**, including **17 USB
rows**. `/dev/usb/usb_extcmd` is a static candidate at **248:7**; no video/audio
row is published in this table. This is package evidence, not an attestation of
live nodes or a blanket assertion about built-in kernel functionality.

Eight stock descriptor pairs are declared, all under vendor `054C`:
`0448`, `047D`, `0BFE`, `0BFF`, `0CA7`, `0CA8`, `0F0E`, `0F0F`.
The updater pair is `054C:03E2`. Descriptor membership does not identify each
operating mode; only Mass Storage was observed on the body.

## 3. Native debugger assessment

| Component | Bytes | SHA-256 | Original-package comparison |
| --- | --- | --- | --- |
| `devno.ko` | 4,308 | `74096566ca4132ef3e947dc122427b6f3044ae5ab2d1657f5c6eb12945b1efa5` | Strict equivalence except allowed build-id/comment metadata |
| `libusbcmd.so` | 15,996 | `23b94deb094d31f160cfe1d46330f2425e94d4801dfccb66720c4cf4b81cfb7e` | Strict equivalence except allowed comment metadata |
| `usb_extcmd.ko` | 14,796 | `d47d05ec891d18c8582baf19e413967c5d3fd5c36438d76f6d2e8a7f112428e3` | **Not identity-equivalent: different file size** |

The source-identified a6400A `PackParamDriver` function (Thumb entry `0x2783`,
26 bytes) runs in Unicorn against constructed public/driver buffers. The expected
24-byte public structure becomes the expected 20-byte driver structure, with
reserved bytes untouched. The original-a6400 control also passes. This exercises
packing only: no registration, transfer, root permission or kernel reply is supplied.

The driver shares 31 named functions with the reference; 29 have identical
relocation-masked instructions and relocation names. `list_delete_node` and
`list_finalize` differ. Masked relocation addends do not prove loaded-object
identity or callability. This is promising porting evidence, not a deployment
approval or a reason to weaken the existing identity guard.

**Do not run the old installer as a compatibility test.** It uses Senser and
writes payloads/startup configuration after its original-input checks. Its
strict driver comparison would reject this packaged module. No a6400A bootstrap
or daemon installation was attempted, and installed-debugger presence remains
unknown. Host USBSTOR enumeration does not answer that question.

## 4. Bounded updater execution

The existing boot-set and boot-contract parsers recover load addresses
`0x00108000`, `0x00700000`, `0x00103000`, machine ID `0xDA9`, two RAM banks and
the package's Sony `kemco` boot-parameter text.

The prefix experiment uses a Cortex-A9 CPU **fixture**, a declared zero-initialized
16 MiB window inside the package's first RAM bank, the original kernel/initrd,
and reconstructed entry registers. It installs **no old address hooks, code
patches, automatic mappings or MMIO replies**.

It executes **3,001 instructions** from physical `0x00108000`, then stops at
PC **`0x0011FB78`** on an unmapped write to **`0xF2000038`** (PL011 register
window). Exit 2 is the preserved unsupported-hardware boundary, not application
success. No high-virtual entry, console output, root mount, shell or camera boot
is claimed.

## 5. Physical observation and safety

With the owner-confirmed camera connected in unchanged Mass Storage mode,
Windows CIM reports:

- USB identity **`054C:0F0F`**, `REV_0200`.
- USB storage class `08/06/50`, service **USBSTOR**.
- Signed Microsoft `usbstor.inf`, driver version `10.0.26100.9444`.
- Device status **OK**, configuration error **0**.

The final host-only postcheck still reports the same identity, USBSTOR and
OK/error-0 state.

Device-instance serials were not retained. No camera file, partition, process,
kernel memory or `/dev/mem` was read. No proprietary input is committed.
USB presence/status is not an uptime or native-debugger responsiveness measurement.

## 6. Changes and validation

- Added the separately sourced **reference** profile and public registry export.
- Kept UIPC handles, live build and untested USB modes unknown.
- Added source/output selection and optional expected-SHA checking to
  `usb_debug_abi_trace`, preserving its original defaults.
- Added focused rejection cases for changed input identity, another CPU's ELF,
  and an ARM library without the required dynamic symbol table.
- Dependency-complete baseline: **82 tests OK, 2 optional skips**.
- ABI/profile/cross-model/boot-contract checks: **57 tests OK, 6 optional skips**.
- Actual a6400A packing replay and original-a6400 control: **both passed**.
- Documentation, dashboard geometry and repository-layout checks: **52 tests OK**.
- Final combined qualification, CPU/TLB, transport, profile and documentation
  validation: **152 run, 6 skipped, no failures or errors**.
- Full-suite rerun after restoring the declared missing PyUSB dependency:
  **1,556 run, 2 failures, 13 errors, 71 skipped**. It is **not green** on this host.

The remaining failures require the original a6400 read-only boot-set dump,
ZV-E10/reference module inputs, compiled UVC bridge/selector artifacts, overlay
and descriptor manifests, or the tree-model build receipt/payload. Those inputs
are absent here. Failure-stack source files were compared to the initial Git
HEAD and are unchanged. No test was weakened, skipped by a new policy, or fed
the different a6400A image in place of its required historical capture.
The first full run and final rerun are retained separately; the initial missing
PyUSB test dependency was installed from the existing camera-extra pin.

The dashboard's 1,595-test passing record remains explicitly the **historical
E0482 record**, not a new successful full-suite run or an a6400A compatibility
certificate.

The host initially lacked Git, WSL and several analysis dependencies. Missing-module
failures are retained; dependencies were installed into a new ignored project
venv, not globally. A local Dulwich read recorded the initially clean worktree.
No ARM cross-compilation, REA/Ghidra run or compiled daemon validation is claimed.

## 7. Receipts and reproduction

Retained locally under `artifacts/analysis/e0483-a6400a-qualification/`:
updater identity/signature, cabinet listing, extraction and dependency logs,
`qualify.py`, `static-qualification.json`, `cross-model.json`, ABI traces,
`kernel_prefix.py`/receipt, driver-function comparison, and serial-free host USB
metadata. Failed initial checks are retained alongside successful receipts.
Original binaries remain in ignored firmware/artifact directories.
`tool-input-manifest.json` records tool/source identities, and
`input-recheck.json` confirms the download and all twelve qualified candidate
assets remained byte-identical after the checks.

Core commands, from the repository root, with fresh output directories:

```powershell
.\venv\Scripts\python.exe -m tools.research.sony_updater_payload `
  .\firmware\Update_ILCE6400AV101.exe .\artifacts\analysis\e0483-a6400a-qualification\payload

& "$env:SystemRoot\System32\expand.exe" '-F:FirmwareData_ILCE6400AV101.dat' `
  .\artifacts\analysis\e0483-a6400a-qualification\payload\Update_ILCE6400AV101.cab `
  .\artifacts\analysis\e0483-a6400a-qualification\cabinet

.\venv\Scripts\python.exe .\fwtool.py\fwtool.py unpack `
  -f .\artifacts\analysis\e0483-a6400a-qualification\cabinet\FirmwareData_ILCE6400AV101.dat `
  -o .\firmware\extracted_a6400a_v101

.\venv\Scripts\python.exe -m tools.research.cross_model_report .\firmware `
  --reference extracted_a6400 --only extracted_a6400 extracted_a6400a_v101 `
  --json .\artifacts\analysis\e0483-a6400a-qualification\cross-model.json

.\venv\Scripts\python.exe -m tools.research.usb_debug_abi_trace `
  --library .\firmware\extracted_a6400a_v101\firmware.tar_unpacked\0700_part_image\dev\nflasha15_unpacked\lib\libusbcmd.so `
  --sha256 23b94deb094d31f160cfe1d46330f2425e94d4801dfccb66720c4cf4b81cfb7e `
  --output .\artifacts\analysis\e0483-a6400a-qualification\a6400a-packing-trace.json
```

The receipt scripts identify their inputs and scopes. Their kernel prefix and
ABI fixtures do not submit operations to the camera. Unit checks do not require USB.

## 8. Next boundary

Before any dump, qualify a **body-specific native-debugger bootstrap**:
review the different driver and current host transport, build against the
appropriate ABI, preserve existing files, and define recovery/readback checks.
Installation/startup writes or service-mode entry require separate explicit scope.
Only after access is established can small read-only live kernel/module/partition
inventory receipts test whether the installed body matches this package.

The a6400A can already contribute package-based offline research. Full application
execution, hardware behavior, writable overlays and UVC/PTP experiments remain
separate, unverified workstreams.
