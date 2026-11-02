# Evidence 0050: Original MA client consumes fresh original GRM status

## Result

`tools.research.wbi_ma_client` freshly executes E0045's original GRM producer, then copies its output bytes into an explicitly constructed client transport-return context. The original Thumb reply consumer reads the status and follows the original branch:

- `gl_common`: original producer285 instructions; client6 instructions; status0 reaches **operator new call boundary**, requesting **184 bytes (0xb8)**.
- `absent_control`: original producer211 instructions; client5 instructions; status **-9** reaches original **error cleanup boundary**, before any operator-new request.

The transport-return context/frame are **constructed research inputs**, not an executed IPC exchange. No transport acknowledgement, mutex result, operator-new result or host-created client object is supplied to the main process. The success branch does not yet establish client initialization or GUI advancement. Main boundary remains E0034.

## Inputs and original code

Fresh producer input identities are retained in each child `producer/report.json` (same WBI/GRM/kernel as E0045). Client input is checked before and after execution:

`0700_part_image/dev/nflasha15_unpacked/lib/libObj.so`, SHA-256 **60ffd2b0f31f4bc139a7c13a4f62c25cdeb6a531ad5ef35df48471e6e36e88b1**.

Small targeted ELF/Thumb disassembly is used rather than repeating the failed large libObj REA import. This is within the targeted-analysis exception in the dependency workflow; no ET_REL graph or synthetic Ghidra runtime address is invented for this ET_DYN library.

The startup's client entry at linked0x71f3dc validates name/output pointers and tail-branches to **0x720ed0**. That function constructs opcode7 context, copies up to16 name bytes, calls the request helper at **0x720978**, and tests its return status.

The original request helper calls transport logic at0x72005c, then:

| Original linked Thumb address | Instruction/effect |
| --- | --- |
| `0x720986` | `ldr r3,[r4,#4]`: message pointer from context |
| `0x720988` | `ldr r0,[r3,#0x14]`: reply status at full packet +20 |
| `0x72098a` | Restore saved registers and return to client |
| `0x720f0a` | Save status in r5 |
| `0x720f0c` | Nonzero status branches to0x720f4a cleanup |
| `0x720f0e` | Load184 into allocation argument |
| `0x720f10` | Original operator-new call; stop before executing it |

Static following instructions show that success subsequently constructs a client object, passing reply physical/size words and the opaque kernel object pointer to original code at0x71fc64, before storing a client object pointer through the startup output. This following constructor/allocation path has **not** executed here. The startup output is not established by simply copying raw kernel handle0x68a96220 into it.

## Constructed context and guards

Each run invokes the original producer directly through its reusable `main(argv)` entry; it does not trust a retained report as the producer. Original producer guards and source identity checks are unchanged. The tool checks normal producer return, takes its four reply words, and constructs the36-byte opcode7 envelope (four-byte header,16-byte name,16-byte reply). Header/context/stack framing remains an explicit experimental setup.

Client begins **after transport**, at0x720986, with a constructed saved helper frame that returns to0x720f0a. The source-backed client page is read/execute-only. Packet and12-byte context are read-only; stack is constructed separately. Execution is restricted to the status-read epilogue and immediate status branch, stopping before allocation/cleanup calls. Other control flow, any writes, mapped padding reads and unmapped reads stop. Limits:100 instructions/100ms backend timeout. Status/bytes are selected by original producer, not by a host success/error decision.

Thus this is an **isolated producer-output/consumer-input compatibility check**, not end-to-end service execution, lock completion, process continuation or successful lookup-object creation.

## Reproduction and verification

```
python -m tools.research.wbi_ma_client --report-dir artifacts/execution/NEW_DIRECTORY
python -m tools.research.wbi_ma_client --name absent_control --report-dir artifacts/execution/NEW_CONTROL_DIRECTORY
```

Artifacts: `artifacts/execution/wbi-ma-client-first`, `wbi-ma-client-repeat`, `wbi-ma-client-absent`, each with a fresh original producer subreport. First/repeat consumer reports agree, including observed status read and allocation size. Negative control preserves-9 and reaches cleanup. No skipped call is represented as serviced.

Three constructed Thumb/ELF fixture tests verify successful status flow to allocation boundary, propagation of-9/-257/-1 to cleanup, and rejection of a mapped packet-padding read rather than consuming zero. They use no proprietary inputs. Full suite **348 passing tests**, `artifacts/execution/wbi-ma-client-suite.txt`. Status image regenerated with unchanged capability counts and no-UI title.

Next: verify original callback mutex/transport effects and the client object's original constructor/lifetime. A separate explicit package-WBI service policy can only be considered after those required state transitions are supported; retain all default startup guards. Do not force success, provide a fabricated allocation, skip cleanup/semaphore operations or write a raw kernel object pointer as the user-space client object.
