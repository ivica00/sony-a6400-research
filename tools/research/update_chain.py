#!/usr/bin/env python3
"""What the camera's update chain actually checks.

The community documentation for this camera states that the firmware image is "AES-encrypted
with unknown per-model keys" and protected by "three layers of integrity checks". Measured on
thirteen official updaters, that is wrong, and the error matters: it made a whole class of work
look impossible. This module produces the measurement instead of repeating either claim.

Two distinctions it refuses to blur:

* **A checksum is not a signature.** ``md5sum -c`` and a CRC32 routine prove that bytes were
  copied intact. They prove nothing about *who* authored them, because anyone can recompute
  them. Treating the first as the second is how "integrity checks" became "unbreakable".
* **The packaged file is not the boot decision.** This module reads the files and the scripts.
  Whether the bootloader accepts an image whose checksum was recomputed is a different question
  that needs a camera; the record says ``unknown`` rather than guessing.

Offline only: no camera, no USB, no updater execution.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ELF_MAGIC = b"\x7fELF"

#: Strings that name a cipher. Kept narrow so a library that merely mentions "aes" in a TLS
#: cipher list is not counted as an image cipher.
_AES_TOKENS = ("AES_set_decrypt_key", "AES_set_encrypt_key", "AES_decrypt", "AES_encrypt",
               "rijndael", "RIJNDAEL")

#: Strings that name a signature scheme, i.e. proof of authorship.
_SIGNATURE_TOKENS = ("rsa_verify", "RSA_verify", "ecdsa", "ECDSA", "verify_signature",
                     "signature", "pubkey", "public_key", "X509_verify", "PKCS7")

#: Strings that name a non-cryptographic integrity check.
_CHECKSUM_TOKENS = ("md5sum", "md5_sum", "MD5_", "uc_crc32sum", "crc32", "CRC32")

_CODE = frozenset("Tt")


def _strings(data: bytes, minimum: int = 5) -> set[str]:
    """Printable ASCII runs, which is where tool and symbol names live."""
    out: set[str] = set()
    current: list[str] = []
    for byte in data:
        if 32 <= byte < 127:
            current.append(chr(byte))
            continue
        if len(current) >= minimum:
            out.add("".join(current))
        current = []
    if len(current) >= minimum:
        out.add("".join(current))
    return out


def crypto_surface(path: Path) -> dict[str, object]:
    """Which cryptographic and integrity primitives a file names.

    ``has_signature`` is deliberately separate from ``has_md5``/``has_crc32``: a checksum
    verifies bytes, a signature verifies authorship, and only the second is a barrier to a
    modified image.
    """
    data = path.read_bytes()
    text = _strings(data)
    joined = "\n".join(text)

    def named(tokens: tuple[str, ...]) -> bool:
        return any(token in joined for token in tokens)

    symbols = tuple(sorted(
        name for name in text
        if any(token in name for token in _AES_TOKENS + _SIGNATURE_TOKENS + _CHECKSUM_TOKENS)))
    return {
        "has_aes": named(_AES_TOKENS),
        "has_signature": named(_SIGNATURE_TOKENS),
        "has_md5": named(("md5sum", "md5_sum", "MD5_")),
        "has_crc32": named(("uc_crc32sum", "crc32", "CRC32")),
        "symbols": symbols,
    }


def _thumb_literals(data: bytes, base: int) -> list[tuple[int, int]]:
    """``(instruction address, literal address)`` for every Thumb ``ldr rX,[pc,#imm]``.

    Only the PC-relative load form is needed: the AES wrapper loads both its ``ctx`` and its
    ``key`` pointer that way, so the literals are what lead to the key.
    """
    out: list[tuple[int, int]] = []
    for pos in range(0, len(data) - 4, 2):
        first = data[pos] | (data[pos + 1] << 8)
        # 16-bit ldr rX,[pc,#imm8] has opcode bits 15..11 = 01001.
        if (first >> 11) == 0b01001:
            imm8 = (first & 0xFF) * 4
            address = base + pos
            out.append((address, ((address + 4) & ~3) + imm8))
            continue
        # 32-bit ldr.w rX,[pc,#imm12]: first halfword 1111 1000 1101 1111.
        second = data[pos + 2] | (data[pos + 3] << 8)
        if (first & 0xFF7F) == 0xF85F:
            imm12 = second & 0xFFF
            address = base + pos
            out.append((address, ((address + 4) & ~3) + imm12))
    return out


def _find_aes_wrapper(data: bytes) -> list[tuple[int, int]]:
    """Locate the routine that sets up a 128-bit AES key.

    The wrapper is identified by the argument, not by a symbol name: it is the code that passes
    ``0x80`` (128 bits) as the key length. Both variants of the library share that shape, which
    is why this survives the layout difference between them.
    """
    for pos in range(0, len(data) - 4, 2):
        # movs r1,#0x80 is 0x2180 in Thumb little endian.
        if data[pos:pos + 2] == b"\x80\x21":
            return [(pos, pos)]
    return []


def _section_bytes(data: bytes) -> tuple[bytes, int] | None:
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError:  # pragma: no cover - dependency is pinned in requirements.txt
        return None
    import io

    try:
        elf = ELFFile(io.BytesIO(data))
    except Exception:
        return None
    sec = elf.get_section_by_name(".text")
    if sec is None:
        return None
    return sec.data(), sec["sh_addr"]


def aes_key_block(path: Path) -> bytes | None:
    """The 16 bytes the ``AES_set_decrypt_key`` caller passes, or ``None`` when absent.

    The chain is read from the ELF's own tables rather than guessed from code shape:

    * ``.text`` holds the wrapper that passes ``0x80`` (128 bits) as the key length;
    * the wrapper's ``ldr rX,[pc,#imm]`` literal plus the following ``add rX,pc`` forms the GOT
      base, and the second literal is an offset into it (``KeyArray`` is such a slot);
    * the GOT slot is filled at load time by an ``R_ARM_RELATIVE`` relocation whose addend is
      the ``.data`` address of the key.

    Using the relocation table means the result does not depend on the code layout that differs
    between the two library variants. Any hop that does not resolve returns ``None``: a wrong
    key here would silently invalidate the record.
    """
    data = path.read_bytes()
    if b"AES_set_decrypt_key" not in data:
        return None

    import io
    import struct

    from elftools.elf.elffile import ELFFile

    elf = ELFFile(io.BytesIO(data))

    def read_vaddr(vaddr: int, size: int) -> bytes | None:
        for sec in elf.iter_sections():
            start = sec["sh_addr"]
            if start and start <= vaddr < start + sec["sh_size"]:
                if sec["sh_type"] == "SHT_NOBITS":
                    return None
                offset = vaddr - start
                return sec.data()[offset:offset + size]
        return None

    # The key lives in a named object. Reading it from the symbol table rather than from a
    # GOT-offset guess is what makes this stable across the two library variants, which differ
    # in exactly that offset. `KeyArray` is 32 bytes; the wrapper passes 0x80 (128 bits), so it
    # uses the first half, and the second half is recorded for the note in the evidence record.
    for dyn in (elf.get_section_by_name(".dynsym"), ):
        if dyn is None:
            continue
        for sym in dyn.iter_symbols():
            if sym.name != "KeyArray":
                continue
            block = read_vaddr(sym["st_value"], min(sym["st_size"] or 16, 32))
            if block is None or len(block) < 16:
                continue
            key = block[:16]
            if key == b"\x00" * 16:
                continue
            return key
    return None


def key_aes_mode(path: Path) -> str | None:
    """Cipher mode the updater's AES helper uses, or ``None`` when there is no helper.

    The wrapper calls ``AES_decrypt``, which transforms one 16-byte block and takes no IV, and
    no ``AES_cbc_encrypt``/``AES_encrypt`` import exists beside it. That is ECB by construction;
    the function reports the mode it can justify rather than assuming the usual default.
    """
    data = path.read_bytes()
    if b"AES_set_decrypt_key" not in data:
        return None
    if b"AES_cbc_encrypt" in data or b"AES_cfb" in data or b"AES_ofb" in data:
        return "chained"
    if b"AES_decrypt" in data:
        return "ECB"
    return "unknown"


def updater_scripts(root: Path) -> list[dict[str, object]]:
    """What each updater shell script verifies.

    ``verifies_signature`` and ``verifies_checksum`` are separate answers on purpose: the
    record's claim is about which one the chain uses.
    """
    rows: list[dict[str, object]] = []
    if not root.is_dir():
        return rows
    for path in sorted(root.rglob("*.sh")):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        lower = text.lower()
        checks: list[str] = []
        if "md5sum" in lower:
            checks.append("md5sum")
        if "crc32" in lower:
            checks.append("crc32")
        if "sha256" in lower or "sha1" in lower:
            checks.append("sha")
        if "-c $sum_file" in lower or "-c $SUM_FILE" in text:
            checks.append("checksum_file")
        signature = any(token in lower for token in
                        ("signature", "verify_sig", "rsa_", "ecdsa", "pubkey", "openssl dgst"))
        rows.append({
            "name": path.name,
            "verifies_signature": signature,
            "verifies_checksum": bool(checks),
            "checks": tuple(sorted(set(checks))),
        })
    return rows


def plain_elfs(root: Path) -> int:
    """How many files under ``root`` are ELFs readable as-is, i.e. needed no decryption."""
    count = 0
    if not root.is_dir():
        return 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            with open(path, "rb") as handle:
                if handle.read(4) == _ELF_MAGIC:
                    count += 1
        except OSError:
            continue
    return count


def key_block_rows(roots: list[Path]) -> list[dict[str, object]]:
    """One row per body: where its ``libupdatertalk.so`` is and what key it carries."""
    import hashlib

    rows: list[dict[str, object]] = []
    for root in roots:
        for lib in sorted(root.glob(
                "*/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libupdatertalk.so")):
            # The body name is the directory immediately under the root that was passed.
            try:
                body = lib.relative_to(root).parts[0]
            except ValueError:
                body = lib.parent.name
            digest = hashlib.sha256(lib.read_bytes()).hexdigest()
            key = aes_key_block(lib)
            rows.append({
                "body": body,
                "library_sha256": digest,
                "key_hex": key.hex() if key else "",
                "is_sha256_of_empty": key == hashlib.sha256(b"").digest()[:16] if key else False,
                # AES_decrypt takes a single block and has no chaining argument, so the mode is
                # ECB; a CBC call would need AES_cbc_encrypt or an IV to be passed.
                "mode": "ECB" if key else "",
            })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--roots", nargs="+", type=Path, default=[],
                        help="unpacked body directories")
    parser.add_argument("--emit-keys", action="store_true",
                        help="print the per-body key-block TSV")
    parser.add_argument("--elfs", type=Path, help="count plain ELFs under this directory")
    parser.add_argument("--surface", type=Path, help="report one file's crypto surface")
    args = parser.parse_args(argv)

    if args.surface:
        for name, value in crypto_surface(args.surface).items():
            print(f"{name}: {value}")
        return 0
    if args.elfs:
        print(plain_elfs(args.elfs))
        return 0
    if args.emit_keys:
        rows = key_block_rows(args.roots)
        if not rows:
            print("no libupdatertalk.so found under the given roots", file=sys.stderr)
            return 2
        print("body\tlibrary_sha256\tkey_hex\tis_sha256_of_empty\tmode")
        for row in rows:
            print(f"{row['body']}\t{row['library_sha256']}\t{row['key_hex']}\t"
                  f"{str(row['is_sha256_of_empty']).lower()}\t{row['mode']}")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
