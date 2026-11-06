# 0088: Camera ELF touch symbol and guarded deployment

User explicitly approved the two-gate native RAM experiment and clarified that the SD read-only policy applies to emulation; physical-camera mod writes to SD are authorized. AGENTS.MD records that clarification. No SD write was needed in this experiment.

## Guarded attempts and camera identity

Initial deployment read-back succeeded in `artifacts/hardware/native-touch-deploy-20261105-161318/`. Its report was retrieved under `artifacts/hardware/touch-inspect-20261105-161342/`. The menu's full 26-byte window matched, but the input function candidate at the preserved-image offset was unrelated code. The constructor reported `original-function identity mismatch; NO WRITES` and detached.

The next version resolves exact exported function names from the on-camera `/usr/lib/libObj.so` and `/usr/lib/viewUnified2.so` ELF32 dynamic symbol/string tables. It bounds table sizes/section counts and requires exactly one defined function symbol. This does not relax the complete function-byte checks. Deployment: `artifacts/hardware/native-touch-deploy-20261105-161507/`; report: `artifacts/hardware/touch-inspect-20261105-161518/`.

Camera exports:

* InputService::setTpEventSw(bool): linked 0x3cf188, live 0x060e7188. Preserved ELF had 0x3cf200: a 0x78-byte difference.
* PAS_MenuSelectMode::setTouchable(bool): linked 0x56dcb0, live 0x15b53cb0; same as preserved ELF.

Observed live input window:

`98b500af044634f5d4ec30b1214633f59cec33f560ee012098bd98bd`

Disassembly at linked 0x3cf188 confirms PUSH, ADD frame pointer, MOV r4,r0, BLX 0x103b38 (GetInstance PLT), null check, MOV r1,r4, BLX 0x102ad0 (SetTpEventSw PLT), BLX 0x102e5c (ReleaseInstance PLT), return one and POP. It has the same absolute PLT destinations and local behavior as the preserved function; only location/relative call encodings differ. The second attempt still compared the old signature, correctly refused all writes, and recorded these actual bytes.

## Matched-version candidate

Updated the **full** input signature to the exact observed camera window. The menu signature remains unchanged. Patch sites are now resolved from on-camera exports: input+4 (0x060e718c), menu+6 (0x15b53cb6). A third one-shot report name prevents confusing this attempt with earlier reports; earlier reports are retained.

Compiled with `-Wall -Wextra -Werror`, original Sony libc and `-Wl,-z,defs`, successfully. `tools/deploy_guarded_native_touch.py --apply` uploaded and verified this version under `artifacts/hardware/native-touch-deploy-20261105-161633/`; preload read-back is `/setting/touch_native_guarded_v1.so`. That filename now holds the version generating `touch_native_guarded_v3.log`. Consult the deployment payload.sha256 for its actual identity, not the older E0087 candidate hash.

After deployment, two immediate USB inspections returned no devices. This does not prove either success or failure of the RAM patch. The third runtime report and physical UI behavior have **not** yet been retrieved or verified. Request physical test/reconnection, then read `/setting/touch_native_guarded_v3.log`. Do not rearm/delete its one-shot log automatically. No claim of working touch menu is justified yet.

The guard still requires exact original bytes at **both** full function windows, writes only two halfwords through aligned PTRACE_POKETEXT while preserving neighboring bytes, checks full post-write windows, attempts rollback on failure, and detaches. No synthetic navigation or Linux evdev reader is installed.
