# Evidence 0031: Backup boot parameters, kernel address conversion, and write pipeline

## Result and scope

Static analysis of original boot configuration and bounded ARM execution now resolve the boot-time module options, kernel address conversion, and write execution pipeline for Sony's `backup.ko` service.

Key findings:
1. **Boot Module Option**: In `sbin/init` (`drivers2` phase, entry 3), `/usr/kmod/backup.ko` is explicitly loaded with argument:
   ```text
   Backup_load=0
   ```
   This overrides the module's static default `Backup_load=1`.
2. **Preexisting RAM Reliance**: In `backupfile_init`, when `load_flag == 0`, the driver skips reloading the file from disk. Instead, it unpacks the 32-bit physical address from header word 0, calls `arch_phys_to_cache(pa)` to obtain the kernel direct-map virtual address, verifies the cookie (`0xaaaaaaaa`), and invokes `Data_init` directly on the preexisting RAM mapping.
3. **Kernel Address Conversion**: `arch_phys_to_cache` in `vmlinux.bin` (`0x6011f07c`, offset `0x1707c`) verifies that `pa < 0x40000000` (1 GB RAM limit) and translates physical addresses to cacheable virtual addresses by adding `0x60000000`:
   - Preset Word 0 `pa = 0x02e80000` translates to `va = 0x62e80000`.
   - LIRO units (`0x00fa007c` / `0x00fa0076`) `pa = 0x035c6000` translate to `va = 0x635c6000`.
   - Bounded execution of original `arch_phys_to_cache` instructions confirms this mapping in 11 instructions.
4. **Write Pipeline**: `Backup_write_core` (`0x5ec`–`0x880` in `backup.ko`) enforces subsystem alignment (`unit >> 16 == subsystem`), acquires `rt_down_write` on `backup_rwlock`, resolves unit descriptors via `Data_SearchId`, validates size/attributes, copies user or kernel data via `__copy_from_user` or `memcpy`, releases `rt_up_write`, and conditionally triggers callback messaging (`backup_sharedcb_send_msg`) if attribute bit 3 (`0x8`) is set.

**The strict startup boundary does not change.** Knowing the kernel address conversion and write pipeline does not supply physical camera nonvolatile state, runtime `/setting/Backup.bin`, or an IPC-connected service. E0029's strict backup guard remains required.

## Inputs and identity

| Input | SHA-256 |
| --- | --- |
| `sbin/init` | `0af5724ece7f60db2831b7a4e61829be369868027877cca0f921f981ae8dc7ad` |
| `vmlinux.bin` | `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707` |
| `usr/kmod/backup.ko` | `63c69e991a8da77e301a7090c8ba6e4dcced43921e88415e3591cf0e96dbb2c6` |
| Preset `CX62600_UC2.bin` | `241c8521035bc9ff1edbe66cf3d42d81879a4bef8ff9e21cbfb84530a1446154` |

All inputs match preserved inventory hashes. No files or camera memory were modified.

## Address conversion and boot logic

Original kernel `arch_phys_to_cache`:
```arm
0x6011f07c: mov ip, sp
0x6011f080: push {r3, r4, fp, ip, lr, pc}
0x6011f084: sub fp, ip, #4
0x6011f088: subs r2, r0, #0
0x6011f08c: bne 0x6011f108
...
0x6011f108: ldr r3, [pc, #0x1c]       ; 0x604d8ca0 (contains limit 0x40000000)
0x6011f10c: ldr r1, [r3]
0x6011f110: cmp r2, r1
0x6011f114: addlo r2, r2, #0x60000000  ; pa + 0x60000000
0x6011f118: blo 0x6011f100
...
0x6011f100: mov r0, r2
0x6011f104: ldm sp, {r3, r4, fp, sp, pc}
```

In `backupfile_init` (`0x4614` in `backup.ko`):
- Word 0 unpacked via byte shifts produces little-endian `0x02e80000`.
- Word 1 verified against cookie `0xaaaaaaaa`.
- `arch_phys_to_cache(0x02e80000)` yields `0x62e80000`.
- With `load_flag == 0`, the driver branches to `0x46bc`, skipping disk load and calling `Data_init(0x62e80000)`.

## Write execution pipeline

Tracing `Backup_write_core` (`0x5ec`):
1. Parameter check: `cmp r6, r4, lsr #16` ensures `subsystem == (unit >> 16)`. If not, returns `-4` (`0xfffffffc`) with error logrec `0x81`.
2. Concurrency lock: `rt_down_write(&backup_rwlock)`.
3. Unit search: `Data_SearchId(unit)` retrieves descriptor.
4. Attribute & ID check: `Data_GetAttr` and `Data_GetID1` enforce read-only / protected unit constraints.
5. Size check: `Data_GetVmaxSize` and `Data_GetSize` validate supplied buffer length.
6. Memory copy:
   - If destination pointer `r5 < 0x5f000000` (userspace buffer), validates thread bounds and calls `__copy_from_user`.
   - If destination pointer `r5 >= 0x5f000000` (kernel pointer), calls `memcpy`.
7. Unlock: `rt_up_write(&backup_rwlock)`.
8. Notification: If unit attribute has bit 3 (`0x8`) set, calls `backup_sharedcb_send_msg(unit, size, data)`.

For startup unit `0x003e000b`:
- Subsystem is `0x3e` (matches).
- Size is 1 byte, vmax_size is 0 (fixed).
- Attribute is `0` (notification bit not set, so `backup_sharedcb_send_msg` is skipped).
- Result is 0 (success).

## Reproduction and verification

```powershell
.\venv\Scripts\python.exe -m tools.research.backup_boot_trace
.\venv\Scripts\python.exe -m unittest tests/test_backup_boot.py -v
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

All **270 tests pass**, including 8 new automated unit tests verifying boot parameter extraction, kernel address translation, header unpacking, cookie validation, and `Backup_write_core` parameter validation.

The strict process boundary remains unchanged (E0029 baseline: 2,107,833 / 2,107,861 instructions without backup reply).
