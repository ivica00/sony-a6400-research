"""Copy an existing Sony monitor ring without changing either cursor."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
from tools.camera_debugger import connect, MAX_DATA
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT


def ring_ranges(read, write, capacity):
    if capacity < 2 or not 0 <= read < capacity or not 0 <= write < capacity:
        raise ValueError('Invalid ring cursors/capacity')
    size=(write-read)%capacity
    first=min(size,capacity-read)
    return [(read,first),(0,size-first)] if size>first else ([(read,first)] if first else [])


def translate_mapping(lines,address,size):
    if size<=0 or address<0 or address+size>0x100000000:
        raise ValueError('Invalid mapping range')
    matches=[]
    for line in lines:
        fields=line.split()
        if len(fields)<6 or fields[-1]!='/dev/mem':continue
        start,end=[int(x,16) for x in fields[0].split('-')]
        if start<=address and address+size<=end:
            physical=int(fields[2],16)+address-start
            if physical+size>0x80000000:raise ValueError('Backing exceeds debugger file-read range')
            matches.append((physical,line))
    if len(matches)!=1:raise ValueError('Expected exactly one complete /dev/mem mapping')
    return matches[0]


def capture(d):
    from elftools.elf.elffile import ELFFile
    source=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libMWF.so'
    raw=source.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    inventory=json.loads((ROOT/'artifacts/inventory/elf-inventory.json').read_text())
    assert digest==next(x['sha256'] for x in inventory['entries'] if x['path']==source.relative_to(ROOT).as_posix())
    elf=ELFFile(io.BytesIO(raw));text=elf.get_section_by_name('.text')
    maps,truncated=d.read_all('/proc/149/maps',256*1024)
    if truncated:raise ValueError('Truncated process mappings')
    lines=maps.decode().splitlines()
    candidates=[int(x.split()[0].split('-')[0],16) for x in lines if x.split()[-1:] == ['/usr/lib/libMWF.so'] and int(x.split()[2],16)==0 and 'x' in x.split()[1]]
    if len(candidates)!=1:raise ValueError('Ambiguous MWF text mapping')
    base=candidates[0]
    def read(path,address,size):
        data=bytearray()
        while len(data)<size:
            n=min(MAX_DATA,size-len(data));part=d.read(path,address+len(data),n)
            if len(part)!=n:raise ValueError('Short memory read')
            data.extend(part)
        return bytes(data)
    def virtual(address,size):return read('/proc/149/mem',address,size)
    def word(address):return struct.unpack('<I',virtual(address,4))[0]
    for address in (0x251c0,0x26608,0x267fe):
        offset=address-text['sh_addr']
        if virtual(base+address,16)!=text.data()[offset:offset+16]:raise ValueError('MWF code prefix differs from source')
    def objects():
        pointers=[]
        for got in (0x41950,0x41830,0x41a2c):
            cell=word(base+got)
            if not cell:raise ValueError('Missing relocated global')
            pointers.append(word(cell))
        if any(not p for p in pointers):raise ValueError('Monitor not initialized')
        input_object,output_object,buffer=pointers
        iq=struct.unpack('<4I',virtual(input_object,16));oq=struct.unpack('<4I',virtual(output_object,16))
        if iq!=(buffer,buffer+4,buffer+16,0x400) or oq!=(buffer+8,buffer+12,buffer+0x410,0x7bf0):raise ValueError('Monitor topology differs from verified layout')
        return pointers,iq,oq
    pointers,iq,oq=objects();buffer=pointers[2]
    physical,mapping=translate_mapping(lines,buffer,0x8000)
    def header():return read('/dev/mem',physical,16)
    attempts=[]
    for attempt in range(3):
        before=header();ir,iw,r,w=struct.unpack('<4I',before)
        ring_ranges(ir,iw,iq[3]);ranges=ring_ranges(r,w,oq[3])
        output=b''.join(read('/dev/mem',physical+0x410+start,size) for start,size in ranges)
        after=header();same_objects=objects()==(pointers,iq,oq)
        attempts.append({'header_before':before.hex(),'header_after':after.hex(),'same_objects':same_objects,'bytes':len(output)})
        if before==after and same_objects:
            return output,dict(status='read_only_stable_cursor_snapshot',camera_writes=False,commands_sent=False,ptrace=False,source_sha256=digest,load_bias=hex(base),physical_buffer=hex(physical),mapping=mapping,input_cursors=[ir,iw],output_cursors=[r,w],output_capacity=oq[3],bytes=len(output),sha256=hashlib.sha256(output).hexdigest(),attempts=attempts,limitations=['Sequential reads with equal before/after cursors are not an atomic snapshot; full-wrap ABA and concurrent producers are not excluded.','Existing output is copied without consuming it; this does not prevent output throttling, prove ownership or execute a command.','Source prefixes and topology are checked, not the complete live library.'])
    raise RuntimeError('Monitor changed during all three bounded snapshot attempts')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',type=Path,required=True)
    out=parser.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):parser.error('Output must remain under artifacts')
    out.mkdir(parents=True,exist_ok=False)
    with connect() as d:output,report=capture(d)
    (out/'monitor-output.bin').write_bytes(output);(out/'monitor-output.txt').write_text(output.decode('utf-8',errors='replace'))
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('status','camera_writes','commands_sent','input_cursors','output_cursors','bytes','sha256')},indent=2))


if __name__=='__main__':main()
