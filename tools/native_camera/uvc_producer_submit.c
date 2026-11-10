/* Bounded producer submission state machine. Offline building block for the
 * proposed producer ioctl; it never calls the driver Update. */
#include "uvc_producer_submit.h"

int a6400_uvc_producer_submit(struct a6400_uvc_producer_state *state,
                              const struct a6400_uvc_producer_frame *frame,
                              unsigned int slot_capacity,
                              const unsigned int *dest_phys, unsigned int dest_size,
                              unsigned int expected_width, unsigned int expected_height)
{
    int slot;
    if (!state || !frame || !dest_phys) return -1;
    if (state->pending.active) return -1;
    slot = a6400_uvc_producer_admit(frame, slot_capacity, dest_phys, dest_size,
                                    state->slots, expected_width, expected_height);
    if (slot < 0) return -1;
    state->pending.active = 1;
    state->pending.slot = (unsigned int)slot;
    state->pending.frame_size = frame->frame_size;
    state->pending.phys_addr = frame->phys_addr;
    state->pending.generation = ++state->next_generation;
    return slot;
}

int a6400_uvc_producer_release(struct a6400_uvc_producer_state *state, unsigned int slot)
{
    if (!state || slot > 1) return -1;
    if (!state->pending.active || state->pending.slot != slot) return -1;
    state->pending.active = 0;
    state->pending.slot = 0;
    state->pending.frame_size = 0;
    state->pending.phys_addr = 0;
    state->slots[slot].ready = 1;
    return 0;
}

int a6400_uvc_producer_get_pending(const struct a6400_uvc_producer_state *state,
                                   unsigned int *slot, unsigned int *frame_size,
                                   unsigned int *phys_addr, unsigned int *generation)
{
    if (!state || !slot || !frame_size || !phys_addr || !generation) return -1;
    *slot = 0; *frame_size = 0; *phys_addr = 0; *generation = 0;
    if (!state->pending.active) return 0;
    *slot = state->pending.slot;
    *frame_size = state->pending.frame_size;
    *phys_addr = state->pending.phys_addr;
    *generation = state->pending.generation;
    return 1;
}
