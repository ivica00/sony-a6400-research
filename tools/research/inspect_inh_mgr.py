import struct
from tools.camera_debugger import connect

def main():
    with connect() as d:
        tbl_addr = 0x05ac4008
        raw_tbl = d.memory(149, tbl_addr, 160 * 4)
        words = struct.unpack(f'<{160}I', raw_tbl)
        
        factor_id = 0x85b
        word_idx = factor_id >> 5
        bit_idx = factor_id & 31
        
        print(f"Factor 0x85b ({factor_id}): word {word_idx}, bit {bit_idx}")
        print(f"Word {word_idx} value: 0x{words[word_idx]:08x}")
        is_set = (words[word_idx] & (1 << bit_idx)) != 0
        print(f"Factor 0x85b is set: {is_set}")
        
        # Check non-zero words
        non_zero = [(i, w) for i, w in enumerate(words) if w != 0]
        print(f"Total non-zero words in inh_tbl: {len(non_zero)} / 160")
        for i, w in non_zero:
            print(f"  word {i:3d} (factors {i*32:4d}-{i*32+31:4d}): 0x{w:08x}")

if __name__ == '__main__':
    main()
