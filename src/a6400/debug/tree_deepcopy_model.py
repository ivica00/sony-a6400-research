"""Offline Unicorn execution model for the E0407b1 tree building block.

The model executes the compiled ARMv7 object produced from
``tools/native_camera/a6400_dbg_tree.c`` (test build, ``-DA6400_TREE_TEST``).
The test build binds only the service layer to ``tree_*`` stubs; the tree,
append, validate, patch, quiesce, swap and free logic are the same compiled
instructions that the kernel module contains.

Two independent machines are used:

* the compiled tree code at 0x10010000 (payload extracted from
  ``artifacts/native/e0407b1-tree/test/tree_test.elf``), and
* the original Sony serializer bytes from the preserved ``vmlinux.bin``
  (``make_device_desc``/``make_config_desc``/``make_string_desc``), executed
  over the module-owned tree exactly as the gadgetcore code would.

No hardware, no kernel: allocations, probe reads/writes, logging and the two
teardown helpers are host stubs with accounting.  The fixture is a synthetic
two-record Mass Storage + vendor tree matching the documented layouts.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KERNEL = (ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/'
          'dev/nflasha3_unpacked/vmlinux.bin')
KERNEL_SHA = '12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707'
PAYLOAD_PATH = ROOT / 'artifacts/tests/e0407b1-tree/tree_test_payload.json'
SOURCE = ROOT / 'tools/native_camera/a6400_dbg_tree.c'
TEST_ELF = ROOT / 'artifacts/native/e0407b1-tree/test/tree_test.elf'

KERNEL_BASE = 0x60108000
KERNEL_MEMCPY = 0x60258B80
MAKE_DEVICE_DESC = 0x602BB988
MAKE_CONFIG_DESC = 0x602BBC54
MAKE_STRING_DESC = 0x602BC0CC

SERVICE_BASE = 0x10030000
SERVICE_STRIDE = 0x10
TRAP = 0x10030F00

GC = 0x60000000
GADGET = 0x60000100
EP0 = 0x60000200
EP0_DESC = 0x60000280
OPS = 0x60000300
ROOT = 0x60001000
CFG = {0x00: 0x60002000, 0x10: 0x60002100, 0x20: 0x60002200}
IFACE = {0x00: 0x60002300, 0x10: 0x60002320, 0x20: 0x60002340}
ALT = {0x00: 0x60002400, 0x10: 0x60002420, 0x20: 0x60002440}
ENDPOINT = {0x00: 0x60002500, 0x10: 0x60002540, 0x20: 0x60002580}
COMPANION = 0x60004000
LANG = 0x60003000
STRINGS = 0x60003010
STRING_DATA = 0x60003040
SERIAL = 0x60003060
BLOB4 = 0x60003070
BLOB8 = 0x60003080
BLOB16 = 0x60003090
SETUP = 0x60080000
OUT = 0x60080100
SERIAL_FAIL_OUT = 0x60080200
ALLOC_START = 0x60010000
ALLOC_END = 0x60080000
STACK_TOP = 0x600F0000
ARENA_BASE = 0x60000000
ARENA_SIZE = 0x00100000
GC_PAGE = 0x6051B000

OS_STRING_ADDR = 0x604E5130
OS_STRING_STOCK = bytes.fromhex('12034d005300460054003100300030003000')
OS_STRING_OS20 = bytes.fromhex('12034d005300460054003200300000000200')
OS_CRC_STOCK = 0x6E795789
OS_CRC_OS20 = 0xFDADFCBA
GC_SLOT = GC  # fixture supplies the gadgetcore global slot value at GC_SLOT_CELL
GC_SLOT_CELL = 0x6051B17C

KERNEL_DEBUG = struct.pack('<HHH', 0x0200, 0x0000, 0x0000)  # unused sentinel


class TreeModelError(RuntimeError):
    pass


def crc32(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 & -(crc & 1))
    return (~crc) & 0xFFFFFFFF


_KERNEL_RAW = None
_PAYLOAD = None


def kernel_bytes() -> bytes:
    global _KERNEL_RAW
    if _KERNEL_RAW is None:
        raw = KERNEL.read_bytes()
        if hashlib.sha256(raw).hexdigest() != KERNEL_SHA:
            raise TreeModelError('kernel image identity mismatch')
        _KERNEL_RAW = raw
    return _KERNEL_RAW


def payload() -> dict:
    global _PAYLOAD
    if _PAYLOAD is None:
        data = json.loads(PAYLOAD_PATH.read_text(encoding='utf-8'))
        if data.get('schema') != 'e0407b1-tree-test-payload-v1':
            raise TreeModelError('unexpected tree test payload schema')
        _PAYLOAD = data
    return _PAYLOAD


def source_sha256() -> str:
    return hashlib.sha256(SOURCE.read_bytes()).hexdigest()


class TreeEngine:
    def __init__(self):
        import unicorn
        from unicorn import arm_const
        self.unicorn = unicorn
        self.arm = arm_const
        self.uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.payload = payload()
        self.symbols = dict(self.payload['symbols'])
        self._map_payload()
        self._map_services()
        self.uc.mem_map(ARENA_BASE, ARENA_SIZE)
        self._map_kernel()
        self.uc.mem_map(GC_PAGE, 0x1000)
        self.uc.mem_write(TRAP, b'\x1e\xff\x2f\xe1')  # bx lr
        self.uc.hook_add(unicorn.UC_HOOK_CODE, self._hook)
        self.reset()

    # -- memory ------------------------------------------------------
    def _map_payload(self):
        self._section_ranges = []
        for section in self.payload['sections']:
            addr = section['addr']
            size = section['size']
            start = addr & ~0xFFF
            end = (addr + size + 0xFFF) & ~0xFFF
            self.uc.mem_map(start, max(0x1000, end - start))
            if section['data']:
                self.uc.mem_write(addr, bytes.fromhex(section['data']))
            self._section_ranges.append((section['name'], addr, size))

    def _map_services(self):
        start = SERVICE_BASE & ~0xFFF
        self.uc.mem_map(start, 0x2000)
        for index in range(0x10):
            self.uc.mem_write(SERVICE_BASE + index * SERVICE_STRIDE,
                              b'\x1e\xff\x2f\xe1')

    def _map_kernel(self):
        if not KERNEL.is_file():
            raise TreeModelError('preserved kernel image is missing')
        raw = kernel_bytes()
        size = (len(raw) + 0xFFF) & ~0xFFF
        self.uc.mem_map(KERNEL_BASE, size)
        self.uc.mem_write(KERNEL_BASE, raw)

    def _service_for(self, address: int):
        if SERVICE_BASE <= address < SERVICE_BASE + 0x100:
            offset = (address - SERVICE_BASE) // SERVICE_STRIDE
            return offset
        return None

    def _hook(self, uc, address, size, user_data):
        try:
            if address == KERNEL_MEMCPY:
                dst = self.reg('R0')
                src = self.reg('R1')
                count = self.reg('R2')
                self.uc.mem_write(dst, bytes(self.uc.mem_read(src, count)))
                self.uc.reg_write(self.arm.UC_ARM_REG_R0, dst)
                self.uc.reg_write(self.arm.UC_ARM_REG_PC,
                                  self.uc.reg_read(self.arm.UC_ARM_REG_LR))
                return
            if address == TRAP:
                self.uc.emu_stop()
                return
            service = self._service_for(address)
            if service is None:
                return
            self._service(service)
        except TreeModelError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise TreeModelError(f'stub fault at {address:08x}: {exc}') from exc

    def _service(self, index):
        handler = {
            0x0: self._stub_alloc,
            0x1: self._stub_kfree,
            0x2: self._stub_memcpy,
            0x3: self._stub_memset,
            0x4: self._stub_probe_read,
            0x5: self._stub_probe_write,
            0x6: self._stub_log,
            0x7: self._stub_pullup,
            0x8: self._stub_stop_disconnect,
            0x9: self._stub_gcw_stop,
        }[index]
        result = handler()
        self.uc.reg_write(self.arm.UC_ARM_REG_R0, result & 0xFFFFFFFF)
        self.uc.reg_write(self.arm.UC_ARM_REG_PC,
                          self.uc.reg_read(self.arm.UC_ARM_REG_LR))

    # -- stubs -------------------------------------------------------
    def _stub_alloc(self):
        size = self.reg('R0')
        self.alloc_attempts += 1
        if self.fail_at_alloc is not None and self.alloc_attempts == self.fail_at_alloc:
            self.failed_alloc_size = size
            return 0
        if size == 0 or size > 0x10000:
            self.invalid_alloc_sizes.append(size)
            return 0
        pointer = self.alloc_next
        span = max(4, (size + 3) & ~3)
        if pointer + span > ALLOC_END:
            self.arena_exhausted = True
            return 0
        self.uc.mem_write(pointer, b'\xA5' * span)
        self.alloc_next = (pointer + span + 7) & ~7
        self.allocs[pointer] = size
        self.alloc_order.append((pointer, size))
        return pointer

    def _stub_kfree(self):
        pointer = self.reg('R0')
        if pointer == 0:
            self.zero_frees += 1
            return 0
        if pointer in self.freed:
            self.double_frees.append(pointer)
            return 0
        if pointer not in self.allocs:
            self.unknown_frees.append(pointer)
            return 0
        self.frees.append(pointer)
        self.freed.add(pointer)
        del self.allocs[pointer]
        return 0

    def _stub_memcpy(self):
        dst = self.reg('R0')
        src = self.reg('R1')
        count = self.reg('R2')
        self.uc.mem_write(dst, bytes(self.uc.mem_read(src, count)))
        return dst

    def _stub_memset(self):
        dst = self.reg('R0')
        value = self.reg('R1') & 0xFF
        count = self.reg('R2')
        self.uc.mem_write(dst, bytes([value]) * count)
        return dst

    def _stub_probe_read(self):
        dst = self.reg('R0')
        src = self.reg('R1')
        count = self.reg('R2')
        try:
            data = bytes(self.uc.mem_read(src, count))
        except Exception:
            self.probe_read_faults.append((src, count))
            return -14
        self.uc.mem_write(dst, data)
        return 0

    def _stub_probe_write(self):
        dst = self.reg('R0')
        src = self.reg('R1')
        count = self.reg('R2')
        self.write_attempts += 1
        if self.fail_at_write is not None and self.write_attempts == self.fail_at_write:
            self.failed_write_size = count
            return -14
        try:
            data = bytes(self.uc.mem_read(src, count))
            self.uc.mem_write(dst, data)
        except Exception:
            self.probe_write_faults.append((dst, count))
            return -14
        return 0

    def _stub_log(self):
        fmt = self.reg('R0')
        try:
            raw = bytes(self.uc.mem_read(fmt, 512)).split(b'\0', 1)[0]
            self.logs.append(raw.decode('latin1'))
        except Exception:
            self.logs.append('<unreadable format>')
        return 0

    def _stub_pullup(self):
        gadget = self.reg('R0')
        on = self.reg('R1')
        self.service_calls.append(('pullup', gadget, on))
        return self.pullup_result

    def _stub_stop_disconnect(self):
        gc = self.reg('R0')
        self.service_calls.append(('stop_disconnect', gc))
        if self.stop_disconnect_clears_config:
            self.write_u8(gc + 0x74, 0)
        return 0

    def _stub_gcw_stop(self):
        self.service_calls.append(('gcw_stop',))
        return 0

    # -- accessors ---------------------------------------------------
    def reg(self, name):
        return self.uc.reg_read(getattr(self.arm, f'UC_ARM_REG_{name}'))

    def read(self, address, length):
        return bytes(self.uc.mem_read(address, length))

    def read_u8(self, address):
        return self.read(address, 1)[0]

    def read_u16(self, address):
        return struct.unpack('<H', self.read(address, 2))[0]

    def read_u32(self, address):
        return struct.unpack('<I', self.read(address, 4))[0]

    def write(self, address, data):
        self.uc.mem_write(address, bytes(data))

    def write_u8(self, address, value):
        self.write(address, bytes([value & 0xFF]))

    def write_u16(self, address, value):
        self.write(address, struct.pack('<H', value & 0xFFFF))

    def write_u32(self, address, value):
        self.write(address, struct.pack('<I', value & 0xFFFFFFFF))

    # -- fixture -----------------------------------------------------
    def reset(self, speed=3, started=0, configured=0, mode=0, os_string=None,
              root_override=None, bcdusb=None):
        # zero the module .bss (g_state)
        for name, addr, size in self._section_ranges:
            if name == '.bss':
                self.write(addr, b'\0' * size)
        self.speed = speed
        self.allocs = {}
        self.alloc_order = []
        self.frees = []
        self.freed = set()
        self.double_frees = []
        self.unknown_frees = []
        self.zero_frees = 0
        self.invalid_alloc_sizes = []
        self.arena_exhausted = False
        self.alloc_attempts = 0
        self.alloc_next = ALLOC_START
        self.fail_at_alloc = None
        self.failed_alloc_size = None
        self.write_attempts = 0
        self.fail_at_write = None
        self.failed_write_size = None
        self.probe_read_faults = []
        self.probe_write_faults = []
        self.logs = []
        self.service_calls = []
        self.pullup_result = 0
        self.stop_disconnect_clears_config = True
        self._build_fixture(speed=speed, started=started, configured=configured,
                            mode=mode, root_override=root_override, bcdusb=bcdusb)
        self.write(OS_STRING_ADDR, os_string if os_string is not None else OS_STRING_STOCK)

    def _build_fixture(self, speed=3, started=0, configured=0, mode=0,
                       root_override=None, bcdusb=None):
        self.write(GC, b'\0' * 0x100)
        self.write(GADGET, b'\0' * 0x40)
        self.write(EP0, b'\0' * 0x40)
        self.write(OPS, b'\0' * 0x40)
        self.write_u32(GC_SLOT_CELL, GC)
        self.write_u32(GC, GADGET)
        self.write_u32(GC + 4, EP0)
        self.write_u32(GC + 0x68, 4 if started else 0)
        self.write_u32(GC + 0x6c, ROOT if root_override is None else root_override)
        self.write_u8(GC + 0x74, configured)
        self.write_u8(GC + 0x84, mode)
        self.write_u32(GADGET + 0x10, OPS)
        self.write_u8(GADGET + 0x20, speed)
        self.write_u16(EP0 + 0x14, 64)
        self.write_u32(EP0 + 0x1c, EP0_DESC)
        self.write_u16(EP0_DESC + 4, 512)
        self.write_u32(OPS + 0x14, self.symbols['tree_pullup'])

        # source root (88 bytes)
        self.write(ROOT, b'\0' * 0x58)
        identities = {0x00: (0x0200, 0x00, 0x00, 0x00),
                      0x10: (0x0110, 0xEF, 0x02, 0x01),
                      0x20: (0x0320, 0xEF, 0x02, 0x01)}
        for slot, (bcd, cls, sub, proto) in identities.items():
            self.write_u16(ROOT + slot, bcd if bcdusb is None or slot != 0 else bcdusb)
            self.write(ROOT + slot + 2, bytes([cls, sub, proto]))
            self.write_u8(ROOT + slot + 5, 1)
            self.write_u32(ROOT + slot + 8, CFG[slot])
        self.write_u16(ROOT + 0x30, 0x054C)
        self.write_u16(ROOT + 0x32, 0x0CAA)
        self.write_u16(ROOT + 0x34, 0x0100)
        self.write_u8(ROOT + 0x37, 1)
        self.write_u8(ROOT + 0x38, 2)
        self.write_u8(ROOT + 0x39, 3)
        self.write_u8(ROOT + 0x3a, 1)
        self.write_u32(ROOT + 0x3c, LANG)
        self.write_u16(ROOT + 0x40, 4)
        self.write_u32(ROOT + 0x44, SERIAL)
        self.write_u32(ROOT + 0x48, 0)
        self.write_u32(ROOT + 0x4c, BLOB4)
        self.write_u32(ROOT + 0x50, BLOB8)
        self.write_u32(ROOT + 0x54, BLOB16)

        for slot in (0x00, 0x10, 0x20):
            self._build_config(slot)
        self.write(SERIAL, b'S\x00N\x00')
        self.write(BLOB4, b'\x11' * 4)
        self.write(BLOB8, b'\x22' * 8)
        self.write(BLOB16, b'\x33' * 16)
        self.write(LANG, struct.pack('<HBBI', 0x0409, 3, 0, STRINGS))
        for index in range(3):
            pointer = STRING_DATA + index * 4
            self.write(STRINGS + index * 8,
                       struct.pack('<BBHI', index + 1, 4, 0, pointer))
            self.write(pointer, bytes([0x41 + index, 0, 0x42 + index, 0]))

    def _build_config(self, slot):
        cfg = CFG[slot]
        self.write(cfg, b'\0' * 0x18)
        self.write(cfg, bytes([0, 1, 1, 0]))
        self.write_u32(cfg + 4, IFACE[slot])
        self.write(cfg + 8, bytes([0, 0x80, 0xFA, 0]))
        self.write_u32(cfg + 0x0c, 0)
        self.write_u8(cfg + 0x10, 0)
        self.write_u32(cfg + 0x14, 0)

        self.write(IFACE[slot], struct.pack('<BBHI', 0, 1, 0, ALT[slot]))
        self.write(ALT[slot], b'\0' * 0x14)
        self.write(ALT[slot], bytes([0, 2]))
        self.write_u32(ALT[slot] + 4, ENDPOINT[slot])
        self.write(ALT[slot] + 8, bytes([0x08, 0x06, 0x50, 0]))
        self.write_u32(ALT[slot] + 0x0c, 0)
        self.write_u32(ALT[slot] + 0x10, 0)

        first = ENDPOINT[slot]
        second = ENDPOINT[slot] + 0x14
        for pointer, address in ((first, 0x81), (second, 0x02)):
            self.write(pointer, b'\0' * 0x14)
            self.write(pointer, bytes([address, 0x02]))
            self.write_u16(pointer + 2, 0x0200)
            self.write_u8(pointer + 4, 0)
            self.write_u32(pointer + 8, 0)
            self.write_u32(pointer + 0x0c, 0)
            self.write_u32(pointer + 0x10, 0)
        if slot == 0x20:
            self.write_u32(first + 0x10, COMPANION)
            self.write(COMPANION, b'\x00' * 4)

    # -- execution ---------------------------------------------------
    def call(self, name, *args, stack_words=()):
        address = self.symbols[name]
        registers = (self.arm.UC_ARM_REG_R0, self.arm.UC_ARM_REG_R1,
                     self.arm.UC_ARM_REG_R2, self.arm.UC_ARM_REG_R3)
        for value, register in zip(args, registers):
            self.uc.reg_write(register, value)
        sp = STACK_TOP - 0x200
        if stack_words:
            self.write(sp, b''.join(struct.pack('<I', word) for word in stack_words))
        self.uc.reg_write(self.arm.UC_ARM_REG_SP, sp)
        self.uc.reg_write(self.arm.UC_ARM_REG_LR, TRAP)
        self.uc.emu_start(address, TRAP, count=2_000_000)
        if self.reg('PC') != TRAP:
            raise TreeModelError(f'no return from {name} (pc={self.reg("PC"):08x})')
        return self.reg('R0')

    def prepare(self, speed=3, started=0, configured=0, mode=0,
                fail_at_alloc=None, fail_at_write=None, pullup_result=0,
                stop_disconnect_clears_config=True, os_string=None,
                root_override=None, bcdusb=None):
        """Reset the machine/fixture and arm fault injection, without running."""
        self.reset(speed=speed, started=started, configured=configured, mode=mode,
                   os_string=os_string, root_override=root_override, bcdusb=bcdusb)
        self.fail_at_alloc = fail_at_alloc
        self.fail_at_write = fail_at_write
        self.pullup_result = pullup_result
        self.stop_disconnect_clears_config = stop_disconnect_clears_config

    def start(self):
        """Run the compiled init_module over the prepared fixture."""
        return self._signed(self.call('init_module'))

    def run_init(self, speed=3, started=0, configured=0, mode=0,
                 fail_at_alloc=None, fail_at_write=None, pullup_result=0,
                 stop_disconnect_clears_config=True, os_string=None,
                 root_override=None, bcdusb=None):
        self.prepare(speed=speed, started=started, configured=configured, mode=mode,
                     fail_at_alloc=fail_at_alloc, fail_at_write=fail_at_write,
                     pullup_result=pullup_result,
                     stop_disconnect_clears_config=stop_disconnect_clears_config,
                     os_string=os_string, root_override=root_override, bcdusb=bcdusb)
        return self.start()

    def run_cleanup(self):
        return self._signed(self.call('cleanup_module'))

    @staticmethod
    def _signed(value):
        return value - 0x100000000 if value & 0x80000000 else value

    # -- inspection --------------------------------------------------
    @property
    def gc(self):
        return self.read_u32(GC_SLOT_CELL)

    @property
    def gadget(self):
        return self.read_u32(self.gc)

    def bss_address(self):
        for name, addr, _size in self._section_ranges:
            if name == '.bss':
                return addr
        raise TreeModelError('test image has no .bss section')

    def state_u32(self, offset):
        return self.read_u32(self.bss_address() + offset)

    def state_u16(self, offset):
        return self.read_u16(self.bss_address() + offset)

    def state_u8(self, offset):
        return self.read_u8(self.bss_address() + offset)

    def installed_root(self):
        return self.read_u32(self.gc + 0x6c)

    def active_record(self):
        return self.installed_root() + (0x20 if self.speed == 5
                                        else 0x00 if self.speed == 3 else 0x10)

    def os_bytes(self):
        return self.read(OS_STRING_ADDR, 18)

    def os_crc(self):
        return crc32(self.os_bytes())

    @property
    def leaks(self):
        return dict(self.allocs)

    @property
    def clean(self):
        return (not self.allocs and not self.double_frees and not self.unknown_frees
                and not self.arena_exhausted and not self.invalid_alloc_sizes)

    # -- tree views --------------------------------------------------
    def tree_view(self, root):
        view = self._root_view(root)
        return view

    def _root_view(self, root):
        root_bytes = self.read(root, 0x58)
        view = {
            'vid': struct.unpack_from('<H', root_bytes, 0x30)[0],
            'pid': struct.unpack_from('<H', root_bytes, 0x32)[0],
            'bcdDevice': struct.unpack_from('<H', root_bytes, 0x34)[0],
            'iMan': root_bytes[0x37], 'iProd': root_bytes[0x38],
            'iSerial': root_bytes[0x39], 'lang_count': root_bytes[0x3a],
            'serial': self.read(struct.unpack_from('<I', root_bytes, 0x44)[0],
                                struct.unpack_from('<H', root_bytes, 0x40)[0])
                      if struct.unpack_from('<H', root_bytes, 0x40)[0] else b'',
            'blobs': [self.read(struct.unpack_from('<I', root_bytes, off)[0], size)
                      for off, size in ((0x4c, 4), (0x50, 8), (0x54, 16))],
            'langs': [], 'records': {},
        }
        lang_count = root_bytes[0x3a]
        lang_array = struct.unpack_from('<I', root_bytes, 0x3c)[0]
        for i in range(lang_count):
            entry = self.read(lang_array + i * 8, 8)
            count = entry[2]
            strings = struct.unpack_from('<I', entry, 4)[0]
            lang = {'langid': struct.unpack_from('<H', entry, 0)[0], 'strings': []}
            for j in range(count):
                rec = self.read(strings + j * 8, 8)
                data_ptr = struct.unpack_from('<I', rec, 4)[0]
                lang['strings'].append({
                    'index': rec[0], 'len': rec[1],
                    'data': self.read(data_ptr, rec[1]) if rec[1] else b'',
                })
            view['langs'].append(lang)
        for slot in (0x00, 0x10, 0x20):
            configs = []
            num = root_bytes[slot + 5]
            array = struct.unpack_from('<I', root_bytes, slot + 8)[0]
            for i in range(num):
                configs.append(self._config_view(array + i * 0x18))
            view['records'][slot] = {
                'bcdusb': struct.unpack_from('<H', root_bytes, slot)[0],
                'class': root_bytes[slot + 2], 'sub': root_bytes[slot + 3],
                'proto': root_bytes[slot + 4], 'numcfg': num,
                'configs': configs,
            }
        return view

    def _config_view(self, cfg):
        raw = self.read(cfg, 0x18)
        count = raw[2]
        array = struct.unpack_from('<I', raw, 4)[0]
        view = {
            'index': raw[0], 'value': raw[1], 'num_ifaces': count,
            'iConfiguration': raw[8], 'bmAttributes': raw[9],
            'bMaxPower': raw[0x0a],
            'one_byte_blob': self.read(struct.unpack_from('<I', raw, 0x0c)[0], 1)
                             if struct.unpack_from('<I', raw, 0x0c)[0] else None,
            'six_records': self.read(struct.unpack_from('<I', raw, 0x14)[0], raw[0x10] * 6)
                            if struct.unpack_from('<I', raw, 0x14)[0] else None,
            'interfaces': [],
        }
        for i in range(count):
            grp = self.read(array + i * 8, 8)
            alt_count = grp[1]
            alt_array = struct.unpack_from('<I', grp, 4)[0]
            iface = {'number': grp[0], 'alts': []}
            for j in range(alt_count):
                iface['alts'].append(self._alt_view(alt_array + j * 0x14))
            view['interfaces'].append(iface)
        return view

    def _alt_view(self, alt):
        raw = self.read(alt, 0x14)
        count = raw[1]
        array = struct.unpack_from('<I', raw, 4)[0]
        view = {
            'alt': raw[0], 'ep_count': count,
            'class': raw[8], 'sub': raw[9], 'proto': raw[10], 'iInterface': raw[11],
            'extra': self.read(struct.unpack_from('<I', raw, 0x10)[0],
                               struct.unpack_from('<I', raw, 0x0c)[0])
                     if struct.unpack_from('<I', raw, 0x0c)[0] else b'',
            'endpoints': [],
        }
        for i in range(count):
            ep = self.read(array + i * 0x14, 0x14)
            view['endpoints'].append({
                'addr': ep[0], 'attr': ep[1],
                'maxpkt': struct.unpack_from('<H', ep, 2)[0], 'interval': ep[4],
                'extra': self.read(struct.unpack_from('<I', ep, 0x0c)[0],
                                   struct.unpack_from('<I', ep, 8)[0])
                         if struct.unpack_from('<I', ep, 8)[0] else b'',
                'companion': self.read(struct.unpack_from('<I', ep, 0x10)[0], 4)
                             if struct.unpack_from('<I', ep, 0x10)[0] else None,
            })
        return view

    def tree_pointers(self, root):
        found = {root}
        root_bytes = self.read(root, 0x58)
        for slot in (0x00, 0x10, 0x20):
            array = struct.unpack_from('<I', root_bytes, slot + 8)[0]
            found.add(array)
            for i in range(root_bytes[slot + 5]):
                cfg = array + i * 0x18
                raw = self.read(cfg, 0x18)
                ifaces = struct.unpack_from('<I', raw, 4)[0]
                found.add(ifaces)
                for j in range(raw[2]):
                    grp = self.read(ifaces + j * 8, 8)
                    alts = struct.unpack_from('<I', grp, 4)[0]
                    found.add(alts)
                    for k in range(grp[1]):
                        alt = self.read(alts + k * 0x14, 0x14)
                        if struct.unpack_from('<I', alt, 4)[0]:
                            eps = struct.unpack_from('<I', alt, 4)[0]
                            found.add(eps)
                            for m in range(alt[1]):
                                ep = self.read(eps + m * 0x14, 0x14)
                                for off in (0x0c, 0x10):
                                    ptr = struct.unpack_from('<I', ep, off)[0]
                                    if ptr:
                                        found.add(ptr)
                        for off in (0x10,):
                            ptr = struct.unpack_from('<I', alt, off)[0]
                            if ptr:
                                found.add(ptr)
                for off in (0x0c, 0x14):
                    ptr = struct.unpack_from('<I', raw, off)[0]
                    if ptr:
                        found.add(ptr)
        for off in (0x3c, 0x44, 0x4c, 0x50, 0x54):
            ptr = struct.unpack_from('<I', root_bytes, off)[0]
            if ptr:
                found.add(ptr)
        lang_array = struct.unpack_from('<I', root_bytes, 0x3c)[0]
        for i in range(root_bytes[0x3a]):
            entry = self.read(lang_array + i * 8, 8)
            strings = struct.unpack_from('<I', entry, 4)[0]
            if strings:
                found.add(strings)
                for j in range(entry[2]):
                    data = struct.unpack_from('<I', self.read(strings + j * 8, 8), 4)[0]
                    if data:
                        found.add(data)
        return found

    # -- original serializer execution -------------------------------
    def run_device_desc(self, setup_value=0x0100, length=18, out=OUT,
                        speed=None):
        if speed is not None:
            self.write_u8(GADGET + 0x20, speed)
        self.write(SETUP, struct.pack('<BBHHH', 0x80, 6, setup_value, 0, length))
        self.write(out, b'\xA5' * 64)
        result = self._signed(self.call_kernel(MAKE_DEVICE_DESC, self.gc, SETUP, out))
        return result, self.read(out, 18)

    def run_config_desc(self, descriptor_type=2, length=255, out=OUT, speed=None):
        if speed is not None:
            self.write_u8(GADGET + 0x20, speed)
        self.write(SETUP, struct.pack('<BBHHH', 0x80, 6, 0x0200, 0, length))
        self.write(out, b'\xA5' * 128)
        result = self._signed(self.call_kernel(MAKE_CONFIG_DESC, self.gc, SETUP,
                                               out, descriptor_type))
        return result, self.read(out, min(length, 128))

    def run_string_desc(self, index=1, language=0x0409, length=255, out=OUT):
        self.write(SETUP, struct.pack('<BBHHH', 0x80, 6, 0x0300 | index,
                                      language, length))
        self.write(out, b'\xA5' * 64)
        result = self._signed(self.call_kernel(MAKE_STRING_DESC, self.gc, SETUP, out))
        return result, self.read(out, 64)

    def call_kernel(self, address, *args):
        registers = (self.arm.UC_ARM_REG_R0, self.arm.UC_ARM_REG_R1,
                     self.arm.UC_ARM_REG_R2, self.arm.UC_ARM_REG_R3)
        for value, register in zip(args, registers):
            self.uc.reg_write(register, value)
        sp = STACK_TOP - 0x1000
        self.uc.reg_write(self.arm.UC_ARM_REG_SP, sp)
        self.uc.reg_write(self.arm.UC_ARM_REG_LR, TRAP)
        self.uc.emu_start(address, TRAP, count=1_000_000)
        if self.reg('PC') != TRAP:
            raise TreeModelError(f'no return from kernel {address:08x}')
        return self.reg('R0')
