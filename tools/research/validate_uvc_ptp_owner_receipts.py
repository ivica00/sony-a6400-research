"""Strict observational owner receipts; never authorizes kernel publication."""
import argparse, hashlib, json, re
from pathlib import Path


def parse(raw):
    lines=raw.decode('ascii').splitlines()
    if not lines or lines[0]!='UVC_OWNER_INVENTORY version=1 observational=1 freeze=0 writes=0':
        raise ValueError('Missing inventory identity')
    owners=[];tasks=[];summary=None
    for index,line in enumerate(lines[1:],1):
        m=re.fullmatch(r'OWNER pid=(\d+) fd=(\d+) major=242 minor=1',line)
        if m:
            owners.append(tuple(map(int,m.groups())));continue
        m=re.fullmatch(r'TASK pid=(\d+) tid=(\d+)',line)
        if m:
            tasks.append(tuple(map(int,m.groups())));continue
        m=re.fullmatch(r'END owners=(\d+) threads=(\d+) errors=(\d+) observational=1',line)
        if not m or index!=len(lines)-1:raise ValueError('Unknown/trailing inventory record')
        summary=tuple(map(int,m.groups()))
    if summary!=(len(owners),len(tasks),0):raise ValueError('Incomplete/error inventory')
    if len(set(owners))!=len(owners) or len(set(tasks))!=len(tasks):raise ValueError('Duplicate records')
    if not owners or {pid for pid,fd in owners}!={149}:raise ValueError('Unsupported USB owner set')
    if not 1<=len(tasks)<=512 or {pid for pid,tid in tasks}!={149} or (149,149) not in tasks:
        raise ValueError('Invalid CPU barrier thread set')
    if any(tid<=0 for pid,tid in tasks):raise ValueError('Invalid TID')
    return dict(owners=sorted(owners),tasks=sorted(tasks))


def load(directory):
    m=json.loads((directory/'manifest.json').read_text())
    if (m.get('status')!='observational_inventory_complete' or m.get('log_truncated') is not False
        or m.get('run')!={'status':0,'flags':0}):raise ValueError('Unsuccessful capture receipt')
    def verified(name):
        data=(directory/name).read_bytes();record=m['files'][name]
        if record.get('truncated') or record['bytes']!=len(data) or record['sha256']!=hashlib.sha256(data).hexdigest():
            raise ValueError('Artifact integrity mismatch: '+name)
        return data
    result=parse(verified('owners.log'))
    if verified('pid-149-comm.txt').strip()!=b'im.elf':raise ValueError('Unexpected owner process')
    status=verified('pid-149-status.txt').decode('ascii')
    if not re.search(r'^TracerPid:\s+0$',status,re.M):raise ValueError('Owner already traced')
    if not re.search(r'^Tgid:\s+149$',status,re.M):raise ValueError('Owner identity mismatch')
    return result


def self_test():
    header=b'UVC_OWNER_INVENTORY version=1 observational=1 freeze=0 writes=0\n'
    body=b'OWNER pid=149 fd=85 major=242 minor=1\nTASK pid=149 tid=149\n'
    good=header+body+b'END owners=1 threads=1 errors=0 observational=1\n'
    assert parse(good)['owners']==[(149,85)]
    bad=[good.replace(b'errors=0',b'errors=1'),good+b'junk\n',good.replace(b'threads=1',b'threads=2'),
         good.replace(b'OWNER pid=149',b'OWNER pid=703'),good.replace(b'tid=149',b'tid=150'),
         header+body+body+b'END owners=2 threads=2 errors=0 observational=1\n',good[:-10]]
    for raw in bad:
        try:parse(raw)
        except ValueError:continue
        raise AssertionError('Invalid inventory accepted')
    return 1+len(bad)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('receipts',nargs='*',type=Path)
    args=p.parse_args();checks=self_test()
    records=[load(path) for path in args.receipts]
    stable=bool(records) and all(record==records[0] for record in records)
    if records and not stable:raise ValueError('Owner/thread sets changed between receipts; refresh before any barrier')
    print(json.dumps(dict(status='observational_receipts_validated',negative_and_positive_cases=checks,
        receipts=len(records),matching_observed_sets=stable,
        owners=records[0]['owners'] if records else [],threads=len(records[0]['tasks']) if records else 0,
        publication_authorized=False,limitations=['Sequential proc observations, no exclusion of future opens or TID reuse.',
        'Must revalidate within a concrete barrier; not VFS/IRQ/DMA quiescence.']),indent=2))


if __name__=='__main__':main()
