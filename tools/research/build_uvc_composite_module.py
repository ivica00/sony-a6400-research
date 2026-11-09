"""Build the complete composite a6400 UVC kernel module.

Integrates reference ZV-E10 usbg_video.ko with:
1. Device node table shim (entry 55: usb/video, major 248, minor 33)
2. Dual-interface gadgetcore callback bridge
3. Proactive DMA quiescence and teardown lifecycle
"""

import argparse
import hashlib
import json
import os
import struct
import subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[2]
REF_KO = ROOT / 'firmware/extracted_zve10_v203_linuxnames/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/usbg_video.ko'
REF_SHA = 'd385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--start-probe-only', action='store_true',
                        help='Validate and log START endpoint; do not enter reference callback')
    parser.add_argument('--native-buffer-allocation', action='store_true',
                        help='Keep original DMM-backed buffer allocation/free implementations')
    parser.add_argument('--coherent-buffer-allocation', action='store_true',
                        help='Use real kernel-owned coherent DMA memory in the MOD allocator')
    parser.add_argument('--experimental-fixed-buffer', action='store_true',
                        help='Explicit historical test policy; uses an unowned fixed RAM window')
    parser.add_argument('--shared-ptp-enumeration-candidate',action='store_true',
                        help='Build OFFLINE shared PTP/UVC enumeration candidate; video START/submission disabled')
    parser.add_argument('--trace-control',action='store_true',help='Bounded descriptor/native-ioctl logging; no extra kernel hooks')
    args = parser.parse_args()
    if args.shared_ptp_enumeration_candidate:
        if args.experimental_fixed_buffer or args.native_buffer_allocation:
            parser.error('Shared enumeration candidate requires owned coherent allocation')
        args.coherent_buffer_allocation=True;args.start_probe_only=True
    if sum([args.native_buffer_allocation,args.coherent_buffer_allocation,
            args.experimental_fixed_buffer])>1:
        parser.error('Choose one native allocator policy')
    if not args.coherent_buffer_allocation and not args.experimental_fixed_buffer:
        args.native_buffer_allocation=True
    out = args.output_dir.resolve()

    if not out.is_relative_to(ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')

    if digest(REF_KO) != REF_SHA:
        raise ValueError('Reference module identity mismatch')

    out.mkdir(parents=True, exist_ok=True)

    shim_src = ROOT / 'tools/native_camera/uvc_composite_shim.c'
    bridge_src = ROOT / 'tools/native_camera/uvc_callback_bridge.c'
    bridge_hdr = ROOT / 'tools/native_camera/uvc_callback_bridge.h'

    rebound_ref = out / 'reference.rebound.o'
    compiled_shim = out / 'composite-shim.o'
    compiled_bridge = out / 'callback-bridge.o'
    final_ko = out / ('usbg_video_a6400_shared_candidate.ko' if args.shared_ptp_enumeration_candidate else 'usbg_video_a6400.ko')
    ioctl_name='a6400_uvc_shared_ioctl' if args.shared_ptp_enumeration_candidate else 'a6400_uvc_video_core_ioctl'
    free_name='a6400_uvc_shared_free_phys_buffer' if args.shared_ptp_enumeration_candidate else 'a6400_usb_sync_free_phys_buffer'

    def rel(path):
        return path.relative_to(ROOT).as_posix()

    def run(tool, cmd_args):
        command = [tool, *cmd_args]
        if os.name != 'posix':
            linux_path = '/mnt/' + ROOT.drive[0].lower() + ROOT.as_posix()[2:]
            command = ['wsl.exe', '--cd', linux_path, '--exec', *command]
        subprocess.run(command, cwd=ROOT, check=True)

    print("Step 1: Redefining symbols in reference usbg_video.ko...")
    redefinitions = [
        '--redefine-sym', 'udif_devnodes=a6400_uvc_devnodes',
        '--redefine-sym', 'usb_gadgetcore_register_driver='+('a6400_uvc_shared_register_hook' if args.shared_ptp_enumeration_candidate else 'a6400_uvc_gadgetcore_register_hook'),
        '--redefine-sym', 'usb_gadgetcore_unregister_driver='+('a6400_uvc_shared_unregister_hook' if args.shared_ptp_enumeration_candidate else 'a6400_uvc_gadgetcore_unregister_hook'),
        '--add-symbol', ioctl_name+'=0,global',
    ]
    if args.shared_ptp_enumeration_candidate:
        redefinitions+=['--add-symbol','a6400_uvc_shared_release=0,global']
    if not args.native_buffer_allocation:
        redefinitions += [
            '--redefine-sym', 'usb_sync_alloc_phys_buffer=a6400_usb_sync_alloc_phys_buffer',
            '--redefine-sym', 'usb_sync_free_phys_buffer='+free_name,
        ]
    else:
        redefinitions += [
            '--redefine-sym', 'osal_snd_msg=a6400_uvc_dmm_snd_log',
            '--redefine-sym', 'osal_rcv_msg_tmo=a6400_uvc_dmm_rcv_log',
        ]
    if args.coherent_buffer_allocation:
        redefinitions += ['--redefine-sym',
                          'arch_phys_to_noncache=a6400_uvc_owned_noncache']
    run('arm-linux-gnueabi-objcopy', [*redefinitions, rel(REF_KO), rel(rebound_ref)])

    # Convert redefined buffer alloc/free and added ioctl wrapper into undefined references
    # so they link to the a6400 composite shim implementation.
    with rebound_ref.open('rb') as f:
        elf_temp = ELFFile(f)
        symtab_temp = elf_temp.get_section_by_name('.symtab')
        st_offset = symtab_temp['sh_offset']
        st_entsize = symtab_temp['sh_entsize']
        sym_indices = {}
        target_undefs = [ioctl_name]
        if args.shared_ptp_enumeration_candidate:target_undefs+=['a6400_uvc_shared_release']
        if not args.native_buffer_allocation:
            target_undefs += ['a6400_usb_sync_alloc_phys_buffer', free_name]
        module_index=None
        for i, s in enumerate(symtab_temp.iter_symbols()):
            if s.name=='__this_module':module_index=i
            if s.name in target_undefs:
                sym_indices[s.name] = i

        reldata_temp = elf_temp.get_section_by_name('.rel.data')
        rel_offset = reldata_temp['sh_offset']
        rel_entsize = reldata_temp['sh_entsize']
        rel_size=reldata_temp['sh_size']
        rel_section_index=next(i for i,s in enumerate(elf_temp.iter_sections()) if s.name=='.rel.data')
        section_table=elf_temp['e_shoff'];section_entry_size=elf_temp['e_shentsize']
        data_offset=elf_temp.get_section_by_name('.data')['sh_offset']
        text_offset=elf_temp.get_section_by_name('.text')['sh_offset']
        ioctl_rel_idx = None
        release_rel_idx=None
        for j, r in enumerate(reldata_temp.iter_relocations()):
            if r.entry['r_offset'] == 100:  # offset 0x64 in .data is unlocked_ioctl
                ioctl_rel_idx = j
            if r.entry['r_offset']==0x78:release_rel_idx=j

    raw_rebound = bytearray(rebound_ref.read_bytes())
    for name, idx in sym_indices.items():
        entry_off = st_offset + idx * st_entsize
        struct.pack_into('<II', raw_rebound, entry_off + 4, 0, 0)  # st_value=0, st_size=0
        struct.pack_into('<H', raw_rebound, entry_off + 14, 0)     # st_shndx=SHN_UNDEF

    if ioctl_rel_idx is not None and ioctl_name in sym_indices:
        ioctl_sym_idx = sym_indices[ioctl_name]
        rel_entry_off = rel_offset + ioctl_rel_idx * rel_entsize
        struct.pack_into('<I', raw_rebound, rel_entry_off + 4, (ioctl_sym_idx << 8) | 2)
    if args.shared_ptp_enumeration_candidate:
        if module_index is None or release_rel_idx is None or ioctl_rel_idx is None:
            raise ValueError('Missing reference file-operations ABI')
        struct.pack_into('<I',raw_rebound,rel_offset+release_rel_idx*rel_entsize+4,
                         (sym_indices['a6400_uvc_shared_release']<<8)|2)
        if struct.unpack_from('<I',raw_rebound,data_offset+0x44)[0]!=0:
            raise ValueError('Unexpected original file-operations owner')
        # Append one valid ELF32 relocation payload and point its unchanged
        # section header to it. Owner=THIS_MODULE pins every open file.
        relocation_payload=bytes(raw_rebound[rel_offset:rel_offset+rel_size])+struct.pack('<II',0x44,(module_index<<8)|2)
        new_offset=(len(raw_rebound)+3)&~3
        raw_rebound.extend(bytes(new_offset-len(raw_rebound)))
        raw_rebound.extend(relocation_payload)
        struct.pack_into('<II',raw_rebound,section_table+rel_section_index*section_entry_size+16,new_offset,len(relocation_payload))
        for offset,old,new in [(0x116c,'7e20e0e3','7b20e0e3'),(0x13e8,'ff5015e2','015055e2')]:
            if raw_rebound[text_offset+offset:text_offset+offset+4]!=bytes.fromhex(old):
                raise ValueError('Reference endpoint/classifier instruction mismatch')
            raw_rebound[text_offset+offset:text_offset+offset+4]=bytes.fromhex(new)

    rebound_ref.write_bytes(raw_rebound)

    print("Step 2: Compiling composite shim and callback bridge...")
    cflags = [
        '-std=gnu11', '-marm', '-march=armv7-a', '-mfloat-abi=softfp',
        '-ffreestanding', '-fno-pic', '-fno-pie', '-fno-stack-protector',
        '-fno-common', '-O2', '-Wall', '-Wextra', '-Werror',
        '-fno-builtin','-fno-tree-loop-distribute-patterns',
        '-I' + rel(ROOT / 'tools/native_camera'),
    ]
    if args.start_probe_only:
        cflags.append('-DA6400_UVC_START_PROBE_ONLY=1')
    if args.trace_control:
        if not args.shared_ptp_enumeration_candidate:parser.error('--trace-control requires shared candidate')
        cflags.append('-DA6400_UVC_TRACE_CONTROL=1')
    if args.coherent_buffer_allocation:
        cflags.append('-DA6400_UVC_COHERENT_ALLOC=1')
    legacy_flags=[]
    if args.shared_ptp_enumeration_candidate:
        cflags.append('-DA6400_UVC_ENUMERATION_ONLY=1')
        legacy_flags=['-Da6400_uvc_gadgetcore_register_hook=a6400_legacy_register_hook',
                      '-Da6400_uvc_gadgetcore_unregister_hook=a6400_legacy_unregister_hook',
                      '-Da6400_uvc_video_core_ioctl=a6400_uvc_legacy_dma_ioctl']
    run('arm-linux-gnueabi-gcc', [*cflags,*legacy_flags, '-c', rel(shim_src), '-o', rel(compiled_shim)])
    run('arm-linux-gnueabi-gcc', [*cflags, '-c', rel(bridge_src), '-o', rel(compiled_bridge)])
    extra_objects=[];extra_sources=[]
    if args.shared_ptp_enumeration_candidate:
        for name in ['uvc_ptp_mode_gate','uvc_ptp_ioctl_guard','uvc_ptp_stop_attest','uvc_ptp_route_lease','uvc_ptp_code_sync','uvc_ptp_route_dryrun','uvc_ptp_entry_hook','uvc_ptp_descriptors','uvc_ptp_descriptor_lease','uvc_ptp_adapter','uvc_ptp_session','uvc_ptp_native_backend','uvc_module_self_ref','uvc_ptp_module_shim']:
            source=ROOT/'tools/native_camera'/(name+'.c');obj=out/(name+'.o')
            run('arm-linux-gnueabi-gcc', [*cflags,'-Wno-unused-const-variable','-c',rel(source),'-o',rel(obj)])
            extra_sources.append(source);extra_objects.append(obj)
        asm_source=ROOT/'tools/native_camera/uvc_ptp_native_ioctl_entry.S'
        asm_obj=out/'uvc_ptp_native_ioctl_entry.o'
        run('arm-linux-gnueabi-gcc', [*cflags,'-c',rel(asm_source),'-o',rel(asm_obj)])
        extra_sources.append(asm_source);extra_objects.append(asm_obj)

    print("Step 3: Linking composite module usbg_video_a6400.ko...")
    run('arm-linux-gnueabi-ld', [
        '-r', '-o', rel(final_ko),
        rel(rebound_ref), rel(compiled_shim), rel(compiled_bridge),*[rel(p) for p in extra_objects]
    ])

    print("Step 4: Localizing private bridge symbols...")
    localize=[
        '--localize-symbol=a6400_uvc_devnodes',
        '--localize-symbol=a6400_uvc_gadgetcore_register_hook',
        '--localize-symbol=a6400_uvc_gadgetcore_unregister_hook',
        '--localize-symbol=a6400_uvc_bridge_prepare',
        '--localize-symbol=a6400_uvc_bridge_activate',
        '--localize-symbol=a6400_uvc_bridge_quiesce',
        '--localize-symbol=a6400_uvc_bridge_retire',
        '--localize-symbol=a6400_uvc_bridge_register',
        '--localize-symbol=a6400_uvc_bridge_unregister',
        '--localize-symbol=a6400_uvc_bridge_shadow',
        '--localize-symbol=a6400_uvc_bridge_size',
        '--localize-symbol=a6400_uvc_bridge_last_error',
        '--localize-symbol=a6400_usb_sync_alloc_phys_buffer',
        '--localize-symbol=a6400_usb_sync_free_phys_buffer',
        '--localize-symbol='+ioctl_name,
    ]
    # Legacy hooks were deliberately renamed in this variant.
    if args.shared_ptp_enumeration_candidate:
        localize=[x for x in localize if x not in ['--localize-symbol=a6400_uvc_gadgetcore_register_hook','--localize-symbol=a6400_uvc_gadgetcore_unregister_hook']]
    run('arm-linux-gnueabi-objcopy',[*localize,rel(final_ko)])

    print("Step 5: Verifying composite module integrity...")
    with REF_KO.open('rb') as f_orig, final_ko.open('rb') as f_mod:
        elf_orig = ELFFile(f_orig)
        elf_mod = ELFFile(f_mod)

        # 1. Executable section verification
        sections = {}
        for s in elf_orig.iter_sections():
            if s['sh_flags'] & 4:  # SHF_EXECINSTR
                cand = elf_mod.get_section_by_name(s.name)
                # Note: mod has additional bridge code appended, so original section prefix must match
                orig_data = s.data()
                expected_data=bytearray(orig_data)
                if args.shared_ptp_enumeration_candidate and s.name=='.text':
                    expected_data[0x116c:0x1170]=bytes.fromhex('7b20e0e3')
                    expected_data[0x13e8:0x13ec]=bytes.fromhex('015055e2')
                mod_data = cand.data() if cand else b''
                prefix_match = mod_data.startswith(expected_data)
                sections[s.name] = {
                    'orig_size': len(orig_data),
                    'mod_size': len(mod_data),
                    'prefix_match': prefix_match,
                    'orig_sha256': hashlib.sha256(orig_data).hexdigest(),
                }
                if not prefix_match:
                    raise ValueError(f'Original executable code modified in {s.name}')

        # 2. Undefined symbol verification against a6400 live kernel
        symtab = elf_mod.get_section_by_name('.symtab')
        undefs = sorted([s.name for s in symtab.iter_symbols() if s.name and s['st_shndx'] == 'SHN_UNDEF'])

        # Check against decoded a6400 kernel kallsyms
        ks_path = ROOT / 'artifacts/analysis/uvc-portability-final-e0135/a6400-kallsyms-checked.json'
        kallsyms_names = set()
        if ks_path.exists():
            ks = json.loads(ks_path.read_text(encoding='utf-8'))
            kallsyms_names = {entry['name'] for entry in ks['symbols']}

        # Known module-exported symbols verified on camera
        live_module_exports = {
            'dma330_mem_transfer_async', 'osal_rcv_msg_tmo', 'osal_snd_msg',
            'osal_free_msg', 'osal_valloc_msg_wait', 'osal_dynamic_id',
            'osal_snd_sync_direct', 'osal_snd_sync_msg', 'malloc_sizes',
            'param_ops_uint', 'udif_km_debug'
        }
        from tools.research.kernel_export_contract import kernel_exports
        export_table=kernel_exports()
        all_known = kallsyms_names | live_module_exports | set(export_table)
        info=elf_mod.get_section_by_name('.modinfo').data().decode().split('\0')
        licenses=[x[8:] for x in info if x.startswith('license=')]
        gpl_compatible=any(x in ('GPL','GPL v2','GPL and additional rights','Dual BSD/GPL','Dual MIT/GPL','Dual MPL/GPL') for x in licenses)
        forbidden=[n for n in undefs if n in export_table and export_table[n]['kind']=='gpl' and not gpl_compatible]
        if forbidden:raise ValueError('GPL-only imports unavailable to module license metadata: '+str(forbidden))

        missing_symbols = [u for u in undefs if u not in all_known]
        print(f"Total undefined symbols: {len(undefs)}")
        print(f"Verified against retained kernel/module evidence: {len(undefs) - len(missing_symbols)} / {len(undefs)}")

        if missing_symbols:
            raise ValueError(f"Unresolved undefined symbols: {missing_symbols}")

    report = {
        'start_probe_only': args.start_probe_only,
        'shared_ptp_enumeration_candidate':args.shared_ptp_enumeration_candidate,
        'trace_control_requests':args.trace_control,
        'enumeration_rejects_uvc_class_vendor':args.shared_ptp_enumeration_candidate,
        'deployable':False if args.shared_ptp_enumeration_candidate else None,
        'physical_test_ready':False if args.shared_ptp_enumeration_candidate else None,
        'buffer_allocation': ('owned_kernel_coherent' if args.coherent_buffer_allocation
                             else 'original_dmm' if args.native_buffer_allocation
                              else 'experimental_fixed_ram_window'),
        'target': final_ko.name,
        'sha256': digest(final_ko),
        'size_bytes': final_ko.stat().st_size,
        'reference_sha256': REF_SHA,
        'files': {
            rel(p): digest(p) for p in [REF_KO, shim_src, bridge_src, bridge_hdr,*extra_sources,*[p.with_suffix('.h') for p in extra_sources if p.with_suffix('.h').exists()], final_ko]
        },
        'sections_verified': sections,
        'undefined_symbols_count': len(undefs),
        'undefined_symbols': undefs,
        'kernel_export_classes':{n:export_table[n] for n in undefs if n in export_table},
        'license_metadata':licenses,
        'device_node': {
            'name': 'usb/video',
            'major': 248,
            'minor': 33,
            'status': 'statically resolved in module private storage',
        },
        'callback_bridge': {
            'dual_shadow_descriptors': True,
            'proactive_quiescence': True,
            'dma_flushing': True,
        },
        'status': 'SUCCESS - Composite module built and verified without unresolved dependencies',
    }
    if args.shared_ptp_enumeration_candidate:
        report['status']='OFFLINE shared enumeration candidate linked and statically audited'
        report['limitations']=['Enumeration/control candidate only: reference video START suppressed and UPDATE/ENABLE/WAIT ioctls rejected.',
            'Not loaded on camera; native USB mode-worker serialization and physical restore remain unproven.',
            'Kernel module file-operations owner and target-verified native self-reference guard lifetime; runtime session behavior still needs verification.',
            'No native sensor producer, video stream, camera-control writes or Windows driver-binding proof.']
        report['reference_modifications']={'start_tag_text_offset':'0x116c','wire_classifier_text_offset':'0x13e8',
            'ioctl_relocation':'0x64','release_relocation':'0x78','file_owner_added_relocation':'0x44'}

    manifest_path = out / 'manifest.json'
    manifest_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"\n>>> Composite module built successfully: {final_ko} <<<")
    print(f">>> SHA256: {report['sha256']} ({report['size_bytes']} bytes) <<<\n")


if __name__ == '__main__':
    main()
