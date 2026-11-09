import sys, io
sys.path.insert(0, 'Sony-PMCA-RE')
from pmca.backup import BackupFile

with open('artifacts/hardware/Backup.original.bin', 'rb') as f:
    data = f.read()

bf = BackupFile(io.BytesIO(data))
props = list(bf.listProperties())
print(f"Total backup properties: {len(props)}")
print(f"First element: {props[0]}")
for item in props:
    prop_id = item[0] if isinstance(item, tuple) else item.id
    if (prop_id >> 16) in [0x0108, 0x0164, 0x0171, 0x0107, 0x0166]:
        prop_data = item[1].data if hasattr(item[1], 'data') else (item[1] if isinstance(item[1], bytes) else str(item[1]))
        print(f"ID 0x{prop_id:08x}: {prop_data}")
