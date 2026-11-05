import struct
import unittest
from src.a6400.execution.guest_sem import GuestSem, IPC_CREAT, IPC_EXCL, IPC_NOWAIT, SETALL, GETALL, SETVAL, GETVAL, IPC_RMID


class TestGuestSem(unittest.TestCase):
    def setUp(self):
        self.sem = GuestSem()
        self.memory = {}

    def memory_reader(self, addr, size):
        return bytes(self.memory.get(addr + i, 0) for i in range(size))

    def memory_writer(self, addr, data):
        for i, b in enumerate(data):
            self.memory[addr + i] = b

    def test_semget_create_and_lookup(self):
        # semget with IPC_CREAT
        semid = self.sem.semget(0x10020000, 4, IPC_CREAT | 0o666)
        self.assertGreaterEqual(semid, 0)

        # Lookup same key returns same semid
        semid2 = self.sem.semget(0x10020000, 4, 0o666)
        self.assertEqual(semid, semid2)

        # IPC_EXCL on existing returns -EEXIST (-17)
        err = self.sem.semget(0x10020000, 4, IPC_CREAT | IPC_EXCL | 0o666)
        self.assertEqual(err, -17)

    def test_semctl_setall_and_getall(self):
        semid = self.sem.semget(0x10020000, 4, IPC_CREAT | 0o666)
        
        # Prepare 4 short values in memory: [1, 2, 3, 4]
        vals = [1, 2, 3, 4]
        raw_vals = struct.pack('<4H', *vals)
        self.memory_writer(0x2000, raw_vals)

        # SETALL (0x11)
        res = self.sem.semctl(semid, 0, SETALL, 0x2000, memory_reader=self.memory_reader)
        self.assertEqual(res, 0)
        self.assertEqual(self.sem.sets_by_id[semid].values, [1, 2, 3, 4])

        # GETALL (0x13) to another buffer
        res = self.sem.semctl(semid, 0, GETALL, 0x3000, memory_writer=self.memory_writer)
        self.assertEqual(res, 0)
        readback = struct.unpack('<4H', self.memory_reader(0x3000, 8))
        self.assertEqual(list(readback), [1, 2, 3, 4])

    def test_semop_increment_and_decrement(self):
        semid = self.sem.semget(0x10020000, 4, IPC_CREAT | 0o666)

        # Operation: increment sem 0 by 5
        # struct sembuf { uint16 sem_num; int16 sem_op; int16 sem_flg; }
        op1 = struct.pack('<Hhh', 0, 5, 0)
        self.memory_writer(0x4000, op1)
        res = self.sem.semop(semid, 0x4000, 1, memory_reader=self.memory_reader)
        self.assertEqual(res, 0)
        self.assertEqual(self.sem.sets_by_id[semid].values[0], 5)

        # Operation: decrement sem 0 by 2
        op2 = struct.pack('<Hhh', 0, -2, 0)
        self.memory_writer(0x4000, op2)
        res = self.sem.semop(semid, 0x4000, 1, memory_reader=self.memory_reader)
        self.assertEqual(res, 0)
        self.assertEqual(self.sem.sets_by_id[semid].values[0], 3)


if __name__ == '__main__':
    unittest.main()
