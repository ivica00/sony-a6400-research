# E0489 — The update chain checks CRC32 and MD5, not a per-model cipher

Date: 2026-11-13. Offline only: thirteen hash-pinned official updaters, unpacked with `fwtool`.
No camera, no USB, no updater execution.

This record exists because the ecosystem repeats a claim that made an entire class of work look
impossible. The widely-read community README for this camera states the image is "AES-encrypted
with unknown per-model keys and has three layers of integrity checks". Measured against the
packaged files, that is false, and the error is worth correcting in public because it changed
what people believed they were allowed to attempt.

## 0. Short answer

1. **The packaged image is not encrypted.** 484 files under the a6400 tree are ELF objects read
   as-is, with working symbol tables; `libObj.so` alone has 3,297 named functions.
2. **The integrity checks are CRC32 and MD5, and neither proves authorship.** `uc_crc32sum.elf`
   carries no cryptographic import at all, and `loader_writer.sh` runs `md5sum -c`. Anyone who
   can read a file can recompute either.
3. **No updater script verifies a signature.** The updater tree holds 41 files, 18 of them shell
   scripts, and not one contains a signature-verification call or a public key. Five of the 18
   check a checksum; the rest only compare versions, LSI types and file existence.
4. **There is an AES helper, but it does not protect the image.** `libupdatertalk.so` is 3,456
   or 3,404 bytes, present in three variants across thirteen bodies, and it exists to unscramble
   updater talk. Its key is `e3b0c44298fc1c149afbf4c8996fb924`, which is `sha256("")[:16]` — a
   published test vector, identical on every body, used in ECB with no IV.
5. **What this record does not settle.** Whether the bootloader accepts an image whose checksum
   was recomputed. That needs a camera. It is recorded as `unknown`, not as impossible.

## 1. Inputs

The thirteen bodies, their packages and hashes are those of E0477. The files this record reads:

| file | body | size | SHA-256 (truncated) |
| --- | --- | --- | --- |
| `libupdatertalk.so` | a6100a, zve10, ILCE-7C, ILCE-7M3, ILCE-7RM4A | 3,404 | `0daa4aa52f79d110…` |
| `libupdatertalk.so` | a6400, ILCE-7RM3, ILCE-9 | 3,456 | `1e36b989214aafb0…` |
| `libupdatertalk.so` | a6600, DSC-RX0M2, ILCE-7RM4, ILCE-9M2, ZV-1 | 3,404 | `5a22e281c8ae0cac…` |
| `uc_crc32sum.elf` | a6400 | 10,076 | — |
| `ud_genlock_firmup.elf` | a6400 | 13,296 | — |
| `loader_writer.sh` | a6400 | — | — |

The updater tree itself is 41 files: 18 shell scripts, 23 ELF binaries and config files.

The full per-body table is `docs/evidence/cross_model/aes-key-blocks.tsv`.

## 2. Method, and how to reproduce it each way

```bash
# 1. how many files needed no decryption at all
python3 -I tools/research/update_chain.py --elfs <a6400 unpacked tree>
#   → 484

# 2. what cryptographic primitives one file names
python3 -I tools/research/update_chain.py --surface <tree>/updater.img_unpacked/bin/uc_crc32sum.elf
#   → has_aes: False, has_signature: False, has_crc32: True

# 3. the key each body's AES helper uses
python3 -I tools/research/update_chain.py --roots <all unpacked roots> --emit-keys
#   → 13 rows, key_hex = e3b0c442…b924, is_sha256_of_empty = true, mode = ECB

# 4. what the updater scripts check
python3 -c "import sys; sys.path.insert(0,'tools/research'); import update_chain as u; \
from pathlib import Path; [print(r) for r in u.updater_scripts(Path('<tree>/updater.img_unpacked/bin'))]"
#   → 18 scripts, verifies_signature False on every one, 5 with verifies_checksum True
```

`aes_key_block` reads the key from the `KeyArray` symbol rather than from a code offset,
because the two library variants differ exactly in that offset. `key_aes_mode` reports `ECB`
because the helper imports `AES_decrypt` (one 16-byte block, no IV argument) and does not
import `AES_cbc_encrypt`, `AES_cfb*` or `AES_ofb*`.

## 3. The two mechanisms, and why the claim survived

**The cipher that is there.** `libupdatertalk.so` exports `Dec_ScrambleInit` and `Dec_Scramble`;
`Dec_Scramble` calls through a table of function pointers that resolves to
`AES_set_decrypt_key` and `AES_decrypt`. It passes `0x80` (128 bits) as the key length. The key
object is `KeyArray`, 32 bytes at `.data` offset — the helper uses the first 16, which are the
first half of `sha256("")`. The second 16 bytes are `27ae41e4649b934ca495991b7852b855`, the
second half of the same digest, which is what a developer gets when they fill a 32-byte buffer
with a digest of nothing.

**Why the claim survived.** Three things make the wrong reading easy. The symbol is called
`AES_decrypt`, so a string search finds AES and stops. The library sits in the same tree as the
updater, so it looks like the image path. And a flat list of "integrity checks" is easy to
repeat. The measurement that separates them is the key: a per-model secret would differ per
body, and this one is a constant that anyone can type from memory.

## 4. Alternative explanations

- **"The image is encrypted elsewhere and we only see the decrypted cache."** No: the files are
  read from the packaged `.exe` container through `fwtool` with no decryption step in our
  pipeline, and 558 ELF magics appear inside the raw `firmware.fdat` before any extraction.
- **"The key is real but wrapped."** The bytes at `KeyArray` are literally the published
  SHA-256 of the empty string, followed by its second half; a wrapped secret would not be that.
- **"CRC32 is a signature in disguise."** It is not: it is linear, unkeyed and recomputable, and
  the string table of `uc_crc32sum.elf` shows `check sum OK`/`NG` messages with no key material.
- **"Some other stage checks a signature we did not look for."** Possible, and the reason
  section 5 draws the line where it does. What is established is that the packaged files and the
  updater scripts contain no signature check.

## 5. Confidence and limitations

- **Verified from artifacts:** the 484 plain ELFs, the three library hashes, the key bytes and
  their equality with `sha256("")[:16]`, the absence of crypto imports in `uc_crc32sum.elf`, the
  `md5sum -c` call, and the absence of signature strings across all 41 updater files.
- **Not verified:** that a modified image, with its CRC list recomputed, is accepted by the
  device. This record cannot reach the bootloader; that needs a camera or a preserved boot log.
  Anyone reading this as "custom firmware is now possible" is reading a claim the evidence does
  not make.
- **Not verified:** what the boot ROM does with `firmware.fdat` before the updater runs. The
  143 KB `updater.img` is a CRAMFS image read without a key, and `UDTRFIRM` heads the payload,
  but the acceptance path above the shell scripts is outside this measurement.

## 6. Dependent implementation

`tools/research/update_chain.py` implements §2 as a library with 12 tests, three of which run
against a real unpacked body when `A6400_UNPACKED_ROOT` is set. The tests pin the distinction
this record turns on: a checksum tool must report `has_md5`/`has_crc32` and must never report
`has_signature`, and a moved function must not be described as data.

Any later claim about flash writing must say which of the three levels it means — the packaged
file, the updater script, or the boot acceptance — and mark the third `unknown` until a camera
confirms it.

## 7. Next experiment

Take one body, change a single byte inside a partition image, recompute the CRC32 list with
`uc_crc32sum.elf -s -c` under the same tool, and see whether `ud_genlock_firmup.elf`'s
read-back comparison passes and whether the device boots. That is a physical experiment and needs
an explicit authorisation; until then the boundary stays where this record puts it.
