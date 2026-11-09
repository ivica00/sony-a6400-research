"""Read actual export classes from the hash-verified retained Sony kernel."""
import hashlib,json,struct
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT,KERNEL,KERNEL_SHA


def kernel_exports():
    raw=KERNEL.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=KERNEL_SHA:raise ValueError('Kernel identity changed')
    names={r['name']:r['address'] for r in json.loads((ROOT/'artifacts/analysis/uvc-portability-final-e0135/a6400-kallsyms-checked.json').read_text())['symbols']}
    result={};base=0x60108000
    for kind,left,right in [('normal','__start___ksymtab','__stop___ksymtab'),
                            ('gpl','__start___ksymtab_gpl','__stop___ksymtab_gpl')]:
        lo,hi=names[left],names[right]
        if hi<lo or (hi-lo)%8:raise ValueError('Invalid export range')
        for entry in range(lo,hi,8):
            value,pointer=struct.unpack_from('<II',raw,entry-base)
            offset=pointer-base
            if offset<0 or offset>=len(raw):raise ValueError('Export string outside kernel image')
            end=raw.find(b'\0',offset,offset+256)
            if end<0:raise ValueError('Unterminated export name')
            name=raw[offset:end].decode('ascii')
            if name in result:raise ValueError('Duplicate export '+name)
            result[name]=dict(kind=kind,address=hex(value),entry=hex(entry))
    return result
