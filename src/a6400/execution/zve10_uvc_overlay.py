"""Declared ZV-E10 -> a6400 UVC overlay plan (E0322).

Pure planning helpers: turn the E0321 enablement manifest into an explicit,
hash-pinned overlay plan.  No deployment, camera access or file writes: the plan
is data, and it stays `blocked` until its open items are resolved.
"""

# Component -> target path inside the a6400 environment (declared overlay).
OVERLAY_TARGETS = {
    'usbg_video.ko': {
        'target': '/usr/kmod/usbg_video.ko',
        'action': 'add',
        'source_tree': 'zve10',
    },
    'usbg_audio.ko': {
        'target': '/usr/kmod/usbg_audio.ko',
        'action': 'add',
        'source_tree': 'zve10',
    },
    'libInfraStreamingUsb.so': {
        'target': '/usr/lib/libInfraStreamingUsb.so',
        'action': 'add',
        'source_tree': 'zve10',
    },
    'libInfraUsbCmn.so': {
        'target': '/usr/lib/libInfraUsbCmn.so',
        'action': 'replace',
        'source_tree': 'zve10',
    },
    'devno.ko': {
        'target': '/usr/kmod/devno.ko',
        'action': 'replace',
        'source_tree': 'zve10',
    },
}

OVERLAY_PREREQUISITES = (
    'usbg_cmn.ko present (both models; exports usbg_cmn_reg/dereg and '
    'sync phys-buffer APIs)',
    'module load order usbg_cmn -> usbg_video/usbg_audio (implied by '
    'usbg_cmn_reg, not physically proven)',
    'PTP usbg_stillimage remains in the same gadgetcore configuration',
)

OVERLAY_OPEN_ITEMS = (
    'device-node namespace: /dev/usb/audio 248:32 and /dev/usb/video 248:33 '
    'must exist; verify whether the a6400 rootfs creates them from devno.ko '
    'or whether an explicit node overlay is required',
    'physical module load requires separate explicit authorization with '
    'recovery/teardown plan',
    'usbg_video register/transfer contract: context+0x2D writer, buffer '
    'table/blob semantics and 0xD0/0x24 object contents are still undecoded',
    'host USB enumeration/SET_CONFIG contract (E0318) is orthogonal',
)


def build_overlay_plan(manifest):
    """Build the declared overlay plan from an E0321-style manifest.

    Returns a dict with hash-pinned operations and an explicit readiness value;
    the plan is never marked executable by this function.
    """
    component_check = manifest.get('component_check', {})
    operations = []
    for name, target in OVERLAY_TARGETS.items():
        row = component_check.get(name, {})
        operations.append({
            'component': name,
            'source_tree': target['source_tree'],
            'target': target['target'],
            'action': target['action'],
            'pinned_sha256': row.get('pinned_sha256'),
            'a6400_status': row.get('status', 'unknown'),
        })
    missing = [row['component'] for row in operations
               if row['a6400_status'] not in ('verified', 'hash_mismatch')]
    node_gaps = manifest.get('verdict', {}).get('reasons', [])
    node_blocked = any('device_node_gaps' in reason for reason in node_gaps)
    return {
        'e': 'E0322',
        'objective': 'enable ZV-E10 2.03 UVC chain on the a6400 target',
        'readiness': 'blocked' if (missing or node_blocked) else 'ready',
        'executable': False,
        'operations': operations,
        'prerequisites': list(OVERLAY_PREREQUISITES),
        'open_items': list(OVERLAY_OPEN_ITEMS),
        'blocking_reasons': ([('missing A6400-side components: ' +
                               ', '.join(missing))] if missing else []) +
                             (['device nodes absent'] if node_blocked else []),
        'boundaries': [
            'plan only; no file was written, no module loaded, no camera '
            'mode change',
            'hash-pinned sources are the ZV-E10 2.03 components verified in '
            'E0316/E0321',
        ],
    }
