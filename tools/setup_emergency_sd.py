import hashlib
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
e_root = Path('E:/')

if not e_root.exists():
    print("ERROR: Drive E: not found!")
    sys.exit(1)

print("[1] Verifying authentic Backup.original.bin...")
orig_backup = ROOT / 'artifacts/hardware/Backup.original.bin'
if not orig_backup.exists():
    print("ERROR: artifacts/hardware/Backup.original.bin not found!")
    sys.exit(2)

backup_bytes = orig_backup.read_bytes()
sha = hashlib.sha256(backup_bytes).hexdigest()
print(f"  Length: {len(backup_bytes)} bytes, SHA-256: {sha}")
if sha != '11860ebe42f3b248284cfb3409ee65f18e658acd893658b5811c706ef709982a':
    print("WARNING: Backup checksum mismatch from original!")
    sys.exit(3)

# Copy backup to E:
print("[2] Copying Backup.original.bin and Backup.bin to E:...")
(e_root / 'Backup.original.bin').write_bytes(backup_bytes)
(e_root / 'Backup.bin').write_bytes(backup_bytes)

print("[3] Copying ARM native binaries...")
bin_emergency = ROOT / 'tools/native_camera/emergency_restore_arm'
bin_tiny = ROOT / 'tools/native_camera/patch_backup_tiny'

shutil.copy2(bin_emergency, e_root / 'emergency_restore')
shutil.copy2(bin_emergency, e_root / 'modern_menu')
shutil.copy2(bin_tiny, e_root / 'patch_backup_tiny')

print("[4] Creating recovery scripts...")
script_text = """#!/bin/sh
export PATH=/usr/bin:/bin:/sbin:/usr/sbin:/tmp

LOG="/mnt/EMERGENCY_RESTORE.log"
echo "=== EMERGENCY RESTORE SCRIPT STARTED ===" > "$LOG"

# 1. Restore Backup.bin directly from SD card
if [ -f /mnt/Backup.original.bin ]; then
    cp /mnt/Backup.original.bin /setting/Backup.bin
    echo "[+] Restored /setting/Backup.bin from Backup.original.bin" >> "$LOG"
elif [ -f /mnt/Backup.bin ]; then
    cp /mnt/Backup.bin /setting/Backup.bin
    echo "[+] Restored /setting/Backup.bin from Backup.bin" >> "$LOG"
fi

# 2. Run emergency_restore binary if executable
if [ -f /mnt/emergency_restore ]; then
    chmod 755 /mnt/emergency_restore /mnt/patch_backup_tiny /mnt/modern_menu 2>/dev/null
    /mnt/emergency_restore >> "$LOG" 2>&1
elif [ -f /mnt/patch_backup_tiny ]; then
    chmod 755 /mnt/patch_backup_tiny 2>/dev/null
    /mnt/patch_backup_tiny revert >> "$LOG" 2>&1
fi

# 3. Disable all hooks and preloads
rm -f /etc/ld.so.preload /tmp/ld.so.preload /tmp/autoexec.lock /tmp/autoexec_hook.so 2>/dev/null
echo "[+] Removed /etc/ld.so.preload and hooks" >> "$LOG"

# 4. Clean up any mod binaries in /tmp
rm -f /tmp/stream_dumper.elf /tmp/liba6400mod.so /tmp/clean_border.elf /tmp/a6400_gui.elf /tmp/modern_menu.elf /tmp/ritual_daemon /tmp/patch_backup 2>/dev/null

# 5. Clean autoexec.sh in /tmp
cat << 'EOF' > /tmp/autoexec.sh
#!/bin/sh
exit 0
EOF
chmod 755 /tmp/autoexec.sh

# 6. Create killswitch flags
touch /mnt/disable_hook /mnt/disable.txt /tmp/disable_hook 2>/dev/null
echo "[+] Created killswitch files" >> "$LOG"

sync
echo "=== EMERGENCY RESTORE COMPLETED ===" >> "$LOG"
""".replace('\r\n', '\n')

for name in ['watchdog.sh', 'autoexec.sh', 'restore.sh']:
    (e_root / name).write_bytes(script_text.encode('utf-8'))

a6400hb_dir = e_root / 'a6400hb'
a6400hb_dir.mkdir(exist_ok=True)
for name in ['watchdog.sh', 'autoexec.sh']:
    (a6400hb_dir / name).write_bytes(script_text.encode('utf-8'))

bin_dir = a6400hb_dir / 'bin'
bin_dir.mkdir(exist_ok=True)
shutil.copy2(bin_emergency, bin_dir / 'modern_menu')

print("[5] Verifying files on E:...")
files = list(e_root.iterdir())
for f in sorted(files):
    sz = f.stat().st_size if f.is_file() else "DIR"
    print(f"  - {f.name:25s} ({sz})")

print("\nSUCCESS: Emergency Reset SD Card is 100% prepared on E:!")
