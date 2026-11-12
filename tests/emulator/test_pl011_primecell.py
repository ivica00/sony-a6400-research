"""PL011 PrimeCell identification register tests (E0424)."""
import struct
import unittest

from unicorn.arm_const import UC_ARM_REG_R2, UC_ARM_REG_R3

from src.a6400.execution.arm_atags import build_atags
from src.a6400.execution.unicorn_machine import UnicornMachine

MACHINE_ID = 0x0DA9
PERIPHID = [0x11, 0x10, 0x14, 0x00]
PCELLID = [0x0D, 0xF0, 0x05, 0xB1]


def id_read_program(uart_base=0xF2000000, storage=0x00100000):
    image = bytearray(0x100)
    words = [
        0xE321F0D3,  # msr cpsr_c,#0xd3
        0xE59F0054,  # 0x04 ldr r0,[pc,#0x54] -> 0x60 uart base
        0xE59F3054,  # 0x08 ldr r3,[pc,#0x54] -> 0x64 storage
    ]
    # ldr r2,[r0,#imm] ; str r2,[r3,#imm] for +0xFE0..+0xFFC
    for index in range(8):
        offset = 0xFE0 + index * 4
        words.append(0xE5902000 | offset)      # ldr r2,[r0,#offset]
        words.append(0xE5832000 | offset)      # str r2,[r3,#offset]
    words.append(0xEAFFFFFE)                   # b .
    for index, word in enumerate(words):
        struct.pack_into('<I', image, index * 4, word)
    struct.pack_into('<2I', image, 0x60, uart_base, storage)
    return bytes(image)


class PrimeCellIdTests(unittest.TestCase):
    def test_pl011_identification_registers(self):
        machine = UnicornMachine(id_read_program(), b'\x00' * 64,
                                 build_atags('console=ttyAM0', [(0, 0x40000000)]),
                                 machine_id=MACHINE_ID, instruction_limit=200,
                                 exclusive_patch=False, data_abort_delivery=False)
        machine.run()
        data = bytes(machine.uc.mem_read(0x00100000 + 0xFE0, 0x20))
        values = struct.unpack('<8I', data)
        self.assertEqual(list(values[:4]), PERIPHID)
        self.assertEqual(list(values[4:]), PCELLID)
        self.assertEqual(int.from_bytes(b''.join(
            bytes([v]) for v in values[:4]), 'little'), 0x00141011)


if __name__ == '__main__':
    unittest.main()
