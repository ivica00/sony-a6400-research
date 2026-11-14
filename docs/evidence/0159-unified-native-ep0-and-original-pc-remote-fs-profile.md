# E0159: Unified Native EP0 and Original PC Remote Full Speed Profile

Date: 2026-11-08. Continuation of E0158. No physical camera access in this step.

## Original a6400 FS Proof

In original a6400 `libInfraUsbCmn.so`, SHA-256 `5338bafbb545ebc223fac15c9253a41ac9fe49c01fe32c73af40c3fb50eec0a6`, dynamic symbol `remotepc_interface_desc` has VA `1ae34` and size 24. Three native interface groups point to HS/FS/SS alternate records.

Verified by real pointer chain and exact bytes:

| Profile | Group VA | Alternate VA | Endpoint array VA |
|---|---|---|---|
| HS | `1ae34` | `1adf8` | `1ae4c` |
| FS | `1ae3c` | `1ae0c` | `1ae88` |

Both original alternates have class/subclass/protocol `06/01/01`, alternate 0, and three endpoints. HS: 81 Bulk 512, 02 Bulk 512, 83 Interrupt 32/interval 7. FS: 81 Bulk 64, 02 Bulk 64, 83 Interrupt 32/interval 10. Native byte 5 of endpoint records is also preserved (HS 2 / FS 1). All 60 endpoint array bytes of the compiled candidate match the original profile for the corresponding speed. This is proof from a static firmware file, not reading live library bytes.

Original `remotepc_desc_tbl` metadata contains generic/old PID 0641, different from physical 0caa. Therefore metadata was not blindly copied: VID/PID, bcdDevice, and strings remain the actual read data from E0158.

## MOD Speed Policy

The candidate is extended with its own FS configuration, interface, alternate, and endpoints. At HS it exposes PTP 0 + UVC 1/2. At FS it exposes only PTP 0 and does not advertise UVC video. This is an explicit MOD policy, not an original Sony decision or physically proven automatic mode switch. FS endpoint parameters are original; configuration attributes/power follow the previously read candidate `80/fa`. Native strings and device identity belong to the same object.

## Unified Descriptor Reply

`a6400_uvc_ptp_candidate_descriptor_reply` in `tools/native_camera/uvc_ptp_descriptors.{c,h}` now handles:

- Device (1), configuration (2), string/language (3).
- Device qualifier (6).
- Other-speed configuration (7).

It calls original Sony `make_device_desc`, `make_config_desc`, `make_string_desc`, and `make_device_qualifier_desc` (`602bbfec`), plus original `memcpy`. It uses a local full request and 512-byte staging, then copies only the requested prefix after confirming the expected length. Thus strings, whose original serializer writes the full description before truncating the return length, cannot overflow a small caller output.

HS configuration is 173 bytes (PTP+UVC+IAD), FS 39 (PTP-only). Other-speed HS request returns FS 39/type 7; FS request HS 173/type 7 with video IAD. The original serializer produces type 7, which is temporarily normalized to type 2 only in local staging for the existing IAD validator and then restored to 7. Native caller setup is not modified.

Qualifier for both profiles: `0a 06 00 02 ef 02 01 40 01 00`. Both speeds have one configuration. SuperSpeed is rejected because a shared SS profile is not implemented.

Before the original serializer, owned HS/FS pointer trees, alternate/endpoint counts, bounded extra blocks, and owned strings are validated. Only standard GET_DESCRIPTOR requests for supported indices, language 0409, and current speed 2 (FS) or 3 (HS) are accepted. Unsupported descriptor/language/index, foreign table, insufficient output, and aliased setup/tree buffers are rejected. The caller must hold topology stable during the call; no live lock.

## Checks

`build_uvc_ptp_descriptor_candidate` executes the real compiled reply path and original Sony functions to return. Kernel is immutable during execution and code/write guards remain active. Gadgetcore memory, speed, EP0, caller objects, and stack are explicit offline fixtures. No service/callback return is fabricated.

511 cumulative checks pass (including the previous 254). For both speeds, device/config/qualifier/other-speed and string 0..3 were tested, each for `wLength` 0, 9, 65535. Return length, bytes, untouched output beyond return length, unchanged setup, and owned tree were confirmed. Negative cases include unsupported type/string/language, too-small output, and SS. These are not 511 physical tests nor proof of Windows driver binding.

Artifacts: `artifacts/native/uvc-ptp-unified-ep0-e0159/manifest.json`, standalone ARM ELF, and `unified-2-*`/`unified-3-*` raw replies, where 2=FS, 3=HS. Earlier artifacts were not overwritten. Existing live module builder and EP0 hook were not modified.

## Remaining

EP0 callback integration and real device-group binding are not yet proven. Still needed: wire this owned tree, UVC reference MOD, and endpoint selector while retaining the original PTP driver, and verify registration/STOP/unregister and rollback. Native JPEG/DMM ownership and sensor UVC frames remain open. Staging solves reply length, not the lifetime of the whole module or native EP0 completion. Host detection must support the planned Sony UVC interface with PID 0caa instead of assuming 0322.

No camera uploads, loaded shared module, feeder processes, USB mode change, SD, or persistent writes. Physical shared UVC+PTP is not confirmed.
