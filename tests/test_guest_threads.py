import unittest
import struct
import unicorn
import unicorn.arm_const as arm
from src.a6400.execution.guest_threads import (
    GuestThreads,
    EXPECTED_PTHREAD_CLONE_FLAGS,
    PR_SET_NAME, GuestThread, REGISTER_LIST
)


class GuestThreadsTests(unittest.TestCase):
    def setUp(self):
        self.memory = {}
        self.clone_context = {register: 0x110000 + index for index, register in enumerate(REGISTER_LIST)}
        self.clone_context[arm.UC_ARM_REG_PC] = 0x1800
        self.clone_context[arm.UC_ARM_REG_CPSR] = 0x80000010

    def mem_reader(self, addr: int, size: int) -> bytes:
        data = bytearray()
        for i in range(size):
            data.append(self.memory.get(addr + i, 0))
        return bytes(data)

    def mem_writer(self, addr: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.memory[addr + i] = b

    def test_initial_state(self):
        gt = GuestThreads(initial_tid=1000)
        self.assertEqual(gt.current_tid, 1000)
        self.assertIn(1000, gt.threads)
        self.assertEqual(gt.threads[1000].name, 'main')
        self.assertEqual(gt.threads[1000].state, 'running')

    def test_clone_creates_runnable_thread_with_proper_registers(self):
        gt = GuestThreads(initial_tid=1000)
        child_stack = 0x50c7ef98
        parent_tidptr = 0x50c7f4c8
        child_tidptr = 0x50c7f4c8
        tls_val = 0x50c7f920
        fn = 0x50085035  # Thumb function pointer (bit 0 set)
        arg = 0x50c7f460

        # Setup child stack words: [child_stack] = fn, [child_stack + 4] = arg
        self.mem_writer(child_stack, struct.pack('<II', fn, arg))

        tid, event = gt.handle_clone(
            flags=EXPECTED_PTHREAD_CLONE_FLAGS,
            child_stack=child_stack,
            parent_tidptr=parent_tidptr,
            tls_val=tls_val,
            child_tidptr=child_tidptr,
            mem_reader=self.mem_reader,
            mem_writer=self.mem_writer,
            syscall_registers=self.clone_context
        )

        self.assertEqual(tid, 1001)
        self.assertEqual(event['child_tid'], 1001)
        # Check that child TID was written to parent_tidptr
        written_tid = struct.unpack('<I', self.mem_reader(parent_tidptr, 4))[0]
        self.assertEqual(written_tid, 1001)

        # Check child thread properties
        child = gt.threads[1001]
        self.assertEqual(child.state, 'runnable')
        self.assertEqual(child.child_stack, child_stack)
        self.assertEqual(child.tls_val, tls_val)
        self.assertIsNone(child.fn)
        self.assertIsNone(child.arg)

        # Child registers
        self.assertEqual(child.regs[arm.UC_ARM_REG_R0], 0)
        self.assertEqual(child.regs[arm.UC_ARM_REG_SP], child_stack)
        for register in REGISTER_LIST:
            if register not in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_SP):
                self.assertEqual(child.regs[register], self.clone_context[register])
        self.assertEqual(self.clone_context[arm.UC_ARM_REG_R0], 0x110000)

    def test_clone_rejects_unsupported_flags(self):
        gt = GuestThreads(initial_tid=1000)
        with self.assertRaises(ValueError):
            gt.handle_clone(
                flags=0x1234,  # missing required NPTL flags
                child_stack=0x1000,
                parent_tidptr=0x2000,
                tls_val=0x3000,
                child_tidptr=0x2000,
                mem_reader=self.mem_reader,
                mem_writer=self.mem_writer,
                syscall_registers=self.clone_context
            )

    def test_clone_rejects_extra_flags_and_incomplete_context_before_mutation(self):
        for flags, registers in ((EXPECTED_PTHREAD_CLONE_FLAGS | 0x4000, self.clone_context),
                                 (EXPECTED_PTHREAD_CLONE_FLAGS, {})):
            with self.subTest(flags=flags, complete=bool(registers)):
                gt = GuestThreads()
                with self.assertRaises(ValueError):
                    gt.handle_clone(flags, 0x1000, 0x2000, 0x3000, 0x2000,
                                    self.mem_reader, self.mem_writer, syscall_registers=registers)
                self.assertEqual(self.memory, {})
                self.assertEqual(gt.next_tid, 1001)
                self.assertEqual(list(gt.threads), [1000])

    def test_clone_child_executes_guest_wrapper_and_selects_function_instruction_set(self):
        for base, thumb_function in ((0x1000, False), (0x11000, True)):
            with self.subTest(base=base, thumb_function=thumb_function):
                mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
                mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
                mu.mem_map(base, 0x4000)
                mu.mem_map(0xffff0000, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
                # Constructed ARM wrapper: choose child branch, read arg/function
                # from its stack, establish LR, call, and store the returned value.
                wrapper = (0xe3500000, 0x1a000003, 0xe59d0004, 0xe1a0e00f,
                           0xe49df008, 0xe5850000, 0xe1a00000)
                mu.mem_write(base, struct.pack('<7I', *wrapper))
                function = base + 0x1000
                mu.mem_write(function, bytes.fromhex('01307047') if thumb_function else
                             struct.pack('<2I', 0xe2800001, 0xe12fff1e))
                stack, output = base + 0x2000, base + 0x3000
                mu.mem_write(stack, struct.pack('<II', function | int(thumb_function), 41))
                registers = dict(self.clone_context)
                registers.update({arm.UC_ARM_REG_PC: base, arm.UC_ARM_REG_R5: output})
                def unexpected_stack_read(address, size):
                    self.fail('clone must leave child-stack decoding to guest code')
                gt = GuestThreads()
                tid, event = gt.handle_clone(EXPECTED_PTHREAD_CLONE_FLAGS, stack, output + 4,
                                             0x12345000, output + 4, unexpected_stack_read,
                                             mu.mem_write, syscall_registers=registers)
                self.assertEqual(event['child_resume_pc'], base)
                gt.restore_context(mu, tid)
                trace = []
                mu.hook_add(unicorn.UC_HOOK_CODE, lambda uc, address, size, _: trace.append(address))
                mu.emu_start(base, base + 24, count=20)
                self.assertEqual(trace[:2], [base, base + 4])
                self.assertIn(function, trace)
                self.assertIn(base + 20, trace)
                self.assertEqual(struct.unpack('<I', mu.mem_read(output, 4))[0], 42)
                self.assertEqual(mu.reg_read(arm.UC_ARM_REG_SP), stack + 8)

    def test_gettid_and_prctl(self):
        gt = GuestThreads(initial_tid=1000)
        tid, _ = gt.handle_gettid()
        self.assertEqual(tid, 1000)

        # prctl PR_SET_NAME
        name_buf = 0x20000
        self.mem_writer(name_buf, b"THREAD_INFRA0\x00")
        ret, _ = gt.handle_prctl(PR_SET_NAME, name_buf, self.mem_reader)
        self.assertEqual(ret, 0)
        self.assertEqual(gt.threads[1000].name, "THREAD_INFRA0")

    def test_futex_wait_and_wake_lifecycle(self):
        gt = GuestThreads(initial_tid=1000)
        # Create a runnable child thread
        self.mem_writer(0x1000, struct.pack('<II', 0x5000, 0x6000))
        gt.handle_clone(
            flags=EXPECTED_PTHREAD_CLONE_FLAGS,
            child_stack=0x1000,
            parent_tidptr=0x2000,
            tls_val=0x3000,
            child_tidptr=0x2000,
            mem_reader=self.mem_reader,
            mem_writer=self.mem_writer,
            syscall_registers=self.clone_context
        )

        uaddr = 0x7feffd0c
        # Futex mutex value is 2
        self.mem_writer(uaddr, struct.pack('<I', 2))

        # 1. FUTEX_WAIT with mismatch value returns -EAGAIN
        ret, next_tid, _ = gt.handle_futex_wait(uaddr, 1, self.mem_reader)
        self.assertEqual(ret, 0xfffffff5)
        self.assertIsNone(next_tid)
        self.assertEqual(gt.threads[1000].state, 'running')

        # 2. FUTEX_WAIT with matching value blocks thread 1000 and switches to 1001
        ret, next_tid, _ = gt.handle_futex_wait(uaddr, 2, self.mem_reader)
        self.assertIsNone(ret)
        self.assertEqual(next_tid, 1001)
        self.assertEqual(gt.threads[1000].state, 'blocked_futex')

        # 3. FUTEX_WAKE unblocks thread 1000
        woken, _ = gt.handle_futex_wake(uaddr, 1)
        self.assertEqual(woken, 1)
        self.assertEqual(gt.threads[1000].state, 'runnable')
        self.assertEqual(gt.threads[1000].regs[arm.UC_ARM_REG_R0], 0)

    def test_futex_mismatch_leaves_memory_and_wait_state_unchanged(self):
        gt = GuestThreads(initial_tid=1000)
        address = 0x2000
        self.mem_writer(address, struct.pack('<I', 7))
        ret, next_tid, event = gt.handle_futex_wait(address, 2, self.mem_reader)
        self.assertEqual(ret, (-11) & 0xffffffff)
        self.assertEqual(event['returned'], ret)
        self.assertIsNone(next_tid)
        self.assertEqual(gt.futex_waiters, {})
        self.assertEqual(gt.threads[1000].state, 'running')
        self.assertEqual(self.mem_reader(address, 4), struct.pack('<I', 7))

    def test_context_switch_updates_tls_seen_by_original_arm_mrc(self):
        mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
        mu.mem_map(0x1000, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
        mu.mem_map(0xffff0000, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
        # mrc p15,0,r0,c13,c0,3: the same TLS accessor used by original NPTL.
        mu.mem_write(0x1000, struct.pack('<I', 0xee1d0f70))
        mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
        gt = GuestThreads(initial_tid=1000)
        gt.threads[1000].tls_val = 0x11111000
        child = GuestThread(1001, 'child', 'runnable', tls_val=0x22222000)
        gt.threads[1001] = child
        for tid, expected in ((1000, 0x11111000), (1001, 0x22222000), (1000, 0x11111000)):
            gt.restore_context(mu, tid)
            mu.emu_start(0x1000, 0x1004, count=1)
            self.assertEqual(mu.reg_read(arm.UC_ARM_REG_R0), expected)
            self.assertEqual(struct.unpack('<I', mu.mem_read(0xffff0ff0, 4))[0], expected)
            self.assertEqual(gt.current_tid, tid)
        self.assertEqual(list(mu.mem_regions())[-1][2], unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)

    def test_restored_tls_keeps_kuser_model_and_hardware_consistent(self):
        from src.a6400.execution.guest_kuser import GuestKuser
        # set_tls requires an existing helper page, not instruction template bytes.
        # This fixture isolates context switching; template validation has its own tests.
        mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
        mu.mem_map(0xffff0000, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
        kuser = GuestKuser.__new__(GuestKuser)
        kuser.mu, kuser.tls_value = mu, 0
        gt = GuestThreads()
        gt.threads[1000].tls_val = 0x12345000
        gt.restore_context(mu, 1000, kuser)
        self.assertEqual(kuser.tls_value, 0x12345000)
        self.assertEqual(mu.reg_read(arm.UC_ARM_REG_C13_C0_3), kuser.tls_value)
        self.assertEqual(struct.unpack('<I', mu.mem_read(0xffff0ff0, 4))[0], kuser.tls_value)
        self.assertEqual(list(mu.mem_regions())[0][2], unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)

    def test_thread_exit_clears_child_tidptr(self):
        gt = GuestThreads(initial_tid=1000)
        child_stack = 0x1000
        child_tidptr = 0x2000
        self.mem_writer(child_stack, struct.pack('<II', 0x5000, 0x6000))
        tid, _ = gt.handle_clone(
            flags=EXPECTED_PTHREAD_CLONE_FLAGS,
            child_stack=child_stack,
            parent_tidptr=0x100,
            tls_val=0x200,
            child_tidptr=child_tidptr,
            mem_reader=self.mem_reader,
            mem_writer=self.mem_writer,
            syscall_registers=self.clone_context
        )

        # Switch to child
        gt.threads[1000].state = 'runnable'
        gt.current_tid = tid
        gt.threads[tid].state = 'running'

        # Child exits
        next_tid, _ = gt.handle_exit(0, self.mem_writer)
        self.assertEqual(gt.threads[tid].state, 'terminated')
        self.assertEqual(next_tid, 1000)
        # Check that child_tidptr was cleared to 0
        cleared_val = struct.unpack('<I', self.mem_reader(child_tidptr, 4))[0]
        self.assertEqual(cleared_val, 0)

    def test_sched_getparam_and_getscheduler(self):
        gt = GuestThreads(initial_tid=1000)
        param_addr = 0x3000
        ret, event = gt.handle_sched_getparam(1000, param_addr, self.mem_writer)
        self.assertEqual(ret, 0)
        self.assertEqual(event['syscall'], 'sched_getparam')
        prio = struct.unpack('<I', self.mem_reader(param_addr, 4))[0]
        self.assertEqual(prio, 0)

        ret, event = gt.handle_sched_getscheduler(1000)
        self.assertEqual(ret, 0)
        self.assertEqual(event['syscall'], 'sched_getscheduler')


if __name__ == '__main__':
    unittest.main()
