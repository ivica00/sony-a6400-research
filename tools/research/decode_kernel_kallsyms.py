"""Decode bounded legacy absolute-address kallsyms from BIONZ X kernel bytes."""
import argparse
import hashlib
import json
import struct
from pathlib import Path


def decode(raw):
    if not 1024*1024<=len(raw)<=8*1024*1024:raise ValueError('Kernel size outside profile')
    runs=[];start=None;last=0
    for off in range(0,len(raw)-3,4):
        value=struct.unpack_from('<I',raw,off)[0]
        valid=0x60100000<=value<0x61000000
        if valid and (start is None or value>=last):
            if start is None:start=off
        else:
            if start is not None and off-start>=20000:runs.append((start,off,(off-start)//4))
            start=off if valid else None
        last=value
    candidates=[]
    for begin,end,count in runs:
        count_positions=[p for p in range(end,min(end+32,len(raw)-4),4)
                         if struct.unpack_from('<I',raw,p)[0]==count]
        for cp in count_positions:
            names=cp+4
            while names<cp+36 and raw[names]==0:names+=1
            pos=names;encoded=[]
            for _ in range(count):
                if pos>=len(raw):break
                size=raw[pos];pos+=1
                if not size or pos+size>len(raw):break
                encoded.append(raw[pos:pos+size]);pos+=size
            if len(encoded)!=count:continue
            found=None
            for index in range((pos+1)&~1,min(pos+20000,len(raw)-512),2):
                offsets=struct.unpack_from('<256H',raw,index)
                if offsets[0] or offsets[-1]>16384 or not all(0<offsets[i+1]-offsets[i]<=64 for i in range(255)):continue
                for gap in range(16):
                    token_end=index-gap
                    for last_size in range(1,65):
                        base=token_end-offsets[-1]-last_size
                        if base<pos:continue
                        strings=[]
                        for i,off in enumerate(offsets):
                            stop=base+offsets[i+1] if i<255 else token_end
                            chunk=raw[base+off:stop]
                            if not chunk or chunk[-1]!=0 or any(v<32 or v>126 for v in chunk[:-1]):break
                            strings.append(chunk[:-1].decode('ascii'))
                        if len(strings)==256:found=(base,index,strings);break
                    if found:break
                if found:break
            if not found:continue
            base,index,strings=found
            expanded=[''.join(strings[v] for v in name) for name in encoded]
            if any(len(name)<2 or name[0] not in 'aAbBdDrRtTvVwWuUnN?' for name in expanded):continue
            addresses=struct.unpack_from('<'+'I'*count,raw,begin)
            symbols=[{'address':address,'type':name[0],'name':name[1:]}
                     for address,name in zip(addresses,expanded)]
            if not any(s['name']=='usb_gadgetcore_register_driver' for s in symbols):continue
            candidates.append({'addresses_offset':begin,'names_offset':names,'token_table_offset':base,
                'token_index_offset':index,'symbol_count':count,'symbols':symbols})
    if len(candidates)!=1:raise ValueError('Absent or ambiguous legacy kallsyms profile')
    return candidates[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();raw=args.input.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    if sha!=args.sha256:raise ValueError('Kernel input identity mismatch')
    result=decode(raw);result.update(source_sha256=sha,camera_access=False)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Decoded',result['symbol_count'],'original kernel symbols')


if __name__=='__main__':main()
