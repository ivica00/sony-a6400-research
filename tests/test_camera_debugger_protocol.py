import struct
import unittest
from tools.camera_debugger import (Debugger, DebuggerError, ProtocolError, HEADER, MAGIC,
                                  MAX_DATA, FRAME_SIZE, RECOVER_ARG, encode, decode)


def response(op, request_id, data=b'', status=0, flags=0, arg0=0, arg1=0):
    return (HEADER.pack(MAGIC,1,op,request_id,status,len(data),flags,arg0,arg1)+data).ljust(FRAME_SIZE,b'\0')


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


class DebuggerV2ProtocolTests(unittest.TestCase):
    def test_ping_echoes_the_nonce_and_rejects_a_mismatch(self):
        seen=[]
        def exchange(raw):
            magic,version,op,seq,status,length,flags,arg0,arg1=HEADER.unpack_from(raw)
            seen.append((op,arg0))
            return response(op,seq,('PONG protocol=2 nonce=0x%08x\n'%arg0).encode(),arg0=arg0)
        text=Debugger(exchange).ping(0x12345678)
        self.assertIn('nonce=0x12345678',text)
        self.assertEqual(seen,[(13,0x12345678)])

        def broken(raw):
            magic,version,op,seq,status,length,flags,arg0,arg1=HEADER.unpack_from(raw)
            return response(op,seq,b'PONG\n',arg0=arg0^1)
        with self.assertRaises(ProtocolError):
            Debugger(broken).ping(1)

    def test_usb_state_is_operation_8(self):
        seen=[]
        def exchange(raw):
            magic,version,op,seq,status,length,flags,arg0,arg1=HEADER.unpack_from(raw)
            seen.append((op,arg0,arg1))
            return response(op,seq,b'A6400_USB_DEBUG_STATE\nprotocol=2\n')
        text=Debugger(exchange).usb_state()
        self.assertTrue(text.startswith('A6400_USB_DEBUG_STATE'))
        self.assertEqual(seen,[(8,0,0)])

    def test_recover_names_the_operation_and_returns_receipt(self):
        seen=[]
        def exchange(raw):
            magic,version,op,seq,status,length,flags,arg0,arg1=HEADER.unpack_from(raw)
            seen.append((op,arg1))
            return response(op,seq,b'RECOVER_V1\nresult=clean\n')
        text=Debugger(exchange).recover()
        self.assertIn('result=clean',text)
        self.assertEqual(seen,[(9,RECOVER_ARG)])

    def test_chunked_readout_advances_offsets_and_verifies_snapshot_length(self):
        source=bytes(range(256))*20
        offsets=[]
        def exchange(raw):
            magic,version,op,seq,status,length,flags,arg0,arg1=HEADER.unpack_from(raw)
            offsets.append(arg0)
            return response(op,seq,source[arg0:arg0+arg1],arg0=len(source))
        data,total,secondary=Debugger(exchange).dmesg()
        self.assertEqual(data,source)
        self.assertEqual(total,len(source))
        self.assertIsNone(secondary)
        self.assertEqual(offsets[0],0)
        self.assertEqual(offsets[1],MAX_DATA)

    def test_changed_snapshot_between_chunks_is_rejected(self):
        calls=[0]
        total_sizes=[3*MAX_DATA,14*MAX_DATA]
        def exchange(raw):
            magic,version,op,seq,status,length,flags,arg0,arg1=HEADER.unpack_from(raw)
            total=total_sizes[min(calls[0],1)]
            calls[0]+=1
            return response(op,seq,b'x'*min(arg1,MAX_DATA,3*MAX_DATA-arg0),arg0=total)
        with self.assertRaises(ProtocolError):
            Debugger(exchange).dmesg(limit=3*MAX_DATA)

    def test_short_readout_is_rejected(self):
        def exchange(raw):
            magic,version,op,seq,status,length,flags,arg0,arg1=HEADER.unpack_from(raw)
            return response(op,seq,b'',arg0=64)
        with self.assertRaises(ProtocolError):
            Debugger(exchange).dmesg(limit=64)

    def test_ring_capture_cross_checks_dump_against_receipt(self):
        import struct as _struct, zlib
        from src.a6400 import usb_debug_ring
        body=('[    0.016837] WARMBOOT\n').encode()+b'log line\n'
        capacity=usb_debug_ring.DEFAULT_CAPACITY
        raw=(b'klog'+_struct.pack('<II',len(body),0)+body).ljust(capacity,b'\x55')
        receipt=('\n'.join(['KLOG_RING_V1','valid=1','klog.addr=0x035a5000',
            f'klog.size=0x{capacity:08x}','header.write_position=%d'%len(body),
            'header.wrap=0','data_bytes=%d'%len(body),
            'crc32=0x%08x'%(zlib.crc32(raw[:12+len(body)])&0xffffffff),'warmboot_markers=1',''])).encode()
        def exchange(request):
            magic,version,op,seq,status,length,flags,arg0,arg1=HEADER.unpack_from(request)
            if op==12:
                return response(op,seq,receipt)
            return response(op,seq,raw[arg0:arg0+arg1],arg0=12+len(body),arg1=0)
        captured,analysis,parsed,verification=Debugger(exchange).ring_capture()
        self.assertEqual(captured,raw[:12+len(body)])
        self.assertEqual(analysis['boot_count'],1)
        self.assertTrue(verification['verified'])
        self.assertEqual(parsed['klog.address'],0x035A5000)


if __name__=='__main__': unittest.main()
