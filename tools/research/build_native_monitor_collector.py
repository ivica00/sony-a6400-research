"""Build bounded monitor collector against Sony libc; does not deploy."""
import argparse,hashlib,json,os,subprocess
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',required=True)
    out=(ROOT/parser.parse_args().output_dir).resolve()
    if not out.is_relative_to(ROOT/'artifacts'):parser.error('Output must remain under artifacts')
    if (out/'manifest.json').exists():parser.error('Use a new artifact directory')
    out.mkdir(parents=True,exist_ok=True)
    source=ROOT/'tools/native_camera/native_monitor_collector.c';target=out/'native_monitor_collector.elf'
    reader=ROOT/'tools/native_camera/native_monitor_output_ack.c'
    header=ROOT/'tools/native_camera/native_monitor_snapshot.h'
    rel=lambda p:p.relative_to(ROOT).as_posix()
    command=['arm-linux-gnueabi-gcc',*'-std=gnu11 -march=armv7-a -mfloat-abi=softfp -O2 -Wall -Wextra -Werror -nostdlib -DA6400_MONITOR_EMBEDDED -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 -U_TIME_BITS -D_TIME_BITS=32 -U_FILE_OFFSET_BITS -D_FILE_OFFSET_BITS=32 -fno-stack-protector'.split(),'-Wl,-e,_start,-z,defs,-z,max-page-size=4096,--dynamic-linker=/lib/ld-linux.so.3','-o',rel(target),'tools/native_camera/snapshot_start.S',rel(source),rel(reader),'tools/sony_sysroot/lib/libc.so','-lgcc']
    if os.name=='nt':command=['wsl.exe','--cd','/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:],'--exec',*command]
    subprocess.run(command,cwd=ROOT,check=True)
    (out/'manifest.json').write_text(json.dumps({'status':'built_not_deployed','camera_access':False,'command':command,'limitations':['Passive, fixed --sd-info and fixed --sd-journal/--sd-journal-verify modes; journal commands are compile-time constants and only the run-owned expected RAM path is parameterized. No arbitrary command text. No physical verification.','SD modes preserve output before prefix acknowledgement; this is not exclusive ownership. Journal creation is not O_EXCL: a read-only cmp checks the fixed target path is absent before writing, but creation is not atomic against another writer.'],'files':{rel(p):{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in [source,reader,header,target,ROOT/'tools/native_camera/snapshot_start.S',ROOT/'tools/sony_sysroot/lib/libc.so']}},indent=2)+'\n')
    print('Built bounded monitor collector; not deployed')


if __name__=='__main__':main()
