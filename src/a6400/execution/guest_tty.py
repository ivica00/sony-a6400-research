"""Opt-in console log sink for /dev/tty (E0338).

The inbound USB-event handler path opens ``/dev/tty`` with flags 0x902
(O_RDWR|O_NOCTTY|O_NONBLOCK) for console/log output (observed in e0687,
instruction 557,164,099).  This module models only that log-sink purpose:

* open serves the observed flag subset and returns an owner token;
* write accepts bounded guest buffers and records them (no host terminal I/O);
* read/ioctl are explicit unsupported boundaries.

It is not a terminal emulator and claims no TTY semantics beyond the log sink.
"""

TTY_OPEN_ALLOWED_MASK = 0x902  # O_RDWR | O_NOCTTY | O_NONBLOCK (observed)
TTY_MAX_WRITE = 0x10000


class UnsupportedTtyError(Exception):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = {'reason': reason, **details}


class GuestTty:
    """Fail-closed /dev/tty log sink (opt-in)."""

    def __init__(self, max_write=TTY_MAX_WRITE):
        self.max_write = max_write
        self.report = None
        self.opens = 0
        self.writes = 0
        self.bytes_written = 0
        self.log = []

    def open(self, flags, caller_pid=None, caller_tgid=None):
        unknown = int(flags) & ~TTY_OPEN_ALLOWED_MASK
        if unknown:
            raise UnsupportedTtyError(
                'tty_open_flags_unsupported', flags=flags, unknown_bits=unknown)
        self.opens += 1
        return {'owner': len(self.log), 'flags': int(flags),
                'pid': caller_pid, 'tgid': caller_tgid}

    def write(self, owner, data, tid=None):
        data = bytes(data)
        if len(data) > self.max_write:
            raise UnsupportedTtyError(
                'tty_write_too_large', size=len(data), limit=self.max_write)
        self.writes += 1
        self.bytes_written += len(data)
        text = data.decode('utf-8', errors='replace')
        self.log.append({'tid': tid, 'size': len(data),
                         'text': text[:256],
                         'hex': data[:64].hex()})
        return len(data)

    def read(self):
        raise UnsupportedTtyError('tty_read_not_supplied')

    def ioctl(self, cmd, arg):
        raise UnsupportedTtyError('tty_ioctl_not_supplied', cmd=cmd, arg=arg)

    def describe(self):
        return {'policy': 'log-sink', 'opens': self.opens,
                'writes': self.writes, 'bytes_written': self.bytes_written,
                'log_entries': len(self.log),
                'last': self.log[-1] if self.log else None}
