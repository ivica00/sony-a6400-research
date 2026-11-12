# E0405 — Option A offline pre-flight: mode-gate reference audit and the remaining B2/B3 unknowns

Date: 2026-11-12. Offline disassembly only. No camera access, no module build
beyond the earlier read-only probe, no kernel write, no descriptor change, no
PC Remote, no UVC/`VS_PROBE`/`ffmpeg` change.

Option A (bounded save/restore of `gadgetcore+0x84`) was accepted. This record
completes the mandated offline pre-flight and states plainly why B2/B3 were not
started: the mode-gate write is **not** the only missing piece, and the
device-descriptor / `bcdUSB` and EP0/char-device layers are not yet decoded to a
standard that permits a safe hardware module.

## 1. `gadgetcore+0x84` reference audit (`0x602b8000..0x602be000`)

A brute-force ARM scan (Capstone decoding each word independently, because the
linear disassembly stops at literal pools) found four byte references and two
unrelated word references:

| Address | Access | Context |
| --- | --- | --- |
| `0x602bc15c` | `ldrb r3,[r0,#0x84]` | hardcoded `0xEE` OS-string handler: returns the 18-byte descriptor only when the byte is non-zero |
| `0x602ba314` | `ldrb r3,[r0,#0x84]` | hardcoded `bRequest 0x30 / wIndex 4` compat-ID handler: same gate |
| `0x602b89cc` | `ldrb r0,[r4,#0x84]` | gadgetcore ioctl start path: passes the byte to `usb_gcw_start` |
| `0x602bcd88` | `strb r3,[r7,#0x84]` | gadgetcore ioctl descriptor-set path: the camera app itself writes mode and max-speed bytes |
| `0x602bdf94/b0` | `ldr/str [r4,#0x84]` | list-link operations on a different struct; not gadgetcore |

`usb_gcw_start` (`0x602bd7f8`) stores its argument in a gcw global and returns;
it does not reconfigure the UDC synchronously. `usb_gcw_start` maps the value
`1` to internal start value `3` and every other value to `2`.

**Verdict:** no MSC/Bulk-Only/SCSI path reads `gadgetcore+0x84`. While the
camera is idle in Mass Storage, setting it to `1` only enables the two Microsoft
OS descriptor handlers. It is **also** the mode value the camera app supplies
when it drives gadgetcore start/reconfiguration (`0x602bcd88` writer +
`0x602b89cc` reader). Therefore a `mode=1` write is only safe if no app-driven
USB reconfiguration runs while it is active; the module must restore the byte
before allowing any mode change, and must not itself invoke gadgetcore start
with that value.

## 2. `bcdUSB` / device-descriptor layout — not resolved

The read-only probe read the live root (`0x69567d20`) as
`00 02 00 00 00 01 00 00 <config_ptr>` for the first 16-byte entry. That is
consistent with an internal per-speed record (two `0x200`/`0x100`-sized fields
and a config pointer), **not** a raw 18-byte USB device descriptor. The native
tree is a pointer graph; the 18-byte device descriptor is built at request time.

What was checked offline:

- no static `12 01 … 4c 05` device descriptor exists in the preserved
  `vmlinux.bin` (the descriptor is generated, not stored);
- 26 code sites load the root pointer (`gc+0x6c`), so the builder is among them,
  but the exact field-to-descriptor mapping and the source of `bcdUSB` were not
  proven in this pass.

**Consequence:** whether `bcdUSB` is already `>= 0x0210` (required for
Windows to issue MS OS 2.0 requests) is unknown. Without that fact, a B2 module
cannot know whether it must alter a device-descriptor source, and writing a
guess is exactly the class of change that previously caused enumeration
failures. The device-descriptor builder must be decoded first (or read through
a Windows-side descriptor query).

## 3. What B2 still needs beyond Option A

Even with the 18-byte OS-string patch and the one-byte mode write:
1. device-descriptor `bcdUSB` answer (above);
2. a descriptor-tree extension (data-only): clone the live per-speed records,
   append a zero-endpoint interface `0xFF/0xDB/0x01`, swap `gc+0x6c`, and force
   a re-enumeration (sysfs `soft_connect` or gcw start) so the host reads it;
3. EP0 vendor IN/OUT queueing (the decoded request layout exists, but the
   alloc/queue/completion sequence has never been executed by our code);
4. a `/dev/a6400_dbg` char device (cdev + file_operations ABI) and the
   daemon-side 64-byte chunk framing; and
5. a Microsoft OS 2.0 **configuration-subset** answer in addition to the
   device-level compatible-ID set, so WinUSB binds only the vendor function and
   not the composite parent (which would risk Mass Storage).

These are multi-part kernel changes; none is implemented or hardware-tested
here.

## 4. Reversibility status

No write was made in this step. The previously verified B1c state remains: the
OS string is stock (`CRC 6e795789`), `gadgetcore+0x84` is stock `0x00`, and the
probe module from E0404 was unloaded and deleted. A battery pull still returns a
100% stock cold boot.

## 5. Recommendation

Continue with two bounded increments before any hardware module:

- **E0405a (offline):** decode the device-descriptor builder and its `bcdUSB`
  source from the 26 root-pointer sites; decide whether a data-field edit or a
  Windows-side descriptor query is required. Also build the MS OS 2.0
  configuration-subset bytes and validate them against the Windows spec.
- **E0405b (offline):** prototype the tree extension in the Unicorn descriptor
  model and the EP0 vendor queue against the decoded request ABI, then one RAM
  module load in Mass Storage for enumeration only (no WinUSB claim).

Only after those pass should the one-byte mode write and vendor interface be
combined, with the same save/restore receipts.
