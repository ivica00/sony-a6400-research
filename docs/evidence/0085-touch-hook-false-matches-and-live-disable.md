# 0085: Touch hook false matches and verified live disable

## Physical observation, 2026-11-05

User reconnected the ILCE-6400 in mass-storage mode after a power cycle and menu-touch test. `tools/inspect_touch_camera.py` reached authenticated Senser mode. `/etc/ld.so.preload` contained `/setting/input_sniffer.so`.

Initial diagnostics lost log data on a USB exception. The reader now preserves partial output and exception chains, and stops after a transport failure rather than treating subsequent failures as missing files. A fresh attempt retained 327,680 bytes from `/setting/input_dump.log` in `artifacts/hardware/touch-inspect-20261105-155053/setting__input_dump.log.partial`. Its manifest records the USB timeout. This is an incomplete prefix of a pre-existing log; it does not date every logged action to this session.

The retained log repeatedly reports `No input devices found to monitor`, concurrent ptrace attachment failures, and patches at many different addresses under the name `InputService::setTpEventSw`. Source inspection explains the progression: a six-byte common function prologue is patched at its first match, destroying that match; subsequent constructors scan again and patch the next matching prologue. There is no target-identity check or process-wide guard before patching. The input collector exits on failure and removes its PID file, permitting repeated attempts.

These observations invalidate E0084's claim that this pattern provides reliable function identification. A successful write/read-back proves byte modification, not semantic function identity. The existence or role of Linux event nodes is also unconfirmed by this attempt: open failures were logged without errno. Zero-byte `/proc` file transfers through Senser do not establish empty kernel interfaces.

## Live containment

`tools/disable_unsafe_touch_hook.py` removed only known touch preload entries, preserving any other entries. The camera read-back matched the expected empty file. Before/after copies are retained under `artifacts/hardware/touch-disable-20261105-155126/`. This prevents future loading through that preload file. It does **not** undo RAM patches or terminate previously loaded instances. A normal OFF/ON may preserve modified RAM because of the hibernation behavior described in E0084; do not claim restoration without verification. No SD writes were performed.

## Prepared next diagnostic and blocked deployment

`devcrashday_a6400/hook/touch_probe_v1.c` is a bounded one-shot constructor that writes `/setting/touch_probe_v1.log`, lists available device names, copies bounded kernel text, and records open errno and device names for event0..2. It performs no ptrace, guest memory patching, key injection, input-event reads, process launches, or thread creation. `O_EXCL` suppresses repeat collection while its report exists. Runtime execution remains unverified.

Built with the existing WSL ARM compiler, `-march=armv7-a -mfloat-abi=softfp -fPIC -shared -nostdlib -U_TIME_BITS -D_TIME_BITS=32 -U_FILE_OFFSET_BITS -D_FILE_OFFSET_BITS=32`, and linked against `tools/sony_sysroot/lib/libc.so`, with `-Wl,-soname,touch_probe_v1.so,-z,defs`. Initial builds exposed unavailable modern stat/time64 references; those were removed or avoided, and the final link succeeded with undefined-symbol rejection enabled.

`tools/deploy_touch_probe.py` uploads and reads back the library before configuring its preload entry and refuses to replace a nonempty preload file. Automatic approval review rejected its execution because uploading executable code and changing persistent startup preload require explicit deployment approval. The script did not run and the new probe was not installed. Await the user's explicit approval before this deployment. Do not work around the rejection.

The touch-menu objective is still open. Establish actual hardware input contracts and native menu state before implementing selection behavior. Existing tab-selector code's inferred initial tab and single-next-tab injection are not proof of native direct selection.

## Explicitly approved deployment

The user subsequently explicitly approved installing the diagnostics. The first upload attempt timed out reading back the 67-KB library and did not arm preload. Rebuilt the same collector using `-Wl,-z,max-page-size=4096` to avoid excessive ELF padding; resulting library is 6,408 bytes. Retried the approved deployment: the complete uploaded library matched its local bytes, and `/etc/ld.so.preload` read back exactly `/setting/touch_probe_v1.so\n`. Evidence and SHA-256 are retained in `artifacts/hardware/touch-probe-deploy-20261105-155605/`. The diagnostic is now installed; runtime collection awaits a new process startup. SD remained untouched. This supersedes the earlier deployment-blocked status above.
