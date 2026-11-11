"""Declared ZV-E10 -> a6400 UVC overlay plan (E0322).

Pure planning helpers: turn the E0321 enablement manifest into an explicit,
hash-pinned overlay plan.  No deployment, camera access or file writes: the
plan is data, and its readiness stays `blocked` and `executable` stays False
even when every offline verification gate passes.
"""

from src.a6400.execution.zve10_uvc_enablement import (
    ZVE10_REQUIRED_USB_NODES,
    assess_load_authorization,
    model_devno_usb_namespace,
)

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

# Device-node targets the declared overlay would have to register.  They are
# modelled as data only; the plan never creates or installs a node.
OVERLAY_DEVNO_NODES = {
    path: {
        'major': row['major'],
        'minor': row['minor'],
        'dev': '%d:%d' % (row['major'], row['minor']),
        'registration': 'declared_overlay_only_no_write',
    }
    for path, row in ZVE10_REQUIRED_USB_NODES.items()
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

PLAN_NON_EXECUTABLE_REASON = (
    'declared_plan_is_data_only: no file write, module load or node '
    'installation is permitted by this plan')


def _gate_refusals(hygiene):
    gates = (hygiene or {}).get('gates', {})
    refusals = []
    for gate_name in ('components', 'vermagic', 'api_symbols'):
        gate = gates.get(gate_name) or {}
        refusals.extend(gate.get('refusals', []))
    node_gate = gates.get('device_nodes') or {}
    refusals.extend(node_gate.get('refusals', []))
    return refusals


def build_overlay_plan(manifest, load_authorization=None):
    """Build the declared overlay plan from an E0321-style manifest.

    Args:
        manifest: E0321 manifest dict; may include a `hygiene` verification
            section (new) or only the legacy `component_check`/`verdict`.
        load_authorization: optional caller-supplied data; absent by default,
            which is a refusal (`load_unauthorized`).  Even a complete record
            never makes the plan executable or unblocks its readiness.

    Returns:
        A data-only plan dict.  ``readiness`` is always ``'blocked'`` and
        ``executable`` is always False.
    """
    manifest = manifest or {}
    component_check = manifest.get('component_check', {})
    hygiene = manifest.get('hygiene') or {}
    gates = hygiene.get('gates', {})

    operations = []
    for name, target in OVERLAY_TARGETS.items():
        row = component_check.get(name, {})
        operation = {
            'component': name,
            'source_tree': target['source_tree'],
            'target': target['target'],
            'action': target['action'],
            'pinned_sha256': row.get('pinned_sha256'),
            'a6400_status': row.get('status', 'unknown'),
        }
        if name == 'devno.ko':
            operation['node_registrations'] = [
                dict(path=path, **spec)
                for path, spec in sorted(OVERLAY_DEVNO_NODES.items())
            ]
            operation['node_registration_policy'] = (
                'declared_overlay_only_no_write')
        operations.append(operation)

    missing = [row['component'] for row in operations
               if row['a6400_status'] not in ('verified', 'hash_mismatch')]
    node_gate = gates.get('device_nodes') or {}
    node_model = node_gate or model_devno_usb_namespace({})
    node_blocked = bool(node_model.get('missing') or
                        node_model.get('mismatched') or
                        node_model.get('invalid'))
    if not node_gate:
        # Legacy manifests only carry a textual verdict reason.
        node_blocked = node_blocked or any(
            'device_node_gaps' in reason
            for reason in manifest.get('verdict', {}).get('reasons', []))

    load_check = assess_load_authorization(
        load_authorization or
        (gates.get('load_authorization') or {}).get('record'))
    gate_refusals = _gate_refusals(hygiene)
    verified_gates = bool(hygiene.get('gates_pass')) and not gate_refusals
    would_be_ready = (
        not missing and not node_blocked and verified_gates and
        load_check['authorized'])

    blocking_reasons = []
    if missing:
        blocking_reasons.append('missing A6400-side components: ' +
                                ', '.join(sorted(missing)))
    if node_blocked:
        blocking_reasons.append('device nodes absent or mismatched for '
                                '/dev/usb/audio 248:32 and /dev/usb/video 248:33')
    blocking_reasons.extend(gate_refusals)
    blocking_reasons.extend(load_check['reasons'])
    blocking_reasons.append(PLAN_NON_EXECUTABLE_REASON)

    verification = {
        'components': gates.get('components') or {
            name: component_check.get(name, {})
            for name in OVERLAY_TARGETS
        },
        'vermagic': gates.get('vermagic'),
        'api_symbols': gates.get('api_symbols'),
        'device_nodes': node_model,
        'load_authorization': load_check,
    }
    return {
        'e': 'E0322',
        'objective': 'enable ZV-E10 2.03 UVC chain on the a6400 target',
        'readiness': 'blocked',
        'executable': False,
        'would_be_ready_if_authorized': bool(would_be_ready),
        'verification': verification,
        'devno_namespace_model': node_model,
        'operations': operations,
        'prerequisites': list(OVERLAY_PREREQUISITES),
        'open_items': list(OVERLAY_OPEN_ITEMS),
        'blocking_reasons': blocking_reasons,
        'boundaries': [
            'plan only; no file was written, no module loaded, no camera '
            'mode change, no device node installed',
            'hash-pinned sources are the ZV-E10 2.03 components verified in '
            'E0316/E0321',
            'all verification gates are offline data; they never authorize '
            'a physical load',
        ],
    }
