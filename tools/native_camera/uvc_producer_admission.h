/* Producer admission contract for the shared UVC path. Pure validation and
 * slot bookkeeping; the caller owns mapping, DMA and the driver Update call.
 * No allocation, I/O, busy-wait or hardware access. */
#ifndef A6400_UVC_PRODUCER_ADMISSION_H
#define A6400_UVC_PRODUCER_ADMISSION_H

#define A6400_UVC_HEADER_SIZE 12u

/* ready: 1 when the driver has released the destination slot for reuse.
 * last_len: payload length of the last admitted frame (diagnostic). */
struct a6400_uvc_slot_state {
    unsigned int ready;
    unsigned int last_len;
};

/* slot: 0 or 1 destination half. prefix/prefix_len: caller-read bounded JPEG
 * prefix (SOI..SOF header is enough); never dereferenced beyond prefix_len. */
struct a6400_uvc_producer_frame {
    unsigned int frame_size;
    unsigned int phys_addr;
    unsigned int slot;
    const unsigned char *prefix;
    unsigned int prefix_len;
};

/* Returns the admitted slot index (0/1) and consumes it (ready=0, last_len set)
 * on success, or -1 without touching slot state. Rejects: bad pointers, slot>1,
 * zero size/address, slot capacity overflow/wrap, source/destination overlap,
 * a slot that is not ready, malformed/truncated JPEG and dimension mismatch. */
int a6400_uvc_producer_admit(const struct a6400_uvc_producer_frame *frame,
                             unsigned int slot_capacity,
                             const unsigned int *dest_phys, unsigned int dest_size,
                             struct a6400_uvc_slot_state slot_state[2],
                             unsigned int expected_width, unsigned int expected_height);

#endif
