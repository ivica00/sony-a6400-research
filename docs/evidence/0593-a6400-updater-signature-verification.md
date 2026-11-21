# E0593 — Updater firmware signature: how the camera checks it and whether custom firmware can be pushed (ILCE-6400)

Date: 2026-11-21. Offline binary analysis plus one live camera experiment
(ILCE-6400, firmware v2.00). The experiment replaced the updater initrd on
`nflasha1` twice, pushed an unsigned FDAT, and restored the stock image afterwards.
The camera was left in normal mode with the stock updater initrd; no partition
content was deliberately changed.

## Inputs

- Official `Update_ILCE6400V200.exe`, SHA-256
  `ea460cbec5f8b62119630f0a653eeca4f4ffad887670e60c0fd9c0345e6b30a6`
  (matches [E0477](0477-bionz-x-platform-map-13-updaters.md)).
- Extracted `FirmwareData_ILCE6400V200.dat`, 304,833,928 B, SHA-256
  `78a6881eddd16609758951c80d533ac82042858eac919bd94453941ba6b766f2`.
- Updater initrd from the 13-Nov `nflasha1` capture, 4,354,048 B, SHA-256
  `e6315bf0c84300b763b33dc3a9a5e9ac2b4fdb18090ecd80e136f86afa4f1845`.
- `/usr/bin/sauu` from that initrd, 84,428 B (module strings
  `SignatureVerification.cpp`, `UFPDecryptorModule.cpp`).
- Test payload `fdat_v201_unsigned.bin`, 304,833,808 B (derivation below).

## Analysis

### Where the check is

Only `sauu` references the verification key. It imports `RSA_verify` and
`PEM_read_RSA_PUBKEY`; no other binary in the updater stack (initrd or
`nflasha15`) imports any signature function, and the string
`/etc/VerificationKey.pem` appears only there.

Call chain, `sauu` virtual addresses:

    `0x10a78`  UFPDecryptorModule.cpp, state "Waiting for Firmware Copy Completion"
      `0x104e0`  wrapper, passes the PEM path
        `0x10368`  SignatureVerification.cpp
          `0x1053c`  PEM_read_RSA_PUBKEY("/etc/VerificationKey.pem")
          `0x10554`  SHA256(message)
          `0x10568`  RSA_verify(NID_sha256WithRSAEncryption = 0x2a0, digest, 32,
                                data + len - 0x100, 256, rsa)

Argument setup at `0x10adc` through `0x10afe` defines the message:

    `total`       bytes copied into RAM (logged as "total_data_size = %d")
    `message`     data[0 .. total-0x100]
    `signature`   data[total-0x100 .. total]     256 bytes
    `IV`          data[total-0x110 .. total-0x100]

The result must be exactly 1 (`0x1056c`: `cmp r0,#1`; `0x1056e`: `beq 0x10588`).
On failure the module logs `Signature Verification Error` (line 97) and throws
(`__cxa_allocate_exception` / `__cxa_throw`); it never reaches the IV extraction and
decrypt stage. On success it copies the 16-byte IV to `ctx+0x4a8` and stores the
ciphertext length (`total-0x110`) at `ctx+0x45c` before decryption.

The message layout matches the package exactly: FDAT records plus the 16-byte IV,
signed with RSA-2048/PKCS#1 v1.5/SHA-256. The same check reproduces on the host
with the PEM extracted from the initrd.

### The other integrity checks

- `crypter.elf` (MS-crypt path, `mode5`): no RSA, no `EVP_Verify`. Its
  `DecryptorModule.cpp` at `0xe638` requires `len % 16 == 0` and decrypts the whole
  payload with `Dec_Scramble` (AES-128-ECB, `K1 = SHA-256("")[0:16]`), 16 bytes at a
  time. No signature exists anywhere in that path.
- That path is unreachable as shipped: `insmod.sh` comments out `ms_drv.ko` and
  `mcmn_drv.ko`, `/sbin/init` comments out `is_valid_boot.sh`, and a live attempt
  to insert both drivers in updater mode failed with `unknown symbol in module, or
  unknown parameter` (errno 2). `/dev/mmca` nodes exist but no driver binds;
  `mount` fails with `ENOENT`. `Fsys_Mount` therefore cannot succeed.
- The loader `nflashaB0` contains no CRC32 table, no MD5 IV, no SHA-256 round
  constants, and no hash-related strings; it size-checks `vmlinux.bin` and
  `initrd.img` and jumps. `libupdaterbody.so` and `libupdatercommon.so` import no
  crypto; the body's checks are model/region/version flags plus the shell-layer
  CRC32/MD5 `.sum` files.
- `checkGuard` rejects an equal or older firmware version (`Invalid version`) before
  any data is processed, so a same-version image never reaches the signature check.

## Live experiment

Test image: the shipped FDAT with only the first 512-byte ECB block changed —
header version 2.00 to 2.01, header CRC recomputed, record-0 checksum
recomputed, everything from byte 512 onward byte-identical to stock, stock RSA
trailer left in place (now invalid).

| Run | Updater initrd | Result |
| --- | --- | --- |
| 1 | stock `sauu` | `guard OK`; `writeFirmware` raised `Firmware update error: Invalid data` after 57.1 s (full transfer). |
| 2 | `0x1056c`: `cmp/beq` replaced by `movs r0,#1 ; nop` | Same `Invalid data` at 56.8 s. This patch removes the branch to the success label, so control falls into the error path; the outcome equals run 1 for the wrong reason. |
| 3 | `0x1056c`: `cmp/beq` replaced by `nop ; b 0x10588` (`00 bf 0b e0`) | `writeFirmware` returned OK after 157.1 s, `complete()` OK, camera re-enumerated as `054C:0CA8` and the debugger answered. |

Run 3 is the bypass: the camera accepted a deliberately unsigned image and
proceeded past the point where run 1 rejected it.

### CRAMFS writing pitfall (corrected)

Replacing a multi-block file in the initrd requires that compressed blocks are
**not** padded: in the original image the gap between a block end and the next
block start is zero and block ends are not 4-aligned. A writer that aligns every
block corrupts any file larger than one block (`sauu` is 21 blocks) and produces
an updater that does not boot. Single-block replacements (`/sbin/init`) mask the
error.

## Conclusion

- A stock camera rejects custom firmware: `sauu` verifies an RSA-2048/SHA-256
  signature over the FDAT ciphertext with `/etc/VerificationKey.pem` before
  decrypting, and the private key is not present anywhere on the device, in the
  package, or in the PC updater (which performs no crypto at all).
- With `sauu`'s verify branch neutralised, the camera accepts an unsigned FDAT
  and runs the update to completion. Custom content then only has to satisfy the
  container format, the record framing, the header CRC, the model/region
  (`0x81030011`), a newer version field, and the body's `.sum` checks — none of which
  need a secret.
- Prerequisite: one write to `nflasha1:/boot/initrd.img` from outside the update
  path (on this body, the normal-mode USB debug daemon with root exec). The
  update chain itself cannot provide that first write, because it is the thing
  being gated.
- The MS-crypt/crypter route is unauthenticated but cannot be reached in the
  shipped kernel because the media drivers do not load.

## Caveats

- The payload used in the live run was the stock firmware, so a successful
  rewrite cannot be distinguished from no rewrite by content; the evidence for
  the write is the 157 s run time and the reboot after `complete()`. No partition
  hash baseline was taken before the run.
- Pushing *modified* partition images has not been exercised end to end.
- The camera's pre-experiment initrd (`98303d33`) was overwritten in a staging copy
  during the experiment; the stock captured image was restored and verified
  (`e6315bf0`, both halves read back).
- A failed or interrupted write of a modified image can brick the camera;
  recovery is service-level. Any real attempt needs a full partition backup and
  a verified restore path first.
