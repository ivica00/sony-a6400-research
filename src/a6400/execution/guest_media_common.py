"""Authentic Sony MediaCommonDriver (mcmn_drv.ko) UIPC responder.

Reverse-engineered from /usr/kmod/mcmn_drv.ko (offsets 0x3e00-0x4100) and
/usr/lib/libInfraMediaDetect.so (offsets 0xddc0-0xdf20).

Handles category 2 (media insertion/status), subcmd 1 (check inserted media)
on queue 0x00d9016e (MEDIA_COMMON_DRIVER_QUEUE).
"""

import struct
from typing import Dict, Optional

MEDIA_COMMON_DRIVER_QUEUE = 0x00d9016e

MEDIA_TYPE_NONE = 0
MEDIA_TYPE_UNKNOWN = 1
MEDIA_TYPE_MS = 2     # MemoryStick
MEDIA_TYPE_SD = 3     # SD / SDHC / SDXC
MEDIA_TYPE_SSD = 4    # Internal flash / SSD


class GuestMediaCommon:
    """Services UIPC messages sent to MediaCommonDriver queue (0x00d9016e)."""

    def __init__(self, media_type: int = MEDIA_TYPE_SD):
        self.media_type = media_type
        self.transactions = []
        self.queries_serviced = 0

    def handle_message(self, memory_reader, memory_writer, msg_ptr: int, uipc) -> Optional[Dict[str, object]]:
        """Handles a UIPC message sent to 0x00d9016e.
        
        Request message layout (32 bytes):
          +0x00: uint32 category (2 = media status)
          +0x04: uint16 subcmd (1 = check inserted media)
          +0x06: uint16 payload_len (8)
          +0x08: uint32 reply_queue
          +0x0c: uint32 status
          +0x10: uint32 reserved1
          +0x14: uint32 reserved2
          +0x18: uint32 slot_id (0)
          +0x1c: uint32 reserved3
        """
        raw = memory_reader(msg_ptr, 32)
        category, subcmd_payload, reply_queue, status, r1, r2, slot_id, r3 = struct.unpack('<IIIIIIII', raw)
        subcmd = subcmd_payload & 0xffff
        payload_len = (subcmd_payload >> 16) & 0xffff

        record = {
            'type': 'media_common_request',
            'category': category,
            'subcmd': subcmd,
            'payload_len': payload_len,
            'reply_queue': reply_queue,
            'slot_id': slot_id,
        }

        if category == 2 and subcmd == 1:
            reply_size = 32
            reply_ptr = uipc.allocate_message(reply_size)
            reply_data = struct.pack(
                '<IIIIIIII',
                category,
                subcmd_payload,
                reply_queue,
                0,  # status = 0
                0,
                0,
                slot_id,
                self.media_type,
            )
            memory_writer(reply_ptr, reply_data)
            uipc.enqueue_message(reply_queue, reply_ptr)

            record['status'] = 'serviced'
            record['reply_ptr'] = reply_ptr
            record['media_type'] = self.media_type
            record['classification'] = 'authentic-mcmn CheckInsertedMedia SD presence reply'
            self.queries_serviced += 1
            self.transactions.append(record)
            return record

        record['status'] = 'unsupported_category_subcmd'
        self.transactions.append(record)
        return record
