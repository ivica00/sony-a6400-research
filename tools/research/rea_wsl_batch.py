"""Bounded, hash-checked static queries through one local REA/WSL session.

No REA setup, target execution, snapshot mutation, or device operations.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from project_paths import PROJECT_ROOT
from tools.research.rea_evidence_cache import EvidenceCache

DEFAULT_TARGET = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/backup.ko'


def checked_input(root, relative, expected):
    # Keep this launcher stdlib-only so it can also run directly inside the
    # established WSL runtime without installing firmware-analysis packages.
    path = (root / relative).resolve()
    if not path.is_relative_to((root / 'firmware').resolve()):
        raise ValueError('Evidence input escapes firmware directory')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('Evidence input hash mismatch')
    return data


def wsl_path(path):
    path = Path(path).resolve()
    if os.name == 'posix':
        return path.as_posix()
    if not path.drive or len(path.drive) != 2:
        raise ValueError('Expected a Windows drive path for the WSL trial')
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


class Session:
    def __init__(self, stderr):
        command = [
            'env',
            'GHIDRA_INSTALL_DIR=/home/administrator/a6400-rea-tools/ghidra_12.1.4_PUBLIC',
            'JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64',
            'REA_GHIDRA_STARTUP_TIMEOUT_MS=330000', 'node',
            '/home/administrator/a6400-rea-tools/runtime/node_modules/rea-agents/scripts/rea.mjs', '--mcp']
        if os.name != 'posix':
            command = ['wsl.exe', '--exec'] + command
        self.process = subprocess.Popen(command,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)
        self.messages = queue.Queue()
        self.ident = 0
        def reader():
            for line in self.process.stdout:
                self.messages.put(line)
            self.messages.put(None)
        self.reader = threading.Thread(target=reader, daemon=True)
        self.reader.start()

    def send(self, data):
        self.process.stdin.write((json.dumps(data) + '\n').encode('utf-8'))
        self.process.stdin.flush()

    def request(self, method, params):
        self.ident += 1
        self.send({'jsonrpc': '2.0', 'id': self.ident, 'method': method, 'params': params})
        deadline = time.monotonic() + 420
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('REA request exceeded 420 seconds')
            line = self.messages.get(timeout=remaining)
            if line is None:
                raise RuntimeError('REA exited before returning a response')
            data = json.loads(line)
            if data.get('id') != self.ident:
                continue
            if 'error' in data:
                raise RuntimeError(json.dumps(data['error']))
            return data['result']

    def tool(self, name, arguments):
        result = self.request('tools/call', {'name': name, 'arguments': arguments})
        if result.get('isError'):
            raise RuntimeError(json.dumps(result))
        return result

    def stop(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=10)
            raise RuntimeError('REA did not exit after its input was closed')
        if self.process.returncode:
            raise RuntimeError(f'REA process exited with {self.process.returncode}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', default=DEFAULT_TARGET, help='Inventoried project-relative ELF')
    parser.add_argument('--inventory', default='artifacts/inventory/elf-inventory.json',
                        help='Hash inventory under artifacts, including isolated reference-camera inventories')
    parser.add_argument('--procedure', action='append', required=True)
    parser.add_argument('--instructions', action='append', default=[])
    parser.add_argument('--report-dir', required=True, help='New directory under artifacts/')
    parser.add_argument('--reuse-evidence', action='store_true', help='Reuse hash/profile-checked completed Ghidra 12.1.4 evidence')
    args = parser.parse_args()
    if len(args.procedure) + len(args.instructions) > 48:
        parser.error('At most 48 static queries per session')
    target = (PROJECT_ROOT / args.target).resolve()
    relative = target.relative_to(PROJECT_ROOT).as_posix()
    inventory_path=(PROJECT_ROOT / args.inventory).resolve()
    if not inventory_path.is_relative_to((PROJECT_ROOT/'artifacts').resolve()):
        parser.error('Inventory must remain under artifacts')
    inventory = json.loads(inventory_path.read_text(encoding='utf-8'))
    expected = next(row['sha256'] for row in inventory['entries'] if row['path'] == relative)
    checked_input(PROJECT_ROOT, relative, expected)
    output = (PROJECT_ROOT / args.report_dir).resolve()
    output.relative_to(PROJECT_ROOT / 'artifacts')
    output.mkdir(parents=True, exist_ok=False)
    report = {'target': relative, 'sha256': expected, 'status': 'running', 'queries': [],
              'limitations': ['Static Ghidra reconstruction, not target execution or runtime state.',
                              'Linux tooling paths are this local trial installation, not dependency locking.']}
    started = time.monotonic()
    session = None
    opened = False
    cache = EvidenceCache(PROJECT_ROOT / 'artifacts/tools/rea') if args.reuse_evidence else None
    def save(name, data):
        (output / name).write_text(json.dumps(data, indent=2), encoding='utf-8')
    try:
        with (output / 'rea.stderr').open('wb') as stderr:
            for operation, procedures in [('procedure_pseudo_code', args.procedure),
                                          ('read_function_instructions', args.instructions)]:
                for procedure in procedures:
                    index = len(report['queries'])
                    before = time.monotonic()
                    retained = cache.lookup(expected, operation, procedure) if cache else None
                    if retained:
                        data = retained['data']
                    else:
                        if session is None:
                            session = Session(stderr)
                            save('initialize.json', session.request('initialize', {'protocolVersion': '2024-11-05',
                                 'capabilities': {}, 'clientInfo': {'name': 'a6400-local-research', 'version': '1'}}))
                            session.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
                            save('open.json', session.tool('open_binary', {'path': wsl_path(target), 'provider_id': 'ghidra'}))
                            opened = True
                        data = session.tool(operation, {'procedure': procedure})
                    evidence = data.get('structuredContent')
                    if evidence is None:
                        raise ValueError('REA did not return structured Evidence')
                    if evidence.get('subject', {}).get('digest', {}).get('sha256') != expected:
                        raise ValueError('REA Evidence target identity differs from the preserved input')
                    filename = f'{index:02d}-{operation}.json'
                    save(filename, data)
                    elapsed = round(time.monotonic() - before, 3)
                    report['queries'].append({'procedure': procedure, 'operation': operation,
                                              'file': filename, 'elapsed_seconds': elapsed})
                    if retained:
                        report['queries'][-1]['reused_evidence'] = {k: v for k, v in retained.items() if k != 'data'}
                    print(operation, procedure, 'cached' if retained else elapsed, flush=True)
            if session is not None:
                save('close.json', session.tool('close_binary', {}))
                opened = False
                session.stop()
                session = None
        checked_input(PROJECT_ROOT, relative, expected)
        report.update(status='completed', source_unchanged=True)
    except Exception as error:
        report.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        if session is not None:
            try:
                if opened:
                    save('cleanup-close.json', session.tool('close_binary', {}))
                session.stop()
            except Exception as error:
                report['cleanup_error'] = f'{type(error).__name__}: {error}'
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        report['source_sha256_after'] = hashlib.sha256(target.read_bytes()).hexdigest()
        save('manifest.json', report)
    print(output)


if __name__ == '__main__':
    main()
