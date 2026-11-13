"""E0455: model of the Linux 3.0 workqueue list invariant that B23 violated.

Run B23's warm kernel ring (docs/evidence/0453) shows `__queue_work+0x220`
(VA 0x6014a280) doing:

    ldr r2, [work, #4]        ; work->entry.next
    add r3, work, #4          ; &work->entry
    cmp r2, r3
    beq ok
    bl  __bug_noarg           ; BUG_ON(!list_empty(&work->entry))

struct work_struct on this 32-bit ARM kernel is {data, entry.next, entry.prev,
func}. A zero-initialised work item therefore has entry.next == 0 and is NOT an
empty list; schedule_work() BUGs and the camera's exception monitor reboots.
The module fix self-links entry.next/entry.prev to &entry and clears data
(WORK_DATA_INIT) before the first schedule (tools/native_camera/
uvc_callback_bridge.c: a6400_work_init).
"""
import unittest


class WorkqueueWorkInitModel(unittest.TestCase):
    ENTRY_OFFSET = 4  # data at 0, list_head entry at 4

    @staticmethod
    def list_empty(words, base):
        """Kernel list_empty(&work->entry): next == prev == &entry."""
        entry = base + WorkqueueWorkInitModel.ENTRY_OFFSET
        return words[1] == entry and words[2] == entry

    def test_zero_initialised_work_item_trips_the_kernel_bug(self):
        base = 0x70520030
        old_layout = [0, 0, 0, 0x1234]  # data, next, prev, func (as built for E0446)
        self.assertFalse(self.list_empty(old_layout, base),
                         'zeroed work_struct must not look like an empty list')

    def test_initialised_work_item_is_eligible_for_schedule(self):
        base = 0x70520030
        entry = base + self.ENTRY_OFFSET
        fixed = [0, entry, entry, 0x1234]
        self.assertTrue(self.list_empty(fixed, base))
        self.assertEqual(fixed[0], 0, 'WORK_DATA_INIT is zero on Linux 3.0')

    def test_initialised_work_item_still_rejects_a_queued_item(self):
        # while a work item is pending the kernel links it into a worklist, so
        # entry.next != &entry; scheduling it again is the same BUG.
        base = 0x70520030
        entry = base + self.ENTRY_OFFSET
        queued = [0, 0x70600000, 0x70600000, 0x1234]
        self.assertFalse(self.list_empty(queued, base))
        self.assertNotEqual(queued[1], entry)


if __name__ == '__main__':
    unittest.main()
