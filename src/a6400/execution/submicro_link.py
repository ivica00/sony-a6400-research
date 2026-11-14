"""Clean-room Sony BIONZ X sub-microcontroller link transport & TLV codec.

Implements the 128-byte Slot A/B CRC-16/CCITT-FALSE framing, Slot B TLV
status frames (types ``0x30``/``0x31``), and 8-byte command headers documented
in ``Oein/a5000-emulator`` (``docs/RE_SUBMICRO_LINK.md``, CC BY 4.0, by
Park SungHyun / Oein).

Note on provenance:
    The transport protocol and Slot B TLV layout were documented on Sony
    ILCE-5000 (``CXD90014``) ``av-cam.bin`` (link module + task 48).
    ``CXD90045`` parity for individual TLV IDs and SIO channel mappings must
    be verified against ``CXD90045`` ``av-cam.bin`` / live link traces.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Dict, List, Optional, Sequence, Tuple

FRAME_SIZE = 128
FRAME_PAYLOAD_END = 126
SLOT_B_TYPE_MICRO_TO_CPU = 0x30
SLOT_B_TYPE_CPU_TO_MICRO = 0x31
MAX_CMD_DATA_LEN = 0x17A0


def crc16_ccitt_false(data: bytes) -> int:
    """Compute CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no final XOR)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def verify_frame_crc(frame: bytes) -> bool:
    """Verify the little-endian CRC-16/CCITT-FALSE at bytes 126..127."""
    if len(frame) != FRAME_SIZE:
        return False
    expected = crc16_ccitt_false(frame[:FRAME_PAYLOAD_END])
    actual = struct.unpack_from('<H', frame, FRAME_PAYLOAD_END)[0]
    return expected == actual


def stamp_frame_crc(frame: bytearray) -> bytes:
    """Write the little-endian CRC-16/CCITT-FALSE at bytes 126..127."""
    if len(frame) != FRAME_SIZE:
        raise ValueError(f'Frame must be {FRAME_SIZE} bytes, got {len(frame)}')
    crc = crc16_ccitt_false(bytes(frame[:FRAME_PAYLOAD_END]))
    struct.pack_into('<H', frame, FRAME_PAYLOAD_END, crc)
    return bytes(frame)


@dataclass(frozen=True)
class SlotBTlvRecord:
    """One TLV record inside a 128-byte Slot B frame."""

    tlv_id: int
    data: bytes


@dataclass(frozen=True)
class SlotBFrame:
    """Decoded 128-byte Slot B TLV status frame."""

    frame_type: int
    tlv_byte_count: int
    records: Tuple[SlotBTlvRecord, ...]
    crc_valid: bool

    def by_id(self) -> Dict[int, bytes]:
        return {rec.tlv_id: rec.data for rec in self.records}

    @property
    def version_code(self) -> Optional[int]:
        """Return ``100*a + 10*b + c`` from TLV 0 data[0..2], if present."""
        tlv0 = self.by_id().get(0)
        if tlv0 is None or len(tlv0) < 3:
            return None
        return 100 * tlv0[0] + 10 * tlv0[1] + tlv0[2]


def decode_slot_b_frame(frame: bytes) -> SlotBFrame:
    """Decode a 128-byte Slot B TLV frame (type 0x30 or 0x31)."""
    if len(frame) != FRAME_SIZE:
        raise ValueError(f'Slot B frame must be {FRAME_SIZE} bytes, got {len(frame)}')

    frame_type = frame[0]
    tlv_byte_count = frame[2]
    crc_ok = verify_frame_crc(frame)
    end = min(4 + tlv_byte_count, FRAME_PAYLOAD_END)

    records: List[SlotBTlvRecord] = []
    pos = 4
    while pos + 4 <= end:
        tlv_id = frame[pos]
        tlv_len = frame[pos + 1]
        data_start = pos + 4
        data_end = data_start + tlv_len
        if data_end > end:
            break
        records.append(SlotBTlvRecord(tlv_id=tlv_id, data=bytes(frame[data_start:data_end])))
        pos = data_end

    return SlotBFrame(
        frame_type=frame_type,
        tlv_byte_count=tlv_byte_count,
        records=tuple(records),
        crc_valid=crc_ok,
    )


def encode_slot_b_frame(
    frame_type: int,
    tlvs: Sequence[Tuple[int, bytes]],
) -> bytes:
    """Encode a 128-byte Slot B TLV frame with little-endian CRC-16/CCITT-FALSE."""
    if frame_type not in (SLOT_B_TYPE_MICRO_TO_CPU, SLOT_B_TYPE_CPU_TO_MICRO):
        raise ValueError(f'Invalid Slot B frame_type: 0x{frame_type:02x}')

    buf = bytearray(FRAME_SIZE)
    buf[0] = frame_type
    buf[1] = 0

    pos = 4
    for tlv_id, payload in tlvs:
        if not (0 <= tlv_id <= 0xFF):
            raise ValueError(f'Invalid TLV id: {tlv_id}')
        needed = 4 + len(payload)
        if pos + needed > FRAME_PAYLOAD_END:
            raise ValueError('Slot B TLVs exceed 122-byte payload limit')
        buf[pos] = tlv_id
        buf[pos + 1] = len(payload)
        buf[pos + 2] = 0
        buf[pos + 3] = 0
        buf[pos + 4 : pos + 4 + len(payload)] = payload
        pos += needed

    buf[2] = pos - 4
    buf[3] = 0
    return stamp_frame_crc(buf)


@dataclass(frozen=True)
class SubmicroCommandHeader:
    """8-byte command-exchange header (``RE_SUBMICRO_LINK.md`` §2)."""

    raw_b0: int
    category: int
    command: int
    direction: int
    data_length: int
    extra_u16: int = 0

    @property
    def is_cpu_to_micro(self) -> bool:
        return self.direction == 2

    @property
    def is_slot_ab_exchange(self) -> bool:
        return self.category == 5 and self.command == 4 and not self.is_cpu_to_micro


def decode_command_header(raw: bytes) -> SubmicroCommandHeader:
    """Decode an 8-byte micro <-> CPU command header."""
    if len(raw) != 8:
        raise ValueError(f'Command header must be 8 bytes, got {len(raw)}')
    b0, cat, cmd, direction, length, extra = struct.unpack('<BBBBHH', raw)
    return SubmicroCommandHeader(
        raw_b0=b0,
        category=cat,
        command=cmd,
        direction=direction,
        data_length=length,
        extra_u16=extra,
    )


def encode_command_header(
    category: int,
    command: int,
    direction: int,
    data_length: int,
    *,
    raw_b0: int = 0,
    extra_u16: int = 0,
) -> bytes:
    """Encode an 8-byte micro <-> CPU command header."""
    if not (0 <= data_length <= MAX_CMD_DATA_LEN):
        raise ValueError(f'data_length out of range (0..0x{MAX_CMD_DATA_LEN:x}): {data_length}')
    return struct.pack(
        '<BBBBHH',
        raw_b0 & 0xFF,
        category & 0xFF,
        command & 0xFF,
        direction & 0xFF,
        data_length,
        extra_u16 & 0xFFFF,
    )
