# E0101 — Controller observer coverage limitation and menu-triggered revision

Date: 2026-11-05. User reconnected after the E0100 physical sequence.

## Returned V1 result

Normal USB preserved `native-menu-controller-probe-pid2259-after-test.log`
before creating its own stop marker; final copy is
`artifacts/hardware/native-menu-controller-probe-pid2259-final.log`.
It contains start, scan start and END only:224 private-anonymous ranges,
1532 chunks,392306688 bytes,0 candidates,0 failed chunks,result0.
There is no OBSERVE/STATE record. No controller/button trace was obtained.

The fixed60-second start did not independently verify that MENU was open at
scan time; the V1 scan excluded file-backed private data and stream RAM. A zero
candidate result therefore cannot establish absence during the physical test.
No new physical UI result or touch compatibility is claimed.

## Unaffected follow-up work over USB

Extended one-pass read-only scans completed without failed chunks:

| Retained log | Scope | Ranges/chunks/bytes | Candidates |
| --- | --- | --- | --- |
| native-viewsetting-scan-v2-usb.log | private writable mappings, including library data |325/1652/399261696|0|
| native-viewsetting-scan-v3-usb.log | same plus known /dev/stream RAM mappings |334/1825/443523072|0|

These are USB-mode observations, not disconnected-menu coverage. Source:
`devcrashday_a6400/native_viewsetting_scan.c`. V2 binary upload/readback hash
0d724ad5795748ae95b9473ab45e71cd4811c7fd533f1a1da6f1406eac513cd7;
V3 hash4eeb978c552bf4bcf3fd1df9407856af6088787bbb979bfd1166b0940a809fb4.

Additional original live/file-equal code is retained in
`native-viewsetting-toinstance.json`, `native-viewsetting-constructor.json`
and `native-menu-alternative-constructors.json`. Export ViewSettingMenuToInstance
is a **factory**, allocating0x3d0 bytes then calling its constructor; it must not
be remotely invoked as a singleton getter. Constructor writes its primary table
at object+0 and a secondary table at +0x28. Other exported factories include
ViewGlobalMenuToInstance and ViewBaseMenuToInstance; those are not established
as the active menu controller and their object layouts differ.

## V2 observer

`native_menu_controller_probe.c` now waits for the **verified native widget
tree to contain PAS_MenuListTab**, checking every500ms for at most600 attempts.
It logs MENU_DETECTED with object address before scanning. The scan now covers
private writable mappings plus known /dev/stream RAM, with bounded chunks,
detach between chunks, total/chunk/count guards and explicit failures. It does
not read other shared MMIO device mappings. If the native menu is never seen,
it reports menu_not_observed instead of claiming a menu scan.

After discovery it captures a matched ViewSettingMenu whose model provider is
the verified root, then observes up to1800 samples/100ms. Its dedicated stop file
is `/tmp_bt/native_menu_controller_probe_v2.stop`; old V1 stop marker is not used.
No application functions called, patches, key injection or SD writes. ARM build
with warnings-as-errors passed. Actual upload/start must be verified before a
new interaction request. Preserve `/tmp_bt/native_menu_controller_probe_v2.log`
first on callback; distinguish MENU_DETECTED, scan END and OBSERVE_END.

Next physical sequence once verified running:unplug without power-off, MENU,
hold30 seconds, three clockwise wheel steps with3-second gaps, one reverse step,
center opening a submenu/wait5 seconds, MENU back/wait5 seconds, reconnect.
This requests fresh coverage because the prior observer never obtained a
controller trace, not because a negative touch result was inferred. Touch MENU
remains incomplete.

Deployment/start verified:11636 bytes, SHA-256
e67b7ae75b52a19ac6f53de128eb673c0c03c4338baabc265a38bc600744fbad,
native upload/readback equal at `/setting/native_menu_controller_probe.elf`.
Running PID2349 confirmed by ps. Start log
`artifacts/hardware/native-menu-controller-probe-v2-start.log` has wait_menu
attempt0/result0, confirming the tree observer is running and sees no list tab
in USB state. No claim of actual menu/controller discovery yet.
