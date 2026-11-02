"""Check guest page permissions before host-side syscall copies."""


def accessible(mu, address, size, permissions):
    if address < 0 or size < 0 or address + size > 0x100000000:
        return False
    if size == 0:
        return True
    end = address + size
    cursor = address
    for begin, last, protection in sorted(mu.mem_regions()):
        if last + 1 <= cursor:
            continue
        if begin > cursor or protection & permissions != permissions:
            return False
        cursor = min(end, last + 1)
        if cursor == end:
            return True
    return size == 0


def cstring_preview(mu, address, limit=256):
    """Diagnostic only: bounded reads; never resolves or opens a host path."""
    import unicorn
    raw = bytearray()
    for index in range(limit):
        if not accessible(mu, address + index, 1, unicorn.UC_PROT_READ):
            return {'status': 'unreadable', 'bytes_hex': raw.hex()}
        byte = bytes(mu.mem_read(address + index, 1))
        if byte == b'\0':
            return {'status': 'terminated', 'value': raw.decode('utf-8', errors='backslashreplace')}
        raw.extend(byte)
    return {'status': 'limit', 'bytes_hex': raw.hex()}
