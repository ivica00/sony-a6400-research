import os
import sys
import subprocess
import tarfile
import shutil
import struct

from project_paths import PROJECT_ROOT as _PROJECT_ROOT, REFERENCE_ASSETS, legacy_output
PROJECT_ROOT = str(_PROJECT_ROOT)
FWTOOL_PATH = os.path.join(PROJECT_ROOT, "fwtool.py", "fwtool.py")
PYTHON_EXE = sys.executable
UFU_MAGIC = b'\x89\x55\x46\x55\x0d\x0a\x1a\x0a'

def extract_dat_from_exe(exe_path, out_dat_path):
    print(f"[*] Tražim Sony UFU zaglavlje u: {os.path.basename(exe_path)}...")
    with open(exe_path, 'rb') as f:
        data = f.read()
    
    idx = data.find(UFU_MAGIC)
    if idx == -1:
        raise ValueError("Sony UFU potpis (\\x89UFU\\r\\n\\x1a\\n) nije pronađen u izvršnom fajlu.")
    
    print(f"[+] UFU zaglavlje pronađeno na offsetu: {hex(idx)}")
    
    # Locate DEND chunk to find exact size
    dend_magic = b'DEND'
    dend_idx = data.find(dend_magic, idx)
    if dend_idx != -1:
        # DEND chunk header is 4 bytes size, 4 bytes type ('DEND'), 4 bytes CRC
        # The size field is 4 bytes before dend_idx
        dat_end = dend_idx + 4 + 4 # 'DEND' + 4-byte CRC
        dat_size = dat_end - idx
    else:
        # Fallback to end of file
        dat_size = len(data) - idx

    print(f"[*] Izdvajam DAT kontejner ({dat_size:,} bajtova) -> {out_dat_path}...")
    with open(out_dat_path, 'wb') as out_f:
        out_f.write(data[idx:idx + dat_size])
    print("[+] DAT fajl uspešno ekstraktovan.")

def unpack(input_file, output_dir=None):
    if not os.path.exists(input_file):
        print(f"[-] Greška: Fajl '{input_file}' ne postoji.")
        return

    base_name = os.path.splitext(os.path.basename(input_file))[0]
    if output_dir is None:
        output_dir = os.path.join(PROJECT_ROOT, "firmware", f"extracted_{base_name}")

    os.makedirs(output_dir, exist_ok=True)
    print("=" * 60)
    print(" SONY a6400 FIRMWARE UNPACKER & STATIC ANALYSIS TOOL")
    print("=" * 60)
    print(f"[*] Ulazni fajl: {input_file} ({os.path.getsize(input_file):,} bajtova)")

    target_dat = input_file
    if input_file.lower().endswith('.exe'):
        extracted_dat = os.path.join(output_dir, "firmware_extracted.dat")
        extract_dat_from_exe(input_file, extracted_dat)
        target_dat = extracted_dat

    print(f"[*] Izlazni folder: {output_dir}")
    print("[*] Pokretanje dekripcije (CXD90045 AES-CBC) i raspakivanja preko fwtool.py...")

    cmd = [PYTHON_EXE, FWTOOL_PATH, "unpack", "-f", target_dat, "-o", output_dir]
    res = subprocess.run(cmd)

    if res.returncode == 0:
        print("\n[+] Uspešno raspakovan i dešifrovan firmware!")
        print("\n[GOTOVO] Svi fajlovi, particije i skripte su izvučeni.")
    else:
        print("\n[-] fwtool.py je prijavio grešku pri raspakivanju.")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        candidates = []
        for f in os.listdir(os.path.join(PROJECT_ROOT, "firmware")):
            if f.lower().endswith(('.exe', '.dat', '.dmg')):
                candidates.append(os.path.join(PROJECT_ROOT, "firmware", f))
        
        if candidates:
            target = candidates[0]
            print(f"[*] Automatski detektovan firmware fajl: {target}")
        else:
            print("Upotreba: python -m tools.research.unpack_firmware <putanja_do_Update_ILCE6400V200.exe>")
            sys.exit(0)

    unpack(target)
