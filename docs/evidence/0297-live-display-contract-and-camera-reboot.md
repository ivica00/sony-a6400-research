# E0297 - Live display contract and GUI; checkpoint frame extracted; camera OSD probe rebooted the camera

Date: 2026-11-09. Offline implementation plus one deliberate read-only camera
attempt. No camera mode switch, Senser/updater, UVC/PTP, SD write or display
write was performed. The E0296 composite/liveview line remains paused.

> Superseded display claim: [E0298](0298-safe-osd-capture-and-sugilite-correction.md)
> shows that the 960x540 `sugilite_color0` buffer is an internal patterned
> buffer, not a display, and that OSD A/B (640x480 RGBA4444) are the verified
> camera display surfaces. The failed `/dev/stream` OSD capture and the camera
> reboot below remain valid and must not be repeated; E0298 records the safer
> ptrace method.

## What was implemented

* `src/a6400/execution/guest_display.py`: evidence-backed read-only display
  contract. Surfaces: OSD A/B at PA `0x23A80000`/`0x23B16000`, 640x480
  RGBA4444 (E0074/E0044), and a Sugilite colour-buffer candidate at PA
  `0x202E1000`, 960x540 16 bpp (E0081/E0082; format remains
  `evidence-hypothesis`). RGBA4444/RGB565/ARGB8888 decoders, exact-length
  checks, mapping containment, guest-write provenance (count, first/last PC,
  TID, instruction), and explicit `unmapped`/`unwritten`/`written` states.
  No host rendering, no invented geometry, no zero padding.
* `src/a6400/execution/interpreter_probe.py`: optional display observer
  (`display_profile`), write hooks installed only on mapped display ranges,
  `capture_display()`, `report['display']`, and an explicit
  `begin()`/`run_slice()`/`pause()`/`finish()` API for bounded interactive
  slices. `run()` keeps its previous single-shot semantics.
* `src/a6400/execution/guest_stream.py`: serialisable mapping/guard state for
  checkpoints (the Unicorn object is not pickled).
* `src/a6400/execution/guest_checkpoint.py`: persists stream and display
  state; older checkpoints re-register the display mapping only from their
  recorded `/dev/stream` mmap entry. No virtual address is invented.
* `tools/research/emulator_session.py`: the verified boot construction was
  factored out of `experiment_ui_boot` and is reused unchanged by the CLI and
  GUI. `--display-contract camera-e0074-e0044` is opt-in.
* `tools/research/emulator_gui.py`: Tkinter live screen, headless mode and
  checkpoint viewer. The screen canvas receives only decoded guest bytes; the
  GUI has no camera-icon/text overlay and no host navigation. The old
  checkpoint viewer's synthetic shutter/menu bindings were removed.
* `tools/native_camera/capture_display_readonly.c` and
  `tools/research/capture_display_ground_truth.py`: a read-only helper that
  opens `/dev/stream` O_RDONLY, maps OSD/Sugilite pages with PROT_READ, and
  writes bounded dumps only under `/tmp_bt`. It was built offline (6548 bytes,
  Sony libc, `-Werror`). The Python build helper could not start WSL from this
  harness (`Wsl/E_ACCESSDENIED` for a distro launched by a Python child
  process), so the same compiler/flags were run from an interactive shell; no
  build manifest was produced. The ELF SHA-256 is
  `d2727ef447c8c78532a3302b64d46d23a465ca27a26ac5112d72f64af860dc06`.

## Offline observations

Checkpoint `artifacts/checkpoints/boot-172m-touch-input.ckpt` (local):
201,325,952 instructions, 51 threads, `/dev/stream` at VA `0x53F50000`
(PA `0x202E0000`). Read-only extraction selected `sugilite_color0`:

```
width=960 height=540 stride=1920 bytes=1036800 format=rgba4444
status=snapshot-content provenance.count=0
raw_sha256=978e23b579ce423ba4e9613689dcb0de37e50658c0312624887dc8138cbd2dd8
rgba_sha256=079c730de12204e05c70f1cc5a42ed202d4e3e462b2818527d704382d224fe16
```

The image is sparse and is **not** a live guest-rendered UI frame. The
checkpoint predates display-write persistence, so no writer PC is claimed.

Live resume from that checkpoint with the display contract
(`artifacts/execution/display-resume-201m.json`): 201,325,952 ->
213,816,538 instructions, status `instruction_budget_exhausted`, display
surface `mapped=true`, **`state.count=0`**. The raw/content hashes are
identical to the checkpoint frame. In the saved thread context, TID 1008
(Sugilite display worker) is at libc `ioctl` with `r1=GLES_LOCK_SEMAPHORE`,
and the stream contains an authentic DMP draw sequence (viewport 336x448,
colour-buffer registers, vertex shader/uniforms, `GP_START`). The render loop
is active (196,535 lock / 196,533 unlock ioctls in the checkpoint), but the
colour buffer receives no CPU writes in this window: the original pipeline
submits GPU commands and the emulator does not execute the PICA200 GPU.
Therefore the first **live guest-rendered** frame is not claimed; the next
gate is bounded GPU command interpretation (or a CPU-written display surface
with evidence).

## Camera attempt (failed; camera rebooted)

A single read-only OSD capture was attempted through the installed native USB
debugger (`tools/camera_debugger.py`; MSC extcmd, PID 703, uid=euid=0).

1. `push` of the 6548-byte helper to `/tmp_bt/a6400_capture_display.elf`
   succeeded with read-back verification.
2. The first exec was rejected because the pushed file lacked execute
   permission (`sh: Permission denied`); no helper code ran.
3. After `chmod 700`, the exec of
   `.../capture_display_readonly.elf osd_a 0 614400 /tmp_bt/osd_a.raw`
   did not return a response; the USB read failed
   (`AttributeError: 'NoneType' object has no attribute 'signature'`).
4. The camera then disappeared from the PMCA MSC/MTP list. It returned a few
   seconds later: debugger `info` answered again (same deterministic PID 703),
   `/proc/uptime` was **50.89 s**, and `/tmp_bt` contained only the debugger
   daemon files (our helper and dump were gone). This is a camera reboot; the
   exact kernel/userland cause was not recovered (`dmesg` retained no
   panic/oops line; only UDIF `resume start/end: stream`).

Conclusion: reading the OSD/Sugilite physical pages through `/dev/stream`
from an external MSC process is **not safe** under this method. Do not repeat
it. The read-only intent, `O_RDONLY` open and `PROT_READ` mappings did not
prevent the camera-side reset. No SD write, display write or persistent change
was requested; the SD/display state after reboot was not modified by this
attempt. The camera is back in Mass Storage with the debugger intact. A later
read-only check showed `/proc/uptime` 459.70 s, `im.elf` PID 149 and debugger
PID 703; no repeated reset was observed during the check.

## Validation

Full suite: **694 tests OK** (19.0 s). `test_menu_touch_policy` reused the
already built policy DLL (`artifacts/analysis/menu_touch_policy_test.dll`)
because a compiler launched from this harness crashes as a child process
(`0xC0000409`); the test source and assertions are unchanged. The new tests
cover decoders, exact-length rejection, mapping containment, write
provenance, checkpoint stream state, pause/resume slices and headless
checkpoint frames.

## Boundaries and next work

* No live guest-rendered display frame and no camera display comparison.
* The Sugilite 16 bpp format is a hypothesis; OSD A/B are camera-documented
  but not mapped in the emulator.
* The emulator does not execute the PICA200 GPU; the observed draw call is
  the next concrete contract.
* Do not repeat the `/dev/stream` OSD read on MSC. A safer camera-evidence
  design must be reviewed first (for example reading a process that already
  maps the OSD, or an explicitly bounded diagnostic with its own review).
* E0296 snapshot3 / composite liveview work remains paused.
