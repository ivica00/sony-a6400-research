"""Verify binary upload over normal USB, then remove only this probe file."""
import json
from pathlib import Path
from datetime import datetime
from tools.camera_debugger import connect

ROOT=Path(__file__).resolve().parents[2]


def main():
    destination=ROOT/'artifacts/hardware'/('native-debug-upload-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    destination.mkdir(parents=True,exist_ok=False)
    data=bytes(range(256))*3+b"\x00'\\\xff"
    with connect() as debugger:
        report=debugger.push('/tmp_bt/a6400_debug_upload_probe.bin',data)
        cleanup=debugger.request(3,b'rm -f /tmp_bt/a6400_debug_upload_probe.bin')
        report.update(mode_switches=False,cleanup_status=cleanup['status'])
    (destination/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(report); print(destination)


if __name__=='__main__': main()
