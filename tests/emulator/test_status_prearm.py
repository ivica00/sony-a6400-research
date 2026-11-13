"""E0472: status pre-arm for the UVC class GET_CUR 3-stage control read.

E0469 root cause: the host's single Status OUT arrives right after the DATA-IN;
DWC3 arms the OUT status TRB only in the later XferNotReady(STATUS) event, so
the first Status OUT is NAK'd. The fix pre-arms the status TRB at the class
request's data-stage completion:

  * only when ``dwc->ep0state == 2 (DATA) && ep0_next_event == 3 (NRDY_STATUS)``
    and only for a 3-stage class IN request (wLength != 0, bmRequestType IN);
  * it writes ``dwc->ep0state = 3 (STATUS)`` BEFORE calling the kernel's
    ``__dwc3_ep0_do_control_status(dwc, dwc->eps[0])`` (VA 0x602b253c) - the
    E0366/B10 rule: with ep0state still 2 a status XferComplete dispatches to
    the DATA handler and dereferences the wrong request;
  * the later XferNotReady(STATUS) then sees ``ep0_next_event == 1`` and is
    ignored, so exactly one arm happens (start_trans also guards on BUSY).

The Unicorn harness ``artifacts/analysis/e0472-status-prearm-unicorn/``
executes the compiled callback bridge to verify ordering/arguments/idempotency;
these tests pin the same contract in the suite, including a source check.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / 'tools/native_camera/uvc_callback_bridge.c'


class PrearmOrderingModel(unittest.TestCase):
    def prearm(self, ep0state, next_event, eps0_valid=True):
        """Model of the inlined a6400_uvc_status_prearm decision (E0472)."""
        trace = []
        if not (ep0state == 2 and next_event == 3 and eps0_valid):
            return {'action': 'skip', 'trace': trace, 'ep0state': ep0state, 'next': next_event}
        trace.append(('write', 'ep0state', 3))
        trace.append(('call', 'do_control_status', 'eps0'))
        # dwc3_ep0_start_trans success: ep0_next_event = 1
        return {'action': 'arm', 'trace': trace, 'ep0state': 3, 'next': 1}

    def test_arms_only_for_state2_next3(self):
        self.assertEqual(self.prearm(2, 3)['action'], 'arm')
        for state, nxt in ((1, 3), (3, 1), (2, 1), (0, 3), (2, 2)):
            self.assertEqual(self.prearm(state, nxt)['action'], 'skip',
                             f'state={state} next={nxt} must not arm')
        self.assertEqual(self.prearm(2, 3, eps0_valid=False)['action'], 'skip')

    def test_ep0state_status_written_before_kernel_arm(self):
        result = self.prearm(2, 3)
        names = [entry[0] + ':' + str(entry[2]) for entry in result['trace']]
        self.assertEqual(names, ['write:3', 'call:eps0'])
        self.assertEqual(result['ep0state'], 3)
        self.assertEqual(result['next'], 1)

    def test_late_status_nrdy_ignored_after_arm(self):
        # kernel NRDY(STATUS) handler (0x3448..0x34b0): arm only when next==3
        def nrdy_handler(state, next_event):
            if next_event != 3:
                return {'armed': False, 'state': state, 'next': next_event}
            return {'armed': True, 'state': 3, 'next': 1}

        pre = self.prearm(2, 3)
        late = nrdy_handler(pre['ep0state'], pre['next'])
        self.assertFalse(late['armed'], 'late XferNotReady(STATUS) must be ignored')
        # control: without the pre-arm the NRDY path arms exactly once
        control = nrdy_handler(2, 3)
        self.assertTrue(control['armed'])
        self.assertEqual(control['next'], 1)


class DispatchModel(unittest.TestCase):
    def dispatch(self, ep0state):
        """Model of dwc3_ep0_xfer_complete (0x2cd4 cmp ep0state,#2; status 0x334c)."""
        if ep0state == 3:
            return {'path': 'status_cmpl', 'ep0state': 1}  # 0x334c: giveback + out_start
        if ep0state == 2:
            return {'path': 'complete_data', 'ep0state': 2}  # B10 hazard: NULL deref in B24
        return {'path': 'other', 'ep0state': ep0state}

    def test_status_completion_dispatches_to_status_path(self):
        result = self.dispatch(3)
        self.assertEqual(result['path'], 'status_cmpl')
        self.assertEqual(result['ep0state'], 1)
        self.assertEqual(self.dispatch(1)['path'], 'other')

    def test_b10_regression_data_path_when_ep0state_left_at_2(self):
        # If the arm forgets the ep0state=3 write (the B10 defect), a status
        # XferComplete is dispatched to complete_data; that path is the B24
        # NULL-dereference hazard. The fix's ordering prevents this state.
        self.assertEqual(self.dispatch(2)['path'], 'complete_data')
        armed = PrearmOrderingModel().prearm(2, 3)
        self.assertEqual(self.dispatch(armed['ep0state'])['path'], 'status_cmpl')


class ThunkGatingModel(unittest.TestCase):
    def complete_thunk(self, pending, req, class_req, class_in, wlen, status=0):
        """Model of the E0472 gating in ring queue wrapper + completion thunk."""
        if status != 0:
            return {'pending': False, 'armed': False}  # error/setup-pending giveback
        if not (class_in and wlen != 0):
            return {'pending': False, 'armed': False}
        if pending and req == class_req:
            return {'pending': False, 'armed': True}
        return {'pending': pending, 'armed': False}

    def test_only_matching_class_in_request_arms(self):
        self.assertTrue(self.complete_thunk(1, 0x68A84560, 0x68A84560, True, 26)['armed'])
        self.assertFalse(self.complete_thunk(1, 0x68A84DA0, 0x68A84560, True, 26)['armed'])
        self.assertFalse(self.complete_thunk(1, 0x68A84560, 0x68A84560, False, 26)['armed'])
        self.assertFalse(self.complete_thunk(1, 0x68A84560, 0x68A84560, True, 0)['armed'])
        self.assertFalse(self.complete_thunk(0, 0x68A84560, 0x68A84560, True, 26)['armed'])

    def test_error_status_never_arms(self):
        # setup-pending / data-stage errors give back with req->status != 0;
        # the status stage must not be pre-armed from such a completion.
        self.assertFalse(self.complete_thunk(1, 0x68A84560, 0x68A84560, True, 26,
                                             status=-22)['armed'])
        self.assertFalse(self.complete_thunk(1, 0x68A84560, 0x68A84560, True, 26,
                                             status=-71)['armed'])

    def test_second_completion_cannot_arm_again(self):
        first = self.complete_thunk(1, 0x68A84560, 0x68A84560, True, 26)
        second = self.complete_thunk(first['pending'], 0x68A84560, 0x68A84560, True, 26)
        self.assertTrue(first['armed'])
        self.assertFalse(second['armed'])


class SourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = BRIDGE.read_text(encoding='utf-8')

    def test_ep0state_status_write_precedes_kernel_call(self):
        write = self.src.index('*(volatile uvc_u32 *)(dwc+A6400_DWC_EVENT)=3u;')
        call = self.src.index('A6400_FN_EP0_DO_CONTROL_STATUS)(dwc,eps0)')
        self.assertLess(write, call, 'ep0state=3 must be written before the arm')

    def test_guard_requires_state2_and_next3(self):
        self.assertIn('if (state!=2u || next!=3u', self.src)

    def test_thunk_calls_prearm_before_original_completion(self):
        thunk = self.src.index('static void a6400_uvc_ring_complete_thunk')
        prearm = self.src.index('a6400_uvc_status_prearm(ep,req);', thunk)
        orig = self.src.index('((void (*)(void *,void *))orig)((void *)ep,(void *)req);', thunk)
        self.assertLess(prearm, orig)

    def test_class_gate_is_in_direction_with_wlength(self):
        self.assertIn('if (drq && (drq[0]&0x80u) &&', self.src)
        self.assertIn('(((uvc_u32)drq[6]|((uvc_u32)drq[7]<<8))!=0u)', self.src)
        self.assertIn('if (g_prearm_active && !g_class_dir_out', self.src)

    def test_error_giveback_guard_present(self):
        self.assertIn('(int)a6400_uvc_rd32(r+0x2cu)!=0', self.src)


if __name__ == '__main__':
    unittest.main()
