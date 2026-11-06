import struct
import unittest
from tools.camera_debugger import Debugger, DebuggerError, ProtocolError, HEADER, MAGIC, MAX_DATA, FRAME_SIZE, encode, decode


def response(op, request_id, data=b'', status=0, flags=0):
    return (HEADER.pack(MAGIC,1,op,request_id,status,len(data),flags,0,0)+data).ljust(FRAME_SIZE,b'\0')


class DebuggerProtocolTests(unittest.TestCase):
    def test_rejects_stale_mismatched_and_oversized_responses(self):
        for raw in (response(1,2),response(2,1),response(1,1)[:-1],
                    HEADER.pack(MAGIC,1,1,1,0,MAX_DATA+1,0,0,0).ljust(FRAME_SIZE,b'\0')):
            with self.assertRaises(ProtocolError): decode(raw,1,1)

    def test_read_all_advances_offsets_handles_partial_reads_and_eof(self):
        source=b'x'*(MAX_DATA+19)
        offsets=[]
        def exchange(raw):
            _,_,op,seq,_,length,_,offset,size=HEADER.unpack_from(raw)
            self.assertEqual(raw[HEADER.size:HEADER.size+length],b'/proc/149/maps')
            offsets.append(offset)
            return response(op,seq,source[offset:offset+min(size,127)])
        actual,truncated=Debugger(exchange).read_all('/proc/149/maps')
        self.assertEqual(actual,source)
        self.assertFalse(truncated)
        self.assertEqual(offsets[-1],len(source))

    def test_exact_read_limit_probes_eof_and_reports_real_truncation(self):
        for source,expected in ((b'abc',False),(b'abcd',True)):
            def exchange(raw):
                _,_,op,seq,_,_,_,offset,size=HEADER.unpack_from(raw)
                return response(op,seq,source[offset:offset+size])
            self.assertEqual(Debugger(exchange).read_all('/file',3),(b'abc',expected))

    def test_negative_errno_and_positive_command_exit_are_distinct(self):
        with self.assertRaises(DebuggerError) as caught:
            Debugger(lambda raw:response(1,1,status=-13)).request(1)
        self.assertEqual(caught.exception.status,-13)
        self.assertEqual(Debugger(lambda raw:response(3,1,b'failed',7)).request(3,b'exit 7')['status'],7)

    def test_memory_requires_exact_successful_length(self):
        with self.assertRaises(ProtocolError):
            Debugger(lambda raw:response(4,1,b'xx')).memory(149,0x1000,4)
        with self.assertRaises(ValueError):
            Debugger(None).memory(149,0xfffffffe,4)

    def test_bounds_and_paths_checked_before_transport(self):
        for path in ('relative','/a\0b','/'+('a'*511)):
            with self.assertRaises(ValueError): Debugger(None).read(path)
        with self.assertRaises(ValueError): encode(1,1,b'x'*(MAX_DATA+1))
        self.assertEqual(len(encode(1,1,b'x'*MAX_DATA)),FRAME_SIZE)


if __name__=='__main__': unittest.main()
