"""Linux anonymous pipe contract (sys_pipe / sys_poll / read / write) for guest IPC."""


class UnsupportedPipe(Exception):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.reason = reason
        self.details = {'reason': reason, **details}


POLLIN = 0x0001
POLLOUT = 0x0004
POLLERR = 0x0008
POLLHUP = 0x0010
POLLNVAL = 0x0020
POLLRDNORM = 0x0040
POLLWRNORM = 0x0100


class GuestPipe:
    """Manages in-memory FIFO channels created by sys_pipe (r7 = 42)."""

    def __init__(self):
        self.next_pipe_id = 1
        self.pipes = {}
        self.transactions = []

    def create(self, flags=0, pid=None, tgid=None):
        if flags != 0:
            raise UnsupportedPipe('unsupported_pipe_flags', flags=flags)
        pipe_id = self.next_pipe_id
        self.next_pipe_id += 1
        self.pipes[pipe_id] = {
            'pipe_id': pipe_id,
            'buffer': bytearray(),
            'read_open': True,
            'write_open': True,
            'pid': pid,
            'tgid': tgid,
        }
        self.transactions.append({'op': 'create', 'pipe_id': pipe_id, 'pid': pid})
        return self.pipes[pipe_id]

    def poll(self, pipe_id, end):
        channel = self.pipes.get(pipe_id)
        if channel is None:
            return POLLNVAL
        mask = 0
        if end == 'read':
            if len(channel['buffer']) > 0:
                mask |= POLLIN | POLLRDNORM
            if not channel['write_open']:
                mask |= POLLHUP
        elif end == 'write':
            if not channel['read_open']:
                mask |= POLLERR
            else:
                mask |= POLLOUT | POLLWRNORM
        return mask

    def write(self, pipe_id, data: bytes):
        channel = self.pipes.get(pipe_id)
        if channel is None or not channel['write_open']:
            raise UnsupportedPipe('write_on_closed_pipe', pipe_id=pipe_id)
        if not channel['read_open']:
            raise UnsupportedPipe('broken_pipe', pipe_id=pipe_id)
        channel['buffer'].extend(data)
        self.transactions.append({'op': 'write', 'pipe_id': pipe_id, 'count': len(data)})
        return len(data)

    def read(self, pipe_id, count: int):
        channel = self.pipes.get(pipe_id)
        if channel is None or not channel['read_open']:
            raise UnsupportedPipe('read_on_closed_pipe', pipe_id=pipe_id)
        if len(channel['buffer']) == 0:
            if not channel['write_open']:
                return b''
            return None  # Would block
        take = min(count, len(channel['buffer']))
        out = bytes(channel['buffer'][:take])
        del channel['buffer'][:take]
        self.transactions.append({'op': 'read', 'pipe_id': pipe_id, 'count': len(out)})
        return out

    def close_end(self, pipe_id, end):
        channel = self.pipes.get(pipe_id)
        if channel is None:
            return
        if end == 'read':
            channel['read_open'] = False
        elif end == 'write':
            channel['write_open'] = False
        self.transactions.append({'op': 'close', 'pipe_id': pipe_id, 'end': end})
