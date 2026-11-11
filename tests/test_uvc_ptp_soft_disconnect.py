"""Static contract checks for the ordered soft-disconnect teardown (E0352).

The compiled teardown itself is executed by
``artifacts/analysis/unicorn-teardown-e0352/b4_soft_disconnect_verify.py`` against
the linked module object. These tests only pin the source-level ordering and the
guards that the Unicorn run depends on, so a later edit cannot silently restore
the E0350 ordering (pullup(0) before the interface stop) or free the descriptor
table while the EP0 hooks are still bound.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tools/native_camera/uvc_ptp_soft_disconnect.c'
HEADER = ROOT / 'tools/native_camera/uvc_ptp_soft_disconnect.h'
SESSION = ROOT / 'tools/native_camera/uvc_ptp_session.c'
BUILDER = ROOT / 'tools/research/build_uvc_composite_module.py'


def read(path):
    return path.read_text(encoding='utf-8')


def phase_order():
    header = read(HEADER)
    block = re.search(r'enum \{\s*(A6400_TD_UNCONFIGURE.*?)\};', header, re.S)
    if not block:
        raise AssertionError('phase enum not found')
    return re.findall(r'(A6400_TD_[A-Z_0-9]+)', block.group(1))


def positions(text, markers):
    """Index of each marker, asserting it is present and unique."""
    found = []
    for marker in markers:
        count = text.count(marker)
        if count != 1:
            raise AssertionError('%r appears %d times' % (marker, count))
        found.append(text.index(marker))
    return found


class SoftDisconnectOrderTest(unittest.TestCase):
    def test_phase_enum_order(self):
        self.assertEqual(phase_order(), [
            'A6400_TD_UNCONFIGURE', 'A6400_TD_BRIDGE_QUIESCE',
            'A6400_TD_EP_MAP', 'A6400_TD_UDC_DOWN', 'A6400_TD_UNBIND_EP0',
            'A6400_TD_UNREGISTER', 'A6400_TD_DESCRIPTOR', 'A6400_TD_DEMOTE',
            'A6400_TD_RECONNECT', 'A6400_TD_PHASE_COUNT'])

    def test_teardown_call_order(self):
        source = read(SOURCE)
        order = positions(source, [
            'ret=s->ops.unconfigure(gc);',
            'a6400_uvc_bridge_quiesce(&s->bridge)',
            'td_read_ep_map(t);',
            'ret=s->ops.quiesce(gc);',
            'ret=s->ops.unbind_ep0(gc);',
            'ret=a6400_uvc_bridge_unregister(&s->bridge,s->ops.unreg);',
            'ret=td_restore_descriptors(s,t);',
            'ret=s->ops.resume(gc);',
        ])
        self.assertEqual(order, sorted(order),
                         'the teardown order changed: interface stop and endpoint '
                         'release must precede the UDC stop, and the reconnect '
                         'must come last')

    def test_unconfigure_before_pullup(self):
        source = read(SOURCE)
        self.assertIn('if (!s->stopped) {\n        td_phase(t,A6400_TD_UNCONFIGURE);', source)
        self.assertIn('if (s->ops.unconfigure)', source)
        # The old failure mode: pullup(0) while interfaces 0/1/2 are configured.
        self.assertLess(source.index('td_phase(t,A6400_TD_UNCONFIGURE)'),
                        source.index('td_phase(t,A6400_TD_UDC_DOWN)'))

    def test_endpoint_map_gate(self):
        source = read(SOURCE)
        self.assertIn('if (t->ep_state==A6400_TD_EP_RESIDUAL) return td_fail(t,A6400_TD_EP_MAP,-16);',
                      source)
        self.assertLess(source.index('td_read_ep_map(t);'),
                        source.index('ret=s->ops.quiesce(gc);'))

    def test_descriptor_guards(self):
        source = read(SOURCE)
        # A table the owner replaced is never overwritten with the saved root.
        self.assertIn('if (*(void **)((unsigned char *)gc+0x6c)!=s->lease.installed)', source)
        self.assertIn('A6400_TD_DESC_OWNER_KEPT', source)
        # No free while a shadow driver record is still linked, and no free with
        # the EP0 hooks still bound (steps 5-7 are skipped on those paths).
        self.assertIn('if ((shadow0 || shadow1) && td_shadow_records(gc,shadow0,shadow1,0)!=0)',
                      source)
        self.assertLess(source.index('ret=s->ops.unbind_ep0(gc);'),
                        source.index('ret=td_restore_descriptors(s,t);'))

    def test_late_failure_still_reconnects(self):
        source = read(SOURCE)
        reachable = [line for line in source.splitlines() if 'goto demote;' in line]
        self.assertGreaterEqual(len(reachable), 5,
                                'every late failure must fall through to the '
                                'demote/reconnect tail instead of stranding the UDC down')
        self.assertIn('s->stopped=0; /* resume may partially enable hardware even on failure */',
                      source)

    def test_native_errors_still_reported(self):
        source = read(SOURCE)
        self.assertEqual(source.count('(ret=s->ops.check_error(gc))'), 4,
                         'the native error checkpoints must stay: after the UDC '
                         'stop, after each unregister path, and after the '
                         'descriptor restore')
        self.assertIn('return error;', source)
        self.assertIn('t->failed_phase=phase;', source)


class SessionDelegationTest(unittest.TestCase):
    def test_session_end_delegates(self):
        session = read(SESSION)
        self.assertIn('ret=a6400_uvc_soft_disconnect(s,&s->teardown);', session)
        # The old inline order must not come back.
        for marker in ('s->ops.quiesce(s->gc)', 's->ops.unbind_ep0(s->gc)',
                       'a6400_uvc_bridge_unregister(&s->bridge, s->ops.unreg)',
                       'a6400_uvc_bridge_unregister(&s->bridge,s->ops.unreg)'):
            self.assertNotIn(marker, session)
        self.assertIn('if (ret) return hold(s,ret);', session)

    def test_held_session_still_not_releasable(self):
        session = read(SESSION)
        self.assertIn('!s->hook_attempted && !s->bridge.magic', session)
        self.assertIn('a6400_descriptor_source_releasable(&s->lease)', session)

    def test_builder_compiles_the_new_source(self):
        builder = read(BUILDER)
        self.assertIn("'uvc_ptp_soft_disconnect'", builder)
        self.assertLess(builder.index("'uvc_ptp_soft_disconnect'"),
                        builder.index("'uvc_ptp_session'"))


if __name__ == '__main__':
    unittest.main()
