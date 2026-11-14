"""Uncapped aggregate counters fed from the same appends as the capped syscall/UIPC logs.

Report layout (``report['summary']``; covers events since this process started, i.e. since
the checkpoint resume, not the whole history):
  syscalls: {name: {count, errnos: {ENOENT: n}}}
  opens:    {"<syscall> <path>": {count, results: {fd|ok|ENOENT|...: n}, first_instruction, last_instruction}}
            for open openat stat64 lstat64 access readlink execve
  uipc:     {ops: {"<queue hex> <op>": {count, first_instruction, last_instruction}},
             by_op: {op: n}, queue_max_depth: {queue hex: n}, kernel_consumed: {"<queue hex> <module>": n}}
            (events without a queue, e.g. valloc, use "-"; sync_cb_*/wait_cb_* are in by_op)
  ioctls:   {"<fd path> <cmd hex>": {count, results}}
  threads:  {tid: {name, created_at, state, syscalls}}   (created_at = instruction of the clone)
  mmaps:    {path: {count, bytes, first_instruction, munmaps, munmap_bytes}}  (anonymous = "[anon]";
            a munmap only attributes to a path when it starts at an mmap2 base address, else "[unknown]")
"""
import errno as _errno

PATH_SYSCALLS = frozenset(('open', 'openat', 'stat64', 'lstat64', 'access', 'readlink', 'execve'))


def _result(ret, name=None):
    if ret is None:
        return 'blocked'
    if ret >= 0xFFFFF000:  # guest returns -errno as u32
        return _errno.errorcode.get(0x100000000 - ret, f'E{0x100000000 - ret}')
    return 'fd' if name in ('open', 'openat') else 'ok'


def _hex(v):
    return f'{v:#x}' if isinstance(v, int) else str(v)


def _hist(table, key):
    table[key] = table.get(key, 0) + 1


class RunSummary:
    def __init__(self, clock, tid_fn=lambda: None, fd_path=lambda fd: None, queue_depth=lambda q: 0):
        self.clock, self.tid_fn, self.fd_path, self.queue_depth = clock, tid_fn, fd_path, queue_depth
        self.syscalls, self.opens, self.ioctls, self.mmaps = {}, {}, {}, {}
        self.uipc_ops, self.uipc_by_op, self.max_depth, self.consumed = {}, {}, {}, {}
        self.tid_syscalls, self.created_at, self._mmap_bases = {}, {}, {}
        self.errors = 0

    def syscall(self, e):
        try:
            self._syscall(e)
        except Exception:  # shortcut: an odd event shape must never abort a run; counted, not diagnosed
            self.errors += 1

    def uipc(self, e):
        try:
            self._uipc(e)
        except Exception:
            self.errors += 1

    def _syscall(self, e):
        name = e.get('syscall')
        if not isinstance(name, str):
            return
        ret = e.get('returned')
        res = _result(ret, name)
        s = self.syscalls.get(name)
        if s is None:
            s = self.syscalls[name] = {'count': 0, 'errnos': {}}
        s['count'] += 1
        if res not in ('ok', 'fd', 'blocked'):
            _hist(s['errnos'], res)
        tid = self.tid_fn()
        self.tid_syscalls[tid] = self.tid_syscalls.get(tid, 0) + 1
        if name in PATH_SYSCALLS:
            path = e.get('path')
            if path is not None:
                now = self.clock()
                key = f'{name} {path}'
                o = self.opens.get(key)
                if o is None:
                    o = self.opens[key] = {'count': 0, 'results': {}, 'first_instruction': now}
                o['count'] += 1
                _hist(o['results'], res)
                o['last_instruction'] = now
        elif name == 'ioctl' or name == 'gles_wait':
            key = f"{self.fd_path(e.get('fd')) or e.get('device') or '?'} {_hex(e.get('cmd', 0))}"
            o = self.ioctls.get(key)
            if o is None:
                o = self.ioctls[key] = {'count': 0, 'results': {}}
            o['count'] += 1
            _hist(o['results'], res)
        elif name == 'mmap2':
            args = e.get('arguments') or (0,) * 6
            m = e.get('mapping') or {}
            path = m.get('path') or (self.fd_path(args[4]) if args[4] != 0xFFFFFFFF else None) or '[anon]'
            o = self.mmaps.get(path)
            if o is None:
                o = self.mmaps[path] = {'count': 0, 'bytes': 0, 'first_instruction': self.clock(),
                                        'munmaps': 0, 'munmap_bytes': 0}
            o['count'] += 1
            o['bytes'] += args[1]
            if ret is not None and ret < 0xFFFFF000:
                self._mmap_bases[ret] = path
        elif name == 'munmap':
            args = e.get('arguments') or (0, 0)
            o = self.mmaps.setdefault(self._mmap_bases.pop(args[0], '[unknown]'),
                                      {'count': 0, 'bytes': 0, 'first_instruction': None,
                                       'munmaps': 0, 'munmap_bytes': 0})
            o['munmaps'] += 1
            o['munmap_bytes'] += args[1]
        elif name == 'clone' and ret is not None and ret < 0xFFFFF000:
            self.created_at[ret] = self.clock()

    def _uipc(self, e):
        op = e.get('type')
        q = e.get('queue', e.get('target_queue'))
        qs = f'{q:#x}' if isinstance(q, int) else '-'
        key = f'{qs} {op}'
        now = self.clock()
        o = self.uipc_ops.get(key)
        if o is None:
            o = self.uipc_ops[key] = {'count': 0, 'first_instruction': now}
        o['count'] += 1
        o['last_instruction'] = now
        _hist(self.uipc_by_op, op)
        if isinstance(q, int):
            if isinstance(op, str) and op.startswith('snd'):
                depth = self.queue_depth(q)
                if depth > self.max_depth.get(qs, 0):
                    self.max_depth[qs] = depth
            if 'consumed_by' in e:
                _hist(self.consumed, f"{qs} {e['consumed_by']}")

    def build(self, threads=None):
        threads = threads or {}
        tids = set(self.tid_syscalls) | set(self.created_at) | set(threads)
        return {'syscalls': self.syscalls, 'opens': self.opens, 'ioctls': self.ioctls, 'mmaps': self.mmaps,
                'uipc': {'ops': self.uipc_ops, 'by_op': self.uipc_by_op,
                         'queue_max_depth': self.max_depth, 'kernel_consumed': self.consumed},
                'observer_errors': self.errors,
                'threads': {str(t): {'name': getattr(threads.get(t), 'name', None),
                                     'created_at': self.created_at.get(t),
                                     'state': getattr(threads.get(t), 'state', None),
                                     'syscalls': self.tid_syscalls.get(t, 0)}
                            for t in sorted(tids, key=lambda x: (x is None, x or 0))}}
