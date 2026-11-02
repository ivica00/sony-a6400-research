import sys
import struct
import json
import unicorn
import unicorn.arm_const as arm
from src.a6400.execution.interpreter_probe import InterpreterProbe
from src.a6400.execution.guest_gles import GuestGles, GlesBinding, GLES_LOCK_SEMAPHORE
from src.a6400.execution.guest_gpio import GuestGpio
from src.a6400.execution.guest_usb_buspower import GuestUsbBusPower
from src.a6400.execution.kernel_task_identity import KernelTaskObservation
from src.a6400.execution.guest_threads import REGISTER_LIST

def main():
    print("[*] Loading components for yield test...")
    with open('artifacts/intermediate/filesystem_manifest.json', 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    with open('bin/im.elf', 'rb') as f:
        app = f.read()

    with open(r'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/initrd.img_unpacked/lib/ld-2.11.2.so', 'rb') as f:
        interp = f.read()

    with open('tests/fixtures/kuser_template.bin', 'rb') as f:
        kuser_template = f.read()

    uname_profile = {
        'sysname': 'Linux',
        'nodename': 'localhost',
        'release': '3.0.8',
        'version': '#1 PREEMPT Wed Sep 25 15:45:20 JST 2019',
        'machine': 'armv7l',
        'domainname': ''
    }

    probe = InterpreterProbe(
        syscall_policy='threads',
        uname_profile=uname_profile,
        filesystem=manifest,
        kuser_template=kuser_template,
        madvise_policy='private-anonymous-dontneed',
        backup_service_policy='preset-backed',
        graphics_service_policy='authentic-grm',
        null_page_policy='accessible',
        kmod_service_policy='verified-image-modules',
        mmap_base=0x50000000,
        mmap_search_low=0x10000000
    )

    probe.prepare(app, interp, ['/usr/bin/im.elf'], stack_bottom=0x5e390000, stack_size=0x800000)

    # Setup devices
    header = struct.pack('<6I', 0, 1, 0x5f000000, 0x8000, 0, 0)
    task_bytes = bytearray(0x10c)
    struct.pack_into('<I', task_bytes, 8, 0x2000)
    struct.pack_into('<2I', task_bytes, 0x104, 1003, 1000)
    task_obs = KernelTaskObservation.read(lambda a, s: header if a == 0x2000 else task_bytes, 0x2000)
    probe.gles = GuestGles(GlesBinding(task_obs))
    probe.gpio = GuestGpio()
    probe.usb_buspower = GuestUsbBusPower()

    # Wrap _hook_syscall to yield on GLES_LOCK_SEMAPHORE if runnable threads exist
    orig_hook = probe._hook_syscall
    yield_events = []

    def wrapped_hook(uc, user_data):
        # Read syscall info
        thumb = bool(uc.reg_read(arm.UC_ARM_REG_CPSR) & 0x20)
        number = uc.reg_read(arm.UC_ARM_REG_R7)
        if number == 54: # ioctl
            fd = uc.reg_read(arm.UC_ARM_REG_R0)
            cmd = uc.reg_read(arm.UC_ARM_REG_R1)
            if fd == 10 and cmd == GLES_LOCK_SEMAPHORE:
                # Check runnable threads
                runnable = [t.tid for t in probe.threads.threads.values() if t.state == 'runnable' and t.tid != probe.threads.current_tid]
                if runnable and len(yield_events) < 50:
                    curr_tid = probe.threads.current_tid
                    next_tid = runnable[0]
                    # Let orig_hook execute the ioctl first
                    orig_hook(uc, user_data)
                    # Now yield
                    probe.threads.save_context(uc)
                    probe.threads.threads[curr_tid].state = 'runnable'
                    probe.threads.restore_context(uc, next_tid, probe.kuser)
                    yield_events.append({'from': curr_tid, 'to': next_tid, 'instruction': probe.instructions})
                    print(f"[+] Yielded GLES_LOCK_SEMAPHORE from TID {curr_tid} to TID {next_tid} at instruction {probe.instructions}")
                    return
        orig_hook(uc, user_data)

    probe.mu.hook_del(probe._syscall_hook)
    probe._syscall_hook = probe.mu.hook_add(unicorn.UC_HOOK_INTR, wrapped_hook)

    print("[*] Running probe to 83,000,000 instructions...")
    rep = probe.run(instruction_budget=83000000, timeout_us=120000000)
    print("\n=== Result ===")
    print("Status:", rep.get("status"))
    print("Instructions:", rep.get("instructions_executed"))
    print("Threads:", {tid: t.get("name") + ":" + t.get("state") for tid, t in rep.get("threads", {}).items()})
    print("Yield events:", yield_events)

if __name__ == "__main__":
    main()
