import os
import sys
import re
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM

from project_paths import PROJECT_ROOT as _PROJECT_ROOT, REFERENCE_ASSETS, legacy_output
PROJECT_ROOT = str(_PROJECT_ROOT)
KMOD_DIR = os.path.join(
    PROJECT_ROOT, "firmware", "extracted_a6400", "firmware.tar_unpacked",
    "0700_part_image", "dev", "nflasha7_unpacked", "kmod"
)
BIN_DIR = os.path.join(
    PROJECT_ROOT, "firmware", "extracted_a6400", "firmware.tar_unpacked",
    "0700_part_image", "dev", "nflasha15_unpacked", "bin"
)

def print_separator(title):
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)

def extract_strings(data, min_len=4):
    """Extract printable ASCII strings from binary data"""
    return re.findall(rb'[A-Za-z0-9_\-\.\:\/]{' + str(min_len).encode() + rb',}', data)

def analyze_kmod(filepath):
    filename = os.path.basename(filepath)
    print_separator(f"KERNEL DRIVER ANALYSIS: {filename}")
    
    with open(filepath, 'rb') as f:
        elf = ELFFile(f)
        
        # 1. Modinfo
        modinfo_sec = elf.get_section_by_name('.modinfo')
        if modinfo_sec:
            raw_info = modinfo_sec.data().decode('latin1', 'ignore').split('\x00')
            print("[*] .modinfo (Driver information):")
            for item in raw_info:
                if item:
                    print(f"    - {item}")

        # 2. Section Map
        print("\n[*] Memory sections in ELF object:")
        for s in elf.iter_sections():
            if s.data_size > 0:
                print(f"    {s.name:<24} | Size: {s.data_size:>7,} B | Type: {s['sh_type']}")

        # 3. Functions & Symbols
        symtab = elf.get_section_by_name('.symtab')
        if symtab:
            funcs = []
            mmio_calls = []
            for sym in symtab.iter_symbols():
                name = sym.name
                st_type = sym['st_info']['type']
                if st_type == 'STT_FUNC' and name:
                    funcs.append((name, sym['st_value']))
                if any(k in name.lower() for k in ['ioremap', 'request_mem', 'dma_', 'register', 'mpr', 'ioctl', 'irq']):
                    mmio_calls.append(name)
            
            print(f"\n[*] Functions found in driver: {len(funcs)}")
            for name, val in funcs[:15]:
                print(f"    - {name:<35} @ 0x{val:08x}")
            if len(funcs) > 15:
                print(f"      ... and {len(funcs) - 15} more functions.")

            if mmio_calls:
                print("\n[*] Hardware / MMIO / Registration function references:")
                for call in sorted(set(mmio_calls)):
                    print(f"    --> {call}")

        # 4. Device Nodes (/dev/...) and Hardware Strings
        f.seek(0)
        all_data = f.read()
        dev_nodes = set(re.findall(rb'/dev/[A-Za-z0-9_\-]+', all_data))
        if dev_nodes:
            print("\n[*] Registered /dev/ nodes for communication:")
            for d in dev_nodes:
                print(f"    [DEVICE NODE]: {d.decode('latin1')}")

def analyze_user_binary(filepath):
    filename = os.path.basename(filepath)
    print_separator(f"USER PROCESS ANALYSIS: {filename}")
    
    with open(filepath, 'rb') as f:
        elf = ELFFile(f)
        
        # Dynamic libraries
        dyn_sec = elf.get_section_by_name('.dynamic')
        if dyn_sec:
            libs = []
            for tag in dyn_sec.iter_tags():
                if tag.entry.d_tag == 'DT_NEEDED':
                    libs.append(tag.needed)
            print("[*] Dependent shared libraries (DT_NEEDED):")
            for lib in libs:
                print(f"    - {lib}")

        # Device nodes referenced
        f.seek(0)
        data = f.read()
        devs = set(re.findall(rb'/dev/[A-Za-z0-9_\-]+', data))
        if devs:
            print("\n[*] Accesses hardware /dev/ nodes:")
            for d in devs:
                print(f"    --> {d.decode('latin1')}")

        # IPC & Service calls
        ipc_strings = [s.decode('latin1') for s in extract_strings(data, 6) if any(w in s.lower() for w in [b'dmac', b'ws_', b'fb', b'disp', b'sen', b'mpr'])]
        if ipc_strings:
            print("\n[*] Key symbols and IPC commands (sample):")
            for s in sorted(set(ipc_strings))[:15]:
                print(f"    - {s}")

if __name__ == '__main__':
    print("=" * 70)
    print(" SONY a6400 (CXD90045) HARDWARE REVERSE ENGINEERING & MMIO DISCOVERY")
    print("=" * 70)
    
    # 1. Analyze kmods
    if os.path.exists(KMOD_DIR):
        for kmod in ['dmac.ko', 'lld.ko', 'ldec.ko', 'emmc.ko', 'nand.ko']:
            kp = os.path.join(KMOD_DIR, kmod)
            if os.path.exists(kp):
                analyze_kmod(kp)
    else:
        print(f"[-] Kmod directory does not exist: {KMOD_DIR}")

    # 2. Analyze key user binaries
    if os.path.exists(BIN_DIR):
        for b in ['WS_SubProcess.elf', 'im.elf', 'adjstctl.elf']:
            bp = os.path.join(BIN_DIR, b)
            if os.path.exists(bp):
                analyze_user_binary(bp)
    else:
        print(f"[-] Bin directory does not exist: {BIN_DIR}")
