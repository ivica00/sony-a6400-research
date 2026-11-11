"""ZV-E10 UVC-chain enablement manifest for the a6400 target (E0321).

Pure helpers only: parse the Sony `devno.ko` device-node table, compare hash-
pinned ZV-E10 UVC components with an a6400 tree, verify module vermagic / API
symbols and model the offline device-node namespace.  Everything here is data:
no deployment, camera access, module load or fabricated compatibility.  The
overlay plan built from this module is always non-executable (E0322).
"""

import hashlib
import re
from pathlib import Path

# Hash-pinned ZV-E10 2.03 UVC chain (E0316/E0320).
ZVE10_UVC_COMPONENTS = {
    'usbg_video.ko': {
        'size': 20668,
        'sha256': 'd385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb',
        'role': 'UVC gadget video driver (iso-in, DMA330, /dev/usb/video)',
    },
    'usbg_audio.ko': {
        'size': 20456,
        'sha256': '8f73572784aab15da291c9f311a945d4ec56d2dd4162218164bc2aa18cc5fae0',
        'role': 'UVC audio gadget driver',
    },
    'libInfraStreamingUsb.so': {
        'size': 52524,
        'sha256': '0a9448e364e8f014db02edc8e164470c70f2d2143ce5de74697e9ffba697cce8',
        'role': 'UVC host start/stop, PROBE/COMMIT state machine, VideoEsManager',
    },
    'libInfraUsbCmn.so': {
        'size': 94612,
        'sha256': 'af830315ce51c38b010995f2147d556286364323734f64b877fcc3bb1a916c02',
        'role': 'CUsbGadgetStreaming, PAL/NTSC tables, video buffer API',
    },
    'devno.ko': {
        'size': 4368,
        'sha256': '273db657a8e2c9c8752b0ace56817357ddea38285a52b5cb7007a3fcf9df33c1',
        'role': 'device-node table with /dev/usb/audio + /dev/usb/video',
    },
}
ZVE10_REQUIRED_USB_NODES = {
    '/dev/usb/audio': {'major': 248, 'minor': 0x20},
    '/dev/usb/video': {'major': 248, 'minor': 0x21},
}
A6400_DEVNO_SHA256 = (
    '3b36fcea8687d7f29112a7008ce61fde9229679ebc24c65ec2d21cf3af632f56')
# a6400 module exports that satisfy the ZV-E10 UVC chain imports (E0316).
A6400_PROVIDER_MODULES = ('dma330.ko', 'osal_uipc.ko', 'usbg_cmn.ko',
                          'usb_gadgetcore.ko')

DEVNO_ENTRY_SIZE = 12
DEVNO_FIRST_NAME = b'nflasha\x00'
DEVNO_USB_MAJOR = 248

# Kernel vermagic observed on both the a6400 8.2.5.7 and ZV-E10 2.03 module
# chains (E0316/E0320).  Symbol/vermagic parity is not loadability proof.
ZVE10_VERMAGIC = '3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7'

# API symbols that must be exported by the a6400 provider module (usbg_cmn.ko)
# and referred to by the ZV-E10 UVC consumer modules.  Names are from the
# emitted module symbol tables (E0319/E0320), not assumptions.
ZVE10_API_SYMBOLS = {
    'providers': (
        'usbg_cmn_reg',
        'usbg_cmn_dereg',
        'usbg_cmn_copy_probe_info',
        'usbg_cmn_clear_probe_info',
        'usbg_cmn_make_ep_list',
        'usbg_cmn_clear_ep_list',
        'usb_sync_alloc_phys_buffer',
        'usb_sync_free_phys_buffer',
    ),
    'consumers': (
        'usb_gadgetcore_register_driver',
        'usb_gadgetcore_unregister_driver',
        'usb_sync_alloc_phys_buffer',
        'usb_sync_free_phys_buffer',
        'usbg_cmn_reg',
        'usbg_cmn_dereg',
        'usbg_cmn_copy_probe_info',
        'usbg_cmn_clear_probe_info',
        'usbg_cmn_make_ep_list',
        'osal_snd_msg',
        'osal_rcv_msg_tmo',
    ),
    # Video-only references (the audio driver does not import DMA330).
    'consumer_specific': {
        'usbg_video.ko': ('dma330_mem_transfer_async',),
    },
}

# Physical load always needs a separate explicit authorization plus recovery
# and teardown evidence; no code path here is allowed to authorize itself.
LOAD_AUTHORIZATION_FIELDS = ('authorized', 'explicit_scope',
                             'recovery_plan', 'teardown_receipts')


def parse_devno_table(table_bytes, names_data):
    """Parse a Sony `devno.ko` table into ``path -> {major, minor, ...}``.

    ``table_bytes`` is the raw ``udif_devnodes`` object; ``names_data`` is the
    module blob used to resolve name offsets (E0320 layout: 12-byte entries
    ``{name_offset, dev_t, flags}`` relative to the first device name).  For
    ``usb/*`` entries the flags word is ``0x10000 | minor``.  Returns ``{}``
    when the anchor is absent; never guesses.
    """
    anchor = names_data.find(DEVNO_FIRST_NAME)
    if anchor < 0:
        return {}
    data = table_bytes
    # Locate the udif_devnodes object: walk the ELF section table minimally is
    # out of scope for the pure parser; callers pass exactly the table bytes.
    entries = {}
    offset = 0
    while offset + DEVNO_ENTRY_SIZE <= len(data):
        chunk = data[offset:offset + DEVNO_ENTRY_SIZE]
        name_offset, dev_t, flags = (
            int.from_bytes(chunk[0:4], 'little'),
            int.from_bytes(chunk[4:8], 'little'),
            int.from_bytes(chunk[8:12], 'little'),
        )
        end = names_data.find(b'\x00', anchor + name_offset)
        if end < 0:
            break
        name = names_data[anchor + name_offset:end].decode('latin1', 'replace')
        # Sony devno codes use major<<16 | minor; the usb/* group keeps its
        # minor in the flags word (0x10000 | minor, E0320).
        major = dev_t >> 16
        minor = dev_t & 0xFFFF
        if 0x10000 <= flags < 0x20000:
            minor = flags - 0x10000
        entries[name] = {
            'major': major,
            'minor': minor,
            'dev_t': dev_t,
            'flags': flags,
        }
        offset += DEVNO_ENTRY_SIZE
    return entries


def hash_file(path):
    digest = hashlib.sha256()
    size = 0
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
            size += len(chunk)
    return {'size': size, 'sha256': digest.hexdigest()}


def module_vermagic(path):
    data = Path(path).read_bytes()
    match = re.search(rb'vermagic=([^\x00]+)', data)
    return match.group(1).decode('latin1', 'replace').strip() if match else None


def module_symbol_names(path):
    """Return the sorted symbol names from a module/ELF file (offline helper).

    Prefers the full `.symtab` (kernel modules keep it) and falls back to
    `.dynsym` for user-space libraries.  Returns `()` when neither exists.
    """
    from elftools.elf.elffile import ELFFile

    names = set()
    with open(path, 'rb') as handle:
        elf = ELFFile(handle)
        for section_name in ('.symtab', '.dynsym'):
            section = elf.get_section_by_name(section_name)
            if section is None:
                continue
            for symbol in section.iter_symbols():
                if symbol.name:
                    names.add(symbol.name)
    return tuple(sorted(names))


def compare_components(present):
    """Compare ``{name: hashes}`` against the pinned ZV-E10 components."""
    report = {}
    for name, pinned in ZVE10_UVC_COMPONENTS.items():
        found = present.get(name)
        if found is None:
            report[name] = {'status': 'missing', 'pinned_sha256': pinned['sha256']}
            continue
        matches = (found['size'] == pinned['size'] and
                   found['sha256'] == pinned['sha256'])
        report[name] = {
            'status': 'verified' if matches else 'hash_mismatch',
            'pinned_sha256': pinned['sha256'],
            'found_sha256': found['sha256'],
        }
    return report


def verify_component_hashes(present):
    """Fail-closed hash verification with an explicit refusal list."""
    report = compare_components(present)
    refusals = []
    for name, row in report.items():
        if row['status'] == 'missing':
            refusals.append('component_missing: ' + name)
        elif row['status'] == 'hash_mismatch':
            refusals.append('component_hash_mismatch: ' + name)
    return {
        'components': report,
        'verified': not refusals,
        'refusals': refusals,
    }


def verify_vermagic(vermagic_by_component, expected=ZVE10_VERMAGIC):
    """Verify every supplied module vermagic equals the pinned expected value.

    Missing/empty vermagic is a refusal (never assume compatibility).
    """
    found = {}
    refusals = []
    for name in sorted(vermagic_by_component):
        value = vermagic_by_component[name]
        found[name] = {'vermagic': value}
        if not value:
            refusals.append('vermagic_missing: ' + name)
        elif value != expected:
            refusals.append('vermagic_mismatch: ' + name)
    return {
        'expected': expected,
        'modules': found,
        'equal': not refusals and bool(found),
        'refusals': refusals,
    }


def verify_api_symbols(provider_symbols, consumer_symbols,
                       requirements=ZVE10_API_SYMBOLS):
    """Verify provider exports and consumer references for the UVC chain.

    ``provider_symbols``/``consumer_symbols`` map module name -> iterable of
    symbol names (or ``None`` when unavailable).  Missing provider exports or
    consumer references are refusals; unknown modules are refused too.
    """
    provider_rows = {}
    consumer_rows = {}
    refusals = []
    for name, symbols in sorted(provider_symbols.items()):
        available = set(symbols or ())
        missing = [s for s in requirements['providers'] if s not in available]
        provider_rows[name] = {'missing': missing, 'symbol_count': len(available)}
        if missing:
            refusals.append('api_provider_missing: %s (%s)'
                            % (name, ', '.join(missing)))
    for name, symbols in sorted(consumer_symbols.items()):
        available = set(symbols or ())
        required = list(requirements['consumers'])
        required.extend(requirements.get('consumer_specific', {}).get(name, ()))
        missing = [s for s in required if s not in available]
        consumer_rows[name] = {'missing': missing, 'symbol_count': len(available)}
        if missing:
            refusals.append('api_consumer_missing: %s (%s)'
                            % (name, ', '.join(missing)))
    if not provider_symbols:
        refusals.append('api_provider_missing: no provider module supplied')
    if not consumer_symbols:
        refusals.append('api_consumer_missing: no consumer module supplied')
    return {
        'providers': provider_rows,
        'consumers': consumer_rows,
        'ok': not refusals,
        'refusals': refusals,
    }


def _normalise_devno_path(path):
    if path.startswith('/dev/'):
        return path
    if path.startswith('/'):
        return path
    return '/dev/' + path


def model_devno_usb_namespace(entries, required_nodes=ZVE10_REQUIRED_USB_NODES,
                              usb_major=DEVNO_USB_MAJOR):
    """Model the offline /dev/usb node namespace from parsed devno entries.

    This is a read-only model: it records which required nodes the table would
    register, their dev_t identity and whether they match the required
    248:32/33 spec.  It never installs a node (`installable` is always False,
    `install_policy` is declared-overlay-only).
    """
    nodes = {}
    missing = []
    mismatched = []
    invalid = []
    for path, required in sorted(required_nodes.items()):
        found = entries.get(path[5:]) or entries.get(path) or entries.get(
            path.lstrip('/'))
        if found is None:
            missing.append(path)
            nodes[path] = {
                'required_dev': '%d:%d' % (required['major'], required['minor']),
                'found_dev': None,
                'registered': False,
                'spec_matches': False,
            }
            continue
        dev = '%d:%d' % (found['major'], found['minor'])
        matches = (found['major'], found['minor']) == (
            required['major'], required['minor'])
        if not matches:
            mismatched.append(path)
        nodes[path] = {
            'required_dev': '%d:%d' % (required['major'], required['minor']),
            'found_dev': dev,
            'registered': True,
            'spec_matches': matches,
        }
    # Any usb/* entry whose major is not the UVC usb major is invalid for this
    # namespace even if it is not one of the required nodes.
    for path, row in sorted(entries.items()):
        normalised = _normalise_devno_path(path)
        if not normalised.startswith('/dev/usb/'):
            continue
        if normalised in required_nodes:
            continue
        if row['major'] != usb_major:
            invalid.append('%s (%d:%d)' % (normalised, row['major'],
                                           row['minor']))
    refusals = []
    for path in missing:
        refusals.append('device_node_absent: ' + path)
    for path in mismatched:
        found = nodes[path]['found_dev']
        refusals.append('device_node_mismatch: %s (%s expected %s)'
                        % (path, found, nodes[path]['required_dev']))
    for entry in invalid:
        refusals.append('device_node_invalid_usb_major: ' + entry)
    return {
        'model': 'offline_devno_usb_namespace_v1',
        'usb_major': usb_major,
        'nodes': nodes,
        'missing': missing,
        'mismatched': mismatched,
        'invalid': invalid,
        'registered': not refusals,
        'installable': False,
        'install_policy': 'declared_overlay_only_no_write',
        'refusals': refusals,
    }


def assess_load_authorization(authorization):
    """Refuse physical load unless an explicit, complete authorization is given.

    `authorization` is data supplied by the caller (default: absent).  Every
    field in ``LOAD_AUTHORIZATION_FIELDS`` must be explicitly truthy; an empty
    dict/None is a refusal.  This function never authorizes by itself.
    """
    reasons = []
    record = dict(authorization or {})
    for field in LOAD_AUTHORIZATION_FIELDS:
        if not record.get(field):
            reasons.append('load_authorization_missing: ' + field)
    return {
        'authorized': not reasons,
        'record': record,
        'reasons': reasons,
        'refusal': None if not reasons else 'load_unauthorized',
    }


def assess_enablement_hygiene(components, devno_entries, *,
                              vermagic_by_component=None,
                              provider_symbols=None,
                              consumer_symbols=None,
                              load_authorization=None):
    """Aggregate all offline enablement gates into one fail-closed verdict.

    The returned dict is data only: even when every gate passes and an explicit
    load authorization is supplied, ``executable`` stays False and the
    readiness remains blocked by the declared-plan policy.
    """
    component_check = (components if isinstance(components, dict) and
                       'components' in components else
                       verify_component_hashes(components))
    vermagic_check = verify_vermagic(vermagic_by_component or {})
    api_check = verify_api_symbols(provider_symbols or {},
                                   consumer_symbols or {})
    devno_model = model_devno_usb_namespace(devno_entries or {})
    load_check = assess_load_authorization(load_authorization)
    refusals = []
    refusals.extend(component_check.get('refusals', []))
    refusals.extend(vermagic_check.get('refusals', []))
    refusals.extend(api_check.get('refusals', []))
    refusals.extend(devno_model.get('refusals', []))
    refusals.extend(load_check.get('reasons', []))
    gates_pass = (component_check.get('verified', False) and
                  vermagic_check.get('equal', False) and
                  api_check.get('ok', False) and
                  devno_model.get('registered', False) and
                  load_check.get('authorized', False))
    if not gates_pass and not refusals:
        refusals.append('enablement_gates_incomplete')
    return {
        'gates': {
            'components': component_check,
            'vermagic': vermagic_check,
            'api_symbols': api_check,
            'device_nodes': devno_model,
            'load_authorization': load_check,
        },
        'gates_pass': gates_pass,
        'refusals': refusals,
        'ready': gates_pass,
        'executable': False,
        'readiness': 'blocked',
        'policy': 'declared_overlay_only_no_write; physical load needs a '
                  'separate explicit scope',
    }


def enablement_verdict(components, devno_entries, vermagic_equal):
    """Return a fail-closed enablement verdict and ordered reasons."""
    reasons = []
    missing = [name for name, row in components.items()
               if row['status'] == 'missing']
    mismatched = [name for name, row in components.items()
                  if row['status'] == 'hash_mismatch']
    if missing:
        reasons.append('missing_components: ' + ', '.join(sorted(missing)))
    if mismatched:
        reasons.append('hash_mismatch: ' + ', '.join(sorted(mismatched)))
    node_gaps = []
    for path, required in ZVE10_REQUIRED_USB_NODES.items():
        found = devno_entries.get(path)
        if found is None:
            node_gaps.append(path + ' (absent)')
        elif (found['major'], found['minor']) != (required['major'],
                                                  required['minor']):
            node_gaps.append(path + ' (%d:%d expected %d:%d)'
                             % (found['major'], found['minor'],
                                required['major'], required['minor']))
    if node_gaps:
        reasons.append('device_node_gaps: ' + '; '.join(node_gaps))
    if not vermagic_equal:
        reasons.append('module_vermagic_mismatch')
    return {
        'enabled': not reasons,
        'verdict': 'ready_for_declared_overlay' if not reasons
                   else 'not_enabled',
        'reasons': reasons,
    }
