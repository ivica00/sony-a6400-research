"""Live emulator screen GUI and checkpoint display viewer.

The screen canvas shows only bytes read from guest display memory.  The host
decodes the verified pixel format and scales the image; it never draws camera
icons, text or backgrounds.  A frame that the guest did not write is labelled
as such instead of being presented as firmware output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import queue
import sys
import threading
import time
import zlib
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Tuple

from project_paths import PROJECT_ROOT
from src.a6400.execution.guest_display import (
    DISPLAY_SURFACES, DisplayModel, GL_COMMON_POOL, display_contract, surface_to_image,
)

#: Verified boot flag set used by the physical experiments E0071/E0074.  The
#: GUI uses it as a default; explicit command-line flags still win.
REFERENCE_BOOT = {
    'argument': ['i'],
    'stimulus': 'none',
    'urandom_open': True,
    'urandom_entropy': 'deterministic',
    'tmp_overlay': 'experimental-empty',
    'proc_overlay': 'experimental-empty',
    'setting_overlay': 'observed-gps',
    'media_service': 'authentic-sd',
    'stream_device': 'image-driver',
    'regular_inode_rdev': True,
    'readonly_image_times': True,
    'backup_service': 'preset-backed',
    'graphics_service': 'authentic-grm',
    'grm_pools': 'captured-e0044',
    'null_page': 'read-zero',
    'madvise_dontneed': True,
    'gles_device': 'kernel-bound',
    'gpio_device': 'driver-bound',
    'kmod_service': 'verified-image',
    'usb_buspower_device': 'driver-bound',
    'usb_event_device': 'driver-bound',
    'usb_otgcore_device': 'driver-bound',
    'usb_reply_policy': 'verified-connect',
    'hdmi_device': 'driver-bound',
    'cec_device': 'driver-bound',
    'mmca_char_device': 'driver-bound',
    'fast_hooks': True,
    'display_contract': 'camera-e0074-e0044',
    'quiet_boot': True,
    'instructions': 250_000_000,
}


class CheckpointMemory:
    """Read a saved checkpoint's mapped regions without restoring a probe."""

    def __init__(self, path: Path):
        import pickle
        with Path(path).open('rb') as handle:
            self.payload = pickle.load(handle)
        self.regions = [(int(region['begin']), int(region['end']), region['data'])
                        for region in self.payload['regions']]
        self._cached_index: Optional[int] = None
        self._cached_bytes: Optional[bytes] = None

    def read(self, address: int, size: int) -> bytes:
        if size <= 0:
            raise ValueError('Checkpoint read size must be positive')
        for index, (begin, end, data) in enumerate(self.regions):
            if begin <= address and address + size <= end + 1:
                if self._cached_index != index:
                    self._cached_bytes = zlib.decompress(data)
                    self._cached_index = index
                offset = address - begin
                return self._cached_bytes[offset:offset + size]
        raise ValueError(f'Checkpoint has no region covering {address:#x}+{size:#x}')

    def stream_mapping(self) -> Optional[Dict[str, object]]:
        mappings = (self.payload.get('subsystems', {}).get('mmap', {}) or {}).get('mappings', [])
        candidates = [mapping for mapping in mappings
                      if mapping.get('device') == 'stream' and mapping.get('address') is not None]
        if not candidates:
            return None
        for mapping in candidates:
            if mapping.get('physical_start') == GL_COMMON_POOL['physical_base']:
                return mapping
        return candidates[0]


def checkpoint_display(path: Path, contract: str = 'camera-e0074-e0044',
                       profile: Optional[Dict[str, object]] = None) -> Tuple[DisplayModel, object]:
    """Build a display model over a saved checkpoint and read its best frame."""
    memory = CheckpointMemory(path)
    mapping = memory.stream_mapping()
    if mapping is None:
        raise ValueError('Checkpoint has no /dev/stream mapping to place the display contract')
    model = DisplayModel(profile if profile is not None else display_contract(contract))
    model.register_mapping(int(mapping['address']), int(mapping['length']),
                           int(mapping['physical_start']), 'stream')
    state = (memory.payload.get('subsystems') or {}).get('display')
    if isinstance(state, dict):
        model.from_state(state)
    frame = model.read_frame(memory.read)
    if frame is None:
        raise ValueError('Checkpoint maps no verified display surface (OSD A/B); '
                         'internal buffers are not presented as a screen')
    return model, frame


def save_frame(frame, directory: Path, stem: Optional[str] = None) -> Dict[str, object]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = stem or f'emulator-screen-{frame.surface.name}'
    image_path = directory / f'{stem}.png'
    receipt_path = directory / f'{stem}.json'
    surface_to_image(frame.surface, frame.rgba).save(image_path)
    receipt = {
        'kind': 'read-only guest display extraction',
        'host_drawing': False,
        'image': image_path.name,
        'image_sha256': hashlib.sha256(image_path.read_bytes()).hexdigest(),
        **frame.metadata(),
    }
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


class FramePump:
    """Capture display frames from the probe's progress hook, de-duplicated."""

    def __init__(self, probe, sink: Callable[[object], None], max_frames: Optional[int] = None,
                 min_interval: float = 0.2):
        self.probe = probe
        self.sink = sink
        self.max_frames = max_frames
        self.min_interval = min_interval
        self.frames: List[object] = []
        self.last_sha: Optional[str] = None
        self.last_time = 0.0

    def capture(self, probe=None) -> Optional[object]:
        probe = probe or self.probe
        now = time.monotonic()
        if now - self.last_time < self.min_interval:
            return None
        frame = probe.capture_display()
        if frame is None or frame.raw_sha256 == self.last_sha:
            return None
        self.last_time = now
        self.last_sha = frame.raw_sha256
        self.frames.append(frame)
        self.sink(frame)
        if self.max_frames is not None and len(self.frames) >= self.max_frames:
            probe.pause()
        return frame


class LiveBootWorker(threading.Thread):
    """Run the emulator in slices and publish display frames to the GUI."""

    def __init__(self, args, frame_sink: Callable[[object], None],
                 status_sink: Callable[[str], None]):
        super().__init__(daemon=True, name='emulator-live-worker')
        self.args = args
        self.frame_sink = frame_sink
        self.status_sink = status_sink
        self.probe = None
        self.paused = threading.Event()
        self.step_requested = threading.Event()
        self.stop_requested = threading.Event()
        self.error: Optional[str] = None
        self.report: Optional[dict] = None
        self.pump: Optional[FramePump] = None

    def request_pause(self):
        if self.probe is not None:
            self.probe.pause()

    def request_resume(self):
        self.paused.clear()

    def request_step(self):
        self.step_requested.set()
        self.paused.clear()

    def request_stop(self):
        self.stop_requested.set()
        if self.probe is not None:
            self.probe.pause()
        self.paused.clear()

    def run(self):
        try:
            from tools.research.emulator_session import build_boot_session
            self.status_sink('Preparing hash-checked boot inputs...')
            session = build_boot_session(self.args)
            self.probe = session.probe
            if session.usb_connect_event:
                self.probe.arm_usb_connect_event(session.usb_connect_event, session.usb_connect_at)
                self.status_sink(f'Armed verified USB connect event ({len(session.usb_connect_event)} bytes).')
            if session.uipc_inject_payload:
                self.probe.inject_uipc_message(session.uipc_inject_queue,
                                               session.uipc_inject_payload, source='gui')
                self.status_sink('Injected verified UIPC message.')
            self.pump = FramePump(self.probe, self.frame_sink,
                                  max_frames=getattr(self.args, 'frames', 0) or None,
                                  min_interval=1.0 / max(1.0, getattr(self.args, 'fps', 5.0)))
            self.probe._progress_interval = getattr(self.args, 'capture_interval', 5_000_000)
            self.probe._on_progress = lambda current: self.pump.capture(current)
            self.status_sink('Running...')
            self.probe.begin(self.args.instructions, self.args.timeout_us)
            while not self.stop_requested.is_set():
                if self.paused.is_set():
                    time.sleep(0.05)
                    continue
                count = 1_000_000 if self.step_requested.is_set() else getattr(self.args, 'slice_instructions', 5_000_000)
                report = self.probe.run_slice(count)
                self.pump.capture()
                self.status_sink(self._status_text(report))
                if report['status'] == 'paused':
                    self.paused.set()
                    if self.pump.max_frames and len(self.pump.frames) >= self.pump.max_frames:
                        break
                    continue
                if report['status'] != 'running':
                    break
            self.report = self.probe.finish(reason='stopped_by_user' if self.stop_requested.is_set() else None)
            self.status_sink(self._status_text(self.report))
        except Exception as error:  # surfaced in the GUI, not swallowed
            self.error = str(error)
            self.status_sink(f'ERROR: {error}')

    def _status_text(self, report: dict) -> str:
        display = report.get('display') or {}
        frames = len(self.pump.frames) if self.pump else 0
        return (f"status={report.get('status')} instructions={report.get('instructions_executed')} "
                f"frames={frames} threads={len(report.get('threads') or {})} "
                f"contract={display.get('contract', 'none')}")


class EmulatorScreenWindow:
    """Tk window presenting guest display bytes; no host UI on the screen canvas."""

    def __init__(self, scale: float = 1.0, on_pause=None, on_resume=None,
                 on_step=None, on_save=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.scale = scale
        self.root = tk.Tk()
        self.root.title('Sony ILCE-6400 emulator screen')
        self.root.configure(bg='#121214')
        self.width = int(960 * scale)
        self.height = int(540 * scale)
        self.canvas = tk.Canvas(self.root, width=self.width, height=self.height,
                                bg='#000000', highlightthickness=0)
        self.canvas.pack(side=tk.TOP)
        controls = ttk.Frame(self.root)
        controls.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(controls, text='Run', command=on_resume).pack(side=tk.LEFT, padx=2)
        ttk.Button(controls, text='Pause', command=on_pause).pack(side=tk.LEFT, padx=2)
        ttk.Button(controls, text='Step', command=on_step).pack(side=tk.LEFT, padx=2)
        ttk.Button(controls, text='Save', command=on_save).pack(side=tk.LEFT, padx=2)
        self.status = tk.Label(self.root, text='No frame', bg='#1c1c20', fg='#a0a0b0',
                               font=('Consolas', 9), anchor=tk.W, padx=8)
        self.status.pack(side=tk.BOTTOM, fill=tk.X, ipady=4)
        self.photo = None
        self.frame = None

    def show_frame(self, frame):
        from PIL import Image, ImageTk
        self.frame = frame
        image = Image.frombytes('RGBA', (frame.surface.width, frame.surface.height), frame.rgba)
        if self.scale != 1.0:
            image = image.resize((self.width, self.height), Image.Resampling.NEAREST)
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.delete('all')
        self.canvas.create_image(0, 0, anchor=self.tk.NW, image=self.photo)
        self.status.config(text=(f"{frame.surface.name} {frame.surface.width}x{frame.surface.height} "
                                 f"{frame.surface.pixel_format} status={frame.status} "
                                 f"writes={frame.provenance.get('count')}"))

    def set_status(self, text):
        self.status.config(text=text)

    def run(self):
        self.root.mainloop()


def _gui_parser():
    from tools.research.experiment_ui_boot import build_parser
    parser = build_parser()
    parser.set_defaults(**{key: value for key, value in REFERENCE_BOOT.items()
                           if key != 'argument'})
    parser.add_argument('--checkpoint', type=Path, default=None,
                        help='display one saved checkpoint instead of running')
    parser.add_argument('--headless', action='store_true', help='write frames/receipt without a window')
    parser.add_argument('--frames', type=int, default=0, help='stop after this many frames (0 = run to budget)')
    parser.add_argument('--out', type=Path, default=PROJECT_ROOT / 'artifacts/display',
                        help='output directory for headless frames and receipts')
    parser.add_argument('--scale', type=float, default=1.0, help='window scale factor')
    parser.add_argument('--fps', type=float, default=5.0, help='maximum display refresh rate')
    parser.add_argument('--capture-interval', type=int, default=5_000_000,
                        help='instruction interval between display capture hooks')
    parser.add_argument('--slice-instructions', type=int, default=5_000_000,
                        help='instructions per interactive slice')
    return parser


def main():
    parser = _gui_parser()
    args = parser.parse_args()
    if not args.argument:
        args.argument = list(REFERENCE_BOOT['argument'])
    if args.checkpoint:
        try:
            model, frame = checkpoint_display(args.checkpoint, getattr(args, 'display_contract',
                                                                       'camera-e0074-e0044'))
        except ValueError as error:
            print(f'No verified display surface: {error}', file=sys.stderr)
            return 2
        receipt = save_frame(frame, args.out)
        print(json.dumps(receipt, indent=2))
        if not args.headless:
            window = EmulatorScreenWindow(scale=args.scale)
            window.show_frame(frame)
            window.run()
        return

    if args.headless:
        from tools.research.emulator_session import build_boot_session
        session = build_boot_session(args)
        probe = session.probe
        if session.usb_connect_event:
            probe.arm_usb_connect_event(session.usb_connect_event, session.usb_connect_at)
        if session.uipc_inject_payload:
            probe.inject_uipc_message(session.uipc_inject_queue,
                                      session.uipc_inject_payload, source='gui-headless')
        frames: List[object] = []
        pump = FramePump(probe, lambda item: frames.append(item),
                         max_frames=args.frames or None,
                         min_interval=1.0 / max(1.0, args.fps))
        probe._progress_interval = args.capture_interval
        probe._on_progress = lambda current: pump.capture(current)
        probe.begin(args.instructions, args.timeout_us)
        report = probe.run_slice(args.instructions)
        pump.capture()
        report = probe.finish()
        if getattr(args, 'save_checkpoint', None):
            from src.a6400.execution.guest_checkpoint import save_checkpoint
            save_checkpoint(probe, args.save_checkpoint)
        uipc = report.get('uipc') or {}
        grm_transactions = [item for item in uipc.get('transactions', [])
                            if item.get('target_queue') == 0x014C0424
                            or item.get('queue') == 0x014C0424]
        payload = {
            'status': report.get('status'),
            'instructions_executed': report.get('instructions_executed'),
            'grm_pool_policy': report.get('grm_pool_policy'),
            'display': report.get('display'),
            'uipc_transaction_count': len(uipc.get('transactions', [])),
            'grm_transactions': grm_transactions[-256:],
            'usb_event_injection': report.get('usb_event_injection'),
            'usb_event_injection_error': report.get('usb_event_injection_error'),
            'uipc_injection': report.get('uipc_injection'),
            'uipc_injection_error': report.get('uipc_injection_error'),
            'frames': [],
        }
        for index, frame in enumerate(frames):
            payload['frames'].append(save_frame(frame, args.out, stem=f'frame-{index:04d}-{frame.surface.name}'))
        Path(args.out).mkdir(parents=True, exist_ok=True)
        (Path(args.out) / 'run-receipt.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')
        print(json.dumps({'status': report.get('status'),
                          'instructions': report.get('instructions_executed'),
                          'frames': len(frames),
                          'out': str(args.out)}, indent=2))
        return

    frame_queue: 'queue.Queue[object]' = queue.Queue()
    status_queue: 'queue.Queue[str]' = queue.Queue()
    worker = LiveBootWorker(args, frame_queue.put, status_queue.put)
    window = EmulatorScreenWindow(
        scale=args.scale,
        on_pause=worker.request_pause, on_resume=worker.request_resume,
        on_step=worker.request_step,
        on_save=lambda: save_frame(window.frame, args.out) if window.frame else None)
    last_frame = None

    def poll():
        nonlocal last_frame
        while True:
            try:
                item = frame_queue.get_nowait()
            except queue.Empty:
                break
            last_frame = item
            window.show_frame(item)
        while True:
            try:
                window.set_status(status_queue.get_nowait())
            except queue.Empty:
                break
        if worker.is_alive() or last_frame is not None:
            window.root.after(100, poll)
        elif worker.error:
            window.set_status(f'ERROR: {worker.error}')
        else:
            window.set_status('Run finished; no display frame produced.')

    def on_close():
        worker.request_stop()
        window.root.destroy()

    window.root.protocol('WM_DELETE_WINDOW', on_close)
    worker.start()
    window.root.after(100, poll)
    window.run()


if __name__ == '__main__':
    main()
