# E0096 — Physical menu test reaches WidgetSystem mouse records

Date: 2026-11-05. The user reconnected after the requested MENU/wheel/touch test.
Normal USB debugger retained `native-mouse-probe-pid2045-after-test.log` under
`artifacts/hardware`; decoded coordinates are in the adjacent `-decoded.json`.
Observer PID 2045 was stopped with its own stop file and ended at 1085 samples,
result 0. The complete returned log was preserved after stop.

Samples 483–528 include real coordinate changes and state word 1 in mouse
record zero, interleaved with 0x7fff coordinates/state zero. Other three records
remain unchanged in the logged samples. This proves native widget-system mouse
state changed during the user's test; it does not prove which widget received
callbacks or that a menu action occurred. The snapshots are not atomic across
the application's threads.

`tools/research/native_mouse_dispatch.py` captures live/file-identical exported
postMouseMove/Press/Release, passive-region and mouse-hook setters, plus bounded
direct-target windows. Capture: `native-mouse-dispatch-20261105-222051.json`.
Named functions are symbol-sized; unnamed 512-byte windows can contain adjacent
functions/literals and must not be treated as complete inferred functions.
Move uses event type 0, press 1, release 2 at event+0x10 and queues through
0x0630a0ac. setMouseEventHook controls widget+0x20 bit 0; setPassiveRegion
controls bit 1 and updates two associated regions. No application writes.

Additional live/file-identical tree helpers are retained in
`native-tree-helper-contracts.json` and `native-tree-first-child-contract.json`.
Layer root is layer+0x18; widget root is widget+4. Root virtual slot +0xc returns
root+0x10; dereference and clear low two bits, subtract four, then read node+0x18
for the widget. Next sibling reads widget+8, subtracts four and reads node+0x18.
The resulting widget self pointer is at widget+0x1c; tree vtable at widget+4
is 0x07063b28. A bounded read-only traversal yields 70 live USB-mode widgets,
retained in `native-widget-tree-usb.json`. This is not the disconnected menu.

New `devcrashday_a6400/native_widget_probe.c` extends the finite mouse observer
with guarded tree snapshots on mouse changes or every ten samples. It records
object/parent/depth, vtable, flags and mode; maximum 1024 widgets, 48 levels,
64 layers; cycle/self/type/owner checks. Tree failures are explicit and do not
claim complete coverage. It detaches before writing the log and never calls
application functions or writes application RAM. ARM build with warnings as
errors and original libc passed. Deployment/start results must be appended
after actual verification. No SD writes; touch menu is not implemented yet.

Deployment verified: 11496 bytes, SHA-256
`49c8ef5fc7c4b43922305b5aebb312025abdfa8f13ecc748a0ee81931c3f455f`,
uploaded/readback-equal at `/setting/native_widget_probe.elf`. Running PID 2112
confirmed through ps. `native-widget-probe-start.log` retains sample zero:
TREE result=0 count=70 read_ms=4. Output is written after detach. Next callback:
preserve `/tmp_bt/native_widget_probe.log` via normal debugger, then stop using
`/tmp_bt/native_widget_probe.stop` and retain final END. Three-minute finite
window, no new application patches. Request MENU/touch interaction only while
this observer is running; if expired, preserve and rearm before a fresh test.
