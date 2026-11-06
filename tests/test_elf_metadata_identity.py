import struct
import unittest
from tools.research.elf_metadata_identity import compare_metadata_only


def fixture():
    raw=bytearray(0x200+6*40)
    names=b'\0.text\0.comment\0.note.gnu.build-id\0.shstrtab\0'
    raw[:52]=struct.pack('<16sHHIIIIIHHHHHH',b'\x7fELF\x01\x01\x01'+b'\0'*9,
                        1,40,1,0,0,0x200,0,52,0,0,40,6,5)
    raw[0x100:0x104]=b'CODE'; raw[0x104:0x108]=b'META'; raw[0x108:0x10c]=b'NOTE'
    raw[0x110:0x110+len(names)]=names
    for i,(name,kind,flags,offset,size) in enumerate([
            (0,0,0,0,0),(1,1,6,0x100,4),(7,1,0,0x104,4),
            (16,7,2,0x108,4),(0,8,3,0,16),(35,3,0,0x110,len(names))]):
        struct.pack_into('<10I',raw,0x200+i*40,name,kind,flags,0,offset,size,0,0,1,0)
    return bytes(raw)


class ElfMetadataIdentityTests(unittest.TestCase):
    def test_accepts_only_metadata_payload_changes(self):
        original=fixture(); changed=bytearray(original)
        changed[0x104:0x10c]=b'12345678'
        result=compare_metadata_only(bytes(changed),original)
        self.assertTrue(result['equivalent'])
        self.assertEqual(len(result['metadata_differences']),2)

    def test_rejects_code_header_and_layout_changes(self):
        original=fixture()
        for offset in (0x100,24,0x200+2*40+16):
            changed=bytearray(original); changed[offset]^=1
            self.assertFalse(compare_metadata_only(bytes(changed),original)['equivalent'])

    def test_rejects_metadata_overlap_with_code(self):
        original=bytearray(fixture())
        struct.pack_into('<I',original,0x200+2*40+16,0x100)
        changed=bytearray(original); changed[0x100]^=1
        self.assertFalse(compare_metadata_only(bytes(changed),bytes(original))['equivalent'])


if __name__=='__main__': unittest.main()
