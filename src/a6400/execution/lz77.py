"""Sony LZ77: blocks of type 0xf0 (flag byte LSB-first, 2-byte matches) or 0x0f (stored)."""

LENGTHS = tuple(range(3, 17)) + (32, 64)


def inflate_block(data, position, maximum):
    if not 0 <= position < len(data) or not 0 < maximum <= 4 * 1024 * 1024:
        raise ValueError('Invalid bounded LZ77 source/output range')
    out = bytearray()

    def take(count):
        nonlocal position
        if count < 0 or position + count > len(data):
            raise ValueError('Compressed block exceeds supplied bytes')
        result = data[position:position + count]
        position += count
        return result

    def append(value):
        if len(out) + len(value) > maximum:
            raise ValueError('Decompressed block exceeds declared extent')
        out.extend(value)

    kind = take(1)[0]
    if kind == 0x0f:
        take(1)
        count = int.from_bytes(take(2), 'little')
        append(take(count))
    elif kind == 0xf0:
        while True:
            flags = take(1)[0]
            if flags == 0:
                append(take(8))
                continue
            for bit in range(8):
                if flags >> bit & 1:
                    a, b = take(2)
                    distance = (a & 15) << 8 | b
                    if distance == 0:
                        return bytes(out), position
                    length = LENGTHS[a >> 4]
                    if distance > len(out):
                        raise ValueError('LZ77 reference precedes block output')
                    pattern = out[-distance:]
                    append((pattern * ((length + distance - 1) // distance))[:length])
                else:
                    append(take(1))
    else:
        raise ValueError('Unsupported LZ77 block type')
    return bytes(out), position
