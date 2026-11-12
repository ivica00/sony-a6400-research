"""Minimal Unicorn machine runner checks (E0416)."""
import struct
import unittest

from src.a6400.execution.arm_atags import build_atags
from src.a6400.execution.unicorn_machine import UnicornMachine

MACHINE_ID = 0x0DA9


def synthetic_kernel_program():
    """A tiny 'kernel': reads PL011 FR, writes 'AB' to DR, then faults on purpose."""
    image = bytearray(0x200)
    words = [
        0xE321F0D3,  # msr cpsr_c, #0xd3  (required ARM kernel head word)
        0xE59F0028,  # ldr r0, [pc, #0x28] -> 0x34 UART0
        0xE5904018,  # ldr r4, [r0, #0x18]  FR read (MMIO hook)
        0xE59F1024,  # ldr r1, [pc, #0x24] -> 0x38 'A'
        0xE5801000,  # str r1, [r0]
        0xE59F2020,  # ldr r2, [pc, #0x20] -> 0x3c 'B'
        0xE5802000,  # str r2, [r0]
        0xE59F301C,  # ldr r3, [pc, #0x1c] -> 0x40 unmapped address
        0xE5831000,  # str r1, [r3]        (faults -> run stops)
        0xEAFFFFFE,  # b .
    ]
    for index, word in enumerate(words):
        struct.pack_into('<I', image, index * 4, word)
    struct.pack_into('<4I', image, 0x34, 0xF2000000, 0x41, 0x42, 0xDEAD0000)
    return bytes(image)


class UnicornMachineTests(unittest.TestCase):
    def make_machine(self, **kwargs):
        return UnicornMachine(
            synthetic_kernel_program(), b'\x00' * 64,
            build_atags('console=ttyAM0', [(0, 0x40000000)]),
            machine_id=MACHINE_ID, instruction_limit=1000, data_abort_delivery=False, **kwargs)

    def test_uart_serial_capture_and_unmapped_stop(self):
        report = self.make_machine().run()
        self.assertEqual(report['serial_text'], 'AB')
        self.assertEqual(report['stop_reason'], 'unmapped_access')
        self.assertEqual(len(report['unmapped']), 1)
        self.assertEqual(report['unmapped'][0]['address'], '0xdead0000')
        self.assertEqual(report['machine_id'], MACHINE_ID)
        # The PL011 FR register is pre-seeded and read once by the program.
        self.assertEqual(report['stub_hits'], {})

    def test_labelled_mmio_read_stub_is_reported(self):
        machine = self.make_machine(mmio_read_stubs={0xF2000018: 0x90})
        report = machine.run()
        self.assertEqual(report['serial_text'], 'AB')
        self.assertIn('0xf2000018', report['stub_hits'])
        self.assertGreater(report['stub_hits']['0xf2000018'], 0)

    def test_kernel_head_word_is_required(self):
        with self.assertRaises(Exception):
            UnicornMachine(b'\x00' * 0x100, b'\x00', b'', machine_id=MACHINE_ID)


if __name__ == '__main__':
    unittest.main()
