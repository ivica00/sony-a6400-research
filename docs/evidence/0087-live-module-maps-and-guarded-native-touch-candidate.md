# 0087: Live module maps and guarded native touch candidate

## Approved map diagnostic completed

User explicitly approved the expanded `/proc/149/maps` collector. Deployment with full payload/preload read-back succeeded under `artifacts/hardware/touch-probe-deploy-20261105-160701/`. A transient USB disappearance was followed by successful re-enumeration; no user power cycle was needed.

The first map report was capped at 20,000 bytes, cutting off before viewUnified2.so. The same approved map-source collection was narrowed to retain only libObj.so/viewUnified2.so rows, scanning at most 2,048 lines. This version was uploaded and read-back verified under `artifacts/hardware/touch-probe-deploy-20261105-160811/`.

The complete filtered report is `artifacts/hardware/touch-inspect-20261105-160822/setting__touch_probe_maps_v2.log`. Collector PID 973, uid 0; uptime 689.29 seconds. `/proc/149/comm` returned `im.elf`. It scanned 758 lines and reached EOF. Executable mappings with file offset zero:

* libObj.so: 0x05d18000..0x0700e000, `/usr/lib/libObj.so`.
* viewUnified2.so: 0x155e6000..0x15e92000, `/usr/lib/viewUnified2.so`.

These are mapping observations, not proof the preserved ELF functions match live code bytes. The candidate offsets place InputService::setTpEventSw at 0x060e7200 and PAS_MenuSelectMode::setTouchable at 0x15b53cb0; their proposed halfword sites are 0x060e7204 and 0x15b53cb6. Never substitute map identity for the required full function-byte comparison.

## Concrete candidate, not deployed

`devcrashday_a6400/hook/touch_native_guarded_v1.c` implements an experimental native-gate attempt. It verifies PID 149's exact comm, uniquely resolves each offset-zero executable library mapping, attaches with ptrace, confirms a stopped state, and reads complete 28-byte/26-byte original function windows. If either differs from the preserved original, it records observed bytes and performs **no writes**.

If both match, it uses aligned PTRACE_POKETEXT read/modify/write to change only these halfwords:

* InputService +4: `04 46` -> `01 24`, forcing the switch argument to one on future calls.
* Menu +6: `19 b1` -> `00 bf`, removing the false branch while preserving the complete following LDR.W.

It compares complete post-write windows to the exact expected modified windows, attempts to restore both original halfwords on write/verification failure, reports rollback failures, and detaches. A one-shot O_EXCL report suppresses repeated attempts. `/setting/disable_touch_patch` suppresses this constructor before attachment. No scanning, Linux input reader, synthetic key events/navigation, subprocesses, or SD writes are included. The ptrace operation stops the process leader only; other application threads are not globally stopped. Runtime byte checks, ptrace side effects and rollback paths remain untested on hardware. Native touch functionality remains unproven even if byte checks pass.

The local library built successfully with the existing ARM compiler, explicit 32-bit time/file ABI settings, original Sony libc, undefined-symbol rejection and 4-KB ELF page alignment. Size 10,816 bytes, SHA-256 `0a147a4b629ca07c034860202e4b7edfc9bc50193d9b6f8b68952e0be8ce71c2`. The original-code audit from E0086 was rerun successfully; its mode-argument assertions do not exercise this live ptrace candidate.

`tools/deploy_guarded_native_touch.py` defaults to a local preview and requires `--apply` for deployment. Its deployment path backs up current preload, refuses unrelated preload values or an existing attempt log, verifies uploaded library bytes before replacing the diagnostic preload entry, and verifies the resulting entry. No `--apply` invocation has been made. Switching to this experiment means a persistent startup hook that can apply the two guarded RAM patches on the next process launch; this is beyond the just-approved map-only diagnostic. Obtain explicit approval for that concrete action before deployment.

The camera still has the map-only diagnostic configured. No native-touch candidate or new RAM patch was deployed in this step. SD remained untouched.
