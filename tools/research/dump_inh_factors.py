import sys, os, struct
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from tools.camera_debugger import connect

def main():
    tbl_addr = 0x05ac4008
    with connect() as d:
        raw = d.memory(149, tbl_addr, 160 * 4)
    
    words = struct.unpack('<160I', raw)
    active_factors = []
    for w_idx, w in enumerate(words):
        for bit in range(32):
            if (w >> bit) & 1:
                factor_id = w_idx * 32 + bit
                active_factors.append(factor_id)
                
    print(f"Total active inhibition factors in MSC mode: {len(active_factors)}")
    print("Active factors:")
    for f in active_factors:
        print(f"  0x{f:04x} ({f}) [word {f//32}, bit {f%32}]")

if __name__ == '__main__':
    main()
