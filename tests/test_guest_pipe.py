import unittest

from src.a6400.execution.guest_pipe import (
    POLLERR,
    POLLHUP,
    POLLIN,
    POLLNVAL,
    POLLOUT,
    POLLRDNORM,
    POLLWRNORM,
    GuestPipe,
    UnsupportedPipe,
)


class TestGuestPipe(unittest.TestCase):
    def test_create_read_write_and_poll(self):
        pipes = GuestPipe()
        channel = pipes.create(flags=0, pid=1022, tgid=1000)
        pid = channel['pipe_id']
        self.assertEqual(pid, 1)

        # Initially empty: read end has 0 mask, write end has POLLOUT | POLLWRNORM
        self.assertEqual(pipes.poll(pid, 'read'), 0)
        self.assertEqual(pipes.poll(pid, 'write'), POLLOUT | POLLWRNORM)
        self.assertIsNone(pipes.read(pid, 4))

        # Write 1 byte (e.g. HDMI DeviceThread exit wakeup byte)
        written = pipes.write(pid, b'\x01')
        self.assertEqual(written, 1)
        self.assertEqual(pipes.poll(pid, 'read'), POLLIN | POLLRDNORM)

        # Read 1 byte back
        data = pipes.read(pid, 4)
        self.assertEqual(data, b'\x01')
        self.assertEqual(pipes.poll(pid, 'read'), 0)

    def test_close_write_end_signals_pollhup_and_eof(self):
        pipes = GuestPipe()
        channel = pipes.create(flags=0, pid=1022, tgid=1000)
        pid = channel['pipe_id']

        pipes.close_end(pid, 'write')
        self.assertEqual(pipes.poll(pid, 'read'), POLLHUP)
        self.assertEqual(pipes.read(pid, 16), b'')

    def test_close_read_end_signals_pollerr_and_broken_pipe(self):
        pipes = GuestPipe()
        channel = pipes.create(flags=0, pid=1022, tgid=1000)
        pid = channel['pipe_id']

        pipes.close_end(pid, 'read')
        self.assertEqual(pipes.poll(pid, 'write'), POLLERR)
        with self.assertRaises(UnsupportedPipe):
            pipes.write(pid, b'x')

    def test_unknown_pipe_returns_pollnval(self):
        pipes = GuestPipe()
        self.assertEqual(pipes.poll(999, 'read'), POLLNVAL)


if __name__ == '__main__':
    unittest.main()
