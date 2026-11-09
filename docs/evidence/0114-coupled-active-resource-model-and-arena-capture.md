# E0114 — Pending coupled active-MENU state capture

Date: 2026-11-06. E0113 proved that a live header alone does not restore the
corresponding resource cache/list state. No firmware behavior is synthesized.

New native_layout_resource_snapshot_v4.c extends the verified V3 observer:

* original nested layout registries, full ListTab and its+0x127b4 resource;
* correct resource owner and its actual vtable;
* owner's native list at+0x4c, head/tail/reciprocal links, bounded768 nodes;
* each actual node's chunk prefix and resource header, with reported counts of
  nonzero references and presence of the menu resource (observations, not forced
  assumptions about list membership);
* non-main libc heap/arena prefixes when a valid chunk header identifies them;
* actual model root from ListTab+0x186ac, up to six selected levels, their arrays
  and child prefixes, guarded CmnViewSettingNode type and128-child limit;
* main-thread TLS and its observed allocator pointer at TLS+0x34, plus arena.

The libc heap mask comes from original free0x431c9c4/9c6 (shift right/left20),
not a guessed arena alignment. All fields are collected while the verified set
of PID149 CPU threads is stopped, then every attached thread is resumed before
file output. This does not freeze DMA or other processes. Existing512-thread,
two-second attach deadline,2048-record/512KiB raw bound, checked writes and32KiB
free-space reserve remain. Any limit/type/link failure is a failed capture.

Built with warnings-as-errors, uploaded/read-back compared and initial
wait_menu0/result0 verified. Initial pre-interaction PID2987 waited while offline
validation/documentation continued; preserve/rearm if its finite window expires
before the user test. Latest confirmed PID is recorded in AGENTS.MD and the
start/rearm manifest under artifacts/hardware. No prior physical V4 test is
claimed and no app call, application RAM patch or SD write is made.

Fresh rearm: initial PID2987's finite wait ended without MENU. Its before/final
logs were archived; the missing binary was recorded rather than invented. The
installed payload was read-back compared, and only the own stop marker was
removed before relaunch. **PID2991** now has launch status0/flags0 and
wait_menu0/result0 verified;144 available4096-byte blocks. Manifest:
native-layout-resource-snapshot-v4-rearmed.json under artifacts/hardware.

Requested interaction, only after a fresh waiting state is verified: unplug USB
without powering off, open MENU, hold10 seconds, reconnect. A brief display
pause during the CPU capture is expected. No wheel sequence or item activation.

On callback FIRST preserve BOTH files:

* /tmp_bt/native_layout_resource_snapshot_v4.log
* /tmp_bt/native_layout_resource_snapshot_v4.bin

Then validate RESOURCE/RESOURCE_LIST/MAIN_TLS, FREEZE attached/resumed/result0,
SNAPSHOT0/BINARY0/END0 and exact length via decode_native_layout_snapshot.py.
Do not use semantic partial/failure output as complete state. Dedicated stop:
/tmp_bt/native_layout_resource_snapshot_v4.stop. Do not clean/rearm before
archiving. Main-menu touch remains incomplete.
