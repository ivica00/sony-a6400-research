# E0224 — Existing monitor transport and ring contract

Date: 2026-11-09. No monitor command or input byte was sent. No SD/NAND write, camera memory write, module load, mount, ptrace or mode switch occurred.

## Original input/dispatch path

Exact original libMWF.so decompilations: `artifacts/tools/rea/fsys-monitor-entry-e0224` and `fsys-monitor-io-e0224`, identity checked through the firmware inventory.

- Monitor::MainInput polls CmdProc; CmdProc collects up to511characters and parses on CR/LF. Input-empty return is-1.
- CmdParse resolves registered commands (including the IFSYS registration found in E0223), with additional prefix/mode rules. Unknown text must not be assumed harmless without those rules.
- ExecFuncWrapper publishes function/argc/argv into shared monitor globals and creates a worker pthread. Ordinary calls join; `cproc` and special handling can detach. The wrapper returns1 even after pthread_create fails, and does not return the target operation's result. Dispatch return is not file-write success evidence.
- MonDrv::Init uses existing backup-configured fixed-area values to map `/dev/mem`; it constructs input/output queue objects over a shared32768-byte buffer. It was not called. Reading a backup-configured address is not authorization to change Backup settings or initialize a second monitor.

## Executed original ring contract

New `probe_uvc_monitor_ring.py` pins the source against the inventory and executes original IsEmpty, IsFull, EnQueue and DeQueue bodies. Nine cases pass: empty/nonempty, ordinary/wrapped full, free space, enqueue/consume and both wrap paths.

Queue object words are read-index pointer, write-index pointer, data pointer, capacity. One slot remains unused: full means next write index equals read index. EnQueue stores the data byte before publishing the new write index; DeQueue reads the data then advances the read index. These primitives themselves do not enforce producer/consumer ownership or prove cross-CPU ordering. Division is an explicit service recorder; object/cursors/data are fixtures. No native command, filesystem API or live queue write is executed by the tests.

Manifest: `artifacts/analysis/uvc-monitor-ring-e0224/manifest.json`. No new general-suite result claimed; last612passing tests remain E0215.

## Physical read-only validation

PID149 libMWF text load bias0x040f7000; original Getchar prefix matched source. Actual GOT/global pointers were read without ptrace:

- Input object0x000218d0: index pointers0x0450e400/0x0450e404, data0x0450e410, capacity0x400.
- Output object0x000218e8: index pointers0x0450e408/0x0450e40c, data0x0450e810, capacity0x7bf0.
- Shared buffer virtual0x0450e400 belongs to existing mapping `044bb000-04537000 rw-s 20098000 ... /dev/mem`; translated physical start0x200eb400.

Direct `/proc/149/mem` reads of that IO VMA return EIO, despite readable heap queue objects. Read-only access through the mapping's `/dev/mem` backing succeeded. Captured header is input read0/write0 and output read0/write0x75a3. This is a sequential snapshot, not an exclusive-owner certificate. Do not mistake EIO for a missing/uninitialized monitor or write arbitrary fallback addresses.

Artifacts: `artifacts/hardware/uvc-monitor-preflight-e0224/manifest.json`, input.bin, output.bin and io-header-physical.bin. First attempted combined snapshot failed on the IO VMA; the subsequent per-pointer capture and translated read retain that distinction. Only the original-prefix check is claimed, not full live library equality. Camera remained reachable through MSC.

## Remaining transport conditions

Original MonDrv output code has fullness/throttling behavior and may wait for transmission completion. Existing output was not consumed or changed. A useful journal command bridge must first preserve/drain output correctly, establish sole producer/consumer behavior, validate live ring bounds/identity and record explicit operation results. It must not rely on wrapper return1 or join alone, send unbounded help/test output into an unattended queue, reinitialize MonDrv, or use guessed physical addresses.

Next: build a bounded output reader under the verified ring protocol, initially read-only, then validate dispatch with a narrowly selected non-writing command before considering the already-authorized unique SD journal. No SD journal exists yet; E0222 A:/dev/mmca remains the only candidate target and B:/internal flash remains excluded.
