"""Run bounded static REA queries on a provenance-checked ORIL ELF view."""
import argparse
import hashlib
import json
from pathlib import Path

from elftools.elf.elffile import ELFFile
from tools.research.oril_scalar_elf_view import ROOT, SOURCE, SHA
from tools.research.rea_wsl_batch import Session, wsl_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--view-dir', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--procedure', action='append', required=True)
    parser.add_argument('--instructions', action='append', default=[])
    args = parser.parse_args()
    if len(args.procedure)+len(args.instructions)>32:
        parser.error('At most 32 queries')
    view = args.view_dir.resolve()/'scalar-view.elf'; out = args.report_dir.resolve()
    if not view.is_relative_to(ROOT/'artifacts') or not out.is_relative_to(ROOT/'artifacts'):
        parser.error('Derived view and reports must stay under artifacts')
    lineage = json.loads(view.with_name('manifest.json').read_text())
    raw = SOURCE.read_bytes(); expected = lineage['view_sha256']
    if hashlib.sha256(raw).hexdigest()!=SHA or lineage['source_sha256']!=SHA:
        raise ValueError('Original ORIL identity mismatch')
    if hashlib.sha256(view.read_bytes()).hexdigest()!=expected:
        raise ValueError('Derived view identity mismatch')
    with view.open('rb') as stream:
        elf = ELFFile(stream)
        for region in lineage['regions']:
            section=elf.get_section_by_name(region['section'])
            start=region['source_offset']; size=region['length']
            if section['sh_addr']!=region['vaddr'] or section.data()!=raw[start:start+size]:
                raise ValueError('Derived section differs from original bytes/address')
    out.mkdir(parents=True, exist_ok=False)
    report={'status':'running','derived_analysis_view':True,'lineage':lineage,'queries':[]}
    def save(name, data):
        (out/name).write_text(json.dumps(data,indent=2),encoding='utf-8')
    session=None
    try:
        with (out/'rea.stderr').open('wb') as error:
            session=Session(error)
            save('initialize.json',session.request('initialize',{'protocolVersion':'2024-11-05',
                 'capabilities':{},'clientInfo':{'name':'oril-scalar-static-view','version':'1'}}))
            session.send({'jsonrpc':'2.0','method':'notifications/initialized'})
            save('open.json',session.tool('open_binary',{'path':wsl_path(view),'provider_id':'ghidra'}))
            for operation, procedures in [('procedure_pseudo_code',args.procedure),
                                          ('read_function_instructions',args.instructions)]:
                for procedure in procedures:
                    data=session.tool(operation,{'procedure':procedure})
                    if data['structuredContent']['subject']['digest']['sha256']!=expected:
                        raise ValueError('Evidence does not describe the checked view')
                    name=f'{len(report["queries"]):02d}-{operation}.json'
                    save(name,data);report['queries'].append({'operation':operation,
                                                             'procedure':procedure,'file':name})
                    print(operation,procedure,flush=True)
            save('close.json',session.tool('close_binary',{}));session.stop();session=None
        report['status']='completed'
    except Exception as error:
        report.update(status='failed',error=str(error));raise
    finally:
        if session:
            try:
                save('cleanup.json',session.tool('close_binary',{}));session.stop()
            except Exception as error:report['cleanup_error']=str(error)
        save('manifest.json',report)


if __name__=='__main__':main()
