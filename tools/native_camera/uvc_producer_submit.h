/* Bounded producer submission state machine: at most one admitted frame in
 * flight, explicit release after the driver confirms consumption. Pure state;
 * no mapping, I/O, DMA or busy-wait. */
#ifndef A6400_UVC_PRODUCER_SUBMIT_H
#define A6400_UVC_PRODUCER_SUBMIT_H

#include "uvc_producer_admission.h"

struct a6400_uvc_producer_pending {
    unsigned int active;
    unsigned int slot;
    unsigned int frame_size;
    unsigned int phys_addr;
    unsigned int generation;
};

struct a6400_uvc_producer_state {
    struct a6400_uvc_producer_pending pending;
    struct a6400_uvc_slot_state slots[2];
    unsigned int next_generation;
};

/* Admits one frame and records it as pending. Rejects when a frame is already
 * pending or admission fails; a rejection leaves the state unchanged. */
int a6400_uvc_producer_submit(struct a6400_uvc_producer_state *state,
                              const struct a6400_uvc_producer_frame *frame,
                              unsigned int slot_capacity,
                              const unsigned int *dest_phys, unsigned int dest_size,
                              unsigned int expected_width, unsigned int expected_height);

/* Clears the pending frame and marks that slot ready again. The caller asserts
 * that the driver Update/WAIT completed; this function does not wait itself. */
int a6400_uvc_producer_release(struct a6400_uvc_producer_state *state, unsigned int slot);

/* Returns 1 when a frame is pending (with its fields), 0 when idle, -1 on bad
 * arguments. Outputs are zeroed when idle. */
int a6400_uvc_producer_get_pending(const struct a6400_uvc_producer_state *state,
                                   unsigned int *slot, unsigned int *frame_size,
                                   unsigned int *phys_addr, unsigned int *generation);

#endif
