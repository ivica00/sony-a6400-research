# E0097: THREAD_INFRA1 poll is MonDrv output-queue back-pressure

## Finding (static disassembly of camera libMWF.so + trace of TID 1004 from boot-172m-touch-input.ckpt)

The 100 ms `nanosleep` loop of THREAD_INFRA1 (TID 1004, inside libInfraMediaDetect.so) is NOT a media-detect condition.
It is `MonDrv::PutcharSub(int)` (libMWF.so 0x25250):

1. `MonQueue::IsFull(*MonDrv::mp_output)`; if not full -> `MonQueue::EnQueue(ch)`.
2. `++MonDrv::m_putcharCount`; if the count reaches `MonDrv::GetOutputLimit` -> loop at 0x25282:
   `MprUtil::MSleep(100)` then `MonQueue::IsEmpty(...)` (0x265a0: `*read == *write`) until the queue is empty.

So the logging thread blocks until a consumer drains the MonDrv output ring (read ptr 0x1a190010, write ptr 0x1a190014,
buffer 0x1a190020, capacity 0x7bf0, living in /dev/stream PA 0x20098000 window; camera maps it as `/dev/mem 20098000`).
Authentic consumer: `Monitor::MainOutput` (0x25e83) / `MonTskOutput` (0x25e97) -> `MonDrv::OutputProc`
(300 ms loop). Camera has thread `monio(input)` / `mwf_monitor_inp`; the emulator has no running monitor-output thread.

## Problem in current code

`src/a6400/execution/guest_checkpoint.py::restore_checkpoint` has an uncommitted block that fabricates the
`MonDrv::mp_output` queue (0x52201fe0 -> 0x1a190000). This is a host-written approximation, not the authentic
`MonDrv::Init` (0x2504d: mmap of stream area + two `MonQueue` ctors). `Monitor` globals (0x52202500..) are all zero in the
checkpoint => `Monitor::Init` / output thread were never started.

## Next steps
- Remove the fabricated block; execute authentic `MWF_Init` (0x26989 -> `MWF::Initialize` 0x268a0, which calls `Monitor::Init`
  and `ObjThread` start of `mwf_monitor_input`) so MonDrv::Init and the monitor threads run for real.
- Determine why the emulator never reaches/executes `MWF_Init` (IMDB table entry id 0x097 libMWF.so, grp 1) from the checkpoint path.
- Verify against camera: live `mp_output` at `0x0450e3f8`-region shows queue drained (`mem 149 0x04139fe0`-style reads).
