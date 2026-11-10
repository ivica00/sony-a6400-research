/* Host fixture for the UVC producer admission contract. No camera access. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../native_camera/uvc_producer_admission.h"

#define DEST 0x20000000u
#define DEST_SIZE 0x40000u
#define SLOT_CAP 0x20000u
#define FRAME 0x1000u

static unsigned int jpeg(unsigned char *b, unsigned int w, unsigned int h)
{
    unsigned int n = 0;
    b[n++] = 0xff; b[n++] = 0xd8;
    b[n++] = 0xff; b[n++] = 0xc0;
    b[n++] = 0x00; b[n++] = 0x11;
    b[n++] = 0x08;
    b[n++] = (unsigned char)(h >> 8); b[n++] = (unsigned char)h;
    b[n++] = (unsigned char)(w >> 8); b[n++] = (unsigned char)w;
    for (int i = 0; i < 9; i++) b[n++] = 0x22;
    b[n++] = 0xff; b[n++] = 0xd9;
    return n;
}

static void reset(struct a6400_uvc_slot_state *s)
{
    s[0].ready = 1; s[0].last_len = 0;
    s[1].ready = 1; s[1].last_len = 0;
}

int main(void)
{
    unsigned char ok[64], bad[64];
    unsigned int ok_len = jpeg(ok, 1280, 720);
    unsigned int bad_len = jpeg(bad, 1024, 680);
    unsigned int dest[1] = {DEST};
    struct a6400_uvc_slot_state slots[2];
    struct a6400_uvc_producer_frame f;

    memset(&f, 0, sizeof(f));
    f.frame_size = FRAME; f.phys_addr = 0x30000000u; f.prefix = ok; f.prefix_len = ok_len;

    { /* valid slot 0 consumes only slot 0 */
        reset(slots);
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) == 0);
        assert(slots[0].ready == 0 && slots[0].last_len == FRAME);
        assert(slots[1].ready == 1 && slots[1].last_len == 0);
    }
    { /* valid slot 1 */
        reset(slots); f.slot = 1;
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) == 1);
        assert(slots[1].ready == 0 && slots[0].ready == 1);
    }
    { /* maximum payload for the slot */
        reset(slots); f.slot = 0; f.frame_size = SLOT_CAP - A6400_UVC_HEADER_SIZE;
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) == 0);
    }
    { /* one byte over capacity */
        reset(slots); f.frame_size = SLOT_CAP - A6400_UVC_HEADER_SIZE + 1;
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) < 0);
        assert(slots[0].ready == 1 && slots[0].last_len == 0);
    }
    { /* slot not ready is rejected without state change */
        reset(slots); slots[0].ready = 0; slots[0].last_len = 77; f.slot = 0; f.frame_size = FRAME;
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) < 0);
        assert(slots[0].ready == 0 && slots[0].last_len == 77);
    }
    { /* invalid slot, zero size, zero address */
        reset(slots); f.slot = 2; assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) < 0);
        f.slot = 0; f.frame_size = 0; assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) < 0);
        f.frame_size = FRAME; f.phys_addr = 0; assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) < 0);
    }
    { /* 32-bit source wrap */
        reset(slots); f.phys_addr = 0xfffffff0u; f.frame_size = 0x20;
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) < 0);
    }
    { /* source alias from below, inside and above */
        reset(slots); f.phys_addr = 0x1ffff000u; f.frame_size = 0x2000;
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) < 0);
        f.phys_addr = 0x20010000u; f.frame_size = 0x1000;
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) < 0);
        f.phys_addr = 0x2003f000u; f.frame_size = 0x2000;
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) < 0);
    }
    { /* disjoint neighbours are allowed */
        reset(slots); f.phys_addr = 0x1ffff000u; f.frame_size = 0x1000;
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) == 0);
        reset(slots); f.phys_addr = 0x20040000u; f.frame_size = FRAME;
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) == 0);
    }
    { /* destination window wrap is rejected */
        unsigned int wrapped[1] = {0xffffff00u};
        reset(slots);
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, wrapped, 0x200, slots, 1280, 720) < 0);
    }
    { /* malformed or mismatched JPEG prefixes */
        reset(slots);
        f.prefix = ok; f.prefix_len = 1;
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) < 0);
        f.prefix = NULL;
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) < 0);
        f.prefix = bad; f.prefix_len = bad_len;
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) < 0);
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1024, 680) == 0);
        unsigned char no_soi[8] = {0, 0, 0xff, 0xc0, 0, 0x11, 0x08, 0};
        reset(slots); f.prefix = no_soi; f.prefix_len = sizeof(no_soi);
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 720) < 0);
    }
    { /* zero expected dimensions */
        reset(slots); f.prefix = ok; f.prefix_len = ok_len;
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 0, 720) < 0);
        assert(a6400_uvc_producer_admit(&f, SLOT_CAP, dest, DEST_SIZE, slots, 1280, 0) < 0);
    }
    puts("Sixteen producer admission cases passed; host fixture, not a sensor frame or DMA proof");
    return 0;
}
