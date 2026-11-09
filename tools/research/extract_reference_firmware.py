"""Extract a reference updater as data using the installed fwtool parser.

Never executes the supplied updater. Output is confined to a fresh directory.
"""
import argparse
import hashlib
import importlib.util
import json
import shutil
import stat
import struct
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT=Path(__file__).resolve().parents[2]


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args()
    source=args.input.resolve();out=args.output.resolve();reportdir=args.report_dir.resolve()
    if not source.is_relative_to(ROOT/'firmware') or not out.is_relative_to(ROOT/'firmware') or out==ROOT/'firmware':
        parser.error('Inputs and extraction must remain within project firmware directory')
    if not reportdir.is_relative_to(ROOT/'artifacts'):
        parser.error('Report must remain under artifacts')
    if out.exists():parser.error('Extraction directory must be fresh')
    reportdir.mkdir(parents=True,exist_ok=False);out.mkdir()
    tool=ROOT/'fwtool.py/fwtool.py'
    report={'input':str(source),'bytes':source.stat().st_size,'sha256':digest(source),
        'fwtool_sha256':digest(tool),'updater_executed':False,'camera_access':False,
        'output':str(out),'status':'running','skipped_special_entries':[],
        'case_collision_paths':[]}
    def save():
        (reportdir/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    save()
    sys.path.insert(0,str(tool.parent))
    spec=importlib.util.spec_from_file_location('reference_fwtool',tool)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    count=0;total=0

    def safe_write(files,path):
        nonlocal count,total
        base=Path(path).resolve()
        if not base.is_relative_to(out):raise ValueError('Archive base escapes extraction')
        regular=[]
        for entry in files:
            name=entry.path
            if '\\' in name or ':' in name or '..' in PurePosixPath(name).parts:
                raise ValueError('Unsafe archive path: '+name)
            target=(base/name.lstrip('/')).resolve()
            if not target.is_relative_to(out):raise ValueError('Archive target escapes extraction')
            if stat.S_ISDIR(entry.mode):target.mkdir(parents=True,exist_ok=True)
            elif stat.S_ISREG(entry.mode):
                count+=1
                if count>100000:raise ValueError('File count bound exceeded')
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():
                    # Linux archives can contain libxt_DSCP.so/libxt_dscp.so.
                    # Preserve both payloads on a case-insensitive Windows host.
                    original=target
                    suffix=hashlib.sha256(name.encode()).hexdigest()[:12]
                    target=target.with_name(target.name+'__case_'+suffix)
                    report['case_collision_paths'].append({'archive_path':name,
                        'original_host_path':str(original.relative_to(out)),
                        'stored_path':str(target.relative_to(out))})
                with target.open('xb') as f:
                    while True:
                        block=entry.contents.read(1024*1024)
                        if not block:break
                        total+=len(block)
                        if total>8*1024**3:raise ValueError('Extraction byte bound exceeded')
                        f.write(block)
                regular.append(target)
            else:
                report['skipped_special_entries'].append({'path':str(target.relative_to(out)),
                                                         'mode':entry.mode})
        for target in regular:
            with target.open('rb') as f:
                if module.archive.isArchive(f):
                    print('Unpacking',target.relative_to(out),flush=True)
                    safe_write(module.archive.readArchive(f),str(target)+'_unpacked')
    module.writeFileTree=safe_write
    try:
        target=source
        # New Sony Packman embeds a bitwise-inverted CAB, rather than the
        # ZIP/LZH wrappers supported by this installed fwtool version.
        with source.open('rb') as f:
            import mmap
            with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as mapped:
                marker=b'\xb2\xac\xbc\xb9'
                at=mapped.find(marker)
                if mapped[:2]==b'MZ' and at>=0:
                    if mapped.find(marker,at+4)>=0:raise ValueError('Ambiguous inverted CAB markers')
                    table=bytes.maketrans(bytes(range(256)),bytes(255-i for i in range(256)))
                    header=bytes(mapped[at:at+36]).translate(table)
                    size=struct.unpack_from('<I',header,8)[0]
                    if header[:4]!=b'MSCF' or not 36<=size<=len(mapped)-at or header[24:26]!=b'\x03\x01':
                        raise ValueError('Invalid inverted CAB header/bounds')
                    cabinet=out/'packman.cab'
                    with cabinet.open('xb') as cab:
                        for offset in range(at,at+size,1024*1024):
                            cab.write(bytes(mapped[offset:min(offset+1024*1024,at+size)]).translate(table))
                    report['packman']={'offset':at,'cabinet_bytes':size,'transform':'byte XOR ff',
                                       'cabinet_sha256':digest(cabinet)}
                    save()
        if 'packman' in report:
            seven=Path('C:/Program Files/7-Zip/7z.exe')
            listing=subprocess.run([str(seven),'l','-slt',str(cabinet)],capture_output=True,text=True,check=True)
            (reportdir/'cab-listing.txt').write_text(listing.stdout,encoding='utf-8')
            total_size=0
            for line in listing.stdout.splitlines():
                if line.startswith('Path = '):
                    name=line[7:]
                    if name==str(cabinet):continue
                    normalized=name.replace('\\','/')
                    if ':' in normalized or normalized.startswith('/') or '..' in PurePosixPath(normalized).parts:
                        raise ValueError('Unsafe cabinet member: '+name)
                if line.startswith('Size = '):total_size+=int(line[7:])
            if total_size>2*1024**3:raise ValueError('CAB expansion bound exceeded')
            package=out/'packman';package.mkdir()
            extracted=subprocess.run([str(seven),'x','-y','-o'+str(package),str(cabinet)],capture_output=True,text=True,check=True)
            (reportdir/'cab-extraction.txt').write_text(extracted.stdout,encoding='utf-8')
            candidates=list(package.rglob('FirmwareData*.dat'))
            if len(candidates)!=1:raise ValueError('Expected one reference FirmwareData DAT')
            target=candidates[0];report['packman']['firmware_dat']=str(target.relative_to(out));save()
        with target.open('rb') as f:module.unpackCommand(f,str(out))
        report['files']=[{'path':str(p.relative_to(out)),'bytes':p.stat().st_size,
                          'sha256':digest(p)} for p in sorted(out.rglob('*')) if p.is_file()]
        report['status']='completed';report['extracted_regular_files']=count
        report['extracted_bytes']=total
    except Exception as exc:
        report['status']='failed';report['error']=repr(exc)
        raise
    finally:
        report['input_sha256_after']=digest(source)
        report['input_unchanged']=report['input_sha256_after']==report['sha256']
        save()
    print('Reference extraction completed:',out,flush=True)


if __name__=='__main__':main()
