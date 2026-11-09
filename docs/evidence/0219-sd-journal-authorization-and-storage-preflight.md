# E0219 — Persistent diagnostic authorization and storage preflight

Date: 2026-11-09. User explicitly selected a small diagnostic SD-card log for the next test. This supersedes the earlier RAM-only scope **for that journal**, not unrelated SD files, formatting, raw writes or internal NAND logs. No SD write has yet occurred.

## Physical preflight

Read existing camera `/proc/net/dev`, `/proc/net/route`, process status and module list. No active physical network interface or route was present; only loopback/tunnel devices were listed. Existing debugger source is USB ext-command only, with no independent network listener. Therefore there is no currently verified independent network observation channel.

In MSC, `/proc/mounts` contains no SD filesystem. The user then performed an ordinary PC Remote switch without any UVC module or kernel hook. Windows observed native `VID_054C&PID_0CAA` as ILCE-6400/StatusOK. A background shell sampled mounts and partitions after25seconds into unique RAM files; the user returned to MSC and those files were recovered. The sampled mounts again contain no SD filesystem; partitions include `mmca10` and `mmca10p1` (major250/minors10/11). This is a timed snapshot, not a continuously mode-stamped mount trace. Do not infer that SD is absent or unused merely because it is not Linux-mounted.

Own four RAM files were removed after collection. PID149 TracerPid0, no usbg_video module; camera returned in MSC with responsive debugger. No composite activation, SD write, filesystem mount, media-ownership change, network configuration or NAND write was performed.

Receipts: `artifacts/hardware/uvc-ptp-observer-preflight-e0219/`, including mount-probe.json, both mount snapshots, partitions, native-PCRemote observation in tool output, final status/modules. The initial collection attempt occurred before MSC became available; later collection succeeded. An empty storage-FD excerpt is not proof that no process owns the card.

## Native filesystem route

Static inspection found original `libInfraFsys.so` exports Fsys_Open, Fsys_Write, Fsys_WriteAndFlush, Fsys_Flush, Fsys_Close and PrFILE operations. Inventory/hash: `artifacts/analysis/uvc-sd-journal-e0219/native-fsys-candidates.json`. Original Fsys_Open is a substantial stateful function rather than a plain Linux open wrapper. E0057 also establishes that Sony media Mount is not necessarily Linux mount.

These are candidates, not verified live signatures or a journal implementation. Do not instantiate a second filesystem stack or mount the raw card for writing while Sony/Windows may own it. The safe next step is tracing the existing filesystem service's file-create/write/flush contract and volume naming, then testing one uniquely named bounded journal file. No user data should be overwritten. Authorization is already given; do not ask again for the same small SD journal.

## Remaining boundary

Persistent logging is not yet ready. No new configured UVC test should be called ready until a journal can be written/flushed/read back through a verified ownership path. E0212 control rejection, E0215 failure retention and E0218 timeout semantics remain relevant offline work. Sensor video and actual PTP controls remain unproven.
