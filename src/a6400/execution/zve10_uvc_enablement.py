"""ZV-E10 UVC-chain enablement manifest for the a6400 target (E0321).

Pure helpers only: parse the Sony `devno.ko` device-node table, compare hash-
pinned ZV-E10 UVC components with an a6400 tree, and compute a fail-closed
enablement verdict.  No deployment, camera access or fabricated compatibility.
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
