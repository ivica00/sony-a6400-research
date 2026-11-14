"""Render the guest's own mapping table in Linux /proc/<pid>/maps format.

Input is the emulator's live state (Unicorn regions, GuestMmap records, named ELF/stack/heap
ranges), not camera data; only the line format is the camera's (etc/a6400_hw_dump.txt, im.elf maps).
"""
import re

MAP_SHARED = 0x1
PATH_COLUMN = 49  # kernel pads the path to column 25 + 6 * sizeof(void *) on 32-bit ARM
PROC_MAPS_RE = re.compile(r'^/proc/(self|\d+)/maps$')


def _perms(bits, shared):
    return ('r' if bits & 1 else '-') + ('w' if bits & 2 else '-') + ('x' if bits & 4 else '-') + ('s' if shared else 'p')


def render_proc_maps(regions, mappings, named=(), file_ids=None):
    """regions: (start, end_exclusive, unicorn_perms); mappings: GuestMmap.mappings;
    named: (start, end, label); file_ids: path -> (major, minor, inode) or None. Returns bytes."""
    segments = []  # (start, end, perms, shared, offset, path, label)
    for start, end, perms in sorted(regions):
        points = {start, end}
        for m in mappings:
            lo, hi = m['address'], m['address'] + m['length']
            if lo < end and hi > start:
                points.update((max(lo, start), min(hi, end)))
        for lo, hi, _ in named:
            if lo < end and hi > start:
                points.update((max(lo, start), min(hi, end)))
        cuts = sorted(points)
        for a, b in zip(cuts, cuts[1:]):
            owner = next((m for m in reversed(mappings)
                          if m['address'] <= a and b <= m['address'] + m['length']), None)
            path, offset, shared, label = None, 0, False, None
            if owner is not None and owner.get('path'):
                path, offset = owner['path'], owner.get('offset', 0) + a - owner['address']
                shared = bool(owner.get('flags', 0) & MAP_SHARED)
            elif owner is None:
                label = next((n for lo, hi, n in named if lo <= a and b <= hi), None)
            segments.append((a, b, perms, shared, offset, path, label))
    lines = []
    for seg in segments:
        a, b, perms, shared, offset, path, label = seg
        if lines:
            la, lb, lperms, lshared, loff, lpath, llabel = lines[-1]
            contiguous = lb == a and (lperms, lshared, lpath, llabel) == (perms, shared, path, label)
            if contiguous and (not path or loff + (lb - la) == offset):
                lines[-1] = (la, b, lperms, lshared, loff, lpath, llabel)
                continue
        lines.append(seg)
    out = []
    for a, b, perms, shared, offset, path, label in lines:
        dev = (file_ids(path) if path and file_ids else None) or (0, 0, 0)
        head = f'{a:08x}-{b:08x} {_perms(perms, shared)} {offset:08x} {dev[0]:02x}:{dev[1]:02x} {dev[2]} '
        name = path or label
        out.append(head + ' ' * max(1, PATH_COLUMN - len(head)) + name if name else head.rstrip())
    return ('\n'.join(out) + '\n').encode() if out else b''
