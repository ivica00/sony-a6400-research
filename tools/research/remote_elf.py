"""Bounded ELF32 GNU-hash symbol lookup through an explicit file reader."""
import struct


def debugger_reader(debugger,path):
    from tools.camera_debugger import MAX_DATA
    def read(offset,count):
        result=bytearray()
        while len(result)<count:
            block=debugger.read(path,offset+len(result),min(MAX_DATA,count-len(result)))
            if not block: break
            result.extend(block)
        return bytes(result)
    return read


class RemoteElf32:
    def __init__(self,read):
        self.read=read
        header=struct.unpack('<16sHHIIIIIHHHHHH',self.exact(0,52))
        ident,kind,machine,version,entry,phoff,shoff,flags,ehsize,phsize,phnum,shsize,shnum,shstr=header
        if ident[:7]!=b'\x7fELF\x01\x01\x01' or kind!=3 or machine!=40 or version!=1 or ehsize!=52:
            raise ValueError('Expected ELF32 little-endian ARM shared object')
        if shsize!=40 or not 0<shnum<=256 or phsize!=32 or not 0<phnum<=32:
            raise ValueError('Invalid bounded ELF tables')
        section_bytes=self.exact(shoff,shnum*40)
        program_bytes=self.exact(phoff,phnum*32)
        self.sections=[struct.unpack_from('<10I',section_bytes,i*40) for i in range(shnum)]
        self.segments=[struct.unpack_from('<8I',program_bytes,i*32) for i in range(phnum)]
        dynamic=[s for s in self.sections if s[1]==11]
        hashes=[s for s in self.sections if s[1]==0x6ffffff6]
        if len(dynamic)!=1 or len(hashes)!=1:
            raise ValueError('Expected unique dynamic symbols and GNU hash')
        self.symbols=dynamic[0]; self.hashes=hashes[0]
        if self.symbols[9]!=16 or self.symbols[5]%16 or self.symbols[6]>=shnum:
            raise ValueError('Invalid dynamic symbol layout')
        self.strings=self.sections[self.symbols[6]]
        if self.strings[1]!=3 or self.strings[5]>16*1024*1024:
            raise ValueError('Invalid bounded dynamic strings')

    def exact(self,offset,count):
        if not 0<=offset<=0xffffffff or not 0<=count<=16*1024*1024 or offset+count>0x100000000:
            raise ValueError('ELF read outside bounds')
        data=self.read(offset,count)
        if len(data)!=count: raise ValueError('Short ELF read')
        return data

    @staticmethod
    def hash_name(name):
        value=5381
        for byte in name.encode(): value=((value*33)+byte)&0xffffffff
        return value

    def resolve(self,name):
        encoded=name.encode()+b'\0'
        if len(encoded)>512: raise ValueError('Symbol name too long')
        start,size=self.hashes[4],self.hashes[5]
        buckets,symoffset,bloom_size,shift=struct.unpack('<4I',self.exact(start,16))
        if not 0<buckets<=1048576 or not 0<bloom_size<=1048576:
            raise ValueError('Invalid GNU hash sizes')
        bucket_start=start+16+bloom_size*4
        chains=bucket_start+buckets*4
        if chains>start+size: raise ValueError('GNU hash tables exceed section')
        hashed=self.hash_name(name)
        index=struct.unpack('<I',self.exact(bucket_start+(hashed%buckets)*4,4))[0]
        if not index: raise LookupError(name)
        count=self.symbols[5]//16
        found=[]
        for step in range(min(count,65536)):
            if index<symoffset or index>=count: raise ValueError('GNU symbol index outside table')
            chain=chains+(index-symoffset)*4
            if chain+4>start+size: raise ValueError('GNU chain exceeds section')
            value=struct.unpack('<I',self.exact(chain,4))[0]
            if value&~1==hashed&~1:
                strindex,address,symbol_size,info,other,section=struct.unpack('<IIIBBH',self.exact(self.symbols[4]+index*16,16))
                if strindex+len(encoded)<=self.strings[5] and self.exact(self.strings[4]+strindex,len(encoded))==encoded:
                    if section==0 or info&15!=2: raise ValueError('Symbol is not a defined function')
                    found.append({'name':name,'value':address,'size':symbol_size,'index':index})
            if value&1: break
            index+=1
        else: raise ValueError('GNU chain exceeds lookup bound')
        if len(found)!=1: raise LookupError('Absent or ambiguous symbol: '+name)
        return found[0]

    def virtual(self,address,count):
        matches=[p for p in self.segments if p[0]==1 and p[2]<=address and address+count<=p[2]+p[4]]
        if len(matches)!=1: raise ValueError('ELF virtual range not uniquely file-backed')
        p=matches[0]
        return self.exact(p[1]+address-p[2],count)
