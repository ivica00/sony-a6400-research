/* Producer admission contract. Offline building block for the bounded sensor
 * producer; it validates a caller-supplied frame and slot, and consumes a free
 * slot. The caller performs any mapping, DMA completion wait and Update call. */
#include "uvc_producer_admission.h"
#include "uvc_frame_validate.h"

static int overlaps(unsigned int source, unsigned int size,
                    unsigned int dest, unsigned int dest_size)
{
    return source < dest + dest_size && source + size > dest;
}

int a6400_uvc_producer_admit(const struct a6400_uvc_producer_frame *frame,
                             unsigned int slot_capacity,
                             const unsigned int *dest_phys, unsigned int dest_size,
                             struct a6400_uvc_slot_state slot_state[2],
                             unsigned int expected_width, unsigned int expected_height)
{
    unsigned int width = 0, height = 0;
    if (!frame || !dest_phys || !slot_state || !expected_width || !expected_height) return -1;
    if (frame->slot > 1 || !frame->frame_size || !frame->phys_addr) return -1;
    if (slot_capacity < A6400_UVC_HEADER_SIZE ||
        frame->frame_size > slot_capacity - A6400_UVC_HEADER_SIZE) return -1;
    if (frame->phys_addr > 0xffffffffu - frame->frame_size) return -1;
    if (!dest_size || dest_phys[0] > 0xffffffffu - dest_size) return -1;
    if (overlaps(frame->phys_addr, frame->frame_size, dest_phys[0], dest_size)) return -1;
    if (!slot_state[frame->slot].ready) return -1;
    if (!frame->prefix || frame->prefix_len < 2) return -1;
    if (a6400_jpeg_sof_dimensions(frame->prefix, frame->prefix_len, &width, &height)) return -1;
    if (width != expected_width || height != expected_height) return -1;
    slot_state[frame->slot].last_len = frame->frame_size;
    slot_state[frame->slot].ready = 0;
    return (int)frame->slot;
}
