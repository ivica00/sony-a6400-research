/* Host fixture for the UVC producer submission state machine. No camera access. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../native_camera/uvc_producer_submit.h"

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

static void init(struct a6400_uvc_producer_state *s)
{
    memset(s, 0, sizeof(*s));
    s->slots[0].ready = 1;
    s->slots[1].ready = 1;
}

static void fill(struct a6400_uvc_producer_frame *f, unsigned int slot,
                 const unsigned char *prefix, unsigned int prefix_len)
{
    memset(f, 0, sizeof(*f));
    f->frame_size = FRAME;
    f->phys_addr = 0x30000000u;
    f->slot = slot;
    f->prefix = prefix;
    f->prefix_len = prefix_len;
}

int main(void)
{
    unsigned char ok[64], bad[64];
    unsigned int ok_len = jpeg(ok, 1280, 720);
    unsigned int bad_len = jpeg(bad, 1024, 680);
    unsigned int dest[1] = {DEST};
    struct a6400_uvc_producer_state s;
    struct a6400_uvc_producer_frame f;
    unsigned int slot = 0, size = 0, phys = 0, gen = 0;

    { /* first submit is pending and consumes slot 0 */
        init(&s); fill(&f, 0, ok, ok_len);
        assert(a6400_uvc_producer_submit(&s, &f, SLOT_CAP, dest, DEST_SIZE, 1280, 720) == 0);
        assert(a6400_uvc_producer_get_pending(&s, &slot, &size, &phys, &gen) == 1);
        assert(slot == 0 && size == FRAME && phys == 0x30000000u && gen == 1);
        assert(s.slots[0].ready == 0 && s.slots[0].last_len == FRAME);
        assert(s.slots[1].ready == 1);
    }
    { /* one frame in flight only */
        fill(&f, 1, ok, ok_len);
        assert(a6400_uvc_producer_submit(&s, &f, SLOT_CAP, dest, DEST_SIZE, 1280, 720) < 0);
        assert(a6400_uvc_producer_get_pending(&s, &slot, &size, &phys, &gen) == 1);
        assert(slot == 0 && gen == 1);
    }
    { /* wrong-slot release is rejected */
        assert(a6400_uvc_producer_release(&s, 1) < 0);
        assert(a6400_uvc_producer_get_pending(&s, &slot, &size, &phys, &gen) == 1);
    }
    { /* correct release clears pending and frees the slot */
        assert(a6400_uvc_producer_release(&s, 0) == 0);
        assert(a6400_uvc_producer_get_pending(&s, &slot, &size, &phys, &gen) == 0);
        assert(slot == 0 && size == 0 && phys == 0 && gen == 0);
        assert(s.slots[0].ready == 1);
    }
    { /* next submit reuses the slot with a new generation */
        fill(&f, 0, ok, ok_len);
        assert(a6400_uvc_producer_submit(&s, &f, SLOT_CAP, dest, DEST_SIZE, 1280, 720) == 0);
        assert(a6400_uvc_producer_get_pending(&s, &slot, &size, &phys, &gen) == 1);
        assert(slot == 0 && gen == 2);
        assert(a6400_uvc_producer_release(&s, 0) == 0);
    }
    { /* slot 1 path */
        fill(&f, 1, ok, ok_len);
        assert(a6400_uvc_producer_submit(&s, &f, SLOT_CAP, dest, DEST_SIZE, 1280, 720) == 1);
        assert(a6400_uvc_producer_get_pending(&s, &slot, &size, &phys, &gen) == 1);
        assert(slot == 1 && gen == 3);
        assert(a6400_uvc_producer_release(&s, 1) == 0);
        assert(s.slots[1].ready == 1);
    }
    { /* rejected submit leaves pending and generation unchanged */
        fill(&f, 0, ok, ok_len);
        assert(a6400_uvc_producer_submit(&s, &f, SLOT_CAP, dest, DEST_SIZE, 1280, 720) == 0);
        assert(a6400_uvc_producer_release(&s, 0) == 0);
        s.slots[0].ready = 0;
        assert(a6400_uvc_producer_submit(&s, &f, SLOT_CAP, dest, DEST_SIZE, 1280, 720) < 0);
        assert(a6400_uvc_producer_get_pending(&s, &slot, &size, &phys, &gen) == 0);
        s.slots[0].ready = 1;
        fill(&f, 0, bad, bad_len);
        assert(a6400_uvc_producer_submit(&s, &f, SLOT_CAP, dest, DEST_SIZE, 1280, 720) < 0);
        assert(a6400_uvc_producer_get_pending(&s, &slot, &size, &phys, &gen) == 0);
    }
    { /* release without pending is rejected */
        assert(a6400_uvc_producer_release(&s, 0) < 0);
        assert(a6400_uvc_producer_release(&s, 1) < 0);
    }
    { /* invalid pointers and slots */
        assert(a6400_uvc_producer_submit(NULL, &f, SLOT_CAP, dest, DEST_SIZE, 1280, 720) < 0);
        assert(a6400_uvc_producer_submit(&s, NULL, SLOT_CAP, dest, DEST_SIZE, 1280, 720) < 0);
        assert(a6400_uvc_producer_release(NULL, 0) < 0);
        assert(a6400_uvc_producer_release(&s, 2) < 0);
        assert(a6400_uvc_producer_get_pending(NULL, &slot, &size, &phys, &gen) < 0);
        assert(a6400_uvc_producer_get_pending(&s, NULL, &size, &phys, &gen) < 0);
    }
    puts("Ten producer submission cases passed; host fixture, not a driver Update or DMA proof");
    return 0;
}
