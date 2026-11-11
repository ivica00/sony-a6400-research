"""Schema and evidence-discipline validator for `uvc_dma_probe` JSON reports.

Stdlib only, no hardware, no WSL.  The validator is deliberately about the
*contract of the report*, not about the C implementation:

  * required top-level sections exist and nothing unexpected appears;
  * every value has the type the probe promises;
  * a value that would be an unbacked claim is rejected, e.g. a kallsyms entry
    without an address, a device-node entry with neither major:minor nor an
    errno, a masked (all-zero) kallsyms address not flagged `restricted`;
  * the declared caps are actually enforced (get_jpeg_polls <= 100,
    /dev/mem read <= 4096 bytes, uipc window <= 131072 bytes) and the observed
    byte counts do not exceed them;
  * the safety switches stay off (`bulk_devmem_scan`, `device_node_opened_for_io`).

Used by probes/build_probe.py --host-check and by tests/test_probes_report.py.
"""
import json
import re
import sys
from pathlib import Path

TOP_LEVEL = (
    'identity', 'modules', 'udc', 'devnodes', 'pid149', 'kallsyms', 'uipc',
    'get_jpeg_polls', 'bounds', 'notes',
)
OPTIONAL_TOP_LEVEL = (
    'schema', 'tool', 'get_jpeg_frame', 'get_jpeg_error', 'devmem', 'exit_code',
)
MAX_POLLS = 100
MAX_DEVMEM_LEN = 4096
UIPC_READ_CAP = 131072
MAPS_READ_CAP = 65536
DIR_NAMES_CAP = 192
HEX8 = re.compile(r'^0x[0-9a-f]{8}$')
QID = re.compile(r'^0x[0-9a-f]{8}$')


class ReportError(ValueError):
    """Raised when a report does not satisfy the probe's contract."""


def _fail(where, message):
    raise ReportError(f'{where}: {message}')


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _int(where, value, low=None, high=None):
    if not _is_int(value):
        _fail(where, f'expected an integer, got {type(value).__name__}')
    if low is not None and value < low:
        _fail(where, f'{value} is below the minimum {low}')
    if high is not None and value > high:
        _fail(where, f'{value} is above the maximum {high}')
    return value


def _bool(where, value):
    if not isinstance(value, bool):
        _fail(where, f'expected a boolean, got {type(value).__name__}')
    return value


def _str(where, value, allow_empty=False):
    if not isinstance(value, str):
        _fail(where, f'expected a string, got {type(value).__name__}')
    if not allow_empty and not value:
        _fail(where, 'expected a non-empty string')
    return value


def _optional_int(where, value):
    if value is None:
        return None
    return _int(where, value)


def _check_identity(report):
    identity = report['identity']
    if not isinstance(identity, dict):
        _fail('identity', 'expected an object')
    for key in ('uptime', 'version', 'cmdline', 'devices'):
        if key not in identity:
            _fail(f'identity.{key}', 'missing')
        _str(f'identity.{key}', identity[key], allow_empty=True)


def _check_modules(report):
    modules = report['modules']
    if isinstance(modules, dict):
        _int('modules.errno', modules.get('errno'), low=-4096, high=0)
        entries = modules.get('entries')
        if not isinstance(entries, list):
            _fail('modules.entries', 'expected a list')
        return
    if not isinstance(modules, list):
        _fail('modules', 'expected a list or an object')
    for index, module in enumerate(modules):
        where = f'modules[{index}]'
        if not isinstance(module, dict):
            _fail(where, 'expected an object')
        _str(f'{where}.name', module.get('name'))
        _int(f'{where}.size', module.get('size'), low=0)
        _int(f'{where}.refcount', module.get('refcount'), low=0)
        _str(f'{where}.state', module.get('state'), allow_empty=True)
        address = module.get('address')
        if address is not None and not HEX8.match(_str(f'{where}.address', address)):
            _fail(f'{where}.address', 'expected 0x + 8 hex digits')


def _check_attr(where, attr):
    if not isinstance(attr, dict):
        _fail(where, 'expected an object with value or errno')
    if 'value' in attr:
        _str(f'{where}.value', attr['value'], allow_empty=True)
        return
    if 'errno' in attr:
        _int(f'{where}.errno', attr['errno'], low=-4096, high=0)
        return
    _fail(where, 'neither value nor errno')


def _check_udc(report):
    udc = report['udc']
    if isinstance(udc, dict):
        _int('udc.errno', udc.get('errno'), low=-4096, high=0)
        entries = udc.get('entries')
        if not isinstance(entries, list):
            _fail('udc.entries', 'expected a list')
        return
    if not isinstance(udc, list):
        _fail('udc', 'expected a list or an object')
    for index, attr_owner in enumerate(udc):
        where = f'udc[{index}]'
        if not isinstance(attr_owner, dict):
            _fail(where, 'expected an object')
        _str(f'{where}.name', attr_owner.get('name'))
        for attr in ('state', 'current_speed', 'maximum_speed', 'active', 'is_otg'):
            if attr not in attr_owner:
                _fail(f'{where}.{attr}', 'missing')
            _check_attr(f'{where}.{attr}', attr_owner[attr])


def _check_listing(where, entry):
    if not isinstance(entry, dict):
        _fail(where, 'expected an object')
    _str(f'{where}.path', entry.get('path'))
    listing = entry.get('listing')
    if not isinstance(listing, dict):
        _fail(f'{where}.listing', 'expected an object')
    errno = listing.get('errno')
    if errno is not None:
        _int(f'{where}.listing.errno', errno, low=-4096, high=0)
    names = listing.get('names')
    if not isinstance(names, list):
        _fail(f'{where}.listing.names', 'expected a list')
    if len(names) > DIR_NAMES_CAP:
        _fail(f'{where}.listing.names', f'{len(names)} entries exceeds the cap {DIR_NAMES_CAP}')
    for index, name in enumerate(names):
        _str(f'{where}.listing.names[{index}]', name)
    count = _int(f'{where}.listing.count', listing.get('count'), low=0)
    if errno is None and count != len(names):
        _fail(f'{where}.listing.count', 'count does not match the names list')


def _check_stat_entry(where, node):
    if not isinstance(node, dict):
        _fail(where, 'expected an object')
    path = _str(f'{where}.path', node.get('path'))
    if not path.startswith('/'):
        _fail(f'{where}.path', 'expected an absolute path')
    present = _bool(f'{where}.present', node.get('present'))
    errno = node.get('errno')
    if not present:
        if errno is None:
            _fail(where, 'absent node must record the exact errno')
        _int(f'{where}.errno', errno, low=-4096, high=0)
        return
    if errno is not None:
        # present but undecodable: the probe must say so with a negative errno
        _int(f'{where}.errno', errno, low=-4096, high=0)
        return
    major = node.get('major')
    minor = node.get('minor')
    if major is None or minor is None:
        _fail(where, 'present node needs major+minor or an errno')
    _int(f'{where}.major', major, low=0, high=0xfff)
    _int(f'{where}.minor', minor, low=0, high=0xfffff)


def _check_devnodes(report):
    devnodes = report['devnodes']
    if not isinstance(devnodes, dict):
        _fail('devnodes', 'expected an object')
    listings = devnodes.get('listings')
    if not isinstance(listings, list):
        _fail('devnodes.listings', 'expected a list')
    for index, entry in enumerate(listings):
        _check_listing(f'devnodes.listings[{index}]', entry)
    stats = devnodes.get('stat')
    if not isinstance(stats, list):
        _fail('devnodes.stat', 'expected a list')
    for index, node in enumerate(stats):
        _check_stat_entry(f'devnodes.stat[{index}]', node)


def _check_pid149(report):
    pid = report['pid149']
    if not isinstance(pid, dict):
        _fail('pid149', 'expected an object')
    status = pid.get('status')
    if not isinstance(status, dict):
        _fail('pid149.status', 'expected an object')
    for key, value in status.items():
        if key == 'errno':
            _int('pid149.status.errno', value, low=-4096, high=0)
            continue
        _str(f'pid149.status.{key}', value, allow_empty=True)
    _int('pid149.maps_bytes', pid.get('maps_bytes'), low=0, high=MAPS_READ_CAP)
    _bool('pid149.maps_truncated', pid.get('maps_truncated'))
    mappings = pid.get('mappings')
    if not isinstance(mappings, list):
        _fail('pid149.mappings', 'expected a list')
    for index, mapping in enumerate(mappings):
        where = f'pid149.mappings[{index}]'
        if not isinstance(mapping, dict):
            _fail(where, 'expected an object')
        _str(f'{where}.path', mapping.get('path'))
        base = _int(f'{where}.base', mapping.get('base'), low=1, high=0xffffffff)
        end = _int(f'{where}.end', mapping.get('end'), low=1, high=0xffffffff)
        if end <= base:
            _fail(where, 'end must be greater than base')
    _int('pid149.fd_count', pid.get('fd_count'), low=0)
    fds = pid.get('fds')
    if not isinstance(fds, list):
        _fail('pid149.fds', 'expected a list')
    for index, entry in enumerate(fds):
        where = f'pid149.fds[{index}]'
        if not isinstance(entry, dict):
            _fail(where, 'expected an object')
        _str(f'{where}.fd', entry.get('fd'))
        if entry.get('target') is None and entry.get('errno') is None:
            _fail(where, 'neither a readlink target nor an errno')
        if entry.get('target') is not None:
            _str(f'{where}.target', entry['target'], allow_empty=True)
        if entry.get('errno') is not None:
            _int(f'{where}.errno', entry['errno'], low=-4096, high=0)
    _int('pid149.thread_count', pid.get('thread_count'), low=0)


def _check_kallsyms(report):
    kallsyms = report['kallsyms']
    if not isinstance(kallsyms, dict):
        _fail('kallsyms', 'expected an object')
    _bool('kallsyms.readable', kallsyms.get('readable'))
    _int('kallsyms.bytes_read', kallsyms.get('bytes_read'), low=0)
    symbols = kallsyms.get('symbols')
    if not isinstance(symbols, dict):
        _fail('kallsyms.symbols', 'expected an object')
    if not symbols:
        _fail('kallsyms.symbols', 'the exact symbol list must always be present')
    for name, entry in symbols.items():
        where = f'kallsyms.symbols.{name}'
        if entry is None:
            continue
        if not isinstance(entry, dict):
            _fail(where, 'expected null or an object')
        if 'address' not in entry:
            _fail(where, 'a found symbol without an address is a fabricated claim')
        address = _str(f'{where}.address', entry['address'])
        if not HEX8.match(address):
            _fail(f'{where}.address', f'{address!r} is not 0x + 8 hex digits')
        _str(f'{where}.type', entry.get('type'))
        if int(address, 16) == 0 and entry.get('restricted') is not True:
            _fail(f'{where}.address', 'zero address must be flagged restricted=true')


def _check_uipc(report):
    uipc = report['uipc']
    if not isinstance(uipc, dict):
        _fail('uipc', 'expected an object')
    _bool('uipc.opened', uipc.get('opened'))
    errno = uipc.get('errno')
    if errno is not None:
        _int('uipc.errno', errno, low=-4096, high=0)
    _int('uipc.bytes_read', uipc.get('bytes_read'), low=0, high=UIPC_READ_CAP)
    _bool('uipc.truncated', uipc.get('truncated'))
    counts = uipc.get('counts')
    if not isinstance(counts, list) or not counts:
        _fail('uipc.counts', 'expected a non-empty list')
    seen = set()
    for index, entry in enumerate(counts):
        where = f'uipc.counts[{index}]'
        if not isinstance(entry, dict):
            _fail(where, 'expected an object')
        qid = _str(f'{where}.qid', entry.get('qid'))
        if not QID.match(qid):
            _fail(f'{where}.qid', f'{qid!r} is not 0x + 8 hex digits')
        if qid in seen:
            _fail(f'{where}.qid', 'duplicate queue id')
        seen.add(qid)
        for key in ('ascii_8hex_lower', 'ascii_8hex_upper', 'ascii_0x', 'raw_le_bytes'):
            _int(f'{where}.{key}', entry.get(key), low=0)
    _str('uipc.minfo_head', uipc.get('minfo_head'), allow_empty=True)
    _str('uipc.ulogio_head', uipc.get('ulogio_head'), allow_empty=True)


def _check_polls(report, bounds):
    polls = report['get_jpeg_polls']
    if polls is None:
        return
    if not isinstance(polls, list):
        _fail('get_jpeg_polls', 'expected null or a list')
    if len(polls) > MAX_POLLS:
        _fail('get_jpeg_polls', f'{len(polls)} polls exceeds the cap {MAX_POLLS}')
    cap = bounds.get('get_jpeg_polls_cap')
    if _is_int(cap) and len(polls) > cap:
        _fail('get_jpeg_polls', 'more polls than the declared cap')
    for index, poll in enumerate(polls):
        where = f'get_jpeg_polls[{index}]'
        if not isinstance(poll, dict):
            _fail(where, 'expected an object')
        _int(f'{where}.index', poll.get('index'), low=0)
        _int(f'{where}.err', poll.get('err'))
        ready = _int(f'{where}.ready', poll.get('ready'), low=0, high=1)
        for key in ('size_shift', 'handle1', 'handle2'):
            value = poll.get(key)
            if ready == 1:
                _int(f'{where}.{key}', value, low=0)
            elif value is not None:
                _fail(f'{where}.{key}', 'no frame was ready, so this must be null')


def _check_frame(report):
    frame = report.get('get_jpeg_frame')
    if frame is None:
        return
    if not isinstance(frame, dict):
        _fail('get_jpeg_frame', 'expected null or an object')
    for key in ('handle1', 'handle2', 'size_shift', 'size_upper_bound', 'dmm_size'):
        _int(f'get_jpeg_frame.{key}', frame.get(key), low=0)
    _str('get_jpeg_frame.dmm_phys', frame.get('dmm_phys'))
    _bool('get_jpeg_frame.cleanup_complete', frame.get('cleanup_complete'))
    size_shift = frame['size_shift']
    if frame['size_upper_bound'] != size_shift << 7:
        _fail('get_jpeg_frame.size_upper_bound', 'must equal size_shift << 7')


def _check_bounds(report):
    bounds = report['bounds']
    if not isinstance(bounds, dict):
        _fail('bounds', 'expected an object')
    _int('bounds.maps_cap_bytes', bounds.get('maps_cap_bytes'), low=1, high=MAPS_READ_CAP)
    _int('bounds.maps_bytes_read', bounds.get('maps_bytes_read'), low=0,
         high=bounds['maps_cap_bytes'])
    _int('bounds.uipc_cap_bytes', bounds.get('uipc_cap_bytes'), low=1, high=UIPC_READ_CAP)
    _int('bounds.uipc_bytes_read', bounds.get('uipc_bytes_read'), low=0,
         high=bounds['uipc_cap_bytes'])
    _int('bounds.fd_cap', bounds.get('fd_cap'), low=1)
    _int('bounds.dir_names_cap', bounds.get('dir_names_cap'), low=1, high=DIR_NAMES_CAP)
    _int('bounds.get_jpeg_polls_cap', bounds.get('get_jpeg_polls_cap'), low=1, high=MAX_POLLS)
    _int('bounds.devmem_len_cap', bounds.get('devmem_len_cap'), low=1, high=MAX_DEVMEM_LEN)
    _int('bounds.devmem_len', bounds.get('devmem_len'), low=0, high=bounds['devmem_len_cap'])
    _int('bounds.read_chunk_bytes', bounds.get('read_chunk_bytes'), low=1)
    if bounds.get('bulk_devmem_scan') is not False:
        _fail('bounds.bulk_devmem_scan', 'must be false: bulk /dev/mem scans are banned')
    opened = bounds.get('device_node_opened_for_io')
    if not isinstance(opened, bool):
        _fail('bounds.device_node_opened_for_io', 'expected a boolean')
    opt_in = report.get('devmem') is not None or report.get('get_jpeg_polls') is not None
    if opened and not opt_in:
        _fail('bounds.device_node_opened_for_io',
              'a device node was opened for I/O without any opt-in section')
    return bounds


def _check_devmem(report, bounds):
    devmem = report.get('devmem')
    if devmem is None:
        return
    if not isinstance(devmem, dict):
        _fail('devmem', 'expected an object')
    length = _int('devmem.len', devmem.get('len'), low=0, high=MAX_DEVMEM_LEN)
    if length > bounds['devmem_len_cap']:
        _fail('devmem.len', 'larger than the declared devmem_len_cap')
    _int('devmem.bytes_read', devmem.get('bytes_read'), low=0, high=length)
    _str('devmem.pa', devmem.get('pa'))
    errno = devmem.get('errno')
    if errno is not None:
        _int('devmem.errno', errno, low=-4096, high=0)


def _check_notes(report):
    notes = report['notes']
    if not isinstance(notes, list):
        _fail('notes', 'expected a list')
    if len(notes) > 32:
        _fail('notes', 'more notes than the probe can hold')
    for index, note in enumerate(notes):
        _str(f'notes[{index}]', note)


def validate_report(report):
    """Validate one decoded report; raise ReportError on any contract violation."""
    if not isinstance(report, dict):
        _fail('report', 'expected an object')
    missing = [key for key in TOP_LEVEL if key not in report]
    if missing:
        _fail('report', f'missing top-level keys: {missing}')
    unexpected = [key for key in report if key not in TOP_LEVEL + OPTIONAL_TOP_LEVEL]
    if unexpected:
        _fail('report', f'unexpected top-level keys: {unexpected}')
    if 'schema' in report:
        _str('schema', report['schema'])
        if report['schema'] != 'a6400-uvc-dma-probe/1':
            _fail('schema', 'unknown report schema')
    if 'exit_code' in report:
        _int('exit_code', report['exit_code'], low=0, high=4)
        if report['exit_code'] in (3, 4):
            _fail('exit_code', 'a refused or fatal run must not emit a report')
    _check_identity(report)
    _check_modules(report)
    _check_udc(report)
    _check_devnodes(report)
    _check_pid149(report)
    _check_kallsyms(report)
    _check_uipc(report)
    bounds = _check_bounds(report)
    _check_polls(report, bounds)
    _check_frame(report)
    _check_devmem(report, bounds)
    _check_notes(report)
    return True


def validate_file(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    validate_report(data)
    return data


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print('usage: test_probe_report.py REPORT.json [REPORT.json ...]', file=sys.stderr)
        return 2
    status = 0
    for name in argv:
        try:
            report = validate_file(name)
        except (OSError, json.JSONDecodeError, ReportError) as exc:
            print(f'FAIL {name}: {exc}', file=sys.stderr)
            status = 1
            continue
        print(f'OK {name}: schema={report.get("schema")} '
              f'exit_code={report.get("exit_code")} notes={len(report["notes"])}')
    return status


if __name__ == '__main__':
    sys.exit(main())
