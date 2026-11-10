"""Pure decision policy for the bounded P4 enumeration/teardown experiment.

No camera, filesystem or process access: callers pass the observed bytes.
"""
import re

REQUIRED = {
    'init': b'IOCTL_UVC_INIT returned ret=0',
    'stop_verified': b'STEP 3: Composite session stopped; IDLE/unpinned/no hooks/no error verified.',
    'retired': b'STEP 4: Entry hook retired, 0xe1a0c00d restored',
    'completed': b'SESSION_RUNNER complete result=0',
}
FORBIDDEN = {
    'retained': b'SESSION_RUNNER RETAINED',
    'critical': b'CRITICAL ',
    'fail': b'FAIL ',
}
TRACER_ZERO = re.compile(rb'^TracerPid:\s+0$', re.M)


def parse_uptime(raw):
    """First whitespace-separated field of /proc/uptime as float."""
    return float(raw.split()[0])


def module_loaded(modules, name='usbg_video'):
    prefix = name.encode() + b' '
    return any(line.startswith(prefix) for line in modules.splitlines())


def evaluate_preflight(*, module_sha, runner_sha, audit, modules, status149):
    reasons = []
    if not isinstance(audit, dict) or audit.get('status') != 'offline_module_audit_passed':
        reasons.append('audit_not_passed')
    elif audit.get('module_sha256') != module_sha:
        reasons.append('audit_module_mismatch')
    if not module_sha or not runner_sha:
        reasons.append('missing_identity')
    if module_loaded(modules):
        reasons.append('module_already_loaded')
    if not TRACER_ZERO.search(status149 or b''):
        reasons.append('tracer_not_clean')
    return {'ok': not reasons, 'reasons': reasons}


def evaluate_receipt(receipt):
    reasons = []
    found = {}
    if not receipt:
        return {'ok': False, 'reasons': ['receipt_missing'], 'markers': {}}
    for name, marker in FORBIDDEN.items():
        if marker in receipt:
            reasons.append('forbidden_' + name)
    positions = []
    for name, marker in REQUIRED.items():
        index = receipt.find(marker)
        found[name] = index >= 0
        if index < 0:
            reasons.append('missing_' + name)
        else:
            positions.append(index)
    if not reasons and positions != sorted(positions):
        reasons.append('markers_out_of_order')
    return {'ok': not reasons, 'reasons': reasons, 'markers': found}


def pre_teardown_host_gate(binding):
    """Host enumeration must show the composite parent and a PTP child before teardown."""
    if not isinstance(binding, dict):
        return {'ok': False, 'reasons': ['no_host_binding_sample']}
    reasons = []
    if not binding.get('composite_parent_ready'):
        reasons.append('composite_parent_not_ready')
    if not binding.get('ptp_ready'):
        reasons.append('ptp_not_ready')
    if not binding.get('ptp_children'):
        reasons.append('no_ptp_child')
    return {'ok': not reasons, 'reasons': reasons}


def evaluate_after(*, modules_before, modules_after, uptime_before, uptime_after, receipt_ok):
    reasons = []
    if not receipt_ok:
        reasons.append('receipt_not_verified')
    if modules_after != modules_before:
        reasons.append('modules_not_restored')
    if module_loaded(modules_after):
        reasons.append('usbg_video_loaded')
    try:
        reboot = parse_uptime(uptime_after) < parse_uptime(uptime_before)
    except (ValueError, IndexError, TypeError):
        reasons.append('uptime_unreadable')
        reboot = False
    if reboot:
        reasons.append('reboot_detected')
    return {
        'ok': not reasons,
        'reasons': reasons,
        'module_restored': modules_after == modules_before,
        'usbg_video_after': module_loaded(modules_after),
        'reboot': reboot,
    }
