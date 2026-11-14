import os
import sys
import struct
import hashlib

def print_header(title):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)

class SonyFirmwareParser:
    UFU_MAGIC = b'\x89\x55\x46\x55\x0d\x0a\x1a\x0a' # \x89UFU\r\n\x1a\n

    def __init__(self, filepath):
        self.filepath = filepath
        self.filesize = os.path.getsize(filepath)

    def scan_for_ufu(self):
        """Scans any file (e.g. .exe, .dat, .bin) for the Sony UFU header"""
        print(f"[*] Analyzing file: {os.path.basename(self.filepath)} ({self.filesize:,} bytes)")
        offsets = []
        with open(self.filepath, 'rb') as f:
            chunk_size = 1024 * 1024
            buffer = b''
            offset = 0
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                buffer += data
                pos = 0
                while True:
                    idx = buffer.find(self.UFU_MAGIC, pos)
                    if idx == -1:
                        break
                    offsets.append(offset + idx)
                    pos = idx + len(self.UFU_MAGIC)
                offset += len(data)
                buffer = buffer[-len(self.UFU_MAGIC):]
        return offsets

    def parse_dat(self, start_offset=0):
        """Parses chunks from a DAT/UFU stream starting at start_offset"""
        chunks = []
        with open(self.filepath, 'rb') as f:
            f.seek(start_offset)
            magic = f.read(8)
            if magic != self.UFU_MAGIC:
                raise ValueError("Invalid UFU magic signature.")
            
            while True:
                header = f.read(8)
                if len(header) < 8:
                    break
                chunk_len, chunk_type = struct.unpack('>I4s', header)
                chunk_offset = f.tell()
                
                chunk_info = {
                    'type': chunk_type.decode('latin1', 'replace'),
                    'offset': chunk_offset,
                    'size': chunk_len
                }
                
                # Sample the first 16 bytes of chunk data
                sample = f.read(min(chunk_len, 32))
                chunk_info['sample_hex'] = sample.hex()
                chunks.append(chunk_info)
                
                # Advance to next chunk (aligned)
                f.seek(chunk_offset + chunk_len)
                if f.tell() >= self.filesize:
                    break
        return chunks

    def extract_chunk(self, chunk_info, output_path):
        """Extracts a specific chunk to a standalone binary file"""
        with open(self.filepath, 'rb') as src, open(output_path, 'wb') as dst:
            src.seek(chunk_info['offset'])
            remaining = chunk_info['size']
            while remaining > 0:
                block = src.read(min(remaining, 64 * 1024))
                if not block:
                    break
                dst.write(block)
                remaining -= len(block)
        print(f"[+] Chunk '{chunk_info['type']}' successfully extracted -> {output_path} ({chunk_info['size']:,} bytes)")

def run_analysis(file_path):
    parser = SonyFirmwareParser(file_path)
    offsets = parser.scan_for_ufu()
    
    if not offsets:
        print("[-] Sony UFU firmware header not found in this file.")
        return
    
    print(f"[+] Found {len(offsets)} UFU headers at offsets: {[hex(o) for o in offsets]}")
    for idx, off in enumerate(offsets):
        print_header(f"UFU Container #{idx + 1} (Offset: {hex(off)})")
        chunks = parser.parse_dat(off)
        for i, c in enumerate(chunks):
            print(f" [{i+1:02d}] Type: {c['type']:<6} | Offset: 0x{c['offset']:08x} | Size: {c['size']:>10,} B | Sample: {c['sample_hex'][:32]}")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        run_analysis(sys.argv[1])
    else:
        # Default test against existing DAT files in the repo as baseline
        sample_dat = os.path.join('Sony-PMCA-RE', 'updatershell', 'fdat', 'CXD90014.dat')
        if os.path.exists(sample_dat):
            print_header("BENCHMARK TEST ON EXISTING CXD90014 FIRMWARE DAT")
            run_analysis(sample_dat)
        else:
            print("Usage: python -m tools.research.firmware_analyzer <path_to_exe_or_dat>")
