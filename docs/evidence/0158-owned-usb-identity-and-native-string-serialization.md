# E0158: Full HS Identity and Owned Memory for USB Strings

Date: 2026-11-08. Continuation of E0157.

## Physical Readback Without Link Change

`capture_sony_usb_hub --strings` was extended to read actual strings at the indices listed in the original device descriptor. Readback showed the same Sony 054c:0caa, PTP configuration unchanged, LANGID 0409. Manufacturer Sony, product ILCE-6400, and real serial number CF93603BE631 were saved together with raw UTF-16LE descriptors, not derived from Windows friendly name.

Result: `artifacts/hardware/uvc-ptp-coexistence-e0152/pc-remote-identity-e0158.json`. No USB reset, configuration write, or camera upload was performed.

## Native Table and Ownership

`uvc_ptp_descriptors.{c,h}` candidate now contains the full 88 leading bytes of the Sony descriptor table: three speed entries of 16 bytes and 40 bytes of metadata. Offset of the configuration object behind them is verified by compile-time assert. Language and string entries have the original 8-byte ABI.

`a6400_uvc_ptp_candidate_identity` validates capture format before writing, copies VID/PID/bcdDevice and original UTF-16LE payloads into caller-owned candidate. String pointers and language table point into that same object. Keeping the original table after transition is not required for strings. The candidate must remain alive until full retirement of all native users.

Currently supported is the exact proven source: indices 1/2/3, single LANGID 0409, up to 64 payload bytes per string. Other layouts are not generically accepted. Invalid device/string format, odd length, and oversized payload are rejected without modifying the object.

Device identity retains VID/PID 054c:0caa, bcdDevice 0200, and three real strings. For the experimental shared HS device, class/subclass/protocol are set to EF/02/01 alongside the existing video IAD. This is a MOD declaration of a composite device, not proof of Windows driver binding. No new USB VID/PID was assigned or invented.

## Original Sony Serializers

Executed to return:

- `make_device_desc` `602bb988`.
- `make_string_desc` `602bc0cc`.
- `make_config_desc` `602bbc54` and `memcpy` `60258b80` from the previous contract.

Original kernel SHA-256 and reference library identity remain verified. No host replacement for these functions. Code/write guards constrain execution and writes. Gadgetcore, HS state, EP0 maxpacket 64, and caller object memory are explicit offline fixtures, not a live kernel dump.

After identity init, the original capture buffers in test memory are zeroed. Native string serializer still returns the original strings from the candidate's own memory. The candidate itself does not change during serialization. From the same full table, config reply returns the same 173 bytes.

Important original contract: `make_string_desc` writes the full string and only truncates the return length. Verification therefore allows a full temporary buffer; live EP0 integration must stage it and then copy the appropriate prefix, just as config reply already does. Do not pass a small caller buffer directly to the original string serializer with a small `wLength`.

## Results

254 offline checks pass: includes the earlier 172 and additional checks of HS device identity, language/string replies, short requests, owned-data lifetime, unsupported languages/indices, configuration preservation, and rejections without mutation. These are not physical USB transfer tests. Five tests of the existing hub configuration parser also pass. Full project suite was not repeated after E0156 since the new parts are not wired into existing runtime.

`artifacts/native/uvc-ptp-identity-e0158/` contains the standalone ARM ELF, manifest with hashes, and real outputs of the native serializers:

- `native-hs-device-descriptor.bin`.
- `native-string-0.bin` (LANGID), `native-string-1/2/3.bin`.
- `native-ep0-reply-9.bin` and `native-ep0-reply-173.bin`.

## Remaining Integration

This is a verified HS device/config/string candidate, not a bootable or loaded UVC+PTP module. Missing: live EP0 hook and staging for device/string replies, FS/other-speed/qualifier contract, shared gadgetcore register/stop/unregister and rollback, and native JPEG/DMM producer.

Retained PID 0caa means the existing host UVC auto-launcher that only looks for PID 0322 is insufficient for the future shared device. Detection must be tied to the verified Sony UVC interface identity, while keeping protection against other webcams. That change has not yet been made. Compatibility with Sony desktop programs remains out of scope.

Physical Windows enumeration of the shared device, driver grouping, UVC video, and simultaneous PTP controls remain unconfirmed. The camera was in PC Remote during physical readback; this step did not change that mode, SD, persistent storage, or active modules.
