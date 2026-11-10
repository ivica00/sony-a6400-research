"""Read-only guest loader lookup tracing.

Installs a code hook on the original ``_dl_lookup_symbol_x`` entry and
records the arguments of the lookup for one requested symbol.  It never
injects a symbol, changes loader flags or calls guest code; it only observes
the original ld.so invocation and stops when the target lookup is entered.
"""
import struct

from unicorn import UC_HOOK_CODE
from unicorn import arm_const as arm

DEFAULT_LOOKUP_ADDRESS = 0x4000B200
DEFAULT_SYMBOL = ('_ZN29C_DataflowInfra_Entry_OsdMute11SetData_All'
                  'EPN20DataflowInfra_StdOsd12PIN_OSD_MUTEE')


def _cstring(memory_read, address, limit=256):
    if not address:
        return ''
    try:
        raw = bytes(memory_read(address, limit))
    except Exception:
        return ''
    return raw.split(b'\x00', 1)[0].decode('latin1', errors='replace')


def _link_map_name(memory_read, map_address):
    if not map_address:
        return None
    try:
        name_pointer = struct.unpack('<I', bytes(memory_read(map_address + 4, 4)))[0]
    except Exception:
        return None
    return _cstring(memory_read, name_pointer)


def _scope_entries(memory_read, scope_address, limit=64):
    """Read the loader scope: an array of r_scope_elem pointers."""
    entries = []
    if not scope_address:
        return entries
    for index in range(limit):
        try:
            elem = struct.unpack('<I', bytes(memory_read(scope_address + index * 4, 4)))[0]
        except Exception:
            break
        if not elem:
            break
        try:
            r_list, r_nlist = struct.unpack('<II', bytes(memory_read(elem, 8)))
        except Exception:
            break
        names = []
        for item in range(min(r_nlist, 64)):
            try:
                pointer = struct.unpack('<I', bytes(memory_read(r_list + item * 4, 4)))[0]
            except Exception:
                break
            names.append(_link_map_name(memory_read, pointer))
        entries.append({'index': index, 'scope_elem': elem, 'r_list': r_list,
                        'r_nlist': r_nlist, 'names': names})
    return entries


def install_loader_lookup_trace(probe, address=DEFAULT_LOOKUP_ADDRESS,
                                symbol=DEFAULT_SYMBOL, max_records=4):
    """Hook the original loader lookup entry; stop on the target symbol."""
    records = probe.report.setdefault('loader_lookup_trace', [])
    probe.report['loader_lookup_trace_config'] = {
        'address': address, 'symbol': symbol, 'observe_only': True,
    }

    def hook(uc, hook_address, size, user_data):
        name = _cstring(lambda a, n: uc.mem_read(a, n), uc.reg_read(arm.UC_ARM_REG_R0))
        if symbol and name != symbol:
            return
        scope = uc.reg_read(arm.UC_ARM_REG_R2)
        undef_map = uc.reg_read(arm.UC_ARM_REG_R1)
        version = uc.reg_read(arm.UC_ARM_REG_R3)
        record = {
            'instruction': probe.instructions,
            'address': hook_address,
            'tid': getattr(probe.threads, 'current_tid', None),
            'name': name,
            'name_pointer': uc.reg_read(arm.UC_ARM_REG_R0),
            'undef_map': undef_map,
            'undef_map_name': _link_map_name(lambda a, n: uc.mem_read(a, n), undef_map),
            'scope_pointer': scope,
            'version_pointer': version,
            'scopes': _scope_entries(lambda a, n: uc.mem_read(a, n), scope),
            'sp': uc.reg_read(arm.UC_ARM_REG_SP),
            'lr': uc.reg_read(arm.UC_ARM_REG_LR),
        }
        records.append(record)
        if len(records) >= max_records:
            probe.report['loader_lookup_stop'] = record
            uc.emu_stop()

    probe.mu.hook_add(UC_HOOK_CODE, hook, begin=address, end=address + 0x600)
    return records
