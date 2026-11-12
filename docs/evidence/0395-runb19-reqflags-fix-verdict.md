# E0395 — Run B19 reqflags fix: setting `req+0x1a` bit1 did NOT remove the 5 s GET_CUR status wait

Date: 2026-11-12. Physical Run B19 with `e0395-reqflags-fix`
`7aa5b1fecbdd890400d1cfdd1dd7d87d54983582e06c7613ca661e16b468bc65` (79,984 B, audit
117/8/0, suite 1312 OK, Unicorn flag test PASS). ETW started before PC-Remote switch,
147,431,424 B. Battery pull was needed at the final MSC switch.

## 1. What was changed

In the silent class-IN queue wrapper, before the original queue:
```c
if (!g_class_dir_out && req && a6400_uvc_kernel_ptr((uvc_u32)req))
    *(volatile uvc_u8 *)((uvc_u32)req + 0x1a) |= 0x02;
```
Unicorn exact-object test: request flag byte becomes `0x02`, wrapper result path PASS.
No hot-path printk; RAM ring unchanged.

## 2. Disassembly check of the flag and standard tail

`dwc3_ep0_complete_data 0x602b3180` does read the flag:
```
602b3180 ldrb r9,[r5,#0x1a]
602b3184 and  r9,r9,#2
602b3188 uxtb r9,r9
602b318c cmp  r9,#0
602b3190 beq  0x602b3330          ; bit1 clear -> giveback
602b3194..31e4 bit1 set path
```
So the flag is real and consumed by DWC3. But setting it in B19 did **not** change the
status behavior.

`0x602b8ac8(gc,wIndex)` (called from setup_req 0x9fec for standard requests) switches on
`wIndex-1` (1..3) and calls a function pointer from `gc+0x10/+0x18`; it is the standard
**configuration/interface** handling. It is guarded by `gc+0x81` (configuration state)
and is not relevant to GET_DESCRIPTOR/GET_CUR status staging (`wIndex=0` does not enter
the 1..3 switch). `clear_halt_ep0` is only `strb 0,[gc+0x83]`; no queue/status arm.

## 3. B19 RAM ring (new run at 221.986)

```
RAMRING n=9 ... start=1 class=2 get=1 set=1 queue=2 complete=2
RR 1 h=1 t=215.305028001 bm=a1 rq=81 v=0100 i=0002 l=001a lpos=294 cnt=4 st=01 nx=2 fl=8d
RR 2 h=2 t=215.305057501 req=608a86e0 ... lpos=294 st=01 nx=2 fl=8d
RR 3 h=4 t=215.305083501 bm=a1 rq=81 ... st=02 nx=1 fl=8d
RR 4 h=3 t=215.306000501 req=608a86e0 ... lpos=298 cnt=4 st=02 nx=3 fl=8d act=26 sts=0
RR 5 h=1 t=220.313199501 bm=21 rq=01 ... lpos=2a4 cnt=c st=01 nx=2 fl=89
RR 6 h=2 t=220.313237501 req=608a86e0 ... lpos=2a4 st=01 nx=2 fl=89
RR 7 h=4 t=220.313253501 bm=21 rq=01 ... st=02 nx=1 fl=8b
RR 8 h=3 t=220.313280001 req=608a86e0 ... lpos=2ac cnt=4 st=02 nx=3 fl=89 act=0 sts=0
```
GET data completes at **215.306000** (`actual=26`); SET class starts at
**220.313199** = **5.007199 s later**, and completes `actual=0`. The 5 s status wait is
unchanged by the flag fix.

## 4. Verdict

- `req+0x1a` bit1 is read by DWC3, but setting it in the class queue wrapper did **not**
  fix the GET_CUR status stall. The standard-vs-class differential is not sufficient by
  itself; either the flag value/condition is wrong, or the missing status behavior is in
  another path (the `0x9fe0..0x9ff4` tail is standard config/interface handling and does
  not explain GET_DESCRIPTOR-vs-GET_CUR either).
- B19 ffmpeg still `Could not RenderStream`; no frame.
- Final MSC switch again required a battery pull: the clean order (stop daemon →
  `rmmod`/restore → MSC) was not achievable because the debugger is unreachable in PC
  Remote. B17 succeeded by switching MSC first and then `rmmod`.
- No evidence supports the flag fix; do not carry it forward. Next: instrument the
  **status-stage path** (`0x29c`/`0x2a0`, `do_control_status`, ep0state/next/TRB) with the
  silent ring including status events, and compare GET_DESCRIPTOR's request/status
  bookkeeping in `setup_req` against the class path without assuming the flag bit.
