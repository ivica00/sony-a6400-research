# Evidence 0027: Original clone return and independent startup phases

## Result

The thread contract now resumes a new child at the original syscall-return PC with `r0=0` and the supplied stack. It no longer decodes a library-specific child stack, jumps directly to the pthread function, clears inherited registers, or supplies a fixed libc return address. Original libc instructions select the function, establish its return address and branch to its exit routine.

The corrected `im.elf i` experiment reaches **41,782,801 instructions**, **473 supplied responses**, and the same guarded four-byte `/dev/urandom` read as E0026. No entropy is supplied. No framebuffer transaction or camera UI is demonstrated. The seven additional instructions are explained by executing the previously skipped libc child-entry path; instruction count itself is not a fidelity metric.

## Sources and contracts

The preserved libc input is `firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.11.2.so`, SHA-256 `bceb5cfb7769b54bf9c9d178b8a5f4579531c0f60e673cbcae872a8c7a3508fb`. Other firmware identities and static namespace assumptions remain those of E0026. `tools.research.clone_return_trace` verifies this identity against the ELF inventory and checks exact instruction preimages before recording both windows.

Original ARM instructions show syscall 120 at linked PC `0xa05d4`, return at `0xa05d8`, the child branch at `0xa05ec`, argument read at `0xa061c`, LR establishment at `0xa0620`, function dispatch at `0xa0624`, and exit branch at `0xa0628`. The observed first runtime clone return is `0x502a05d8`, retaining the inherited ARM CPSR, rather than starting at a Thumb pthread function chosen by the host.

The [Linux 3.0 ARM copy_thread implementation](https://raw.githubusercontent.com/torvalds/linux/v3.0/arch/arm/kernel/process.c) copies the saved register frame, overrides child r0 and SP, and records supplied TLS when requested. This specifies the implemented general-register contract. It does not establish execution of Sony's kernel routine or equivalence of its whole kernel to upstream.

Only the exact previously observed NPTL clone flag combination `0x3d0f00` is supported. Extra flags stop explicitly. The syscall handler checks parent-TID write permissions before creating a child or writing through the host memory API, and clears superseded provenance labels after the successful write. It does not inspect the child stack: guest libc owns that read, including any guest memory fault. Register restoration selects the saved CPU mode before restoring banked SP/LR.

## Reproduction

```powershell
.\venv\Scripts\python.exe -m tools.research.clone_return_trace
.\venv\Scripts\python.exe -u -m tools.research.experiment_ui_boot --argument a --stimulus none --urandom-open --madvise-dontneed --trace-library-activation --instructions 3000000 --timeout-us 60000000 --report artifacts/execution/package-h-clone-return-a.json
.\venv\Scripts\python.exe -u -m tools.research.experiment_ui_boot --argument i --stimulus none --urandom-open --madvise-dontneed --trace-library-activation --instructions 45000000 --timeout-us 240000000 --report artifacts/execution/package-h-clone-return-i.json
.\venv\Scripts\python.exe -u -m tools.research.experiment_ui_boot --argument l --stimulus none --urandom-open --madvise-dontneed --trace-library-activation --instructions 3000000 --timeout-us 45000000 --report artifacts/execution/package-h-clone-return-l.json
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

The `a` run exhausts its three-million-instruction bound after 4,546 responses; it retains the original failed `gui.so` load and worker termination/event-loop observation. This is not successful GUI startup. The `i` run stops at syscall 3, PC `0x5008b1c4`, requesting four bytes, with zero supplied. Hardware TLS, software slot, kuser model and the current worker's TLS agree. The `l` repeat stops at 2,222,528 instructions and 196 responses on an unverified `st_rdev` read after opening `/usr/kmod/liro.ko`; no module is inserted.

An independent phase survey performed before this clone correction is preserved as `package-h-phase-{s,g,r,u,l}-corrected.json`. These use E0026's corrected TLS and optional anonymous discard, no injected messages, and separate fresh processes. `s`, `r`, and `u` exhaust three million instructions with 5,248, 5,247 and 5,985 responses respectively; `g` exhausts five million with 21,961 responses. `u` additionally opens `libosal_ulogio.so`. `l` reaches the same metadata boundary reproduced above. All have zero framebuffer transactions. They do not establish camera phase ordering or shared state between independent launches.

## Verification and limitations

All **237 tests pass** in `artifacts/tests/package-h-clone-return-suite-final.txt`. New constructed fixtures execute ARM wrapper code that dispatches either an ARM or Thumb function and returns through a guest-established LR at different load addresses. They check copied registers, both clone return values, original syscall continuation PC, no child-stack read by the host, rejection of unsupported flags/incomplete contexts, and refusal to write a read-only parent-TID location.

Exact flag checking exposed an older fixture instruction `0xe30d0f00`, which encodes `movw r0,#0xdf00` despite its `#0x0f00` comment. The fixture now uses `0xe3000f00` and explicitly asserts the serviced flags equal `0x3d0f00`. The earlier failed suite is retained separately. The fresh default no-response probe remains at 1,183 instructions (`package-h-clone-return-default.json`).

Historical threaded reports retain their recorded implementation, including the direct-function clone shortcut. E0026's TLS fix remains valid, but its clone model is superseded here. VFP/NEON context isolation, signal behavior, scheduler timing, runtime `/etc`, entropy state, authentic IPC service responses, module loading and display geometry/submission remain unresolved. The new report description explicitly scopes the thread context subset. No placeholder GUI alias, host randomness, synthesized pixels or forced library success is introduced. The regenerated `status_a6400.png` is a research checklist, not camera output or a compatibility percentage.
