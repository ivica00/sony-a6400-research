"""Explicit selected ARM short-descriptor table walk; not active TTBR discovery."""
import struct


def translate(memory, root, virtual):
    if root % 16384 or not 0 <= root <= 0xffffc000 or not 0 <= virtual < 1 << 32:
        raise ValueError('Invalid selected translation root/address')
    first_address = root + (virtual >> 20) * 4
    first = struct.unpack('<I', memory.read(first_address, 4))[0]
    evidence = {'root': root, 'virtual': virtual, 'l1_address': first_address, 'l1': first}
    if first & 3 == 2:
        if first & (1 << 18):
            if first & 0x00f001e0:
                raise ValueError('Extended-physical supersection unsupported')
            group = root + ((virtual >> 24) << 6)
            if memory.read(group, 64) != struct.pack('<I', first) * 16:
                raise ValueError('Inconsistent replicated supersection descriptors')
            physical = (first & 0xff000000) | (virtual & 0xffffff)
            evidence['supersection'] = True
        else:
            physical = (first & 0xfff00000) | (virtual & 0xfffff)
    elif first & 3 == 1:
        second_address = (first & 0xfffffc00) + ((virtual >> 12) & 255) * 4
        second = struct.unpack('<I', memory.read(second_address, 4))[0]
        if second & 2 == 0:
            raise ValueError('Only small-page L2 descriptors supported')
        physical = (second & 0xfffff000) | (virtual & 4095)
        evidence.update(l2_address=second_address, l2=second)
    else:
        raise ValueError('Unmapped/unsupported first-level descriptor')
    return physical, {**evidence, 'physical': physical}


def read_virtual(memory, root, address, size):
    if not 0 <= size <= 4 * 1024 * 1024 or not 0 <= address <= address + size <= 1 << 32:
        raise ValueError('Virtual read exceeds bounds')
    output = bytearray()
    while size:
        physical, _ = translate(memory, root, address)
        count = min(size, 4096 - (address & 4095))
        output.extend(memory.read(physical, count))
        address += count
        size -= count
    return bytes(output)
