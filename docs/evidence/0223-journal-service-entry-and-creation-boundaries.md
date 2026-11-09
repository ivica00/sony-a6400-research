# E0223 — Journal creation and existing-service entry boundaries

Date: 2026-11-09. Small SD journal authorization remains valid. No SD/NAND write, native function execution, mode switch or module load occurred in this step.

## Host creation unavailable

Read-only Windows storage inventory finds only fixed C:/D: volumes; E: is not currently exposed. Sony is present as native MSC054C:0CA8/StatusOK. Therefore Windows exclusive file creation on E: is unavailable in the current setup. No driver change, raw block write or mount was attempted. The emulator's historical E: input must not be mistaken for a currently present host volume.

## Original command service

Exact original libInfraFsys.so decompilations are retained under `artifacts/tools/rea/fsys-command-journal-e0223`:

- InfraFsysMcmd::RegisterCommand registers `IFSYS` through MonLib::MonCmdAdd. Static provider lookup identifies the latter in libMWF.so.
- IFSYS_WriteData and IFSYS_WriteAndFlash parse path/size/pattern arguments, allocate a1MiB test buffer and call Fsys_Open with flags6. They generate a numeric pattern, not an arbitrary journal payload. Existing files can be reopened by that Open mode. Command return1 is not file-write/readback proof; short write errors are printed rather than establishing successful journal completion.
- The reconstructed WriteAndFlash argument guard checks fewer arguments than the body later accesses. This is a reason not to send guessed command syntax; no malformed command was executed.

No monitor command, file API or initialization function was called on camera.

## Async API and worker dispatcher

Additional exact queries are retained under `artifacts/tools/rea/fsys-async-journal-e0223`:

- Fsys_WriteDirectFileAsync checks native initialization then calls fsysDepAsync_Execute with100bytes. This is a private in-process job queue, not a verified external RPC interface.
- fsysDepAsync_Execute rejects payloads above128bytes with0x80000088, but waits on a pthread condition without a native deadline while no free queue node exists. Accepted return0 indicates enqueue, not completed write, flush or durability.
- Fsys_WriteDirectFile uses direct-file/physical-area machinery and metadata operations; it is not a safe substitute for a small ordinary byte journal based only on its name.
- InfraFsysThread::DispatchCommand's three static entries are commands1000/1001/1002, version1, minimum payload16bytes. Their relocated member-function targets are RegistRemain, UnregistRemain and RemainUpdate. This dispatcher is not a general file-write service. The interpretation is based on exact relocation records, not guessed zero member pointers in an unrelocated table.

These are static contracts, not executed positive write paths or physical concurrency proof. No new ARM-case count is claimed for this step. Last full general-suite result remains E0215's612passing tests.

## Next

Trace the original monitor input/dispatch transport and its ownership before deciding whether a bounded journal operation can run in the already-initialized process. Do not call arbitrary file APIs from the USB runner, load a separate filesystem instance, send raw pointers from another process, or assume async means nonblocking. Creation must avoid truncating existing files; validate A:/dev/mmca again before any eventual write, exclude B:/internal flash, and require bounded write plus readback and restart-survival evidence. The SD journal is still not implemented or physically written. Camera remains in MSC.
