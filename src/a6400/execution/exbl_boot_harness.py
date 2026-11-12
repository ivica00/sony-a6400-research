"""Unicorn early-boot harness for the nflashaB0 EXBL loader (read-only, offline).

Loads the EXBL segments from the hash-checked boot-area dump at their recorded
load addresses and executes the loader entry (ARM reset vector at
``0xFE047000`` on the observed image) with hard bounds.  Two explicit policies:

* ``stop`` (default): the first modelled-impossible access stops execution and
  is reported.  Any MMIO access, any unmapped access and any access outside the
  mapped regions end the trace; nothing is fabricated.
* ``observe-zero`` (opt-in, explicitly labelled): the 0xF0000000..0xFFFFFFFF
  observation windows are mapped as zero-filled RAM before execution so the
  loader can progress through register polling; every MMIO read/write is
  recorded and reported as *unmodelled observation*, never as hardware
  correctness.  This is how the loader's register map is collected, not a
  claim that the device works.

The harness also watches the boot-parameter window (default
``0x00103000..0x00104000``, the third value of nflasha1 ``boot/loadaddr.txt``)
and reports any reads/writes there.  SRAM is mapped at ``0xFE000000..0xFE100000``
because the observed loader image ends at ``0xFE06C000`` and the reset vector
loads its stack from a literal ``0xFE0F0000``; that window is an inferred SRAM
model, not a measured RAM map.
"""
from __future__ import annotations

from collections import Counter

from unicorn import (UC_ARCH_ARM, UC_HOOK_MEM_READ, UC_HOOK_MEM_UNMAPPED,
                     UC_HOOK_MEM_WRITE, UC_MODE_ARM, Uc)
from unicorn.arm_const import UC_ARM_REG_CPSR, UC_ARM_REG_PC, UC_ARM_REG_SP

MMIO_POLICIES = ('stop', 'observe-zero')
DEFAULT_MMIO_RANGES = ((0xF0000000, 0xFDFFFFFF), (0xFE100000, 0xFFFFFFFF))
DEFAULT_SRAM_WINDOW = (0xFE000000, 0xFE100000)
DEFAULT_LOW_RAM = (0x00000000, 0x01000000)
DEFAULT_BOOT_PARAM = (0x00103000, 0x00104000)
PAGE = 0x1000


def _overlaps(first, second) -> bool:
    return first[0] < second[1] and second[0] < first[1]


class ExblBootHarness:
    """Bounded, instrumented Unicorn run of the EXBL loader."""

    def __init__(self, exbl, *, load_base: int | None = None,
                 sram_window: tuple[int, int] = DEFAULT_SRAM_WINDOW,
                 low_ram: tuple[int, int] | None = DEFAULT_LOW_RAM,
                 mmio_ranges: tuple[tuple[int, int], ...] = DEFAULT_MMIO_RANGES,
                 boot_param_window: tuple[int, int] = DEFAULT_BOOT_PARAM,
                 mmio_policy: str = 'stop',
                 mmio_read_stubs: dict[int, int] | None = None,
                 mmio_counter_stubs: dict[int, int] | None = None,
                 uart_base: int = 0xF2000000,
                 instruction_limit: int = 2_000_000,
                 count_instructions: bool = False,
                 sample_interval: int = 100_000,
                 event_limit: int = 256):
        if mmio_policy not in MMIO_POLICIES:
            raise ValueError(f'unknown MMIO policy {mmio_policy!r}')
        if not 0 < instruction_limit <= 50_000_000:
            raise ValueError('instruction limit outside the supported range')
        if event_limit <= 0:
            raise ValueError('positive event limit required')
        self.exbl = exbl
        self.mmio_policy = mmio_policy
        self.mmio_read_stubs = dict(mmio_read_stubs or {})
        self.mmio_counter_stubs = dict(mmio_counter_stubs or {})
        self._counter_values = {address: 0 for address in self.mmio_counter_stubs}
        self.uart_base = uart_base
        self.instruction_limit = instruction_limit
        self.count_instructions = count_instructions
        self.sample_interval = sample_interval
        self.event_limit = event_limit
        self.load_base = exbl.load_base if load_base is None else load_base
        self.sram_window = sram_window
        self.low_ram = low_ram
        self.mmio_ranges = tuple(mmio_ranges)
        self.boot_param_window = boot_param_window
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self._mapped: list[list[int]] = []
        self._events = {'mmio_reads': [], 'mmio_writes': [], 'boot_param_reads': [],
                        'boot_param_writes': [], 'unmapped': []}
        self._counters = {'mmio_reads': 0, 'mmio_writes': 0, 'boot_param_reads': 0,
                          'boot_param_writes': 0, 'instructions': 0}
        self._mmio_map: dict[int, dict] = {}
        self.stub_hits = Counter()
        self.serial = bytearray()
        self._pc_samples = Counter()
        self.stop_reason = None
        self.stop_pc = None
        self.mapped_ranges: list[dict] = []
        self._build()

    # ------------------------------------------------------------------ build
    def _ensure_mapped(self, begin: int, end: int, perms: int, role: str) -> None:
        begin, end = begin & ~(PAGE - 1), (end + PAGE - 1) & ~(PAGE - 1)
        if end <= begin:
            return
        for existing in self._mapped:
            if begin >= existing[0] and end <= existing[1]:
                return  # already covered by a wider window (e.g. SRAM or MMIO window)
            if begin < existing[1] and existing[0] < end:
                raise ValueError(f'{role} mapping 0x{begin:x}..0x{end:x} overlaps '
                                 f'0x{existing[0]:x}..0x{existing[1]:x}')
        self.uc.mem_map(begin, end - begin, perms)
        self._mapped.append([begin, end])
        self.mapped_ranges.append({'start': begin, 'end': end, 'perms': perms, 'role': role})

    def _build(self) -> None:
        if self.low_ram is not None:
            self._ensure_mapped(self.low_ram[0], self.low_ram[1], 7, 'low RAM observation window')
        self._ensure_mapped(self.sram_window[0], self.sram_window[1], 7, 'inferred SRAM window')
        # MMIO windows are always mapped zero-backed so accesses reach the
        # logging hooks; the policy decides whether the first access stops the
        # run (strict, fail-closed) or is observed and execution continues.
        for begin, end in self.mmio_ranges:
            self._ensure_mapped(begin, end + 1, 7,
                                'MMIO zero-backed observation window (unmodelled)')
        for index, record in enumerate(self.exbl.segments):
            begin = (self.load_base + record.flash_offset) & ~(PAGE - 1)
            end = (self.load_base + record.flash_offset + record.size * 512 + PAGE - 1) & ~(PAGE - 1)
            self._ensure_mapped(begin, end, 7, f'EXBL segment {index}')
            self.uc.mem_write(self.load_base + record.flash_offset, self.exbl.segment_data(index))
        self._install_hooks()

    def _record_event(self, bucket: str, value) -> None:
        if len(self._events[bucket]) < self.event_limit:
            self._events[bucket].append(value)

    def _install_hooks(self) -> None:
        def mmio_read(uc, access, address, size, value, user):
            pc = uc.reg_read(UC_ARM_REG_PC)
            self._counters['mmio_reads'] += 1
            stats = self._mmio_map.setdefault(address, {'reads': 0, 'writes': 0,
                                                        'size': size, 'first_pc': pc})
            stats['reads'] += 1
            if address in self.mmio_counter_stubs:
                self._counter_values[address] += self.mmio_counter_stubs[address]
                self.stub_hits[address] += 1
                stub_value = self._counter_values[address] & 0xFFFFFFFF
                stats['stubbed'] = stub_value
                uc.mem_write(address, stub_value.to_bytes(min(size, 4), 'little'))
            elif address in self.mmio_read_stubs:
                self.stub_hits[address] += 1
                stub_value = self.mmio_read_stubs[address] & ((1 << (size * 8)) - 1)
                stats['stubbed'] = stub_value
                uc.mem_write(address, stub_value.to_bytes(size, 'little'))
            self._record_event('mmio_reads', {'pc': pc, 'address': address, 'size': size,
                                              'value': value})
            if self.mmio_policy == 'stop':
                self.stop_reason = 'mmio_access'
                self.stop_pc = pc
                uc.emu_stop()
                return False
            return True

        def mmio_write(uc, access, address, size, value, user):
            pc = uc.reg_read(UC_ARM_REG_PC)
            self._counters['mmio_writes'] += 1
            if self.uart_base <= address < self.uart_base + 0x1000 and \
                    address == self.uart_base:
                self.serial.append(value & 0xFF)
            stats = self._mmio_map.setdefault(address, {'reads': 0, 'writes': 0,
                                                        'size': size, 'first_pc': pc})
            stats['writes'] += 1
            stats['last_value'] = value
            self._record_event('mmio_writes', {'pc': pc, 'address': address,
                                               'size': size, 'value': value & 0xFFFFFFFF})
            if self.mmio_policy == 'stop':
                self.stop_reason = 'mmio_access'
                self.stop_pc = pc
                uc.emu_stop()
                return False
            return True

        def boot_read(uc, access, address, size, value, user):
            self._counters['boot_param_reads'] += 1
            self._record_event('boot_param_reads', {
                'pc': uc.reg_read(UC_ARM_REG_PC), 'address': address,
                'size': size, 'value': value})
            return True

        def boot_write(uc, access, address, size, value, user):
            self._counters['boot_param_writes'] += 1
            self._record_event('boot_param_writes', {
                'pc': uc.reg_read(UC_ARM_REG_PC), 'address': address,
                'size': size, 'value': value & 0xFFFFFFFF})
            return True

        def unmapped(uc, access, address, size, value, user):
            self.stop_reason = 'unmapped_access'
            self.stop_pc = uc.reg_read(UC_ARM_REG_PC)
            self._record_event('unmapped', {'pc': self.stop_pc, 'address': address,
                                            'size': size, 'access': access})
            uc.emu_stop()
            return False

        for begin, end in self.mmio_ranges:
            self.uc.hook_add(UC_HOOK_MEM_READ, mmio_read, begin=begin, end=end)
            self.uc.hook_add(UC_HOOK_MEM_WRITE, mmio_write, begin=begin, end=end)
        self.uc.hook_add(UC_HOOK_MEM_READ, boot_read,
                         begin=self.boot_param_window[0], end=self.boot_param_window[1] - 1)
        self.uc.hook_add(UC_HOOK_MEM_WRITE, boot_write,
                         begin=self.boot_param_window[0], end=self.boot_param_window[1] - 1)
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, unmapped)
        if self.count_instructions:
            from unicorn import UC_HOOK_CODE

            def code(uc, address, size, user):
                self._counters['instructions'] += 1

            self.uc.hook_add(UC_HOOK_CODE, code)

    # -------------------------------------------------------------------- run
    def run(self) -> dict:
        if not self.exbl.entry:
            raise ValueError('EXBL container has no entry address')
        self.stop_reason = None
        self.stop_pc = None
        self.stop_error = None
        executed = 0
        try:
            if self.count_instructions:
                self.uc.emu_start(self.exbl.entry, 0, count=self.instruction_limit)
                executed = self._counters['instructions']
            else:
                remaining = self.instruction_limit
                while remaining > 0:
                    chunk = min(self.sample_interval, remaining)
                    if not executed:
                        start = self.exbl.entry
                    else:
                        pc_now = self.uc.reg_read(UC_ARM_REG_PC)
                        thumb = self.uc.reg_read(UC_ARM_REG_CPSR) & 0x20
                        start = pc_now | (1 if thumb else 0)
                    self.uc.emu_start(start, 0, count=chunk)
                    executed += chunk
                    remaining -= chunk
                    self._pc_samples[self.uc.reg_read(UC_ARM_REG_PC)] += 1
                    if self.stop_reason is not None:
                        break
            if self.stop_reason is None:
                self.stop_reason = 'instruction_limit'
        except Exception as error:  # unicorn.UcError or host error: keep the receipt
            self.stop_error = type(error).__name__ + ': ' + str(error)
            if self.stop_reason is None:
                self.stop_reason = 'unicorn_error'
        self._counters['instructions'] = executed
        return self.report()

    def report(self) -> dict:
        mmio_addresses = [
            {'address': address, 'reads': stats['reads'], 'writes': stats['writes'],
             'size': stats['size'], 'first_pc': stats['first_pc'],
             **({'last_value': stats['last_value']} if 'last_value' in stats else {})}
            for address, stats in sorted(self._mmio_map.items())]
        return {
            'load_base': self.load_base,
            'entry': self.exbl.entry,
            'mmio_policy': self.mmio_policy,
            'instruction_limit': self.instruction_limit,
            'stop_reason': self.stop_reason,
            'stop_pc': self.stop_pc,
            'stop_error': self.stop_error,
            'counters': dict(self._counters),
            'mmio_address_count': len(mmio_addresses),
            'mmio_addresses': mmio_addresses[:512],
            'events': {name: list(values) for name, values in self._events.items()},
            'mapped_ranges': self.mapped_ranges,
            'boot_param_window': self.boot_param_window,
            'serial_bytes': len(self.serial),
            'serial_text': bytes(self.serial).decode('latin1', errors='replace'),
            'stub_hits': {f'0x{address:08x}': count
                          for address, count in self.stub_hits.items()},
            'hotspots': [{'pc': address, 'samples': count}
                         for address, count in self._pc_samples.most_common(12)],
            'boot_contract_references': self.exbl.boot_contract_references(),
        }
