"""Bounded kikilog descriptor contract; log state/notifications stay unknown."""


class UnsupportedKikilog(RuntimeError):
    def __init__(self, reason, **details):
        self.details = {'reason': reason, 'device': '/dev/usb/kikilog', **details}
        super().__init__(reason)


class GuestKikilog:
    def __init__(self, source_sha256, policy='open-only'):
        if policy not in ('open-only', 'observed-running-e0301'):
            raise ValueError('Unknown kikilog policy')
        self.source_sha256 = source_sha256
        self.policy = policy
        self.owners = {}
        self.next_owner = 1
        self.transactions = []

    def open(self, flags, pid, tgid):
        if flags & ~(2 | 0x800 | 0x80000) or flags & 3 == 1:
            raise UnsupportedKikilog('kikilog_open_flags_not_in_bounded_subset', flags=flags)
        owner = self.next_owner
        self.next_owner += 1
        self.owners[owner] = {'pid': pid, 'tgid': tgid, 'flags': flags}
        self.transactions.append({'operation': 'open', 'owner': owner, 'flags': flags,
                                  'source': self.source_sha256, 'fops_return': 0})
        return owner

    def close(self, owner):
        if owner not in self.owners:
            raise UnsupportedKikilog('kikilog_invalid_owner', owner=owner)
        del self.owners[owner]
        self.transactions.append({'operation': 'close', 'owner': owner, 'fops_return': 0})

    def ioctl(self, owner, command, argument):
        if owner not in self.owners:
            raise UnsupportedKikilog('kikilog_invalid_owner', owner=owner)
        if command == 0x80044a21 and self.policy == 'observed-running-e0301':
            # E0301: original kikilog_resume with existing main thread and
            # notify qid skips file/buffer/thread creation. Their presence is
            # observed on camera; their log payload/notifications are opaque.
            self.get_flag = 0
            self.timer_list = []
            self.status_list = []
            self.mutexes_initialized = True
            self.transactions.append({'operation': 'resume_existing', 'cmd': command,
                                      'returned': 0, 'policy': self.policy,
                                      'log_bytes_supplied': False, 'native_threads_executed': False})
            return 0
        if command == 0x80044a10 and self.policy == 'observed-running-e0301':
            # Stores the argument as the notify queue id; fails unless the main thread exists.
            # Main thread present as in resume_existing; the notifications stay unsupplied.
            if not getattr(self, 'mutexes_initialized', False):
                raise UnsupportedKikilog('kikilog_notify_before_resume', cmd=command, arg=argument)
            self.notify_qid = argument
            self.transactions.append({'operation': 'set_notify_qid', 'cmd': command, 'qid': argument, 'returned': 0,
                                      'policy': self.policy, 'notifications_supplied': False})
            return 0
        raise UnsupportedKikilog('kikilog_ioctl_state_not_supplied', cmd=command, arg=argument,
                                  source=self.source_sha256)
