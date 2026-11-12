"""Minimal Unicorn ARM machine for the CXD90045 updater boot (offline, E0416).

QEMU is not available on this host (checked during E0416), so the L2 bring-up uses a
small, explicit Unicorn machine model built from observed facts:

* RAM identity-mapped at the observed physical banks ``0x00000000 + 0x40000000`` and
  ``0x80000000 + 0x40000000`` (nflasha1 ``boot/kemco.txt``: ``mem=1G@0`` and
  ``mem=1016M@0x80000000@1``);
* the raw ARM kernel (zImage gzip payload decompressed offline) at ``0x00108000``,
  the cramfs initramfs at ``0x00700000`` and the reconstructed ATAGS at ``0x00103000``
  (nflasha1 ``boot/loadaddr.txt``);
* boot registers r0 = 0, r1 = recovered machine ID (``0x00000DA9``), r2 = ATAGS,
  CPSR = SVC with IRQ/FIQ masked, MMU off (the kernel enables its own page tables,
  which Unicorn translates);
* PL011 UART0 at ``0xF2000000``: writes to DR are captured as the ``ttyAM0`` serial
  log, FR reads report TXFE|RXFE, DR reads are 0; every access is counted;
* MMIO windows are mapped as RAM so accesses reach the hooks; a small explicit
  ``mmio_read_stubs`` table serves *labelled* ready values for registers whose
  hardware semantics are not modelled (all hits are reported);
* any unmapped access stops the run with PC/address/registers — never silently
  replaced by zero.

This is a partial machine model: it is not a booted camera, not a timing model and
every stubbed register is listed in the run report.
"""
from __future__ import annotations

import json
import struct
from collections import Counter

from unicorn import (UC_ARCH_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ,
                     UC_HOOK_MEM_UNMAPPED, UC_HOOK_MEM_WRITE, UC_MODE_ARM, Uc)
from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_LR, UC_ARM_REG_PC,
                               UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                               UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5,
                               UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8,
                               UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
                               UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_SPSR)

UART0 = 0xF2000000
PL011_DR = 0x00
PL011_FR = 0x18
PL011_FR_TXFE = 0x80
PL011_FR_RXFE = 0x10
PL011_RIS = 0x3C
PL011_ICR = 0x44

KERNEL_LOAD = 0x00108000
INITRD_LOAD = 0x00700000
BOOT_PARAMS = 0x00103000

#: Recovered in E0416 from the machine_desc/init code.
GIC_DIST = 0xF8001000
GIC_CPU = 0xF8000100
TIMER_BASE = 0xF2403000
TIMER_COUNTER_OFFSET = 0x10C
TIMER_IRQ = 153  # 0x99: ext_timer_setup setup_irq(irq = context[4] + 0x99)
TIMER_HZ = 100  # clock_event period 0x2710 on a 1 MHz timer
TIMER_TICKS_PER_JIFFY = 0x2710
VECTORS_BASE = 0xFFFF0000
CRCDC_BASE = 0xF2A31000
# ARM PL011 PrimeCell identification registers (+0xFE0..+0xFFC).
PL011_ID_REGS = {
    0xFE0: 0x11, 0xFE4: 0x10, 0xFE8: 0x14, 0xFEC: 0x00,   # 0x00141011
    0xFF0: 0x0D, 0xFF4: 0xF0, 0xFF8: 0x05, 0xFFC: 0xB1,   # 0xB105F00D
}
CRCDC_STATUS = 0xF2A31030

GIC_ICCIAR = 0x0C
GIC_ICCEOIR = 0x10
GIC_ICCICR = 0x00
GIC_ICCPMR = 0x04
GIC_SPURIOUS = 1023

DEFAULT_RAM_BANKS = ((0x00000000, 0x40000000), (0x80000000, 0x40000000))
DEFAULT_MMIO_RANGES = ((0xF0000000, 0xFDFFFFFF), (0xFE100000, 0xFFFFFFFF))
DEFAULT_SRAM = (0xFE000000, 0x00100000)
DEFAULT_STUBS = {0xF800277C: 0x100}  # observed early clock/power status poll


class MachineError(RuntimeError):
    pass


class UnicornMachine:
    """Bounded Unicorn machine model for the updater Linux bring-up."""

    def __init__(self, kernel_raw: bytes, initrd: bytes, atags: bytes, *,
                 machine_id: int, kernel_load: int = KERNEL_LOAD,
                 initrd_load: int = INITRD_LOAD, boot_params: int = BOOT_PARAMS,
                 ram_banks=DEFAULT_RAM_BANKS, mmio_ranges=DEFAULT_MMIO_RANGES,
                 sram=DEFAULT_SRAM, uart_base: int = UART0,
                 mmio_read_stubs: dict[int, int] | None = None,
                 timer_irq_model: bool = True,
                 timer_ticks_per_instruction: int = 1,
                 timer_ticks_per_jiffy: int = TIMER_TICKS_PER_JIFFY,
                 timer_irq_start_instructions: int = 5_000_000,
                 timer_irq: int = TIMER_IRQ,
                 vectors_base: int = VECTORS_BASE,
                 unmapped_mmio_policy: str = 'stop',
                 exclusive_fallback: bool = True,
                 exclusive_patch: bool = False,
                 data_abort_delivery: bool = True,
                 data_abort_limit: int = 4096,
                 data_abort_fsr: int = 0x5,
                 ex_table_fixup: bool = True,
                 probe_write_ranges: tuple = (),
                 serial_input: bytes = b'',
                 boot_params_payload: bytes | None = None,
                 trace_user_mode: bool = False,
                 trace_regs: dict | None = None,
                 trace_printk_at: int | None = None,
                 trace_points: dict | None = None,
                 instruction_limit: int = 40_000_000,
                 sample_interval: int = 250_000,
                 use_code_hook: bool = False,
                 boot_patches: dict | None = None,
                 symbols: dict[str, int] | None = None):
        if int.from_bytes(kernel_raw[0:4], 'little') != 0xE321F0D3:
            raise MachineError('kernel_raw does not start with the ARM kernel head')
        if not machine_id:
            raise MachineError('machine ID required')
        if instruction_limit <= 0:
            raise MachineError('positive instruction limit required')
        self.kernel_raw = kernel_raw
        self.initrd = initrd
        self.atags = atags
        self.machine_id = machine_id
        self.kernel_load = kernel_load
        self.initrd_load = initrd_load
        self.boot_params = boot_params
        self.uart_base = uart_base
        self.stubs = dict(mmio_read_stubs if mmio_read_stubs is not None else DEFAULT_STUBS)
        self.instruction_limit = instruction_limit
        self.sample_interval = sample_interval
        self.slice_size = sample_interval if sample_interval > 0 else 250_000
        self.use_code_hook = use_code_hook
        # One-shot runner patches: {pc: [(virtual_address, size, value), ...]}.  They
        # let a bring-up experiment pre-seed runtime variables (e.g. the observed
        # ``lpj`` value) without modifying the kernel image bytes; every patch hit is
        # counted and reported.
        self.boot_patches = dict(boot_patches or {})
        self.patch_hits: Counter = Counter()
        # Timer/GIC model state (E0417).
        self.timer_irq_model = timer_irq_model
        self.timer_ticks_per_instruction = timer_ticks_per_instruction
        self.timer_ticks_per_jiffy = timer_ticks_per_jiffy
        self.timer_irq_start_instructions = timer_irq_start_instructions
        self._instructions_executed = 0
        self.timer_irq = timer_irq
        self.vectors_base = vectors_base
        self.unmapped_mmio_policy = unmapped_mmio_policy
        # Unicorn's ARM target raises UC_ERR_EXCEPTION on the ARMv7 exclusive
        # instructions (LDREX/STREX/DMB/CLREX).  A small local exclusive-monitor
        # model emulates them so the real kernel can keep running; every emulated
        # instruction is counted in the report.
        self.exclusive_fallback = exclusive_fallback
        self.exclusive_patch = exclusive_patch
        self.exclusive_patched: dict = {}
        # ARMv7 data-abort delivery (E0419).
        self.data_abort_delivery = data_abort_delivery
        self.data_abort_limit = data_abort_limit
        self.data_abort_fsr = data_abort_fsr
        # Direct __ex_table fixup application (E0420): a faulting kernel PC
        # with an exception-table entry jumps to its fixup, matching the
        # kernel's native fixup semantics without relying on CP15 DFAR/DFSR
        # visibility in the emulated abort entry.
        self.ex_table_fixup = ex_table_fixup
        self.probe_write_ranges = tuple(probe_write_ranges)
        self.ex_table: dict = {}
        self.ex_table_fixups = 0
        self.ex_table_trace: list[dict] = []
        self.data_aborts_delivered = 0
        self.data_abort_trace: list[dict] = []
        self._abort_last_pc = None
        self._abort_same_pc = 0
        self._exclusive_monitor: tuple[int, int] | None = None
        self._exclusive_cache: dict = {}
        self.exclusive_emulated = 0
        self.exclusive_trace: list[dict] = []
        self._timer_counter = 0
        self._next_jiffy_tick = timer_ticks_per_jiffy
        self._timer_irq_pending = 0
        self._gic_active_irq = None
        self._gic_iar_served = False
        self._gic_regs: dict[int, int] = {}
        self._timer_regs: dict[int, int] = {}
        self._gic_enabled = False
        self._jiffies_injected = 0
        self._timer_counter_reads = 0
        self._gic_iar_reads = 0
        self._gic_iar_pcs: list[str] = []
        self._injection_pcs: list[dict] = []
        self._gic_eoir_writes = 0
        self._unmapped_mmio_mapped: list[int] = []
        # E0421: per-MMIO-address byte stream probe to identify the live
        # console UART data register without guessing its base address.
        self.mmio_write_bytes: dict[int, bytearray] = {}
        # Bidirectional PL011: RX FIFO for injected console input.
        self.serial_input = bytearray(serial_input)
        self.boot_params_payload = boot_params_payload
        self.trace_user_mode = trace_user_mode
        self.trace_regs = trace_regs or {}
        self.trace_reg_values: dict[int, list] = {}
        self.user_mode_entries: list[dict] = []
        # E0429: explicit per-mode SP banking (Unicorn shares R13 across
        # modes) and prefetch-abort support.
        self.mode_sp: dict[str, int | None] = {'svc': None, 'irq': None,
                                              'abt': None, 'usr': None}
        self.mode_lr: dict[str, int | None] = {'svc': None, 'irq': None,
                                              'abt': None, 'usr': None}
        self.user_sp: int | None = None
        self._restore_user_sp = False
        self._pending_exception = ''
        self.prefetch_aborts_delivered = 0
        self.prefetch_abort_trace: list[dict] = []
        # E0428: user-access helpers whose faults must be delivered to the
        # kernel do_DataAbort (handle_mm_fault) instead of being fixed up
        # directly; the exec BSS/stack demand-paging path runs through them.
        self.demand_page_helpers = {
            '__clear_user_std', '__copy_to_user_std', '__copy_from_user_std',
            '__clear_user', '__copy_to_user', '__copy_from_user',
            'padzero', 'copy_strings', 'copy_strings_kernel',
            'create_elf_tables', 'load_elf_binary'}
        self._uart_regs: dict[int, int] = {}
        self._crcdc_regs: dict[int, int] = {}
        self.trace_printk_at = trace_printk_at
        self.trace_points = dict(trace_points or {})
        self.trace_point_hits: list[dict] = []
        self.printk_trace: list[dict] = []
        self.symbols = symbols or {}
        self._symbol_addresses = sorted(self.symbols.values())
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        # The Sony kernel is ARMv7 with VFP-D32; Unicorn's default ARM926 (ARMv5)
        # model BUGs in vfp_init ("VFP is not D16 type").  Match the board CPU.
        try:
            import unicorn.arm_const as arm_const
            self.uc.ctl_set_cpu_model(arm_const.UC_CPU_ARM_CORTEX_A9)
            self.cpu_model = 'cortex-a9'
        except Exception:
            self.cpu_model = 'default'
        self._mapped: list[list[int]] = []
        self.serial = bytearray()
        self.mmio_counts: Counter = Counter()
        self.mmio_writes: Counter = Counter()
        self.stub_hits: Counter = Counter()
        self.pc_samples: Counter = Counter()
        self.unmapped: list[dict] = []
        self.unmapped_counts: Counter = Counter()
        self._instructions = 0
        self._build(ram_banks, mmio_ranges, sram)

    # ------------------------------------------------------------------ helpers
    def _ensure_mapped(self, begin: int, end: int, perms: int = 7) -> None:
        begin, end = begin & ~0xFFF, (end + 0xFFF) & ~0xFFF
        for existing in self._mapped:
            if begin >= existing[0] and end <= existing[1]:
                return
            if begin < existing[1] and existing[0] < end:
                raise MachineError(f'mapping 0x{begin:x}..0x{end:x} overlaps '
                                   f'0x{existing[0]:x}..{existing[1]:x}')
        self.uc.mem_map(begin, end - begin, perms)
        self._mapped.append([begin, end])

    def nearest_symbol(self, address: int) -> str | None:
        import bisect
        if not self._symbol_addresses:
            return None
        index = bisect.bisect_right(self._symbol_addresses, address) - 1
        if index < 0:
            return None
        symbol_address = self._symbol_addresses[index]
        name = next(name for name, value in self.symbols.items()
                    if value == symbol_address)
        delta = address - symbol_address
        return name if not delta else f'{name}+0x{delta:x}'

    # -------------------------------------------------------------------- build
    def _build(self, ram_banks, mmio_ranges, sram) -> None:
        for base, size in ram_banks:
            self._ensure_mapped(base, base + size)
        for start, end in mmio_ranges:
            self._ensure_mapped(start, end + 1)
        self._ensure_mapped(sram[0], sram[0] + sram[1])
        self._ensure_mapped(self.kernel_load, self.kernel_load + len(self.kernel_raw))
        self._ensure_mapped(self.initrd_load, self.initrd_load + len(self.initrd))
        self.uc.mem_write(self.kernel_load, self.kernel_raw)
        self.uc.mem_write(self.initrd_load, self.initrd)
        payload = self.boot_params_payload if self.boot_params_payload is not None else self.atags
        self.uc.mem_write(self.boot_params, payload)
        self.uc.reg_write(UC_ARM_REG_R0, 0)
        self.uc.reg_write(UC_ARM_REG_R1, self.machine_id)
        self.uc.reg_write(UC_ARM_REG_R2, self.boot_params)
        self.uc.reg_write(UC_ARM_REG_CPSR, 0x000000D3)
        self.uc.reg_write(UC_ARM_REG_PC, self.kernel_load)
        self._patch_exclusive_instructions()
        self._build_ex_table()
        self._install_hooks()

    # ------------------------------------------------- exclusive pre-translation
    #: RAM area used for per-site STREX trampolines (VA = PA + PAGE_OFFSET).
    EXCLUSIVE_STUB_PA = 0x02000000

    def _patch_exclusive_instructions(self) -> None:
        """Translate ARMv7 exclusives/barriers in the loaded kernel image.

        Unicorn 2.1.4 raises UC_ERR_EXCEPTION on LDREX/STREX/CLREX/barriers and an
        exception-per-instruction path is far too slow for an SMP kernel (every
        spinlock/atomic uses them).  On our deterministic single-core machine the
        exclusive monitor can only ever be free, so the translation is exact:
        LDREX* -> LDR*, STREX* -> STR* + MOV Rd,#0 via a per-site trampoline, and
        DMB/DSB/ISB/CLREX -> NOP.
        """
        if not self.exclusive_patch:
            return
        start = self.kernel_load
        length = len(self.kernel_raw)
        try:
            data = bytearray(self.uc.mem_read(start, length))
        except Exception:
            return
        page_offset = self.PAGE_OFFSET
        stub_pa = self.EXCLUSIVE_STUB_PA
        counts = {'ldrex': 0, 'strex': 0, 'barrier': 0, 'stubs': 0}

        def branch_word(cond, target_va, site_va):
            offset = ((target_va - (site_va + 8)) >> 2) & 0xFFFFFF
            return (cond & 0xF0000000) | 0x0A000000 | offset

        for off in range(0, length - 3, 4):
            word = int.from_bytes(data[off:off + 4], 'little')
            site_pa = start + off
            site_va = site_pa + page_offset
            if (word & 0x0FF00FFF) == 0x01900F9F:  # LDREX Rd,[Rn]
                cond = word & 0xF0000000
                rn = (word >> 16) & 0xF
                rd = (word >> 12) & 0xF
                data[off:off + 4] = (cond | 0x05900000 | (rn << 16)
                                     | (rd << 12)).to_bytes(4, 'little')
                counts['ldrex'] += 1
                continue
            if (word & 0x0FF00FF0) == 0x01800F90:  # STREX Rd,Rm,[Rn]
                cond = word & 0xF0000000
                rn = (word >> 16) & 0xF
                rd = (word >> 12) & 0xF
                rm = word & 0xF
                stub_va = stub_pa + page_offset
                data[off:off + 4] = branch_word(cond, stub_va, site_va).to_bytes(
                    4, 'little')
                stub = [(cond | 0x05800000 | (rn << 16) | (rm << 12)),
                        (cond | 0x03A00000 | (rd << 12)),
                        (0xEA000000
                         | ((((site_va + 4) - (stub_va + 8)) >> 2) & 0xFFFFFF))]
                self.uc.mem_write(stub_pa, struct.pack('<3I', *stub))
                stub_pa += 16
                counts['strex'] += 1
                counts['stubs'] += 1
                continue
            if word in (0xF57FF05F, 0xF57FF04F, 0xF57FF06F, 0xF57FF01F):
                data[off:off + 4] = (0xE320F000).to_bytes(4, 'little')  # NOP
                counts['barrier'] += 1
        self.uc.mem_write(start, bytes(data))
        self.exclusive_patched = counts

    def _install_hooks(self) -> None:
        uart_start, uart_end = self.uart_base, self.uart_base + 0xFFF
        mmio_starts = [(start, end) for start, end in DEFAULT_MMIO_RANGES]

        def in_range(address, base, size=0x1000):
            return base <= address < base + size

        def uart_reads(address):
            return in_range(address, self.uart_base)

        def uart_register_value(offset):
            if offset == PL011_DR:
                if self.serial_input:
                    self._uart_regs[PL011_RIS] = self._uart_regs.get(PL011_RIS, 0) | 0x10  # RX interrupt status
                    return self.serial_input.pop(0)
                return 0
            if offset == PL011_FR:
                rxfe = 0x10 if not self.serial_input else 0
                return PL011_FR_TXFE | rxfe
            if offset in PL011_ID_REGS:
                if offset == 0xFE0:
                    self.id_reads = getattr(self, 'id_reads', 0) + 1
                return PL011_ID_REGS[offset]
            if offset == PL011_RIS:
                ris = self._uart_regs.get(PL011_RIS, 0)
                if self.serial_input:
                    ris |= 0x10
                return ris
            return self._uart_regs.get(offset, 0)

        def mmio_read(uc, access, address, size, value, user):
            self.mmio_counts[address] += 1
            if address in self.stubs:
                self.stub_hits[address] += 1
                stub_value = self.stubs[address] & ((1 << (size * 8)) - 1)
                uc.mem_write(address, stub_value.to_bytes(size, 'little'))
                return True
            if in_range(address, CRCDC_BASE, 0x1000):
                # CRCDC/clock block: update_crdm writes +0x30=1 and polls bit0;
                # report completion immediately (bit0 clear) instead of timing out.
                uc.mem_write(address, struct.pack('<I', 0))
                return True
            if uart_reads(address):
                offset = address - self.uart_base
                if offset in (PL011_DR, PL011_FR, PL011_RIS) or offset in PL011_ID_REGS:
                    raw = uart_register_value(offset)
                else:
                    raw = self._uart_regs.get(offset, 0)
                uc.mem_write(address, (raw & ((1 << (size * 8)) - 1))
                             .to_bytes(size, 'little'))
                return True
            if in_range(address, TIMER_BASE, 0x200):
                offset = address - TIMER_BASE
                if offset == TIMER_COUNTER_OFFSET:
                    self._timer_counter_reads += 1
                    uc.mem_write(address,
                                 (self._timer_counter & ((1 << (size * 8)) - 1))
                                 .to_bytes(size, 'little'))
                    return True
                stored = self._timer_regs.get(offset, 0)
                uc.mem_write(address, (stored & ((1 << (size * 8)) - 1))
                             .to_bytes(size, 'little'))
                return True
            if in_range(address, GIC_DIST) or in_range(address, GIC_CPU):
                # The distributor window starts at CPU+0xF00, so classify it first.
                if in_range(address, GIC_DIST):
                    key = ('dist', address - GIC_DIST)
                else:
                    key = ('cpu', address - GIC_CPU)
                if key == ('dist', 0x004):
                    # GICD_TYPER: report 1024 interrupt lines so the kernel accepts
                    # the observed CXD timer IRQ 153 (setup_irq validation).
                    uc.mem_write(address, struct.pack('<I', 0x0000001F))
                    return True
                if key == ('cpu', GIC_ICCIAR):
                    self._gic_iar_reads += 1
                    if len(self._gic_iar_pcs) < 20:
                        self._gic_iar_pcs.append(
                            f'0x{uc.reg_read(UC_ARM_REG_PC):08x}')
                    if self._gic_active_irq is not None and not self._gic_iar_served:
                        value = self._gic_active_irq
                        self._gic_iar_served = True
                    else:
                        value = GIC_SPURIOUS
                    uc.mem_write(address, value.to_bytes(size, 'little'))
                    return True
                stored = self._gic_regs.get(key, 0)
                uc.mem_write(address, (stored & ((1 << (size * 8)) - 1))
                             .to_bytes(size, 'little'))
                return True
            # Remaining MMIO reads fall through to the mapped zero/register image
            # (PL011 FR is pre-seeded to TXFE|RXFE).
            return True

        def mmio_write(uc, access, address, size, value, user):
            self.mmio_counts[address] += 1
            self.mmio_writes[address] += 1
            if in_range(address, TIMER_BASE, 0x200):
                self._timer_regs[address - TIMER_BASE] = value & 0xFFFFFFFF
                return True
            if in_range(address, GIC_DIST) or in_range(address, GIC_CPU):
                cpu_side = not in_range(address, GIC_DIST)
                offset = address - (GIC_CPU if cpu_side else GIC_DIST)
                key = ('cpu', offset) if cpu_side else ('dist', offset)
                self._gic_regs[key] = value & 0xFFFFFFFF
                if cpu_side and offset == GIC_ICCEOIR:
                    self._gic_active_irq = None
                    self._gic_eoir_writes += 1
                if cpu_side and offset == GIC_ICCICR:
                    self._gic_enabled = bool(
                        (value & 1) and (self._gic_regs.get(('dist', 0x000), 0) & 1))
                if not cpu_side and offset == 0x000:
                    self._gic_enabled = bool(
                        (value & 1) and (self._gic_regs.get(('cpu', GIC_ICCICR), 0) & 1))
                return True
            if in_range(address, CRCDC_BASE, 0x1000):
                self._crcdc_regs[address - CRCDC_BASE] = value & 0xFFFFFFFF
                return True
            if in_range(address, self.uart_base):
                offset = address - self.uart_base
                if offset == PL011_DR:
                    self.serial.append(value & 0xFF)
                elif offset == PL011_ICR:
                    self._uart_regs[PL011_RIS] = self._uart_regs.get(PL011_RIS, 0) & ~value
                else:
                    self._uart_regs[offset] = value & 0xFFFFFFFF
            if size <= 4:
                stream = self.mmio_write_bytes.setdefault(address, bytearray())
                if len(stream) < 2048:
                    stream.append(value & 0xFF)
            return True

        def unmapped(uc, access, address, size, value, user):
            entry = {'pc': uc.reg_read(UC_ARM_REG_PC), 'address': address, 'size': size,
                     'access': access,
                     'r0': uc.reg_read(UC_ARM_REG_R0), 'r1': uc.reg_read(UC_ARM_REG_R1),
                     'r2': uc.reg_read(UC_ARM_REG_R2),
                     'sp': uc.reg_read(UC_ARM_REG_SP), 'lr': uc.reg_read(UC_ARM_REG_LR)}
            self.unmapped.append(entry)
            self.unmapped_counts[address] += 1
            if (self.unmapped_mmio_policy == 'observe-zero'
                    and address >= 0xF0000000 and address < 0x100000000):
                page = address & ~0xFFF
                if page not in self._unmapped_mmio_mapped and len(self._mapped) < 200:
                    self.uc.mem_map(page, 0x1000, 7)
                    self._mapped.append([page, page + 0x1000])
                    self._unmapped_mmio_mapped.append(page)
                return True  # retry: the page is now zero-backed and logged
            uc.emu_stop()
            return False

        def code(uc, address, size, user):
            self._instructions += 1
            if self._instructions % self.sample_interval == 0:
                self.pc_samples[address] += 1

        def user_code(uc, address, size, user):
            cpsr = uc.reg_read(UC_ARM_REG_CPSR)
            if (cpsr & 0x1F) != 0x10:
                return
            if self._restore_user_sp and self.user_sp is not None:
                uc.reg_write(UC_ARM_REG_SP, self.user_sp)
                self._restore_user_sp = False
            if len(self.user_mode_entries) < 20:
                self.user_mode_entries.append({'pc': address, 'cpsr': cpsr})


        _reg_getters = {
            'r0': UC_ARM_REG_R0, 'r1': UC_ARM_REG_R1, 'r2': UC_ARM_REG_R2,
            'r3': UC_ARM_REG_R3, 'r4': UC_ARM_REG_R4, 'r5': UC_ARM_REG_R5,
            'r6': UC_ARM_REG_R6, 'r7': UC_ARM_REG_R7, 'r8': UC_ARM_REG_R8,
            'r9': UC_ARM_REG_R9, 'r10': UC_ARM_REG_R10, 'r11': UC_ARM_REG_R11,
            'r12': UC_ARM_REG_R12, 'sp': UC_ARM_REG_SP, 'lr': UC_ARM_REG_LR,
            'pc': UC_ARM_REG_PC, 'cpsr': UC_ARM_REG_CPSR,
        }
        for pc, reg_names in self.trace_regs.items():
            def capture(uc, address, size, user, pc=pc, reg_names=reg_names):
                values = {name: uc.reg_read(_reg_getters[name])
                          for name in reg_names if name in _reg_getters}
                self.trace_reg_values.setdefault(pc, []).append(values)
            self.uc.hook_add(UC_HOOK_CODE, capture, begin=pc, end=pc + 3)
        for begin, end in mmio_starts:
            self.uc.hook_add(UC_HOOK_MEM_READ, mmio_read, begin=begin, end=end)
            self.uc.hook_add(UC_HOOK_MEM_WRITE, mmio_write, begin=begin, end=end)
        # The kernel console may reach PL011 through an ioremap/vmalloc virtual
        # address rather than the physical UART base; hook the configured block
        # explicitly so serial capture works for both mappings.
        if not any(begin <= self.uart_base <= end for begin, end in mmio_starts):
            try:
                self.uc.hook_add(UC_HOOK_MEM_READ, mmio_read,
                                 begin=self.uart_base, end=self.uart_base + 0xFFF)
                self.uc.hook_add(UC_HOOK_MEM_WRITE, mmio_write,
                                 begin=self.uart_base, end=self.uart_base + 0xFFF)
            except Exception:
                pass
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, unmapped)
        for begin, end in self.probe_write_ranges:
            def probe_write(uc, access, address, size, value, user):
                stream = self.mmio_write_bytes.setdefault(address, bytearray())
                if len(stream) < 2048:
                    stream.append(value & 0xFF)
                return True
            self.uc.hook_add(UC_HOOK_MEM_WRITE, probe_write, begin=begin, end=end)
        # Code hook is optional: it makes per-instruction sampling possible but is
        # much slower than slice-based PC sampling, so the runner defaults to slices.
        if self.sample_interval and self.use_code_hook:
            self.uc.hook_add(UC_HOOK_CODE, code)
        # E0429: capture the kernel SVC stack pointer right before the kernel
        # returns to user mode; it is used as the ABT-mode stack for delivered
        # user faults so abort frames never land on the user stack.
        ret_to_user = None
        for symbol_name, value in self.symbols.items():
            if symbol_name == 'ret_to_user':
                ret_to_user = value
                break
        if ret_to_user is not None:
            def capture_svc_sp(uc, address, size, user):
                self.mode_sp['svc'] = uc.reg_read(UC_ARM_REG_SP)
            self.uc.hook_add(UC_HOOK_CODE, capture_svc_sp,
                             begin=ret_to_user, end=ret_to_user + 3)
        # E0431: emulate the usr_entry banked store `stmdb r0, {sp, lr}^` in the
        # __pabt_usr/__dabt_usr handlers (Unicorn has no banked R13/R14).
        for handler_name in ('__pabt_usr', '__dabt_usr'):
            handler_pc = self._symbol_address(handler_name)
            if handler_pc is not None:
                banked_pc = handler_pc + 0x1C
                def banked_store(uc, address, size, user, pc=banked_pc):
                    self._emulate_banked_store(pc)
                self.uc.hook_add(UC_HOOK_CODE, banked_store,
                                 begin=banked_pc, end=banked_pc + 3)
        if self.trace_user_mode:
            # Wide low-user window: ld-linux (0x04000000+) and busybox (0x8000+).
            self.uc.hook_add(UC_HOOK_CODE, user_code, begin=0x1000, end=0x60000000)
        # Pre-seed the PL011 FR value so reads hit a defined register image.
        try:
            self.uc.mem_write(self.uart_base + PL011_FR,
                              struct.pack('<I', PL011_FR_TXFE | PL011_FR_RXFE))
        except Exception:
            pass
        # One-shot runner patches at exact kernel PCs (single-address code hooks).
        for pc, writes in self.boot_patches.items():
            def apply(uc, address, size, user, pc=pc, writes=writes):
                for virtual_address, write_size, value in writes:
                    uc.mem_write(virtual_address,
                                 value.to_bytes(write_size, 'little'))
                self.patch_hits[pc] += 1
            self.uc.hook_add(UC_HOOK_CODE, apply, begin=pc, end=pc + 3)
        # Optional printk format-string tracer (offline log visibility without a
        # registered console). Kernel lowmem is linear: VA - 0x60000000 = PA.
        if self.trace_printk_at:
            page_offset = 0x60000000

            def printk_hook(uc, address, size, user):
                if len(self.printk_trace) >= 4000:
                    return
                va = uc.reg_read(UC_ARM_REG_R0)
                pa = va - page_offset if va >= page_offset else va
                text = ''
                try:
                    raw = bytes(uc.mem_read(pa, 200))
                    text = raw.split(b'\x00', 1)[0].decode('latin1', 'replace')
                except Exception:
                    text = ''
                self.printk_trace.append({
                    'pc': address, 'format_va': va, 'format': text,
                    'r1': uc.reg_read(UC_ARM_REG_R1),
                    'r2': uc.reg_read(UC_ARM_REG_R2)})

            hook_handle = self.uc.hook_add(UC_HOOK_CODE, printk_hook,
                                           begin=self.trace_printk_at,
                                           end=self.trace_printk_at + 3)
            self._printk_hook = hook_handle
        for pc, label in self.trace_points.items():
            def trace_point(uc, address, size, user, label=label):
                if len(self.trace_point_hits) < 64:
                    self.trace_point_hits.append({
                        'label': label, 'pc': f'0x{address:08x}',
                        'r0': f'0x{uc.reg_read(UC_ARM_REG_R0):08x}',
                        'r1': f'0x{uc.reg_read(UC_ARM_REG_R1):08x}',
                        'r2': f'0x{uc.reg_read(UC_ARM_REG_R2):08x}',
                        'r3': f'0x{uc.reg_read(UC_ARM_REG_R3):08x}'})
            self.uc.hook_add(UC_HOOK_CODE, trace_point, begin=pc, end=pc + 3)

    # ------------------------------------------------------------------ timer/IRQ
    def _advance_timer(self, instructions: int) -> None:
        if not self.timer_irq_model:
            return
        self._instructions_executed += instructions
        self._timer_counter += instructions * self.timer_ticks_per_instruction
        if self._instructions_executed < self.timer_irq_start_instructions:
            return
        if self._timer_counter >= self._next_jiffy_tick:
            # One pending timer interrupt at a time; keep virtual time monotonic.
            self._timer_irq_pending = 1
            while self._timer_counter >= self._next_jiffy_tick:
                self._next_jiffy_tick += self.timer_ticks_per_jiffy

    def _gic_irq_enabled(self) -> bool:
        cpu_ctlr = self._gic_regs.get(('cpu', GIC_ICCICR), 0)
        dist_ctlr = self._gic_regs.get(('dist', 0x000), 0)
        return bool((cpu_ctlr & 1) and (dist_ctlr & 1))

    def _try_inject_irq(self) -> bool:
        """Deliver the pending timer IRQ by emulating ARM IRQ exception entry."""
        if not self.timer_irq_model or not self._timer_irq_pending:
            return False
        if not self._gic_irq_enabled():
            return False
        cpsr = self.uc.reg_read(UC_ARM_REG_CPSR)
        if cpsr & 0x80:  # CPSR.I: interrupts masked
            return False
        pc = self.uc.reg_read(UC_ARM_REG_PC)
        # Enter ARM IRQ mode first, then write the *banked* SPSR_irq/LR_irq; SPSR is
        # per-mode, so writing it before the CPSR switch would hit SPSR_svc instead.
        self.uc.reg_write(UC_ARM_REG_CPSR, 0x12 | 0xC0)
        self.uc.reg_write(UC_ARM_REG_SPSR, cpsr)
        self.uc.reg_write(UC_ARM_REG_LR, pc + 4)
        self.uc.reg_write(UC_ARM_REG_PC, self.vectors_base + 0x18)
        # ARM exception entry clears the exclusive monitor (spec); our IRQ entry
        # must do the same for a faithful LDREX/STREX retry loop.
        self._exclusive_monitor = None
        self._gic_active_irq = self.timer_irq
        self._gic_iar_served = False
        self._timer_irq_pending = 0
        self._jiffies_injected += 1
        if len(self._injection_pcs) < 20:
            self._injection_pcs.append({'pc': f'0x{pc:08x}',
                                        'cpsr': f'0x{cpsr:08x}'})
        return True

    # ------------------------------------------------------- exclusive fallback
    PAGE_OFFSET = 0x60000000

    def _guest_read(self, va: int, size: int) -> bytes:
        pa = va - self.PAGE_OFFSET if va >= self.PAGE_OFFSET else va
        return bytes(self.uc.mem_read(pa, size))

    def _guest_write(self, va: int, data: bytes) -> None:
        pa = va - self.PAGE_OFFSET if va >= self.PAGE_OFFSET else va
        self.uc.mem_write(pa, data)

    def _emulate_exclusive(self, pc: int, cpsr: int) -> bool:
        """Emulate ARMv7 LDREX/STREX/CLREX/DMB when Unicorn raises an exception."""
        from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
        from capstone.arm import ARM_OP_MEM, ARM_OP_REG

        import unicorn.arm_const as arm_const

        def register_index(name):
            name = name.lower()
            aliases = {'sb': 9, 'sl': 10, 'fp': 11, 'ip': 12,
                       'sp': 13, 'lr': 14, 'pc': 15}
            if name in aliases:
                return aliases[name]
            if name.startswith('r') and name[1:].isdigit():
                return int(name[1:])
            return None

        def read_register(index):
            if index == 13:
                return self.uc.reg_read(UC_ARM_REG_SP)
            if index == 14:
                return self.uc.reg_read(UC_ARM_REG_LR)
            if index == 15:
                return self.uc.reg_read(UC_ARM_REG_PC)
            return self.uc.reg_read(getattr(arm_const, f'UC_ARM_REG_R{index}'))

        def write_register(index, value):
            if index == 13:
                self.uc.reg_write(UC_ARM_REG_SP, value)
            elif index == 14:
                self.uc.reg_write(UC_ARM_REG_LR, value)
            elif index == 15:
                self.uc.reg_write(UC_ARM_REG_PC, value)
            else:
                self.uc.reg_write(getattr(arm_const, f'UC_ARM_REG_R{index}'), value)

        thumb = bool(cpsr & 0x20)
        try:
            raw = self._guest_read(pc, 4)
        except Exception:
            return False
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
        md.detail = True
        instruction = next(md.disasm(raw, pc), None)
        if instruction is None:
            return False
        mnemonic = instruction.mnemonic
        size = instruction.size
        if mnemonic in ('dmb', 'dsb', 'isb', 'clrex'):
            if mnemonic == 'clrex':
                self._exclusive_monitor = None
            self.uc.reg_write(UC_ARM_REG_PC, pc + size)
            return True
        memory = next((op for op in instruction.operands if op.type == ARM_OP_MEM),
                      None)
        registers = [register_index(instruction.reg_name(op.reg))
                     for op in instruction.operands if op.type == ARM_OP_REG]
        registers = [index for index in registers if index is not None]
        if memory is None or not registers:
            return False
        address = read_register(register_index(instruction.reg_name(memory.mem.base)))
        address = (address + memory.mem.disp) & 0xFFFFFFFF
        try:
            widths = {'ldrex': 4, 'ldrexb': 1, 'ldrexh': 2, 'ldrexd': 8,
                      'strex': 4, 'strexb': 1, 'strexh': 2, 'strexd': 8}
            if mnemonic in ('ldrex', 'ldrexb', 'ldrexh', 'ldrexd'):
                width = widths[mnemonic]
                data = self._guest_read(address, width)
                value = int.from_bytes(data, 'little')
                self._exclusive_monitor = (address, value)
                write_register(registers[0], value & 0xFFFFFFFF)
                if width == 8 and len(registers) > 1:
                    write_register(registers[1], (value >> 32) & 0xFFFFFFFF)
                self.uc.reg_write(UC_ARM_REG_PC, pc + size)
                return True
            if mnemonic in ('strex', 'strexb', 'strexh', 'strexd'):
                width = widths[mnemonic]
                data_reg = registers[1] if len(registers) > 1 else registers[0]
                value = read_register(data_reg)
                if width == 8:
                    pair = [read_register(data_reg), read_register(data_reg + 1)]
                    value |= pair[1] << 32
                monitor_ok = (self._exclusive_monitor is not None
                              and self._exclusive_monitor[0] == address)
                if monitor_ok:
                    self._guest_write(address, value.to_bytes(width, 'little'))
                    write_register(registers[0], 0)
                else:
                    write_register(registers[0], 1)
                self._exclusive_monitor = None
                self.uc.reg_write(UC_ARM_REG_PC, pc + size)
                return True
        except Exception:
            return False
        return False

    def _in_demand_page_helper(self, pc: int) -> bool:
        if not self._symbol_addresses:
            return False
        import bisect
        index = bisect.bisect_right(self._symbol_addresses, pc) - 1
        if index < 0:
            return False
        symbol_pc = self._symbol_addresses[index]
        name = None
        for candidate, value in self.symbols.items():
            if value == symbol_pc:
                name = candidate
                break
        return name in self.demand_page_helpers

    #: Scratch frame used to emulate the ARM Linux vector-stub entry when the
    #: CPU's per-mode SP banking cannot be modelled by Unicorn (E0430).
    VECTOR_SCRATCH_PA = 0x02002000

    def _symbol_address(self, name: str) -> int | None:
        for symbol_name, value in self.symbols.items():
            if symbol_name == name:
                return value
        return None

    def _flush_tlb(self) -> None:
        """Flush Unicorn's software TLB after a guest PTE/TTBR0 update (E0431)."""
        try:
            flush = getattr(self.uc, 'ctl_flush_tlb', None)
            if flush is not None:
                flush()
                return
        except Exception:
            pass
        try:
            import unicorn
            self.uc.ctl(unicorn.UC_CTL_TLB_FLUSH, 0)
        except Exception:
            pass

    def _emulate_banked_store(self, pc: int) -> None:
        """Emulate `stmdb r0, {sp, lr}^` using the saved USR bank values.

        Unicorn shares R13/R14 between modes, so the kernel's usr_entry banked
        store would otherwise write the SVC stack/LR into pt_regs.
        """
        base = self.uc.reg_read(UC_ARM_REG_R0)
        user_sp = self.mode_sp.get('usr')
        user_lr = self.mode_lr.get('usr')
        if user_sp is None:
            user_sp = self.user_sp
        try:
            self.uc.mem_write(base - 8, struct.pack('<I', (user_sp or 0) & 0xFFFFFFFF))
            self.uc.mem_write(base - 4, struct.pack('<I', (user_lr or 0) & 0xFFFFFFFF))
        except Exception:
            pass
        self.uc.reg_write(UC_ARM_REG_PC, pc + 4)

    def _deliver_user_exception(self, pc: int, cpsr: int) -> bool:
        """Emulate vector_stub + usr_entry for a user fault (E0430).

        The real ARMv7 vector code uses the banked SP_abt for a 12-byte scratch
        frame before switching to SVC; Unicorn shares R13 between modes, so we
        write that scratch frame ourselves, switch to SVC mode with the saved
        kernel SVC stack pointer and jump straight to the kernel's __dabt_usr /
        __pabt_usr handler with r0 pointing at the scratch frame.
        """
        handler = self._symbol_address(
            '__pabt_usr' if self._pending_exception == 'pabt' else '__dabt_usr')
        if handler is None:
            return False
        if self.mode_sp.get('svc') is None:
            return False
        scratch_pa = self.VECTOR_SCRATCH_PA
        scratch_va = scratch_pa + self.PAGE_OFFSET
        r0 = self.uc.reg_read(UC_ARM_REG_R0)
        self.uc.mem_write(scratch_pa, struct.pack(
            '<3I', r0 & 0xFFFFFFFF, pc & 0xFFFFFFFF, cpsr & 0xFFFFFFFF))
        self.user_sp = self.uc.reg_read(UC_ARM_REG_SP)
        self.mode_sp['usr'] = self.user_sp
        self.mode_lr['usr'] = self.uc.reg_read(UC_ARM_REG_LR)
        self._restore_user_sp = True
        self.uc.reg_write(UC_ARM_REG_CPSR, 0x13 | 0xC0)  # SVC, IRQ/FIQ masked
        self.uc.reg_write(UC_ARM_REG_SP, self.mode_sp['svc'])
        self.uc.reg_write(UC_ARM_REG_R0, scratch_va)
        self.uc.reg_write(UC_ARM_REG_LR, pc)
        self.uc.reg_write(UC_ARM_REG_PC, handler)
        self._flush_tlb()
        return True

    # ------------------------------------------------- data abort delivery
    ABORT_HELPER_PA = 0x02001000

    def _set_cp15_fault(self, address: int, fsr: int) -> bool:
        """Populate DFAR (c6) and DFSR (c5) through emulated MCR instructions."""
        helper_va = self.ABORT_HELPER_PA + self.PAGE_OFFSET
        code = struct.pack('<3I', 0xEE060F10, 0xEE051F10, 0xEAFFFFFE)
        try:
            self.uc.mem_write(self.ABORT_HELPER_PA, code)
        except Exception:
            return False
        saved_r0 = self.uc.reg_read(UC_ARM_REG_R0)
        saved_r1 = self.uc.reg_read(UC_ARM_REG_R1)
        saved_cpsr = self.uc.reg_read(UC_ARM_REG_CPSR)
        # MCR is privileged: run the helper in SVC mode even when the fault
        # came from user mode (E0429).
        self.uc.reg_write(UC_ARM_REG_CPSR, 0xD3)
        self.uc.reg_write(UC_ARM_REG_R0, address & 0xFFFFFFFF)
        self.uc.reg_write(UC_ARM_REG_R1, fsr & 0xFFFFFFFF)
        try:
            self.uc.emu_start(helper_va, 0, count=2)
        except Exception:
            self.uc.reg_write(UC_ARM_REG_R0, saved_r0)
            self.uc.reg_write(UC_ARM_REG_R1, saved_r1)
            self.uc.reg_write(UC_ARM_REG_CPSR, saved_cpsr)
            return False
        self.uc.reg_write(UC_ARM_REG_R0, saved_r0)
        self.uc.reg_write(UC_ARM_REG_R1, saved_r1)
        self.uc.reg_write(UC_ARM_REG_CPSR, saved_cpsr)
        return True

    def _deliver_prefetch_abort(self, pc: int, cpsr: int, address: int) -> bool:
        """Deliver an ARMv7 Prefetch Abort to vector 0xFFFF000C (E0429)."""
        if not self.data_abort_delivery:
            return False
        if (cpsr & 0x1F) == 0x10 and self._symbol_address('__pabt_usr') is not None:
            if not self._set_cp15_prefetch_fault(address, 0x5):
                return False
            self._pending_exception = 'pabt'
            if self._deliver_user_exception(pc, cpsr):
                self.prefetch_aborts_delivered += 1
                if len(self.prefetch_abort_trace) < 64:
                    self.prefetch_abort_trace.append({
                        'pc': f'0x{pc:08x}', 'address': f'0x{address:08x}',
                        'ifsr': '0x00000005', 'user': True})
                return True
        if self.prefetch_aborts_delivered >= self.data_abort_limit:
            return False
        if not self._set_cp15_prefetch_fault(address, 0x5):
            return False
        current_mode = cpsr & 0x1F
        current_sp = self.uc.reg_read(UC_ARM_REG_SP)
        if current_mode == 0x10:
            self.user_sp = current_sp
            if self.mode_sp.get('svc') is not None:
                self.uc.reg_write(UC_ARM_REG_SP, self.mode_sp['svc'])
            self._restore_user_sp = True
        self.uc.reg_write(UC_ARM_REG_CPSR, 0x17 | 0xC0)
        self.uc.reg_write(UC_ARM_REG_SPSR, cpsr)
        self.uc.reg_write(UC_ARM_REG_LR, pc + 4)
        self.uc.reg_write(UC_ARM_REG_PC, 0xFFFF000C)
        self.prefetch_aborts_delivered += 1
        if len(self.prefetch_abort_trace) < 64:
            self.prefetch_abort_trace.append({
                'pc': f'0x{pc:08x}', 'address': f'0x{address:08x}',
                'ifsr': '0x00000005', 'user': current_mode == 0x10})
        return True

    def _set_cp15_prefetch_fault(self, address: int, ifsr: int) -> bool:
        """Populate IFAR (c6,c0,2) and IFSR (c5,c0,1) via emulated MCR."""
        helper_va = self.ABORT_HELPER_PA + self.PAGE_OFFSET
        code = struct.pack('<3I', 0xEE060F50, 0xEE051F30, 0xEAFFFFFE)
        try:
            self.uc.mem_write(self.ABORT_HELPER_PA, code)
        except Exception:
            return False
        saved_r0 = self.uc.reg_read(UC_ARM_REG_R0)
        saved_r1 = self.uc.reg_read(UC_ARM_REG_R1)
        saved_cpsr = self.uc.reg_read(UC_ARM_REG_CPSR)
        self.uc.reg_write(UC_ARM_REG_CPSR, 0xD3)  # helper MCR needs SVC mode
        self.uc.reg_write(UC_ARM_REG_R0, address & 0xFFFFFFFF)
        self.uc.reg_write(UC_ARM_REG_R1, ifsr & 0xFFFFFFFF)
        try:
            self.uc.emu_start(helper_va, 0, count=2)
        except Exception:
            self.uc.reg_write(UC_ARM_REG_R0, saved_r0)
            self.uc.reg_write(UC_ARM_REG_R1, saved_r1)
            self.uc.reg_write(UC_ARM_REG_CPSR, saved_cpsr)
            return False
        self.uc.reg_write(UC_ARM_REG_R0, saved_r0)
        self.uc.reg_write(UC_ARM_REG_R1, saved_r1)
        self.uc.reg_write(UC_ARM_REG_CPSR, saved_cpsr)
        return True

    def _deliver_data_abort(self, pc: int, cpsr: int, address: int,
                            write: bool) -> bool:
        """Deliver an ARMv7 Data Abort to 0xFFFF0010 with DFAR/DFSR populated."""
        if not self.data_abort_delivery:
            return False
        if (cpsr & 0x1F) == 0x10 and self._symbol_address('__dabt_usr') is not None:
            if not self._set_cp15_fault(address, 0x5 | (0x800 if write else 0)):
                return False
            self._pending_exception = 'dabt'
            if self._deliver_user_exception(pc, cpsr):
                return True
        if self.data_aborts_delivered >= self.data_abort_limit:
            return False
        if self._abort_last_pc == pc:
            self._abort_same_pc += 1
            if self._abort_same_pc > 8:
                return False
        else:
            self._abort_last_pc = pc
            self._abort_same_pc = 1
        fsr = self.data_abort_fsr | (0x800 if write else 0)
        if not self._set_cp15_fault(address, fsr):
            return False
        # ABT mode with I/F masked; banked SPSR_abt/LR_abt after the CPSR switch.
        self.uc.reg_write(UC_ARM_REG_CPSR, 0x17 | 0xC0)
        self.uc.reg_write(UC_ARM_REG_SPSR, cpsr)
        self.uc.reg_write(UC_ARM_REG_LR, pc + 8)
        self.uc.reg_write(UC_ARM_REG_PC, 0xFFFF0010)
        self.data_aborts_delivered += 1
        if len(self.data_abort_trace) < 64:
            self.data_abort_trace.append({
                'pc': f'0x{pc:08x}', 'address': f'0x{address:08x}',
                'fsr': f'0x{fsr:08x}', 'write': write})
        return True

    # --------------------------------------------------- __ex_table fixups
    def _mmio_write_candidates(self) -> list[dict]:
        candidates = []
        for address, stream in self.mmio_write_bytes.items():
            if len(stream) < 8:
                continue
            printable = sum(1 for byte in stream if 32 <= byte < 127 or byte in (9, 10, 13))
            ratio = printable / len(stream)
            if ratio < 0.6:
                continue
            text = ''.join(chr(byte) if 32 <= byte < 127 else '.'
                           for byte in stream[:200])
            candidates.append({'address': f'0x{address:08x}', 'bytes': len(stream),
                               'printable_ratio': round(ratio, 2), 'text': text})
        candidates.sort(key=lambda item: item['bytes'], reverse=True)
        return candidates[:8]

    def _build_ex_table(self) -> None:
        """Locate kernel exception-table (insn -> fixup) pairs in the image."""
        self.ex_table = {}
        if not self.ex_table_fixup:
            return
        text_start = self.kernel_load + self.PAGE_OFFSET
        text_end = text_start + len(self.kernel_raw)
        raw = self.kernel_raw
        count = 0
        # Exception-table entries are (insn, fixup) word pairs; collect every
        # candidate pair whose words both fall inside the kernel image.  A random
        # data collision cannot match a real faulting PC, so exact-PC lookup is
        # safe and robust to the on-disk table ordering.
        for offset in range(0, len(raw) - 7, 4):
            insn, fixup = struct.unpack_from('<II', raw, offset)
            if text_start <= insn < text_end and text_start <= fixup < text_end:
                self.ex_table[insn] = fixup
                count += 1
        self.ex_table_entries = count

    def _try_ex_table_fixup(self, pc: int) -> int | None:
        if not self.ex_table_fixup or not self.ex_table:
            return None
        fixup = self.ex_table.get(pc)
        if fixup is None:
            return None
        if len(self.ex_table_trace) < 64:
            self.ex_table_trace.append({
                'pc': f'0x{pc:08x}', 'fixup': f'0x{fixup:08x}'})
        self.ex_table_fixups += 1
        self.uc.reg_write(UC_ARM_REG_PC, fixup)
        return fixup

    def _fault_state(self) -> dict:
        """Register + decoded-instruction snapshot at the current PC."""
        from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
        from capstone.arm import ARM_OP_MEM

        import unicorn.arm_const as arm_const

        def read_register(index):
            if index == 13:
                return self.uc.reg_read(UC_ARM_REG_SP)
            if index == 14:
                return self.uc.reg_read(UC_ARM_REG_LR)
            if index == 15:
                return self.uc.reg_read(UC_ARM_REG_PC)
            return self.uc.reg_read(getattr(arm_const, f'UC_ARM_REG_R{index}'))

        def register_index(name):
            aliases = {'sb': 9, 'sl': 10, 'fp': 11, 'ip': 12,
                       'sp': 13, 'lr': 14, 'pc': 15}
            name = name.lower()
            if name in aliases:
                return aliases[name]
            if name.startswith('r') and name[1:].isdigit():
                return int(name[1:])
            return None

        state = {
            'pc': f'0x{self.uc.reg_read(UC_ARM_REG_PC):08x}',
            'cpsr': f'0x{self.uc.reg_read(UC_ARM_REG_CPSR):08x}',
            'r0': f'0x{self.uc.reg_read(UC_ARM_REG_R0):08x}',
            'r1': f'0x{self.uc.reg_read(UC_ARM_REG_R1):08x}',
            'r2': f'0x{self.uc.reg_read(UC_ARM_REG_R2):08x}',
            'r3': f'0x{self.uc.reg_read(UC_ARM_REG_R3):08x}',
            'r4': f'0x{self.uc.reg_read(UC_ARM_REG_R4):08x}',
            'r5': f'0x{self.uc.reg_read(UC_ARM_REG_R5):08x}',
            'sp': f'0x{self.uc.reg_read(UC_ARM_REG_SP):08x}',
            'lr': f'0x{self.uc.reg_read(UC_ARM_REG_LR):08x}'}
        pc = self.uc.reg_read(UC_ARM_REG_PC)
        cpsr = self.uc.reg_read(UC_ARM_REG_CPSR)
        try:
            raw = self._guest_read(pc, 4)
            md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if cpsr & 0x20 else CS_MODE_ARM)
            md.detail = True
            instruction = next(md.disasm(raw, pc), None)
            if instruction is not None:
                state['mnemonic'] = instruction.mnemonic
                state['size'] = instruction.size
                memory = next((op for op in instruction.operands
                               if op.type == ARM_OP_MEM), None)
                if memory is not None:
                    base_index = register_index(
                        instruction.reg_name(memory.mem.base))
                    if base_index is not None:
                        base_value = read_register(base_index)
                        state['base'] = f'0x{base_value:08x}'
                        state['effective_address'] = (
                            f'0x{(base_value + memory.mem.disp) & 0xFFFFFFFF:08x}')
        except Exception:
            pass
        return state

    def run(self, limit: int | None = None) -> dict:
        limit = limit or self.instruction_limit
        stop_reason = None
        stop_error = None
        executed = 0
        try:
            if self.use_code_hook:
                self.uc.emu_start(self.kernel_load, 0, count=limit)
                executed = self._instructions
            else:
                # Slice-based run: no per-instruction Python callback, so a
                # multi-hundred-million-instruction bring-up stays practical.  The
                # PC after each slice is the sampling record.
                remaining = limit
                while remaining > 0:
                    self._try_inject_irq()
                    slice_size = min(self.slice_size, remaining)
                    pc_now = self.uc.reg_read(UC_ARM_REG_PC)
                    thumb = self.uc.reg_read(UC_ARM_REG_CPSR) & 0x20
                    try:
                        self.uc.emu_start(pc_now | (1 if thumb else 0), 0,
                                          count=slice_size)
                    except Exception as error:
                        message = str(error)
                        if ('UNMAPPED' in message or 'UC_ERR_EXCEPTION' in message
                                or 'FETCH' in message or 'INSN' in message):
                            pc = self.uc.reg_read(UC_ARM_REG_PC)
                            cpsr = self.uc.reg_read(UC_ARM_REG_CPSR)
                            info = self._fault_state()
                            effective = info.get('effective_address')
                            mnemonic = info.get('mnemonic', '')
                            fault_va = int(effective, 16) if effective else None
                            user_mode_cpsr = (cpsr & 0x1F) == 0x10
                            prefetch = ('FETCH' in message
                                        or (fault_va is not None and fault_va == pc)
                                        or (user_mode_cpsr
                                            and (fault_va is None or mnemonic == '')))
                            user_mode = (cpsr & 0x1F) == 0x10
                            if prefetch:
                                address = fault_va if fault_va is not None else pc
                                if self._deliver_prefetch_abort(pc, cpsr, address):
                                    executed += 1
                                    remaining = max(0, remaining - 1)
                                    continue
                            # Demand-paged user VAs (stack/BSS/args) must be reported
                            # to the kernel's do_DataAbort so handle_mm_fault can
                            # allocate the anonymous page; only genuine invalid
                            # accesses (e.g. the futex probe at VA 0) fall back to the
                            # __ex_table fixup.  E0428 fix.
                            user_fault = (self.data_abort_delivery
                                          and fault_va is not None
                                          and 0x1000 <= fault_va < 0x60000000
                                          and (user_mode
                                               or (pc >= 0x60000000
                                                   and self._in_demand_page_helper(pc))))
                            if user_fault:
                                write = mnemonic.startswith(('str', 'stm', 'push'))
                                if self._deliver_data_abort(pc, cpsr, fault_va, write):
                                    executed += 1
                                    remaining = max(0, remaining - 1)
                                    continue
                            if self._try_ex_table_fixup(pc) is not None:
                                executed += 1
                                remaining = max(0, remaining - 1)
                                continue
                            if (not user_fault and fault_va is not None and mnemonic
                                    and 0x1000 <= fault_va < 0x60000000):
                                # Non-user-mapped fault that still looks like user VA:
                                # let do_DataAbort process it (e.g. vmalloc probes).
                                write = mnemonic.startswith(('str', 'stm', 'push'))
                                if self._deliver_data_abort(pc, cpsr, fault_va, write):
                                    executed += 1
                                    remaining = max(0, remaining - 1)
                                    continue
                        if (self.exclusive_fallback
                                and 'UC_ERR_EXCEPTION' in message):
                            pc = self.uc.reg_read(UC_ARM_REG_PC)
                            cpsr = self.uc.reg_read(UC_ARM_REG_CPSR)
                            if self._emulate_exclusive(pc, cpsr):
                                self.exclusive_emulated += 1
                                if len(self.exclusive_trace) < 64:
                                    self.exclusive_trace.append(
                                        {'pc': f'0x{pc:08x}',
                                         'count': self.exclusive_emulated})
                                executed += 1
                                remaining = max(0, remaining - 1)
                                continue
                        raise
                    executed += slice_size
                    remaining -= slice_size
                    self._advance_timer(slice_size)
                    pc = self.uc.reg_read(UC_ARM_REG_PC)
                    self.pc_samples[pc] += 1
                    if self.unmapped and self.unmapped_mmio_policy != 'observe-zero':
                        break
            if not self.unmapped or self.unmapped_mmio_policy == 'observe-zero':
                stop_reason = 'instruction_limit'
        except Exception as error:  # single stop path, report it verbatim
            stop_error = f'{type(error).__name__}: {error}'
            try:
                self.exception_state = self._fault_state()
            except Exception:
                self.exception_state = {}
            if not self.unmapped:
                stop_reason = 'unicorn_error'
        if self.unmapped and stop_reason is None:
            stop_reason = ('instruction_limit'
                           if self.unmapped_mmio_policy == 'observe-zero'
                           else 'unmapped_access')
        self._instructions = executed
        pc = self.uc.reg_read(UC_ARM_REG_PC)
        return self.report(pc, stop_reason, stop_error)

    def report(self, pc: int, stop_reason: str, stop_error: str | None) -> dict:
        hotspots = [
            {'pc': address, 'symbol': self.nearest_symbol(address), 'samples': count}
            for address, count in self.pc_samples.most_common(12)]
        mmio_reads = [{'address': address, 'count': count}
                      for address, count in self.mmio_counts.most_common(48)]
        serial = bytes(self.serial)
        return {
            'machine_id': self.machine_id,
            'kernel_load': self.kernel_load,
            'initrd_load': self.initrd_load,
            'boot_params': self.boot_params,
            'kernel_bytes': len(self.kernel_raw),
            'initrd_bytes': len(self.initrd),
            'atags_bytes': len(self.atags),
            'instruction_limit': self.instruction_limit,
            'instructions_hooked': self._instructions,
            'stop_reason': stop_reason,
            'stop_error': stop_error,
            'stop_pc': pc,
            'stop_symbol': self.nearest_symbol(pc),
            'user_mode_entries': list(self.user_mode_entries),
            'prefetch_aborts_delivered': self.prefetch_aborts_delivered,
            'prefetch_abort_trace': list(self.prefetch_abort_trace),
            'mode_lr': {key: (hex(value) if value is not None else None)
                        for key, value in self.mode_lr.items()},
            'mode_sp': {key: (hex(value) if value is not None else None)
                        for key, value in self.mode_sp.items()},
            'trace_reg_values': {hex(pc): values
                                 for pc, values in self.trace_reg_values.items()},
            'serial_bytes': len(serial),
            'serial_text': serial.decode('latin1', errors='replace'),
            'mmio_reads': mmio_reads,
            'mmio_write_count': sum(self.mmio_writes.values()),
            'stub_hits': {f'0x{address:08x}': count
                          for address, count in self.stub_hits.items()},
            'boot_patch_hits': {f'0x{pc:08x}': count
                                for pc, count in self.patch_hits.items()},
            'hotspots': hotspots,
            'timer_model': {
                'enabled': self.timer_irq_model,
                'timer_irq': self.timer_irq,
                'timer_counter': self._timer_counter,
                'timer_counter_reads': self._timer_counter_reads,
                'ticks_per_instruction': self.timer_ticks_per_instruction,
                'ticks_per_jiffy': self.timer_ticks_per_jiffy,
                'jiffies_injected': self._jiffies_injected,
                'pending': self._timer_irq_pending,
                'gic_enabled': self._gic_enabled,
                'gic_iar_reads': self._gic_iar_reads,
                'gic_iar_pcs': self._gic_iar_pcs,
                'injection_pcs': self._injection_pcs,
                'gic_eoir_writes': self._gic_eoir_writes,
                'gic_active_irq': self._gic_active_irq,
                'gic_registers': {f'{cpu}:0x{offset:02x}': value
                                  for (cpu, offset), value in
                                  sorted(self._gic_regs.items())},
            },
            'unmapped_mmio_mapped': [f'0x{page:08x}'
                                     for page in self._unmapped_mmio_mapped],
            'unmapped_addresses': [{'address': f'0x{address:08x}', 'count': count}
                                   for address, count in
                                   self.unmapped_counts.most_common(256)],
            'mmio_write_candidates': self._mmio_write_candidates(),
            'printk_trace': self.printk_trace[:200],
            'trace_point_hits': self.trace_point_hits[:64],
            'ex_table_entries': getattr(self, 'ex_table_entries', 0),
            'ex_table_fixups': self.ex_table_fixups,
            'ex_table_trace': self.ex_table_trace[:16],
            'data_aborts_delivered': self.data_aborts_delivered,
            'data_abort_trace': self.data_abort_trace[:32],
            'exclusive_patched': self.exclusive_patched,
            'exclusive_emulated': self.exclusive_emulated,
            'exclusive_trace': self.exclusive_trace[:16],
            'exception_state': getattr(self, 'exception_state', None),
            'unmapped': [
                {key: (f'0x{value:08x}' if key in ('pc', 'address') else value)
                 for key, value in entry.items()} for entry in self.unmapped[:64]],
        }


def write_report(report: dict, path) -> None:
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(report, indent=2), encoding='utf-8')
