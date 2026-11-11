"""Single-slot newest-frame handoff; never queue camera frames for slow viewers."""
from dataclasses import dataclass
import threading
import time
import uuid


@dataclass(frozen=True)
class Frame:
    jpeg: bytes
    sequence: int
    fetched_ns: int
    fetch_ms: float

    def age_ms(self):
        return max(0.0, (time.perf_counter_ns() - self.fetched_ns) / 1e6)


class FrameHub:
    def __init__(self):
        self.condition = threading.Condition()
        self.latest = None
        self.sequence = 0
        self.stream_id = uuid.uuid4().hex

    def publish(self, jpeg, fetch_ms=0.0):
        with self.condition:
            self.sequence += 1
            self.latest = Frame(jpeg, self.sequence, time.perf_counter_ns(), fetch_ms)
            self.condition.notify_all()
            return self.latest

    def after(self, sequence=-1, timeout=2.0):
        with self.condition:
            ready = self.condition.wait_for(
                lambda: self.latest is not None and self.latest.sequence > sequence,
                timeout=timeout)
            return self.latest if ready else None
