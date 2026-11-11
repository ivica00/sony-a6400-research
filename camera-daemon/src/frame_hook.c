/* Bounded JPEG SOF parser and depth-1 producer admission for the a6400 daemon.
 *
 * Provenance of every rule:
 *   - SOF parsing: tools/native_camera/uvc_frame_validate.c (same marker walk,
 *     same big-endian height/width offsets) narrowed to SOF0/SOF2 because those
 *     are the two markers the contract names (a6400_frame.h:31-34).
 *   - Admission order and limits: tools/native_camera/uvc_producer_admission.c
 *     plus docs/analysis recon LIVEVIEW_DMA.md:676-697.
 *   - Depth-1 drop-on-busy: uvc_producer_submit.c (a second submit while a
 *     frame is in flight is rejected, never queued) and the latency policy of
 *     a6400_frame.h:16-19.
 *   - The 12-byte UVC header reserve: uvc_composite_shim.c:1046-1050.
 *
 * Pure functions: no I/O, no allocation, no clock, no DMA.
 */
#include "a6400_frame.h"

#include <string.h>

static uint32_t be16(const uint8_t *p)
{
    return ((uint32_t)p[0] << 8) | (uint32_t)p[1];
}

int a6400_jpeg_parse_dimensions(const uint8_t *prefix, uint32_t prefix_len,
                                struct a6400_jpeg_dims *out)
{
    uint32_t i;

    if (!prefix || !out || prefix_len < 4u)
        return -1;
    if (prefix[0] != 0xffu || prefix[1] != (uint8_t)A6400_JPEG_SOI)
        return -1;

    i = 2u;
    while (i + 1u < prefix_len) {
        uint32_t marker, segment;

        if (prefix[i] != 0xffu) {
            /* A stray byte between segments: fail closed rather than resync.
             * Compression data never appears before a SOF marker. */
            return -1;
        }
        while (i < prefix_len && prefix[i] == 0xffu)
            i++;
        if (i >= prefix_len)
            return -1;
        marker = prefix[i++];

        if (marker == 0xd9u || marker == 0xdau)
            return -1; /* EOI or SOS reached without a SOF header */
        if (marker == 0x01u || (marker >= 0xd0u && marker <= 0xd7u))
            continue; /* standalone markers carry no length */

        if (i + 2u > prefix_len)
            return -1;
        segment = be16(prefix + i);
        if (segment < 2u || segment > prefix_len - i)
            return -1; /* truncated or impossible segment */

        if (marker == (uint32_t)A6400_JPEG_SOF0 ||
            marker == (uint32_t)A6400_JPEG_SOF2) {
            uint32_t height, width;

            if (segment < 7u)
                return -1;
            height = be16(prefix + i + 3u);
            width = be16(prefix + i + 5u);
            if (!width || !height)
                return -1;
            out->width = width;
            out->height = height;
            return 0;
        }
        i += segment; /* skip APP0..APPn, DQT, DHT, COM and every other block */
    }
    return -1;
}

void a6400_frame_queue_init(struct a6400_frame_queue *q)
{
    if (!q)
        return;
    memset(q, 0, sizeof(*q));
    q->slot[0].ready = 1;
    q->slot[1].ready = 1;
}

/* Both ranges are already known not to wrap, so plain comparison is safe. */
static int range_overlaps(uint32_t a, uint32_t a_len,
                          uint32_t b, uint32_t b_len)
{
    return a < b + b_len && b < a + a_len;
}

int a6400_frame_admit(struct a6400_frame_queue *q,
                      const struct a6400_frame_candidate *cand,
                      const struct a6400_uvc_dma_meta *meta,
                      uint32_t expected_width, uint32_t expected_height)
{
    uint32_t frame_size, slot, dest0, dest1, usable_prefix;
    struct a6400_jpeg_dims dims;

    if (!q || !cand || !meta)
        return A6400_FRAME_ERR_ARG;

    /* 1. Depth-1: a frame in flight is dropped at the producer, never queued.
     *    This is a policy outcome, not a validation failure, so it counts as a
     *    drop rather than a reject. No slot state is touched. */
    if (q->pending) {
        q->dropped++;
        return A6400_FRAME_ERR_BUSY;
    }

    /* 2. Capacity. size_shift<<7 is the only length the original handler
     *    exposes (an upper bound within 127 bytes, E0144:21). A shift that
     *    would wrap is treated as an oversized frame, never truncated. */
    if (cand->size_shift > (0xffffffffu >> 7)) {
        q->rejected++;
        return A6400_FRAME_ERR_CAPACITY;
    }
    frame_size = cand->size_shift << 7;
    if (!frame_size || !meta->slot_size ||
        meta->slot_size < A6400_UVC_HEADER_SIZE) {
        q->rejected++;
        return A6400_FRAME_ERR_CAPACITY;
    }
    if (frame_size > meta->slot_size - A6400_UVC_HEADER_SIZE) {
        q->rejected++;
        return A6400_FRAME_ERR_CAPACITY;
    }

    /* 3. Zero / overflowing source physical address. */
    if (!cand->phys_addr || cand->phys_addr > 0xffffffffu - frame_size) {
        q->rejected++;
        return A6400_FRAME_ERR_ADDR;
    }

    /* 4. Destination window must itself be representable: two halves of
     *    slot_size starting at meta->phys_addr. */
    if (!meta->phys_addr ||
        meta->slot_size > (0xffffffffu - meta->phys_addr) / 2u) {
        q->rejected++;
        return A6400_FRAME_ERR_ADDR;
    }
    dest0 = meta->phys_addr;
    dest1 = meta->phys_addr + meta->slot_size;

    /* 5. The source must not alias either destination half. This is the fix
     *    for the E0143 aliasing bug where the driver's 12-byte header store
     *    destroyed the source SOI (LIVEVIEW_DMA.md:684-687). */
    if (range_overlaps(cand->phys_addr, frame_size, dest0, meta->slot_size) ||
        range_overlaps(cand->phys_addr, frame_size, dest1, meta->slot_size)) {
        q->rejected++;
        return A6400_FRAME_ERR_OVERLAP;
    }

    /* 6. Slot readiness. A slot becomes consumed only on admission. */
    if (q->slot[0].ready)
        slot = 0;
    else if (q->slot[1].ready)
        slot = 1;
    else {
        q->rejected++;
        return A6400_FRAME_ERR_NOT_READY;
    }

    /* 7. JPEG SOF dimensions. A prefix of fewer than two bytes cannot prove
     *    anything about the payload. It is only tolerated while the accepted
     *    geometry is still unknown (expected_width == expected_height == 0),
     *    i.e. the documented byte-free discovery admission; once geometry is
     *    known a missing prefix is a hard JPEG rejection. SOI is never
     *    fabricated here. */
    usable_prefix = (cand->prefix && cand->prefix_len >= 2u) ? cand->prefix_len : 0u;
    if (usable_prefix) {
        if (a6400_jpeg_parse_dimensions(cand->prefix, usable_prefix, &dims) != 0) {
            q->rejected++;
            return A6400_FRAME_ERR_JPEG;
        }
        if (expected_width && expected_height &&
            (dims.width != expected_width || dims.height != expected_height)) {
            q->rejected++;
            return A6400_FRAME_ERR_DIMENSION;
        }
    } else if (expected_width && expected_height) {
        q->rejected++;
        return A6400_FRAME_ERR_JPEG;
    }

    /* 8. The upper-bound length must fit the mapped DMM unit. */
    if (!cand->mapped_size || frame_size > cand->mapped_size) {
        q->rejected++;
        return A6400_FRAME_ERR_SIZE;
    }

    q->slot[slot].ready = 0;
    q->slot[slot].last_len = frame_size; /* upper bound, documented */
    q->pending = 1;
    q->pending_slot = slot;
    q->generation++;
    return (int)slot;
}

void a6400_frame_release(struct a6400_frame_queue *q, uint32_t slot)
{
    if (!q || slot > 1u)
        return;
    q->slot[slot].ready = 1;
    if (q->pending && q->pending_slot == slot)
        q->pending = 0;
}

void a6400_frame_abort(struct a6400_frame_queue *q)
{
    if (!q)
        return;
    /* The UPDATE path failed after admission: drop the in-flight marker but
     * leave slot readiness to the explicit release that follows. */
    q->pending = 0;
}
