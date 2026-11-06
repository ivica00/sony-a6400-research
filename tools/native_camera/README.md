# Authored native camera research tools

Canonical source copies of the debugger, bounded observers and one-shot context
helper used in E0090–E0109. These were developed in the separate local
`devcrashday_a6400` checkout; this directory preserves their actual source in the
main repository without adding that checkout as an incomplete submodule.

Compiled `.elf`/`.so` outputs, firmware and the original Sony libc sysroot remain
local and ignored. `python -m tools.research.build_native_usb_debugger` builds
the debugger/launcher from this directory into the historical local output paths.
It does not deploy them. The existing compiler is ARM Linux EABI GCC through
WSL on Windows, with the original local Sony libc; no toolchain is downloaded.

Observers use the same startup assembly/libc linking pattern. Inspect each
source's bounds, output paths and stop marker before building or deploying.
`native_thread_context.c` is a one-shot read-only PID149 TLS/register capture;
it detaches before returning. Guarded touch candidates are historical experiments,
not a working touch implementation and not automatically deployed by a build.

Follow [the research workflow](../../docs/LIVE_CAMERA_EMULATOR_WORKFLOW.md) and
latest AGENTS.MD/evidence status before any physical interaction. A source file
being present does not mean its observer is armed or that a test is requested.
