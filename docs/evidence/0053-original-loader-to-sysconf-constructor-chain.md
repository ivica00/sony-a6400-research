# Evidence 0053: Original loader field drives original sysconf and constructor

## Result

The page-size dependency is now serviced by **original producer and consumer code**, under the existing explicitly declared process-entry assumptions:

1. Original interpreter executes **1,183 instructions**, with **zero syscall responses**, and stores4096 at `_rtld_global_ro+16`.
2. A separate bounded constructor run binds the original sysconf PLT slot to original libc and the libc loader-object slot to that producer's actual symbol address. Only the four bytes written by original interpreter code are supplied as loader runtime data.
3. Original PLT, `sysconf(30)` and `getpagesize` execute and return4096; no host sysconf return is substituted.
4. Constructor path executes **86 instructions**, **17 stores**, initializing **68/184 object bytes**, and stops before **pthread_mutex_init**.

The loader's4096 originates in this probe's **declared AT_PAGESZ=4096**, not a new camera measurement or verified reset state. Operator new, pthread initialization, complete object creation, GRM callback locking/IPC and main-process GUI are not completed. E0051 remains an independent kernel-thread-context gate; main execution remains E0034.

## Inputs and producer evidence

| Input | SHA-256 |
| --- | --- |
| im.elf | `866729eb0bc1e6f5aba04d8bf8e45491985afe89a078ccb106a1ce2476865225` |
| rootfs ld-2.11.2.so | `7c215cee6c4175079d69cb1433c6be90189e793f6e44f068ed6ac97621dd7a2c` |
| libc-2.11.2.so | `bceb5cfb7769b54bf9c9d178b8a5f4579531c0f60e673cbcae872a8c7a3508fb` |
| libObj.so | `60ffd2b0f31f4bc139a7c13a4f62c25cdeb6a531ad5ef35df48471e6e36e88b1` |

`tools.research.loader_pagesize_trace` resolves application/PT_INTERP through the retained namespace, verifies the selected input identities against baseline, and prepares the existing default **stop** interpreter probe with argv `im.elf i`. No files/devices/syscalls are serviced. Source images are checked again after execution.

The rootfs interpreter defines `_rtld_global_ro` as a272-byte object at linked0x1fe00. Its field+16 is initially0 in the mapped image. Original Thumb code at runtime **0x4000f778** (`str.w sl,[r3,#0x10]`) writes4096 to **0x4001fe10**. The probe stops at its unchanged first syscall boundary. Reports record the actual AT_PAGESZ entry's stack address, original reads of that entry, the complete original field store/instruction bytes, initial/final field bytes, image mappings and all existing entry assumptions. The actual field is offered to the consumer only after requiring exactly one complete four-byte producer store.

This resolves E0052's missing page-size input **for this explicitly selected process environment**. It does not identify a physical camera's dynamic loader state or justify replacing other loader globals with compiled zeroes.

## Original PLT/libc binding and source-byte guards

Optional `ma_object_constructor --loader-pagesize` freshly runs the producer and original libc path. The default constructor mode still stops at sysconf after32 instructions/seven stores.

Isolated coordinates: libObj bias0, libc bias0x30000000, original producer's interpreter bias0x40000000. These are declared research mappings. The tool checks the original ARM PLT stub's GOT computation and exact symbol relocation before binding sysconf, retaining its Thumb entry bit. It also checks libc's `_rtld_global_ro` undefined GLOB_DAT slot before binding it to the actual producer symbol address. No other undefined import is resolved automatically.

These narrowly selected bindings follow [Arm ELF32 dynamic relocation rules](https://github.com/ARM-software/abi-aa/blob/main/aaelf32/aaelf32.rst#dynamic-relocations): R_ARM_JUMP_SLOT22/R_ARM_GLOB_DAT21 identify symbol-address bindings, while R_ARM_RELATIVE23 uses the selected load bias. This is not execution of a complete dynamic linker, symbol-version search or application-wide relocation process.

Only original file-backed source sections and the producer's **four known runtime bytes** are readable. The rest of the loader object/page remains unknown, despite mapped host backing. Object bytes stay unknown until original stores; mapped padding is not granted object permissions. Existing relative vtable slots and the newly reached user-synchronization vtable slot must match their actual type23 records. Unknown relocated reads, other control flow and writes outside the explicit184-byte object/stack stop.

The actual consumer records a four-byte read at **0x4001fe10**, bytes `00100000`, and records original sysconf's return4096 at caller PC0x71f92c. The nonzero producer field means the visible getpagesize zero-field fallback is not used to supply this result.

## New constructor boundary

Original mapping-subobject constructor now stores its page size, flags, pathname input, null mapping fields and descriptor sentinel, returns to the root constructor, and enters the original user-synchronization constructor. That code writes its relative vtable, advances the object pointer, and requests:

- Call PC **0x71f2a2**.
- PLT target **0x104828**, verified as **pthread_mutex_init**.
- Object address **0x0830005c** (within constructed storage).
- Attributes pointer **0**.

Execution stops before that call. No pthread zero/success return, task identity, lock or condition-variable state is invented. A separate pthread provider/initializer contract must be established before proceeding. This user-space initializer is distinct from E0051's kernel GRM callback mutex.

## Reproduction and validation

```
python -m tools.research.loader_pagesize_trace --report-dir artifacts/execution/NEW_PRODUCER_DIRECTORY
python -m tools.research.ma_object_constructor --loader-pagesize --report-dir artifacts/execution/NEW_CONSTRUCTOR_DIRECTORY
```

Retained producer report: `artifacts/execution/loader-pagesize-first/report.json`. Final chain: `ma-constructor-loader-provenance` / `ma-constructor-loader-repeat`, each with `loader-producer.json` and consumer `report.json`. They agree on the original field read,86 instructions/17 stores, sysconf return and pthread boundary. The earlier `ma-constructor-loader-first` stopped at the now-understood synchronization-constructor entry after75 instructions; it did not supply a missing return.

Default regression `ma-constructor-loader-default` preserves32 instructions/seven stores/sysconf boundary. Existing constructed object-provenance/write-bound tests continue to pass. Full suite **351 passing tests**, `artifacts/execution/ma-constructor-loader-suite.txt`. Status image regenerated and visually checked; capability counts unchanged. No guest backend/process policy or preserved input is modified.

Next: establish the actual pthread provider and original null-attribute initializer paths, preserving field provenance and stopping at unknown services; continue object construction only through verified original effects. Kernel callback-thread state, transport and later stream/physical-memory ownership remain separate requirements before main startup can advance.
