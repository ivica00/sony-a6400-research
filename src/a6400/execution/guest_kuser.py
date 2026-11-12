"""ARM Linux kernel helper (kuser) vectors and TLS management.

Extracts the 160-byte kernel helper template directly from the verified kernel image
(vmlinux.bin) and manages the Linux high vectors page at 0xffff0000.
"""
import hashlib
import struct
from pathlib import Path

import unicorn
from unicorn import arm_const as arm

KUSER_PAGE_ADDR = 0xffff0000
KUSER_PAGE_SIZE = 0x1000
KUSER_TEMPLATE_OFFSET = 0xf60
KUSER_TEMPLATE_SIZE = 160
KUSER_TLS_SOFTWARE_SLOT = 0xffff0ff0
KUSER_VERSION_SLOT = 0xffff0ffc

# Expected SHA256 of the 160-byte template extracted from vmlinux.bin
EXPECTED_KUSER_SHA256 = 'f9e6a6128970c915c1b372dbeb16ebed77e032b9be042e21f1540c466d5f4297'
VMLINUX_KUSER_OFFSET = 0x388fe0
# Per-kernel template offsets, keyed by vmlinux.bin SHA-256. The template bytes are still
# checked against EXPECTED_KUSER_SHA256 (byte-identical in the ILCE-6100A V1.01 kernel).
VMLINUX_KUSER_OFFSETS = {
    '12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707': 0x388fe0,  # a6400 V2.00
    '51c1289c9cd698aa570935aa824fe2ebe67230a79ae34c2b413aaef9b3649b87': 0x390fc0,  # ILCE-6100A V1.01
}


def extract_kuser_template(kernel_path_or_bytes, expected_kernel_hash=None):
    """Extract and verify the kuser helper template from vmlinux.bin."""
    if isinstance(kernel_path_or_bytes, (str, Path)):
        data = Path(kernel_path_or_bytes).read_bytes()
    else:
        data = bytes(kernel_path_or_bytes)

    if expected_kernel_hash is not None:
        actual_kernel_hash = hashlib.sha256(data).hexdigest()
        if actual_kernel_hash != expected_kernel_hash:
            raise ValueError(f'Kernel hash mismatch: expected {expected_kernel_hash}, got {actual_kernel_hash}')

    offset = VMLINUX_KUSER_OFFSETS.get(hashlib.sha256(data).hexdigest(), VMLINUX_KUSER_OFFSET)
    template = data[offset:offset + KUSER_TEMPLATE_SIZE]
    if len(template) != KUSER_TEMPLATE_SIZE:
        raise ValueError(f'Kernel image too small to extract kuser template at offset {hex(VMLINUX_KUSER_OFFSET)}')

    template_hash = hashlib.sha256(template).hexdigest()
    if template_hash != EXPECTED_KUSER_SHA256:
        raise ValueError(f'Kuser template hash mismatch: expected {EXPECTED_KUSER_SHA256}, got {template_hash}')

    # Verify version word at offset 0x9c (offset 0xffc in page)
    version = struct.unpack_from('<I', template, 0x9c)[0]
    if version != 5:
        raise ValueError(f'Unexpected kuser helper version: {version} (expected 5)')

    return template


class GuestKuser:
    """Manages the ARM Linux high vectors page and TLS register/slot."""

    def __init__(self, mu, template_bytes):
        if len(template_bytes) != KUSER_TEMPLATE_SIZE:
            raise ValueError(f'Template must be exactly {KUSER_TEMPLATE_SIZE} bytes')
        template_hash = hashlib.sha256(template_bytes).hexdigest()
        if template_hash != EXPECTED_KUSER_SHA256:
            raise ValueError(f'Template hash mismatch: {template_hash}')
        self.mu = mu
        self.template = bytes(template_bytes)
        self.tls_value = 0

    def map_page(self):
        """Map the high vectors page at 0xffff0000 with the verified helper template."""
        self.mu.mem_map(KUSER_PAGE_ADDR, KUSER_PAGE_SIZE, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
        self.mu.mem_write(KUSER_PAGE_ADDR + KUSER_TEMPLATE_OFFSET, self.template)

    def set_tls(self, tls_val):
        """Service ARM private syscall sys_arm_set_tls (0xf0005).

        Updates both hardware CP15 C13 User Read-Only Thread ID register and the
        kuser helper software slot at 0xffff0ff0.
        """
        self.tls_value = tls_val & 0xffffffff
        self.mu.reg_write(arm.UC_ARM_REG_C13_C0_3, self.tls_value)

        # Update software slot at 0xffff0ff0
        self.mu.mem_protect(KUSER_PAGE_ADDR, KUSER_PAGE_SIZE,
                            unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE | unicorn.UC_PROT_EXEC)
        self.mu.mem_write(KUSER_TLS_SOFTWARE_SLOT, struct.pack('<I', self.tls_value))
        self.mu.mem_protect(KUSER_PAGE_ADDR, KUSER_PAGE_SIZE,
                            unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
        return self.tls_value
