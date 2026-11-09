# E0221 — Physical native volumes during ordinary PC Remote

Date: 2026-11-09. Small SD journal remains authorized, but no SD/NAND write occurred. This was ordinary MSC → PC Remote → MSC, without composite UVC, module load, kernel hook or native filesystem calls.

## Observer and physical result

Verified that root debugger file-read operation can directly pread `/proc/149/mem` without ptrace; a16-byte Open prefix matched the expected source. New `native_fsys_observer.c` uses this path, rediscovers the library text mapping each sample, verifies the same prefix and reads native status/26drive pointers plus16-byte headers for nonzero records. It makes no calls into Sony or filesystem ownership changes.

Compiled Sony-libc observer:6764bytes, SHA-256 `cda710d754a1dbbd9689e614884d97e2b7ee0b68ec484cef82ec2bff00464353`, `artifacts/native/fsys-observer-e0221/native_fsys_observer.elf`. Upload readback verified; physical PID841. First sample confirmed ready in MSC before the user was told to switch. It ran31samples over60nominal seconds at2-second intervals, writing only fresh RAM files and preserving its open output inode through a final fresh RAM receipt copy.

- Samples0..8: status1, no letter-volume records.
- Samples10..60: status1, A at0x04d87ab8 and B at0x04d8a3e8, both16-byte headers readable and stable across those samples.
- Windows observed ordinary native ILCE-6400 `USB\\VID_054C&PID_0CAA\\CF93603BE631`, StatusOK while the user held PC Remote.
- Observer completed; user returned MSC. Complete receipt recovered and all four own RAM paths removed. PID149 TracerPid0; no usbg_video module; debugger responsive.

## Address validation and boundaries

After return, direct memory reads of actual relocated GOT entries confirmed `g_fsys`0x04d87998 and `g_fsysStatus`0x04d4a250, matching the observer's source-derived global targets. This closes the earlier uncertainty about ELF-symbol addresses versus dynamic symbol resolution for this run. Future generalization should resolve/validate GOT before sampling rather than assume all firmware builds share these offsets.

Reads are sequential, without native locks: they are observational snapshots, not coherent ownership tokens or permission to write. The two nonzero volumes do not yet identify which is physical SD. Header byte0x0b agrees with the index letter; other header values must not be guessed into media identity. Prefix equality and GOT equality do not establish full live-library byte equality.

Evidence: `artifacts/hardware/uvc-sd-observer-e0221/observer.log`, `run.json`, final status/modules and ready receipt. `direct-proc-read.json` retains the initial no-ptrace access check. Build recipe/manifest: `tools/research/build_native_fsys_observer.py` and its artifact directory. Read-only observer and ordinary mode cycle passed physically; this is not another configured UVC session or journal-write test.

## Next

Identify A/B's actual media/device associations through original native drive records and existing service contract before creating a uniquely named bounded journal. Do not write both volumes experimentally, mount raw media concurrently or initialize a private filesystem instance. Then validate write/flush/readback and restart survival. No sensor video or PTP control transaction proof was added. Last general suite remains E0215; this isolated observer was compiled with warnings-as-errors and physically verified.
