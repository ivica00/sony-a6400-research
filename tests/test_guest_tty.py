import struct
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r'C:\Users\Administrator\Desktop\a6400 project')))
from src.a6400.execution.guest_tty import GuestTty, UnsupportedTtyError
class T(unittest.TestCase):
    def test_open_write_close(self):
        t=GuestTty(); o=t.open(0x902, 1018, 1000); self.assertEqual(t.write(o,b'MWF> log\n',tid=1018),9)
        d=t.describe(); self.assertEqual(d['opens'],1); self.assertEqual(d['writes'],1); self.assertEqual(d['bytes_written'],9)
    def test_refusals(self):
        t=GuestTty()
        with self.assertRaises(UnsupportedTtyError): t.open(0x1002)
        with self.assertRaises(UnsupportedTtyError): t.write({'owner':0}, b'x'*0x10001)
        with self.assertRaises(UnsupportedTtyError): t.read()
        with self.assertRaises(UnsupportedTtyError): t.ioctl(0x5401,0)
if __name__=='__main__': unittest.main()
