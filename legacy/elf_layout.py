"""Small, testable ARM ELF calculations for the bounded research loader.

Reference: ARM aaelf32, relocation table and dynamic relocations section.
This is not a complete dynamic linker.
"""


def load_span(segments, load_bias, page_size=4096):
    segments = list(segments)
    if not segments:
        raise ValueError('ELF contains no PT_LOAD segments')
    if load_bias % page_size:
        raise ValueError('Load bias must be page aligned')
    for segment in segments:
        if segment['p_filesz'] > segment['p_memsz']:
            raise ValueError('ELF segment file size exceeds memory size')
    first = min(s['p_vaddr'] for s in segments) & ~(page_size - 1)
    last = max(s['p_vaddr'] + s['p_memsz'] for s in segments)
    last = (last + page_size - 1) & ~(page_size - 1)
    if last <= first or load_bias + last > 0x100000000:
        raise ValueError('Invalid ARM32 load range')
    return load_bias + first, last - first


def symbol_relocation(symbol_value, addend, is_function=False):
    thumb = (symbol_value & 1) if is_function else 0
    symbol = symbol_value & ~1 if is_function else symbol_value
    return ((symbol + addend) | thumb) & 0xffffffff
