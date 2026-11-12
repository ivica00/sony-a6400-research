"""CRCDC clock-block model test (E0423)."""
import struct
import unittest

from src.a6400.execution.arm_atags import build_atags
from src.a6400.execution.unicorn_machine import CRCDC_BASE, UnicornMachine

MACHINE_ID = 0x0DA9


def crcdc_program():
    image = bytearray(0x100)
    words = [
        0xE321F0D3,  # msr cpsr_c,#0xd3
        0xE59F0018,  # ldr r0,[pc,#0x18] -> 0x24 base
        0xE3A01001,  # mov r1,#1
        0xE5801030,  # str r1,[r0,#0x30]  start CRCDC update
        0xE5902030,  # ldr r2,[r0,#0x30]  poll status
        0xE59F300C,  # ldr r3,[pc,#0x0c] -> 0x28 storage
        0xE5832000,  # str r2,[r3]
        0xEAFFFFFE,  # b .
    ]
    for index, word in enumerate(words):
        struct.pack_into('<I', image, index * 4, word)
    struct.pack_into('<2I', image, 0x24, CRCDC_BASE, 0x00100000)
    return bytes(image)


class CrcdcModelTests(unittest.TestCase):
    def test_status_reads_ready_after_control_write(self):
        machine = UnicornMachine(crcdc_program(), b'\x00' * 64,
                                 build_atags('console=ttyAM0', [(0, 0x40000000)]),
                                 machine_id=MACHINE_ID, instruction_limit=200,
                                 exclusive_patch=False, data_abort_delivery=False)
        machine.run()
        status = struct.unpack('<I', machine.uc.mem_read(0x00100000, 4))[0]
        self.assertEqual(status & 1, 0)  # update_crdm exits its poll loop
        self.assertEqual(machine._crcdc_regs.get(0x30, None), 1)


if __name__ == '__main__':
    unittest.main()
