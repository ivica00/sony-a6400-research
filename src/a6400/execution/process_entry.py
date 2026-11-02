"""Explicit experimental ARM Linux process stack based on Linux v3.0 ELF setup."""
import struct

AT_NULL, AT_PHDR, AT_PHENT, AT_PHNUM, AT_PAGESZ = 0, 3, 4, 5, 6
AT_BASE, AT_FLAGS, AT_ENTRY = 7, 8, 9
AT_UID, AT_EUID, AT_GID, AT_EGID = 11, 12, 13, 14
AT_PLATFORM, AT_HWCAP, AT_CLKTCK, AT_SECURE, AT_RANDOM, AT_EXECFN = 15, 16, 17, 23, 25, 31


def build_stack(bottom, size, argv, environment, application, interpreter_bias,
                platform='v7l', hwcap=0, random_bytes=bytes(range(16))):
    if not argv or len(random_bytes) != 16 or application['phdr'] is None:
        raise ValueError('Need argv, 16 entropy bytes, and mapped application program headers')
    blob = bytearray(size)
    cursor = size

    def push(raw):
        nonlocal cursor
        cursor -= len(raw)
        if cursor < 0:
            raise ValueError('Process stack overflow')
        blob[cursor:cursor + len(raw)] = raw
        return bottom + cursor

    def push_string(value):
        raw = value.encode('utf-8')
        if b'\0' in raw:
            raise ValueError('Embedded NUL in process string')
        return push(raw + b'\0')

    env = list(reversed([push_string(value) for value in reversed(environment)]))
    args = list(reversed([push_string(value) for value in reversed(argv)]))
    execfn = push_string(argv[0])
    platform_address = push_string(platform)
    random_address = push(random_bytes)
    auxv = [(AT_PHDR, application['phdr']), (AT_PHENT, application['phent']),
            (AT_PHNUM, application['phnum']), (AT_PAGESZ, 4096), (AT_BASE, interpreter_bias),
            (AT_FLAGS, 0), (AT_ENTRY, application['entry']), (AT_UID, 0), (AT_EUID, 0),
            (AT_GID, 0), (AT_EGID, 0), (AT_PLATFORM, platform_address), (AT_HWCAP, hwcap),
            (AT_CLKTCK, 100), (AT_SECURE, 0), (AT_RANDOM, random_address), (AT_EXECFN, execfn), (AT_NULL, 0)]
    words = [len(args), *args, 0, *env, 0, *(value for pair in auxv for value in pair)]
    table = struct.pack('<' + 'I' * len(words), *words)
    cursor = (cursor - len(table)) & ~15
    if cursor < 0:
        raise ValueError('Process stack overflow')
    blob[cursor:cursor + len(table)] = table
    return {'sp': bottom + cursor, 'data': bytes(blob), 'argc': len(args),
            'argv': list(argv), 'environment': list(environment), 'auxv': auxv,
            'random_bytes_hex': random_bytes.hex()}
