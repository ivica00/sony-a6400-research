"""Error/lifetime checks for the bounded E0300 callback transport."""
import struct
import unittest

from src.a6400.execution.guest_uipc import GuestUipc, UnsupportedUipc, UIPC_CMD_WAIT_CB


class CallbackMemory(unittest.TestCase):
    def setUp(self):
        self.data = bytearray(b'\xcc' * 8192)
        self.u = GuestUipc()
        self.u.pool_options_policy = 'kernel-e0300'
        self.u.pool_base = 0x1000
        self.write(0x100, struct.pack('<II', 0, 0x200))
        self.write(0x200, struct.pack('<4I', 0, 0, 0, 2))

    def read(self, address, size):
        return bytes(self.data[address:address + size])

    def write(self, address, value):
        self.data[address:address + len(value)] = value


class CallbackDeliveryTests(CallbackMemory):
    def test_options_preserve_unspecified_bytes_and_legacy(self):
        self.u.pool_options_policy = 'legacy-empty'
        before = bytes(self.data)
        self.u.initialize_pool_options(self.write)
        self.assertEqual(bytes(self.data), before)
        self.u.pool_options_policy = 'kernel-e0300'
        self.u.initialize_pool_options(self.write)
        self.assertEqual(self.read(0x1010, 4), struct.pack('<I', 4))
        self.assertEqual(self.read(0x1014, 4), b'\xcc\x01\x00\xcc')
        self.assertEqual(self.read(0x1018, 8), b'\xcc' * 8)

    def test_geometry_rejects_before_writing(self):
        self.u.total_pool_size = 4096
        before = bytes(self.data)
        with self.assertRaises(UnsupportedUipc):
            self.u.initialize_pool_options(self.write)
        self.assertEqual(bytes(self.data), before)

    def test_empty_wait_delivery_and_completion_boundary(self):
        before = self.read(0x200, 16)
        self.assertIsNone(self.u.handle_ioctl(self.read, self.write, UIPC_CMD_WAIT_CB, 0x100, tid=1001))
        self.assertEqual(self.read(0x200, 16), before)
        self.assertEqual(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1002), -22)
        self.assertEqual(self.read(0x200, 16), before)
        self.u.callbacks[4] = dict(queue=0x12002da, callback=0x1235, user_data=0x5678, flags=0)
        self.u.enqueue_message(0x12002da, 0x110c)
        self.assertEqual(self.u.handle_ioctl(self.read, self.write, UIPC_CMD_WAIT_CB, 0x100, tid=1001), 0)
        self.assertEqual(struct.unpack('<4I', self.read(0x200, 16)), (0x1235, 0x5678, 0x110c, 2))
        with self.assertRaisesRegex(UnsupportedUipc, 'completion_not_implemented'):
            self.u.handle_ioctl(self.read, self.write, UIPC_CMD_WAIT_CB, 0x100, tid=1001)

    def test_sync_and_failed_copy_do_not_consume(self):
        cb = dict(queue=1, callback=0x1235, user_data=0, flags=1)
        self.u.callbacks[4] = cb
        self.u.enqueue_message(1, 0x110c)
        with self.assertRaisesRegex(UnsupportedUipc, 'sync_callback'):
            self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001)
        cb['flags'] = 0
        def fail(address, value):
            raise ValueError('inaccessible output')
        with self.assertRaises(ValueError):
            self.u.handle_wait_cb(self.read, fail, 0x100, tid=1001)
        self.assertEqual(self.u.message_queues[1], [0x110c])


class CallbackCompletionTests(CallbackMemory):
    # Keep the E0300 controls above as their own regression baseline.
    def make_new_policy(self):
        self.u.pool_options_policy = 'kernel-e0301'
        self.u.callbacks[4] = dict(queue=0x12002da, callback=0x1235, user_data=0x5678, flags=0)
        self.u.enqueue_message(0x12002da, 0x110c)

    def test_completion_does_not_read_or_free_message(self):
        self.make_new_policy()
        self.assertEqual(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001), 0)
        before = bytes(self.data)
        def no_message_read(address, size):
            self.assertFalse(address <= 0x110c < address + size)
            return self.read(address, size)
        self.assertIsNone(self.u.handle_wait_cb(no_message_read, self.write, 0x100, tid=1001))
        self.assertEqual(bytes(self.data), before)
        self.assertEqual(self.u.callback_inflight, {})
        self.assertEqual(self.u.transactions[-1]['type'], 'wait_cb_completion')

    def test_busy_queue_is_serialized_across_proxies(self):
        self.make_new_policy()
        self.u.enqueue_message(0x12002da, 0x114c)
        self.assertEqual(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001), 0)
        self.write(0x300, struct.pack('<II', 0, 0x400))
        self.write(0x400, struct.pack('<4I', 0, 0, 0, 1))
        self.assertFalse(self.u.callback_ready())
        self.assertIsNone(self.u.handle_wait_cb(self.read, self.write, 0x300, tid=1002))
        self.assertEqual(self.u.message_queues[0x12002da], [0x114c])
        self.assertEqual(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001), 0)
        self.assertEqual(struct.unpack('<4I', self.read(0x200, 16))[2], 0x114c)

    def test_sync_registration_is_not_async_consumer(self):
        self.u.pool_options_policy = 'kernel-e0301'
        self.u.callbacks[4] = dict(queue=0x12002da, callback=0x7777, user_data=0, flags=1)
        self.u.enqueue_message(0x12002da, 0x110c)
        self.assertFalse(self.u.callback_ready())
        self.assertIsNone(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001))
        self.assertEqual(self.u.message_queues[0x12002da], [0x110c])
        self.u.callbacks[5] = dict(queue=0x12002da, callback=0x1235, user_data=0x5678, flags=0)
        self.assertTrue(self.u.callback_ready())
        self.assertEqual(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001), 0)
        self.assertEqual(struct.unpack('<4I', self.read(0x200, 16))[0], 0x1235)

    def test_broadcast_mode_remains_boundary(self):
        self.u.pool_options_policy = 'kernel-e0301'
        self.u.callbacks[4] = dict(queue=0x1234500, callback=0x1235, user_data=0, flags=0)
        self.u.enqueue_message(0x1234500, 0x110c)
        with self.assertRaisesRegex(UnsupportedUipc, 'queue_mode_not_implemented'):
            self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001)
        self.assertEqual(self.u.message_queues[0x1234500], [0x110c])


class SyncCallbackTests(CallbackMemory):
    def setUp(self):
        super().setUp()
        self.u.pool_options_policy = 'kernel-e0301'
        self.u.callbacks[4] = dict(queue=0xca01a4, callback=0x1235, user_data=0x5678, flags=1)
        self.u.allocated_msgs[0x110c] = 20
        self.write(0x1100, struct.pack('<IBBHI', 0, 0, 1, 1, 0xa5a5a5a5))
        self.write(0x100, struct.pack('<II', 0xca01a4, 0x200))
        self.write(0x200, struct.pack('<3I', 0x110c, 0, 0))

    def test_wrapper_tuple_and_matching_completion_preserve_body(self):
        self.assertEqual(self.u.handle_ioctl(self.read, self.write, 0x80000005, 0x100, tid=1001), 0)
        self.assertEqual(self.read(0x1105, 1), b'\x81')
        self.assertEqual(struct.unpack('<3I', self.read(0x200, 12)), (0x110c, 0x1235, 0x5678))
        self.write(0x110c, b'REPLY')
        self.assertEqual(self.u.handle_ioctl(self.read, self.write, 0x80000005, 0x100, tid=1001), 0)
        self.assertEqual(self.read(0x1105, 1), b'\x01')
        self.assertEqual(self.read(0x110c, 5), b'REPLY')
        self.assertEqual(self.u.sync_callback_inflight, {})

    def test_other_thread_cannot_complete_call(self):
        self.u.handle_ioctl(self.read, self.write, 0x80000005, 0x100, tid=1001)
        before = bytes(self.data)
        with self.assertRaisesRegex(UnsupportedUipc, 'completion_mismatch'):
            self.u.handle_ioctl(self.read, self.write, 0x80000005, 0x100, tid=1002)
        self.assertEqual(bytes(self.data), before)


class GenericE0303CompletionTests(CallbackMemory):
    """E0303 generic async completion: multi-consumer and broadcast queues."""

    def setUp(self):
        super().setUp()
        self.u.pool_options_policy = 'kernel-e0303'

    def _register_async(self, handle, queue, callback, user_data=0):
        self.u.callbacks[handle] = dict(queue=queue, callback=callback,
                                        user_data=user_data, flags=0)

    def test_multiple_async_consumers_share_ordinary_queue_round_robin(self):
        self._register_async(4, 0x12002da, 0x1235, 0x5678)
        self._register_async(5, 0x12002da, 0x7777, 0x9999)
        self.u.enqueue_message(0x12002da, 0x110c)
        self.u.enqueue_message(0x12002da, 0x114c)
        self.write(0x110c, b'M1')
        self.write(0x114c, b'M2')

        self.assertTrue(self.u.callback_ready())
        self.assertEqual(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001), 0)
        self.assertEqual(struct.unpack('<4I', self.read(0x200, 16)),
                         (0x1235, 0x5678, 0x110c, 2))
        self.assertEqual(self.u.message_queues[0x12002da], [0x114c])
        self.assertFalse(self.u.callback_ready())
        # Completion also hands the next message to the next consumer
        # (round-robin) and never reads or frees either message buffer.
        self.assertEqual(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001), 0)
        self.assertEqual(struct.unpack('<4I', self.read(0x200, 16)),
                         (0x7777, 0x9999, 0x114c, 2))
        self.assertEqual(self.u.message_queues[0x12002da], [])
        self.assertFalse(self.u.callback_ready())
        self.assertIsNone(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001))
        self.assertEqual(self.u.callback_inflight, {})
        self.write(0x300, struct.pack('<II', 0, 0x400))
        self.write(0x400, struct.pack('<4I', 0, 0, 0, 1))
        self.assertIsNone(self.u.handle_wait_cb(self.read, self.write, 0x300, tid=1002))
        self.assertEqual(self.read(0x110c, 2), b'M1')
        self.assertEqual(self.read(0x114c, 2), b'M2')
        self.assertEqual(self.u.transactions[-2]['type'], 'wait_cb_delivery')
        completion = [entry for entry in self.u.transactions
                      if entry['type'] == 'wait_cb_completion']
        self.assertTrue(completion)
        self.assertTrue(all(not entry['message_touched'] for entry in completion))

    def test_broadcast_queue_delivers_same_message_to_each_consumer_once(self):
        # Dynamic broadcast pool slot 0x7000 with key 0x55 (E0301 ARM control).
        self._register_async(4, 0x557000, 0x1235, 0x5678)
        self._register_async(5, 0x557000, 0x7777, 0x9999)
        self.u.enqueue_message(0x557000, 0x110c)
        self.write(0x110c, b'BCST')

        self.assertTrue(self.u.callback_ready())
        self.assertEqual(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001), 0)
        self.assertEqual(struct.unpack('<4I', self.read(0x200, 16)),
                         (0x1235, 0x5678, 0x110c, 2))
        # Not dequeued until every registered consumer has been handed it.
        self.assertEqual(self.u.message_queues[0x557000], [0x110c])
        self.assertFalse(self.u.callback_ready())
        self.assertEqual(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001), 0)
        self.assertEqual(struct.unpack('<4I', self.read(0x200, 16)),
                         (0x7777, 0x9999, 0x110c, 2))
        self.assertEqual(self.u.message_queues[0x557000], [])
        self.assertIsNone(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001))
        self.assertEqual(self.u.callback_inflight, {})
        self.assertEqual(self.read(0x110c, 4), b'BCST')
        completion = [entry for entry in self.u.transactions
                      if entry['type'] == 'wait_cb_completion']
        self.assertTrue(completion)
        self.assertTrue(all(entry['broadcast'] and not entry['message_touched']
                            for entry in completion))

    def test_completion_guard_rejects_forged_owner_and_sync_registration(self):
        self._register_async(4, 0x557000, 0x1235, 0x5678)
        self.u.enqueue_message(0x557000, 0x110c)
        self.write(0x110c, b'BCST')
        self.assertEqual(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001), 0)
        self.assertEqual(self.u.callback_proxy_owners, {2: 1001})
        # The completion guard checks the original handle/queue identity; a
        # forged registration cannot complete the call and the message buffer
        # is not touched.
        self.u.callbacks[4]['queue'] = 0x557001
        with self.assertRaisesRegex(UnsupportedUipc, 'completion_mode_not_implemented'):
            self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001)
        self.assertEqual(self.u.callback_inflight[2]['msg_ptr'], 0x110c)
        self.assertEqual(self.read(0x110c, 4), b'BCST')
        # A sync-registered consumer is never completed through the async path.
        self.u.callbacks[4] = dict(queue=0x557000, callback=0x1235,
                                   user_data=0, flags=1)
        with self.assertRaisesRegex(UnsupportedUipc, 'completion_mode_not_implemented'):
            self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001)
        self.assertEqual(self.read(0x110c, 4), b'BCST')


class GenericE0303SyncQueueTests(CallbackMemory):
    """E0303 sync-registered queue 0x009c015b is never consumed by async waits."""

    SYNC_QUEUE = 0x009c015b

    def setUp(self):
        super().setUp()
        self.u.pool_options_policy = 'kernel-e0303'
        self.u.callbacks[4] = dict(queue=self.SYNC_QUEUE, callback=0x1235,
                                   user_data=0x5678, flags=1)
        self.u.allocated_msgs[0x110c] = 20
        self.write(0x1100, struct.pack('<IBBHI', 0, 0, 1, 1, 0xa5a5a5a5))
        self.write(0x100, struct.pack('<II', self.SYNC_QUEUE, 0x200))
        self.write(0x200, struct.pack('<3I', 0x110c, 0, 0))

    def test_sync_delivery_and_completion_use_generic_policy(self):
        self.assertEqual(self.u.handle_ioctl(self.read, self.write, 0x80000005,
                                             0x100, tid=1001), 0)
        self.assertEqual(self.read(0x1105, 1), b'\x81')
        self.assertEqual(struct.unpack('<3I', self.read(0x200, 12)),
                         (0x110c, 0x1235, 0x5678))
        self.write(0x110c, b'REPLY')
        self.assertEqual(self.u.handle_ioctl(self.read, self.write, 0x80000005,
                                             0x100, tid=1001), 0)
        self.assertEqual(self.read(0x1105, 1), b'\x01')
        self.assertEqual(self.read(0x110c, 5), b'REPLY')
        self.assertEqual(self.u.sync_callback_inflight, {})
        types = [entry['type'] for entry in self.u.transactions]
        self.assertIn('sync_cb_delivery', types)
        self.assertIn('sync_cb_completion', types)

    def test_async_wait_never_consumes_sync_registered_queue(self):
        self.u.enqueue_message(self.SYNC_QUEUE, 0x110c)
        self.assertFalse(self.u.callback_ready())
        self.assertIsNone(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001))
        self.assertEqual(self.u.message_queues[self.SYNC_QUEUE], [0x110c])
        self.assertEqual(getattr(self.u, 'callback_inflight', {}), {})
        # The sync ABI still owns delivery and completion for this queue.
        self.assertEqual(self.u.handle_ioctl(self.read, self.write, 0x80000005,
                                             0x100, tid=1001), 0)
        self.assertEqual(struct.unpack('<3I', self.read(0x200, 12)),
                         (0x110c, 0x1235, 0x5678))

    def test_multiple_sync_registrations_remain_an_explicit_boundary(self):
        self.u.callbacks[5] = dict(queue=self.SYNC_QUEUE, callback=0x7777,
                                   user_data=0, flags=1)
        with self.assertRaisesRegex(UnsupportedUipc, 'identity_not_supplied'):
            self.u.handle_ioctl(self.read, self.write, 0x80000005, 0x100, tid=1001)
        self.assertEqual(self.read(0x1105, 1), b'\x01')
