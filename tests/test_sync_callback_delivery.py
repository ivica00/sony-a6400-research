import struct
import unittest

from src.a6400.execution.guest_uipc import GuestUipc, UnsupportedUipc

SYNC_QUEUE = 0x00CA0288
SYNC_HANDLE = 4109
CALLBACK = 0x5641ABCD
USER_DATA = 0x1000


class FakeMemory:
    def __init__(self):
        self.data = {}

    def read(self, addr, size):
        return bytes(self.data.get(addr + offset, 0) for offset in range(size))

    def write(self, addr, data):
        for offset, value in enumerate(data):
            self.data[addr + offset] = value

    @property
    def writer(self):
        return self.write


def make_uipc(policy='unmodelled'):
    uipc = GuestUipc(sync_callback_delivery_policy=policy)
    uipc.pool_base = 0x50000000
    return uipc


def add_sync_registration(uipc):
    uipc.callbacks[SYNC_HANDLE] = {
        'queue': SYNC_QUEUE,
        'callback': CALLBACK,
        'user_data': USER_DATA,
        'flags': 1,
    }


def enqueue_message(uipc, mem, payload=b'\x11\x22\x33\x44'):
    msg = uipc.allocate_message(len(payload), memory_writer=mem.writer)
    mem.write(msg, payload)
    uipc.message_queues.setdefault(SYNC_QUEUE, []).append(msg)
    return msg


def wait_cb_args(mem, arg=0x60000000, params=0x60000100):
    mem.write(arg, struct.pack('<2I', 0, params))
    mem.write(params, b'\x00' * 16)
    return arg


class TestSyncCallbackDelivery(unittest.TestCase):
    """E0332: opt-in kernel-originated delivery to flags=1 sync callbacks."""

    def test_default_policy_still_refuses_sync_callback(self):
        uipc = make_uipc('unmodelled')
        mem = FakeMemory()
        add_sync_registration(uipc)
        enqueue_message(uipc, mem)
        uipc.pool_options_policy = 'legacy-empty'
        with self.assertRaises(UnsupportedUipc) as caught:
            uipc.handle_wait_cb(mem.read, mem.write, wait_cb_args(mem), tid=1001)
        self.assertIn('uipc_sync_callback_not_implemented', str(caught.exception))

    def test_kernel_origin_delivery_and_completion(self):
        uipc = make_uipc('kernel-origin')
        mem = FakeMemory()
        add_sync_registration(uipc)
        msg = enqueue_message(uipc, mem)
        uipc.pool_options_policy = 'kernel-e0301'
        self.assertTrue(uipc.callback_ready())

        arg = wait_cb_args(mem)
        ret = uipc.handle_wait_cb(mem.read, mem.write, arg, tid=1001)
        self.assertEqual(ret, 0)
        params = struct.unpack('<I', mem.read(arg + 4, 4))[0]
        callback, user_data, delivered, index = struct.unpack(
            '<4I', mem.read(params, 16))
        self.assertEqual((callback, user_data, delivered, index),
                         (CALLBACK, USER_DATA, msg, 0))
        # Active marker in the OSAL message header flag byte.
        self.assertEqual(mem.read(msg - 7, 1)[0] & 0x80, 0x80)
        self.assertEqual(uipc.callback_inflight[0]['mode'], 'kernel_sync')
        self.assertEqual(uipc.transactions[-1]['type'], 'wait_cb_sync_delivery')
        self.assertEqual(uipc.message_queues[SYNC_QUEUE], [])

        ret = uipc.handle_wait_cb(mem.read, mem.write, arg, tid=1001)
        self.assertEqual(ret, 0)
        self.assertEqual(mem.read(msg - 7, 1)[0] & 0x80, 0)
        self.assertNotIn(0, uipc.callback_inflight)
        self.assertEqual(uipc.transactions[-1]['type'], 'wait_cb_sync_completion')

    def test_completion_guard_rejects_changed_registration(self):
        uipc = make_uipc('kernel-origin')
        mem = FakeMemory()
        add_sync_registration(uipc)
        enqueue_message(uipc, mem)
        uipc.pool_options_policy = 'kernel-e0301'
        arg = wait_cb_args(mem)
        uipc.handle_wait_cb(mem.read, mem.write, arg, tid=1001)
        uipc.callbacks[SYNC_HANDLE]['flags'] = 0
        with self.assertRaises(UnsupportedUipc) as caught:
            uipc.handle_wait_cb(mem.read, mem.write, arg, tid=1001)
        self.assertIn('uipc_sync_callback_completion_mismatch',
                      str(caught.exception))

    def test_unknown_policy_rejected(self):
        with self.assertRaises(ValueError):
            GuestUipc(sync_callback_delivery_policy='made-up')

    def test_e0303_ready_includes_sync_pending_only_when_enabled(self):
        uipc = make_uipc('unmodelled')
        mem = FakeMemory()
        add_sync_registration(uipc)
        enqueue_message(uipc, mem)
        uipc.pool_options_policy = 'kernel-e0303'
        self.assertFalse(uipc.callback_ready())
        uipc.sync_callback_delivery_policy = 'kernel-origin'
        self.assertTrue(uipc.callback_ready())
