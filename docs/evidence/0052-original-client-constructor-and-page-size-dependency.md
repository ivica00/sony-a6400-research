# Evidence 0052: Original client constructor reaches page-size dependency

## Result

Original `libObj.so` constructor prefixes execute **32 instructions** and **seven object stores**, initializing **28 of184 bytes**, before stopping at the original **sysconf** call. Call PC **0x71f928**, selector **30**, PLT target **0x102f84**, verified against the ELF's actual sysconf PLT relocation.

The object storage is explicitly **constructed uninitialized research storage**, not a supplied operator-new result or a discovered initialized camera object. The constructor has not returned. No page-size response, user mutex/condition initialization, device mapping or GUI is supplied. E0051's kernel-thread-state boundary remains independent; main execution remains E0034.

## Inputs and execution scope

Client input SHA-256 **60ffd2b0f31f4bc139a7c13a4f62c25cdeb6a531ad5ef35df48471e6e36e88b1**. Checked against preserved inventory before and after each run. `tools.research.ma_object_constructor` uses original file-backed ELF sections, an explicit isolated load bias0, constructed stack and184-byte storage at0x08300000. The storage is poison-backed, but its bytes are **unknown** until original stores initialize them. Unknown object reads, source gaps, relocated reads outside the supported slots, stores outside the object, other control flow and unsupported memory access stop.

Two consumed GOT slots are required to be unique **R_ARM_RELATIVE (23), symbol index0** entries. With selected bias0, their existing file addends need no modification:

| GOT slot | Source addend | Original stored vtable pointer (+8) |
| --- | --- | --- |
| `0x013704f0` | `0x01350f78` | `0x01350f80`, object +0 |
| `0x01370a18` | `0x01350ec0` | `0x01350ec8`, nested object +0x2c |

Original root constructor at0x71fbf4 initializes fields +8/+12/+20/+40 to0, +16 to1, and its vtable, then calls the nested mapping-object constructor at0x71f910. The nested constructor writes its vtable and requests sysconf30. It has not yet stored the page-size-dependent fields that follow that call. There is no host-written object layout initialization or substitute return.

Permitted instruction windows end at the original call boundary, with1,000-instruction/100ms limits. Mapped source-page padding does not count as supplied bytes; non-file-backed sections are not silently initialized. Object padding inside the host page is not writable merely because backing exists.

## Page-size dependency: static original libc evidence

Preserved `nflasha7_unpacked/lib/libc-2.11.2.so` SHA-256 **bceb5cfb7769b54bf9c9d178b8a5f4579531c0f60e673cbcae872a8c7a3508fb**. Its exported sysconf/getpagesize entries have the Thumb bit set; decode coordinates are0x7b56c and0x9b580 respectively. These are linked ELF coordinates, not established runtime load addresses.

`tools.research.ma_sysconf_trace` verifies the static selector path:

- Original sysconf uses a Thumb halfword branch table at0x7b596.
- Selector30's entry at0x7b5d2 is0x020c, giving case target0x7b9ae.
- That case calls original getpagesize0x9b580.
- getpagesize reads a relocated pointer to undefined **_rtld_global_ro** (R_ARM_GLOB_DAT21), then the loader object's word +16.
- Only after reading that word does the original function select its visible4096 fallback if it is zero. Neither the pointer nor the runtime field is supplied here, so this fallback is **not** accepted as a page-size reply.

Report: `artifacts/analysis/ma-sysconf-dependency/report.json`. Earlier targeted reports under `ma-constructor-dependencies` retain constructor/mapping/sysconf disassembly and the initial static selector extraction. Generic disassembly also prints unrelated cases/literal data; no such lines are claimed as executed selector30 behavior. Small targeted local checks avoid repeating the previously failed full libObj REA import.

## Following original mapping path, not yet executed

Hash-checked original mapping routine0x71f9f4 chooses the positive-physical-address path containing **/dev/stream**, uses original object flags, computes page-aligned offset/size, and prepares **mmap** with protection3 and flags1. The other static pathname is /dev/mem under a different branch; it is not selected merely because it exists as a string. This map routine is only statically inspected here. No open descriptor, mapping result, physical content or ownership is invented.

The original root constructor also calls a separate user synchronization-object initializer after the mapping subobject constructor. Its imports include pthread_mutex_init/pthread_cond_init. Those operations and the later mapping/lookup-object completion remain unexecuted in this experiment.

## Reproduction and validation

```
python -m tools.research.ma_object_constructor --report-dir artifacts/execution/NEW_DIRECTORY
python -m tools.research.ma_sysconf_trace --report-dir artifacts/analysis/NEW_DIRECTORY
```

All output directories must be new and inside artifacts. Original constructor reports `artifacts/execution/ma-object-constructor-first/report.json` and `ma-object-constructor-repeat/report.json` are byte-identical. They record original bytes, stores, known object offsets, GOT reads, input hash and the sysconf boundary. Preserved inputs are unchanged.

Three constructed Thumb/ELF fixture tests verify that poison/zero backing is not initialized object state, original stores release only the written bytes, and mapped padding does not grant permission beyond184 bytes. Full suite **351 passing tests**, `artifacts/execution/ma-object-constructor-suite.txt`. Status image regenerated and visually checked; capability counts unchanged.

Next: identify the required loader global/page-size field under a declared source-backed state policy, then continue original object initialization without fabricating sysconf or pthread replies. E0051's callback-thread state/locking and full transport remain required before an authentic selected package-WBI service can respond in main startup.
