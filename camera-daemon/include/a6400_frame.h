/* a6400 frame contract: a candidate liveview frame, its validation rules and
 * the depth-1 producer queue that feeds the UVC transport.
 *
 * Every validation rule here is transcribed from existing, physically run
 * code or from the decode of the original handlers:
 *   - SOF dimension parsing: tools/native_camera/uvc_frame_validate.h:7-10
 *   - capacity/wrap/overlap/ready checks: tools/native_camera/uvc_producer_admission.c
 *     (returns the admitted slot; -1 without touching slot state)
 *   - depth-1 one-frame-in-flight semantics: tools/native_camera/uvc_producer_submit.c
 *     (a second submit is rejected while a frame is in flight - drop, never queue)
 *   - source ownership: docs/evidence/0144-native-jpeg-receiver-ownership-and-dma-allocation.md:19-23
 *   - UVC writes a 12-byte header before the payload; slot_capacity excludes it:
 *     tools/native_camera/uvc_composite_shim.c:1046-1050,
 *     tools/native_camera/uvc_producer_admission.h:7
 *
 * Latency policy: queue depth is exactly 1. When a frame is still in flight the
 * new frame is DROPPED at the producer, not buffered. Buffering converts
 * transport stalls into growing latency, which is the failure mode the mission
 * forbids.
 */
#ifndef A6400_FRAME_H
#define A6400_FRAME_H

#include <stdint.h>
#include <stddef.h>

#include "a6400_uvc.h"

#define A6400_UVC_HEADER_SIZE 12u

/* JPEG SOI and SOF markers used by the bounded dimension parser. */
#define A6400_JPEG_SOI 0xd8u
#define A6400_JPEG_SOF0 0xc0u
#define A6400_JPEG_SOF2 0xc2u

/* One candidate frame produced by the GET_JPEG path.
 *
 * Ownership: on successful admission the transport takes over the two DMM
 * handles and must close+free them after the UPDATE/WAIT cycle. On rejection
 * the producer keeps ownership and must free them itself.
 */
struct a6400_frame_candidate {
    uint32_t handle1;        /* first DMM unit from the GET_JPEG reply */
    uint32_t handle2;        /* second DMM unit (0 or 0xffff = absent) */
    uint32_t phys_addr;      /* DMM OpenUnit reply physical address */
    uint32_t mapped_size;    /* DMM OpenUnit reply mapped size */
    uint32_t size_shift;     /* reply size_shift; real size = upper bound - <=127 */
    uint32_t frame_seq;      /* monotonic producer counter, host-visible */
    int64_t  capture_ns;     /* CLOCK_MONOTONIC at GET_JPEG completion */
    const uint8_t *prefix;   /* caller-owned first bytes, at least 4 for SOI/SOF */
    uint32_t prefix_len;     /* bounded by the admission gate; >= 2 required */
};

/* Result of parsing a bounded JPEG prefix. On success width/height are the
 * SOF dimensions; on failure they are left untouched. */
struct a6400_jpeg_dims {
    uint32_t width;
    uint32_t height;
};

/* Bounded prefix parser: never reads past prefix_len; returns 0 when a valid
 * SOF0/SOF2 frame header with non-zero dimensions was found, else -1. */
int a6400_jpeg_parse_dimensions(const uint8_t *prefix, uint32_t prefix_len,
                                struct a6400_jpeg_dims *out);

/* Depth-1 producer queue state. Both destination halves start ready. */
struct a6400_uvc_slot_state {
    uint32_t ready;
    uint32_t last_len;
};

struct a6400_frame_queue {
    struct a6400_uvc_slot_state slot[2];
    uint32_t pending;        /* 0/1: a frame is in flight */
    uint32_t pending_slot;
    uint32_t generation;
    uint32_t dropped;        /* frames dropped because pending was set */
    uint32_t rejected;       /* frames rejected by validation */
};

void a6400_frame_queue_init(struct a6400_frame_queue *q);

/* Validates a candidate and consumes a slot when it is admitted.
 * Returns the slot index (0/1) on success, or a negative A6400_FRAME_ERR_*.
 * On any error the queue is left untouched.
 *
 * `meta` is the destination window from A6400_UVC_IOCTL_MOD_QUERY_DMA. When it
 * is unavailable (stock driver returns ENOTTY) the caller must supply the
 * window it actually registered with REG_BUF; both go through the same checks.
 */
int a6400_frame_admit(struct a6400_frame_queue *q,
                      const struct a6400_frame_candidate *cand,
                      const struct a6400_uvc_dma_meta *meta,
                      uint32_t expected_width, uint32_t expected_height);

/* Marks the given slot ready again; called after the driver completed the
 * read (WAIT) and the transport released the frame. Never blocks. */
void a6400_frame_release(struct a6400_frame_queue *q, uint32_t slot);

/* Drops the in-flight marker without touching slot readiness. Used when the
 * UPDATE path failed after admission; the slot is then explicitly released. */
void a6400_frame_abort(struct a6400_frame_queue *q);

/* ---- error codes --------------------------------------------------------- */

#define A6400_FRAME_ERR_ARG        (-1)
#define A6400_FRAME_ERR_BUSY       (-2)   /* one frame already in flight */
#define A6400_FRAME_ERR_CAPACITY   (-3)   /* frame_size + 12 > slot capacity */
#define A6400_FRAME_ERR_ADDR       (-4)   /* zero/overflowing physical address */
#define A6400_FRAME_ERR_OVERLAP    (-5)   /* source inside either destination */
#define A6400_FRAME_ERR_NOT_READY  (-6)   /* slot is not ready */
#define A6400_FRAME_ERR_JPEG       (-7)   /* SOF missing/short prefix */
#define A6400_FRAME_ERR_DIMENSION  (-8)   /* SOF dims differ from expected */
#define A6400_FRAME_ERR_SIZE       (-9)   /* frame size exceeds mapped size */

#endif /* A6400_FRAME_H */
