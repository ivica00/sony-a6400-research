# E0372 — GEVNT word map, setup_req queue-path re-check, UDC setup-return semantics; fix not yet finalizable

Date: 2026-11-11. **Offline only; no camera run.** Based on the Run B12-probe
`A6400K.LOG`, captured ring dumps, and vmlinux disassembly.

## 1. Word-by-word GEVNT map `0x280..0x2b4`

Reconstructed from the five snapshots (`CLASS pre`/`queue`/`complete` for GET,
`CLASS pre`/`queue`/`complete` for SET, `STOP`); `lpos` is the next (unconsumed)
4-byte event offset, `0x1000`-byte ring at `buf=ffdff000`.

| offset | GET pre | GET queue | GET complete | SET pre | SET queue | SET complete | STOP |
|---|---|---|---|---|---|---|---|
| 0x280 | 000020c0 | 000020c0 | 000020c0 | – | – | – | – |
| 0x284 | 0000c040 | 0000c040 | 0000c040 | 0000c040 | 0000c040 | – | – |
| 0x288 | 000000c6 | 000000c6 | 000000c6 | 000000c6 | 000000c6 | – | – |
| 0x28c | 000010c8 | 000010c8 | 000010c8 | 000010c8 | 000010c8 | 000010c8 | – |
| 0x290 | 0000c040 | 0000c040 | 0000c040 | 0000c040 | 0000c040 | 0000c040 | – |
| 0x294 | 000010c4 | **000010c2** | 000010c2 | 000010c2 | 000010c2 | 000010c2 | 000010c2 |
| 0x298 | 000090c4 | 000090c4 | **0000c042** | 0000c042 | 0000c042 | 0000c042 | 0000c042 |
| 0x29c | 00008044 | 00008044 | **000020c0** | 000020c0 | 000020c0 | 000020c0 | 000020c0 |
| 0x2a0 | – | – | 0000a046 | **0000c040** | 0000c040 | 0000c040 | 0000c040 |
| 0x2a4 | – | – | 000010c4 | **0000c040** | 0000c040 | 0000c040 | 0000c040 |
| 0x2a8 | – | – | – | 000020c2 | 000020c2 | 000020c2 | 000020c2 |
| 0x2ac | – | – | – | 0000c040 | 0000c040 | 0000c040 | 0000c040 |
| 0x2b0 | – | – | – | 000010c4 | 000010c0 | 000010c0 | 000010c0 |
| 0x2b4 | – | – | – | – | – | 000090c4 | 000090c4 |

Decode (`type=(w>>6)&0xf`: 1=XferComplete, 3=XferNotReady; `epnum=(w>>1)&0x1f`;
NRDY subtype = byte1 bits4–7, 1=DATA, 2=STATUS):
- `000020c0` = **XferNotReady(STATUS) ep0** (offsets `0x280`, `0x29c`).
- `0000c042` = **XferComplete ep1** (GET data completion, written at `0x298` after
  GET's completion log).
- `0000c040` = **XferComplete ep0** (`0x284`, `0x290`, `0x2a0`, `0x2a4`, `0x2ac`).
- `000010c2` = XferNotReady(DATA) ep1; `000010c4/000010c8/000010c0` = NRDY(data)
  variants; `0000a046`/`00008044`/`000090c4` = other endpoint/status words.

Sequence facts:
- GET: `lpos 0x290 → 0x298` = two 4-byte events consumed: **`0x290=0c040`
  (XferComplete ep0)** and **`0x294=10c2` (NRDY DATA ep1)**. The real GET data
  completion **`0xc042` is at `0x298` and is still pending** when our completion
  thunk logged (it appears at `0x298` in the GET-complete snapshot). Yet the GET
  request was given back with `actual=26` — i.e. the giveback was triggered by the
  `ep0` XferComplete (0xc040), not by `ep1`'s data-completion event.
- SET: `lpos 0x2a4 → 0x2ac` = consumed **`0x2a4=0c040` (XferComplete ep0)** and
  `0x2a8=20c2` (NRDY STATUS ep1). The pending `XferComplete ep0` at `0x2a4` is
  consumed by the SET giveback while the bounce TRB still has `HWO=1` → the stale
  ep0 completion explanation is confirmed at exact offset level.
- Status NRDYs (`0x20c0`) are present at `0x280`/`0x29c` while `next` was 1/2 and are
  dropped at `0x602b3450`; no later status NRDY appears after `next=3`.

## 2. `setup_req` queue path and UDC return semantics

`0x602b9dac`: `mov r5,sl; mov r6,r0; b 0x602b9f64`. From there **unconditionally**
(it is not gated by wLength, a class flag, or request-list state):
```
0x9f64 ldr r3,[r4,#8]        ; delegated request
0x9f68 ldr r2,[pc,#0x4e8]    ; complete function literal
0x9f6c str r6,[r3,#4]        ; length = 0
0x9f74 str r2,[r3,#0x1c]     ; complete
0x9f78..0x9f8c wLength checks only set a zero-length flag
0x9fb0 bfi  req[+0x1a] bit1  ; zero-length flag
0x9fc0 str r4,[r3]           ; req->gadget/context
0x9fc8 ldr r0,[r4,#4]        ; ep0 object
0x9fcc ldr r1,[r4,#8]        ; delegated request
0x9fd0 ldr r3,[r0,#8]        ; ep0->ops
0x9fd4 ldr r3,[r3,#0x10]     ; ops->queue
0x9fd8 blx r3                ; ep0->ops->queue(ep0, req)
```
So if the class callback returns 0, the delegated zero-length queue **is
unconditional**. However, Run B12's `A6400K.LOG` contains **exactly one `EP0 queue`
line per `CLASS entry`** (GET and SET), i.e. our wrapped queue was called once. Two
possibilities remain, and they must be distinguished before any fix:
1. the gadgetcore-level class callback returned nonzero (so `0x9dac`/`0x9fd8` were
   not reached), or
2. `0x9fd8` executed but with a **different ep0 object/ops than the ep our wrapper
   shadowed** (our CLASS wrapper installs the shadow on the ep0 argument it receives),
   so the second queue was invisible to the log.

The ring evidence (an `ep0` XferComplete consumed before the real `ep1` data
completion, for GET and SET) is consistent with a second ep0 request being queued and
completed, but it does **not yet prove** that our queue wrapper missed it.

UDC handling of `g_setup` return (`r5`) in `dwc3_ep0_interrupt`:
- `0x7fff` (`USB_GADGET_DELAYED_STATUS`): sets `delayed_status` bit5 on
  `dwc+0x2d8` and returns (`0x3084..0x3098`).
- **0**: at `0x2f4c..0x2f6c` it passes through the code that arms the control status
  (writes `0x602b2fa4`/`dwc+0x2d8` bit6) before the common return.
- **1** or any other non-negative value: branches directly to `0x3084` → `r5>=0` →
  returns; **no status arm**.
- **negative**: `0x3084` → `0x30a4` → `0x343c` (`stall_and_restart`).

This means returning 1 from the bridge class hook would make `setup_req` return −22
(0x9db8→0x9ba448) and the UDC would stall/restart — not a viable fix. Returning 0 is
required for UDC status handling, and 0 also takes the delegated-queue path.

## 3. Fix status

The exact fix is **not yet finalizable** from static evidence because the critical
fact — whether `0x9fd8` executed for our path and which ep0/ops it used — is not
proven. A fix must not be guessed:
- If 0x9fd8 executes on a different ep0/ops, the correct change is to prevent the
  invisible double queue (e.g. make the bridge's queue visible/serialized with the
  delegated request, or ensure the class path returns a value that suppresses the
  delegated request *without* turning the UDC return negative). The UDC table above
  rules out a plain "return 1".
- If 0x9fd8 does not execute, the stale ep0 completions must come from a different
  source and the ring/event dispatch analysis must be extended.

Next offline step (no camera): identify the gadgetcore class-driver object at
`[r8]`/`[r0+0x18]` (the callback invoked at `0x602b9b64`), its module/function, and
its exact return value for GET/SET; then map `[r4+4]` (the ep0 used by `0x9fd8`) to
the ep0 pointer our wrapper receives at CLASS entry. Only after that can a fix be
formulated and proven in Unicorn.
