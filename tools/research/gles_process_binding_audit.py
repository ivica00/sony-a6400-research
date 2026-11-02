"""Compare explicit process-model ranges with an observed WBI task; grant no replies."""
import argparse
from dataclasses import asdict
import hashlib
import json

from project_paths import PROJECT_ROOT
from src.a6400.execution.kernel_task_identity import KernelTaskObservation
from tools.research.wbi_gles_execute import load_context
from tools.research.wbi_gles_state import ROOT
from tools.research.wbi_pagewalk import read_virtual


def audit(report_path, thread_info, guest_tgid):
    raw = report_path.read_bytes()
    report = json.loads(raw)
    context = load_context()
    task = KernelTaskObservation.read(
        lambda address, size: read_virtual(context['memory'], ROOT, address, size), thread_info)
    stack = report['stack']
    ranges = [(stack['bottom'], stack['size'])]
    # Mappings are request history. Without a complete unmap reconstruction,
    # report them as historical checks, never as proof of live memory.
    history = [(m['address'], m['length']) for m in report['mappings']]
    pid = report['tls_observation']['current_tid']
    return {'inputs': context['inputs'], 'process_report': str(report_path),
            'process_report_sha256': hashlib.sha256(raw).hexdigest(),
            'observed_task': asdict(task), 'explicit_model_tgid': guest_tgid,
            'model_tid': pid, 'binding_mismatches': task.mismatches(
                guest_pid=pid, guest_tgid=guest_tgid, user_ranges=ranges),
            'historical_mapping_mismatches': task.mismatches(
                guest_pid=task.pid, guest_tgid=task.tgid, user_ranges=history),
            'driver_replies_supplied': 0,
            'limitations': ['Selected captured addr_limit is not a universal TASK_SIZE.',
                            'Mapping history is not a reconstructed live address space.',
                            'Matching identities alone does not establish task creation or driver ownership.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--process-report', required=True)
    parser.add_argument('--thread-info', type=lambda value: int(value, 0), required=True)
    parser.add_argument('--guest-tgid', type=lambda value: int(value, 0), required=True)
    parser.add_argument('--report-dir', required=True)
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Reports must remain under artifacts')
    result = audit(PROJECT_ROOT / args.process_report, args.thread_info, args.guest_tgid)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(result['binding_mismatches'])


if __name__ == '__main__':
    main()
