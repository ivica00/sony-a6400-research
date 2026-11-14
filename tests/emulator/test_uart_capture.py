"""PL011 serial capture configuration tests (E0421)."""
import gc
import struct
import unittest

from src.a6400.execution.arm_atags import build_atags
from src.a6400.execution.unicorn_machine import UnicornMachine

MACHINE_ID = 0x0DA9


def uart_program(base, chars):
    image = bytearray(0x100)
    first, second = chars
    words = [
        0xE321F0D3,  # msr cpsr_c,#0xd3
        0xE59F0020,  # ldr r0,[pc,#0x20] -> 0x2c base
        0xE59F1020,  # ldr r1,[pc,#0x20] -> 0x30 first char
        0xE5801000,  # str r1,[r0]
        0xE59F201C,  # ldr r2,[pc,#0x1c] -> 0x34 second char
        0xE5802000,  # str r2,[r0]
        0xEAFFFFFE,  # b .
    ]
    for index, word in enumerate(words):
        struct.pack_into('<I', image, index * 4, word)
    struct.pack_into('<3I', image, 0x2C, base, ord(first), ord(second))
    return bytes(image)


class UartCaptureTests(unittest.TestCase):
    def tearDown(self):
        gc.collect()

    def make_machine(self, base, **kwargs):
        return UnicornMachine(uart_program(base, 'Hi'), b'\x00' * 64,
                              build_atags('console=ttyAM0', [(0, 0x40000000)]),
                              machine_id=MACHINE_ID, instruction_limit=200,
                              exclusive_patch=False, data_abort_delivery=False,
                              uart_base=base, **kwargs)

    def test_capture_at_physical_uart_base(self):
        machine = self.make_machine(0xF2000000)
        report = machine.run()
        self.assertEqual(report['serial_text'], 'Hi')

    def test_capture_at_remapped_uart_base(self):
        # The kernel may reach PL011 through a static/vmalloc alias; the machine
        # registers explicit read/write hooks for the configured block.
        machine = self.make_machine(0xBF001000)
        report = machine.run()
        self.assertEqual(report['serial_text'], 'Hi')


class UartReceiveTests(unittest.TestCase):
    """Bidirectional PL011: injected RX bytes are visible through DR/FR."""

    def tearDown(self):
        gc.collect()

    def make_machine(self, uart_base, data):
        return UnicornMachine(uart_program(uart_base, 'Hi'), b'\x00' * 64,
                              build_atags('console=ttyAM0', [(0, 0x40000000)]),
                              machine_id=MACHINE_ID, instruction_limit=200,
                              exclusive_patch=False, data_abort_delivery=False,
                              uart_base=uart_base, serial_input=data)

    def test_fr_and_dr_serve_injected_rx_bytes(self):
        import struct
        from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R3
        machine = self.make_machine(0xF2000000, b'AB')
        # Extend the synthetic program: read FR then two DR bytes into RAM.
        program = bytearray(uart_program(0xF2000000, 'Hi'))
        words = [
            0xE59F0038,  # ldr r0,[pc,#0x38] -> 0x44 uart base
            0xE5902018,  # ldr r2,[r0,#0x18] FR
            0xE59F3034,  # ldr r3,[pc,#0x34] -> 0x48 storage
            0xE5832000,  # str r2,[r3]
            0xE5902000,  # ldr r2,[r0] DR -> 'A'
            0xE5832004,  # str r2,[r3,#4]
            0xE5902000,  # ldr r2,[r0] DR -> 'B'
            0xE5832008,  # str r2,[r3,#8]
            0xEAFFFFFE,  # b .
        ]
        struct.pack_into('<9I', program, 0x04, *words)
        struct.pack_into('<2I', program, 0x44, 0xF2000000, 0x00100000)
        machine.kernel_raw = bytes(program)
        machine.uc.mem_write(machine.kernel_load, bytes(program))
        report = machine.run()
        self.assertEqual(report['serial_text'], '')
        data = bytes(machine.uc.mem_read(0x00100000, 12))
        fr, first, second = struct.unpack('<3I', data)
        self.assertEqual(fr & 0x10, 0)  # RXFE clear: byte available
        self.assertEqual(first, ord('A'))
        self.assertEqual(second, ord('B'))

    def test_empty_rx_sets_rxfe(self):
        import struct
        machine = self.make_machine(0xF2000000, b'')
        program = bytearray(machine.kernel_raw)
        words = [0xE59F0018, 0xE5902018, 0xE59F3014, 0xE5832000, 0xEAFFFFFE]
        struct.pack_into('<5I', program, 0x00, *words)
        struct.pack_into('<2I', program, 0x20, 0xF2000000, 0x00100000)
        machine.kernel_raw = bytes(program)
        machine.uc.mem_write(machine.kernel_load, bytes(program))
        machine.run()
        fr = struct.unpack('<I', machine.uc.mem_read(0x00100000, 4))[0]
        self.assertTrue(fr & 0x10)


if __name__ == '__main__':
    unittest.main()
