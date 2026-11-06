import struct
import unittest
from tools.research.remote_elf import RemoteElf32


def fixture():
    data=bytearray(0x200+5*40)
    data[:52]=struct.pack('<16sHHIIIIIHHHHHH',b'\x7fELF\x01\x01\x01'+b'\0'*9,
        3,40,1,0,52,0x200,0,52,32,1,40,5,0)
    struct.pack_into('<8I',data,52,1,0,0,0,len(data),len(data),5,4096)
    struct.pack_into('<IIIBBH',data,0x110,1,0x181,6,0x12,0,4)
    data[0x140:0x143]=b'\0f\0'
    struct.pack_into('<7I',data,0x150,1,1,1,5,0,1,RemoteElf32.hash_name('f')|1)
    data[0x180:0x186]=b'ABCdef'
    for i,(kind,offset,size,link,entsize) in enumerate([(0,0,0,0,0),(11,0x100,32,2,16),
                                                     (3,0x140,3,0,0),(0x6ffffff6,0x150,28,0,0),(1,0x180,6,0,0)]):
        struct.pack_into('<10I',data,0x200+i*40,0,kind,0,offset,offset,size,link,0,4,entsize)
    return data


class RemoteElfTests(unittest.TestCase):
    def test_resolves_export_and_virtual_file_mapping(self):
        data=fixture(); elf=RemoteElf32(lambda offset,count:bytes(data[offset:offset+count]))
        self.assertEqual(elf.resolve('f')['value'],0x181)
        self.assertEqual(elf.virtual(0x180,6),b'ABCdef')
        with self.assertRaises(LookupError): elf.resolve('missing')

    def test_rejects_out_of_range_gnu_bucket(self):
        data=fixture(); struct.pack_into('<I',data,0x164,999)
        elf=RemoteElf32(lambda offset,count:bytes(data[offset:offset+count]))
        with self.assertRaises(ValueError): elf.resolve('f')

    def test_rejects_truncated_or_wrong_architecture(self):
        data=fixture(); data[18]=3
        with self.assertRaises(ValueError): RemoteElf32(lambda offset,count:bytes(data[offset:offset+count]))
        with self.assertRaises(ValueError): RemoteElf32(lambda offset,count:b'')


if __name__=='__main__': unittest.main()
