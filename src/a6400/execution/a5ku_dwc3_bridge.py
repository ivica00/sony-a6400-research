"""A5KU-to-DWC3 Unicorn bridge for offline UVC+PTP control-plane verification.

Connects an ``A5kuDeviceHandler`` (such as ``A5kuUvcTestHandler``) to the real
Sony ``live-vmlinux.bin`` DWC3 EP0 code + compiled ``callback-bridge.o``
inside Unicorn (``artifacts/analysis/e0511-b25-b26-dwc3-emulation/emulate_b25_b26.py``).

Every 3-stage USB control transfer (``GET_DESCRIPTOR``, ``GET_CUR``,
``SET_CUR``, etc.) issued over A5KU TCP is routed through real kernel
``__dwc3_gadget_ep0_queue`` and ``dwc3_ep0_interrupt`` state transitions in
Unicorn, verifying whether the ``STATUS3`` TRB is pre-armed on time and
whether EP0 returns cleanly to ``EP0_SETUP_PHASE`` with a re-armed SETUP TRB.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import struct
import sys
from typing import Any

from src.a6400.execution.a5ku_protocol import A5kuStatus, UsbSetupPacket
from src.a6400.execution.a5ku_server import A5kuUvcTestHandler

_ROOT = Path(__file__).resolve().parents[3]
_EMULATE_B25_B26_PATH = (
    _ROOT / "artifacts/analysis/e0511-b25-b26-dwc3-emulation/emulate_b25_b26.py"
)


def _load_emulate_b25_b26_module():
    """Load the Dwc3B25B26Emulator module from artifacts/ without sys.path leaks."""
    spec = importlib.util.spec_from_file_location(
        "a6400_emulate_b25_b26", _EMULATE_B25_B26_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load DWC3 emulator from {_EMULATE_B25_B26_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("a6400_emulate_b25_b26", mod)
    spec.loader.exec_module(mod)
    return mod


@dataclass(frozen=True)
class Dwc3Ep0TransferTrace:
    """Observed DWC3 EP0 state-machine trace for one A5KU control transfer."""

    bm_request_type: int
    b_request: int
    w_value: int
    w_index: int
    w_length: int
    stage_count: int
    is_in: bool
    use_prearm: bool
    queue_ret: int | None
    status_trb_prearmed: bool
    status_acked: bool
    ep0state_after: int
    setup_trb_armed_after: bool
    warnings: tuple[str, ...]


class A5kuDwc3BridgeHandler:
    """A5KU gadget handler that executes 3-stage EP0 transfers in Unicorn DWC3."""

    def __init__(
        self,
        inner_handler: A5kuUvcTestHandler,
        *,
        use_prearm: bool = True,
    ) -> None:
        self.inner = inner_handler
        self.use_prearm = use_prearm
        self._mod = _load_emulate_b25_b26_module()
        self.emu = self._mod.Dwc3B25B26Emulator(use_prearm=use_prearm)
        self.ep0_traces: list[Dwc3Ep0TransferTrace] = []

    def handle_reset(self) -> tuple[A5kuStatus, int]:
        self.ep0_traces.clear()
        return self.inner.handle_reset()

    def handle_out(
        self, ep: int, data: bytes, flags: int
    ) -> tuple[A5kuStatus, int]:
        return self.inner.handle_out(ep, data, flags)

    def handle_in(self, ep: int, max_length: int) -> tuple[A5kuStatus, bytes]:
        return self.inner.handle_in(ep, max_length)

    def handle_control(
        self, setup: UsbSetupPacket, out_data: bytes
    ) -> tuple[A5kuStatus, bytes]:
        status, payload = self.inner.handle_control(setup, out_data)
        if status != A5kuStatus.OK:
            return status, payload

        if setup.w_length == 0:
            self.ep0_traces.append(
                Dwc3Ep0TransferTrace(
                    bm_request_type=setup.bm_request_type,
                    b_request=setup.b_request,
                    w_value=setup.w_value,
                    w_index=setup.w_index,
                    w_length=0,
                    stage_count=2,
                    is_in=bool(setup.bm_request_type & 0x80),
                    use_prearm=self.use_prearm,
                    queue_ret=None,
                    status_trb_prearmed=False,
                    status_acked=True,
                    ep0state_after=1,
                    setup_trb_armed_after=True,
                    warnings=(),
                )
            )
            return status, payload

        is_in = bool(setup.bm_request_type & 0x80)
        transferred, trace = self._execute_three_stage_ep0(
            setup=setup,
            is_in=is_in,
            data_bytes=payload if is_in else out_data,
        )
        self.ep0_traces.append(trace)

        if trace.queue_ret != 0 or trace.ep0state_after != 1 or not trace.setup_trb_armed_after or trace.warnings:
            return A5kuStatus.STALL, b""

        return A5kuStatus.OK, (transferred if is_in else b"")

    def _execute_three_stage_ep0(
        self,
        *,
        setup: UsbSetupPacket,
        is_in: bool,
        data_bytes: bytes,
    ) -> tuple[bytes, Dwc3Ep0TransferTrace]:
        mod = self._mod
        emu = self.emu
        uc = emu.uc

        if len(data_bytes) > 0x1000:
            raise ValueError(f"EP0 payload {len(data_bytes)} exceeds 4 KiB DATA_BUF")

        warn_start = len(emu.warnings)
        emu.status_trb_armed = False
        emu.data_trb_armed = False
        emu.setup_trb_armed = False

        uc.mem_write(mod.CTRL_REQ, setup.encode())
        # SETUP token completion clears DWC3_EP_BUSY (0x10) from the previous
        # dwc3_ep0_out_start() SETUP TRB before the gadget queues the DATA phase.
        mod.w32(uc, mod.EPS0 + 0x4C, 0x1)
        mod.w32(uc, mod.EPS1 + 0x4C, 0x1)
        mod.w32(uc, mod.EPS0 + 0x24, mod.EPS0 + 0x24)
        mod.w32(uc, mod.EPS0 + 0x28, mod.EPS0 + 0x24)
        mod.w32(uc, mod.EPS1 + 0x24, mod.EPS1 + 0x24)
        mod.w32(uc, mod.EPS1 + 0x28, mod.EPS1 + 0x24)
        # three_stage_setup (bit 0) | ep0_expect_in (bit 2)
        mod.w32(uc, mod.DWC + 0x2D8, 0x05 if is_in else 0x01)
        mod.w32(uc, mod.DWC + 0x2DC, 2)  # ep0_next_event = DATA
        mod.w32(uc, mod.DWC + 0x2E0, 1)  # ep0state = EP0_SETUP_PHASE

        if data_bytes:
            uc.mem_write(mod.DATA_BUF, data_bytes)
        xfer_len = len(data_bytes) if is_in else len(data_bytes)

        mod.w32(uc, mod.REQ + 0x00, mod.DATA_BUF)
        mod.w32(uc, mod.REQ + 0x04, xfer_len)
        mod.w32(uc, mod.REQ + 0x08, mod.DATA_BUF - mod.PHYS_OFFSET)
        mod.w32(
            uc,
            mod.REQ + 0x1C,
            emu.sym("a6400_uvc_ring_complete_thunk")
            if self.use_prearm
            else mod.ORIG_UVC_COMP,
        )
        mod.w32(uc, mod.REQ + 0x24, 0)
        mod.w32(uc, mod.REQ + 0x28, (-115) & 0xFFFFFFFF)
        mod.w32(uc, mod.REQ + 0x34, mod.REQ + 0x34)
        mod.w32(uc, mod.REQ + 0x38, mod.REQ + 0x34)
        uc.mem_write(mod.REQ + 0x40, b"\x00")

        if self.use_prearm:
            mod.w32(uc, emu.sym("g_prearm_pending"), 1)
            mod.w32(uc, emu.sym("g_prearm_req"), mod.REQ)
            mod.w32(uc, emu.sym("g_prearm_active"), 0)
            mod.w32(uc, emu.sym("g_prearm_dir_out"), 0 if is_in else 1)
            mod.w32(uc, emu.sym("g_req_complete_orig"), mod.ORIG_UVC_COMP)

        queue_ret = emu.call(mod.VA_DWC3_GADGET_EP0_QUEUE, r0=mod.EPS0, r1=mod.REQ)

        if is_in:
            emu.host_simulate_data_in_ack()
            emu.send_ep0_event(0x0000C042)  # DATA XferComplete on ep1 (IN)
            status_prearmed = emu.status_trb_armed
            if not status_prearmed:
                emu.send_ep0_event(0x000020C0)  # XferNotReady STATUS on ep0 (OUT)
            status_acked = emu.host_simulate_status_out()
            emu.send_ep0_event(0x0000C040)  # STATUS XferComplete on ep0 (OUT)
            out_payload = bytes(uc.mem_read(mod.DATA_BUF, xfer_len)) if xfer_len else b""
        else:
            emu.host_simulate_data_out_ack(xfer_len)
            emu.send_ep0_event(0x0000C040)  # DATA XferComplete on ep0 (OUT)
            status_prearmed = emu.status_trb_armed
            if not status_prearmed:
                emu.send_ep0_event(0x000020C2)  # XferNotReady STATUS on ep1 (IN)
            status_acked = emu.host_simulate_status_in()
            emu.send_ep0_event(0x0000C042)  # STATUS XferComplete on ep1 (IN)
            out_payload = b""

        snap = emu.state_snapshot()
        trace = Dwc3Ep0TransferTrace(
            bm_request_type=setup.bm_request_type,
            b_request=setup.b_request,
            w_value=setup.w_value,
            w_index=setup.w_index,
            w_length=setup.w_length,
            stage_count=3,
            is_in=is_in,
            use_prearm=self.use_prearm,
            queue_ret=queue_ret,
            status_trb_prearmed=status_prearmed,
            status_acked=status_acked,
            ep0state_after=snap["ep0state"],
            setup_trb_armed_after=snap["setup_trb_armed"],
            warnings=tuple(emu.warnings[warn_start:]),
        )
        return out_payload, trace


def summarize_dwc3_traces(traces: list[Dwc3Ep0TransferTrace]) -> dict[str, Any]:
    """Summarize DWC3 EP0 traces for CLI harnesses and test assertions."""
    three_stage = [t for t in traces if t.stage_count == 3]
    return {
        "total_control_transfers": len(traces),
        "three_stage_transfers": len(three_stage),
        "all_three_stage_prearmed": all(t.status_trb_prearmed for t in three_stage),
        "all_completed_to_setup": all(
            t.ep0state_after == 1 and t.setup_trb_armed_after and not t.warnings
            for t in traces
        ),
    }
