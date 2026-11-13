"""Opt-in bounded event log: a deque(maxlen=N) that still counts every append."""
from collections import deque
from typing import Dict, Iterable, Optional


class CappedLog(deque):
    """Keeps the last ``maxlen`` events; ``total`` and ``counts`` cover every append."""

    def __init__(self, iterable: Iterable = (), maxlen: Optional[int] = None, count_key: str = 'type',
                 total: Optional[int] = None, counts: Optional[Dict[str, int]] = None):
        items = list(iterable)
        self.count_key = count_key
        self.counts: Dict[str, int] = {} if counts is None else dict(counts)
        self.total = len(items) if total is None else total
        if counts is None:
            for item in items:
                self._count(item)
        super().__init__(items, maxlen)

    def _count(self, item) -> None:
        key = str(item.get(self.count_key)) if isinstance(item, dict) else 'non-dict'
        self.counts[key] = self.counts.get(key, 0) + 1

    def append(self, item) -> None:
        self.total += 1
        self._count(item)
        super().append(item)

    def __reduce__(self):
        return (CappedLog, (list(self), self.maxlen, self.count_key, self.total, self.counts))

    @classmethod
    def wrap(cls, items, maxlen: int, count_key: str) -> 'CappedLog':
        """Re-bound an existing list or CappedLog without losing totals or counts."""
        if isinstance(items, CappedLog):
            return cls(items, maxlen, items.count_key, items.total, items.counts)
        return cls(items, maxlen, count_key)
