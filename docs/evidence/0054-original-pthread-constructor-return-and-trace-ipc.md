# Evidence 0054: Original pthread initialization completes the constructor

## Result

The selected original client constructor now **returns normally** after **168 original instructions / 44 object stores**, including original libc sysconf and version-matched libpthread mutex/condition initialization. Original initializer calls both return0; no host pthread success result is supplied. **157/184 bytes** are initialized by original stores; the remaining27 stay unknown.

An additional explicit direct-call experiment feeds a fresh original GRM lookup result into the following original object initializer. It reaches **202 total instructions** (168 constructor +34 initialization prefix), with no additional object stores, and stops before trace-message allocation. No mapping, full client/IPC completion or GUI occurs. Main startup remains E0034; E0051's kernel callback-thread/locking prerequisite is unchanged.

## Provider and symbol verification

New preserved provider: `nflasha7_unpacked/lib/libpthread-2.11.2.so`, SHA-256 **938387093567f5721bdeafa5bf68275d3a8705c8c6536745358e229af27fcab8**. E0053's checked libObj/libc/interpreter/application inputs remain in effect; optional direct initialization also records the fresh WBI/GRM/kernel producer identities.

`im.elf` directly needs libpthread.so.0 before libc.so.6. Both libc and libpthread export the names, so name matching alone does not establish the selected implementation. `pthread_init_profile` checks provider SONAME, application dependency order, defined function symbols, and matching GNU symbol versions:

| Import | Version | Selected pthread Thumb entry | ELF body size |
| --- | --- | --- | --- |
| pthread_mutex_init | GLIBC_2.4 | `0x665d` | 208 |
| pthread_cond_init | GLIBC_2.4 | `0x8725` | 78 |

The selected isolated binding uses provider bias0x50000000. Actual client PLT instructions and their exact R_ARM_JUMP_SLOT records are checked before binding to these original Thumb functions. This is an explicit, version-matched isolated provider policy supported by the source dependency declarations, **not an executed complete runtime symbol-scope search**. No libc substitute is silently selected, and no arbitrary unresolved import receives success.

Source analysis is limited to these small functions and exact ELF metadata; it does not repeat the previously failed full libObj REA import. All input identities are checked before/after runs.

## Original null-attribute initializer effects

Original user synchronization constructor passes:

- Mutex: object **0x0830005c**, attributes0; original function returns0 at caller0x71f2a6.
- Condition variable: object **0x08300078**, attributes0; original function returns0 at caller0x71f2b0.

The mutex's original null-attribute branch reads its source-backed default attribute data and performs original field stores. The condition initializer's original null branch performs its own stores, including doubleword stores. No host memset/pthread implementation is substituted. Other branches, imports, writable provider data and unsupported state remain guarded; no scheduler, owner identity or kernel lock operation is supplied by these initializers.

The root constructor subsequently writes original marker bytes **ca fe fe ed**, trailing zero fields and an empty initial name byte, and returns its constructed storage pointer. The object's kernel-handle field still has its constructor value; physical-memory setup is a later function. Unknown padding/unused bytes are not promoted to initialized state merely because the constructor returned.

## Next direct initializer reaches trace IPC

Optional `--lookup-initialize` requires the completed pthread constructor policy. It freshly executes the original bounded GRM lookup (285 instructions, status0, base0x202e0000, size0x02000000, kernel object0x68a96220) and calls original `libObj.so` initializer **0x71fc64** with those values and source-backed `gl_common` name. This uses an explicitly constructed ABI call frame after an actual constructor return, **not a completed original client transport exchange or operator-new call**.

Original initializer first calls its trace/event helper at0x720800, then0x720724. It reaches:

| Boundary | Value |
| --- | --- |
| Call PC | `0x720740` |
| PLT target / verified symbol | `0x1030a0` / osal_valloc_msg_wait |
| r0 | `0x008f013a` |
| r1 output slot | `0x08002fac` |
| r2 requested bytes | `0x2a` (42) |
| r3 | 0 |

Execution stops before this call. No message allocation, allocation failure, transport acknowledgement or logging-disable flag is invented. Constructor object stores remain44; this prefix has not stored the returned kernel handle or mapped the physical area. The fresh lookup producer's retain mutation is confined to its separate disposable snapshot experiment. It is not a serviced main-process callback.

## Policies, reproduction and validation

```
python -m tools.research.ma_object_constructor --loader-pagesize --pthread-initializers --report-dir artifacts/execution/NEW_CONSTRUCTOR_DIRECTORY
python -m tools.research.ma_object_constructor --loader-pagesize --pthread-initializers --lookup-initialize --report-dir artifacts/execution/NEW_INITIALIZER_DIRECTORY
```

New directories only, under artifacts. Fresh loader-producer state is retained for each chain. Default mode still stops at sysconf after32 instructions/seven stores; loader-only mode still stops before pthread_mutex_init after86/17. New flags do not alter process-backend behavior.

Constructor reports: `artifacts/execution/ma-constructor-pthread-first`, `ma-constructor-pthread-repeat`, final `ma-constructor-pthread-final`. Direct initializer reports: `ma-object-lookup-initializer-first` / `ma-object-lookup-initializer-repeat`, byte-identical including168/34 phase counts,44 stores, original lookup input and exact trace-allocation boundary. Regressions: `ma-pthread-default-regression`, `ma-pthread-loader-only-regression`.

Three constructed version-binding tests verify matching-version selection/Thumb-bit preservation, rejection of undefined/wrong-version/nonfunction providers, and rejection of missing/ambiguous versioned imports/exports. Existing object-memory provenance tests still apply. Full suite **354 passing tests**, `artifacts/execution/ma-constructor-pthread-final-suite.txt`. Status image regenerated and visually checked with unchanged capability counts. Preserved inputs and main execution contracts remain unchanged.

Next: establish the original trace-message allocator/transport contract for queue0x008f013a using the existing declared UIPC environment, without disabling trace or inventing a result; continue original physical mapping setup only afterward. Kernel callback thread-state/locking and actual main-process service connection remain independent requirements.
