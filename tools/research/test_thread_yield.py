import sys
import unicorn.arm_const as arm
from tools.research.experiment_ui_boot import run_experiment

# Run experiment with a custom hook or subclass
from src.a6400.execution.interpreter_probe import InterpreterProbe
from src.a6400.execution.guest_gles import GLES_LOCK_SEMAPHORE

class YieldingProbe(InterpreterProbe):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.yield_count = 0

    def _hook_syscall(self, uc, user_data):
        # We can hook into syscall handling by checking if it's GLES_LOCK_SEMAPHORE
        pass

print("Testing yielding probe script...")
