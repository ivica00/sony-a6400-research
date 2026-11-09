# E0126 — V12 preserved and minimal touch prototype scope

Date2026-11-06. User asks whether evidence is sufficient to try ANY main-menu touch.

## Returned V12

BOTH PID1175 outputs archived FIRST as native-layout-resource-snapshot-pid1175.{log,bin,json}; exact464372 bytes/3023 records/428080 raw, SHA `ff3a568e1e5dfcaa13b96c118a5468c85f096badcb86092825acc9f01f19b665`. MENU210/object10202008.115 element arrays43428 bytes;509 Bitmaps;176 attached/resumed1620ms; first capture/SNAPSHOT/BINARY/END0. Observer completed, none armed.

Prepared current input with original-code-only imports from PID1020, ImageHandle and Bitmap components. Replay passes the previously missing Sprite element reads, reaches40351 instructions after two additional camera/file-equal code captures5e187ec and631e4b4. Stops BEFORE original external array write1a2bcd20/value41000000/size4/PC631e52e (element base1a2bcd18). No unknown bytes needed at this boundary, but external geometry mutations remain guarded until exact setter/element ownership is reviewed. No blanket array write permission or physical patch added. Report menu-activation-coupled-state-probe.json; initial prior code-only boundary retained menu-activation-v12-first-replay.json. Whole input outside native subset remains explicitly non-atomic.

## Answer and changed priority

Evidence supports beginning a LIMITED experimental adapter: physical touch coordinates -> original row hit -> original selected-row method -> original UI refresh. E0097 observed real touch records during MENU but EMPTY menu handlers. E0108 proves native hit predicates and native valid1..6 model selection separately. These alone DO NOT prove physical event routing or visible highlight refresh. E0125/V12 substantially improve refresh-resource execution but full option activation still has not returned.

First hardware prototype target should be selection/highlight of six visible rows, one action per touch release, with existing physical confirm button for opening options. No scrolling, category gestures or synthetic UI. Reuse camera's original selection/rendering, not host-drawn highlights or direct cursor-memory writes. Before deployment, establish callback/event ABI, UI-thread execution and exact native refresh request. Do not transplant GEN_Button's differently sized handler. Normal touch AF behavior and MENU-only lifetime guards must be considered in the concrete implementation.

The user asked a feasibility question, not explicitly for immediate deployment. No new physical capture or touch patch armed in this turn. Future work should prioritize this minimal event-to-selection path instead of treating full popup/resource emulation as a prerequisite for every touch experiment. Current capture/guard work is preserved for continued refresh validation. No app calls/RAM patches/SD writes. Physical touch remains incomplete.
