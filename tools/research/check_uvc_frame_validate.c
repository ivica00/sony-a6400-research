/* Host fixture for the bounded JPEG SOF parser. No camera access. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../native_camera/uvc_frame_validate.h"

static unsigned int build(unsigned char *b, unsigned int w, unsigned int h, unsigned int sof, int app0, int extra_fill)
{
    unsigned int n = 0;
    b[n++] = 0xff; b[n++] = 0xd8;
    if (app0) {
        b[n++] = 0xff; b[n++] = 0xe0; b[n++] = 0x00; b[n++] = 0x10;
        for (int i = 0; i < 14; i++) b[n++] = 0x11;
    }
    for (int i = 0; i < extra_fill; i++) b[n++] = 0xff;
    b[n++] = 0xff; b[n++] = (unsigned char)sof;
    b[n++] = 0x00; b[n++] = 0x11;
    b[n++] = 0x08;
    b[n++] = (unsigned char)(h >> 8); b[n++] = (unsigned char)h;
    b[n++] = (unsigned char)(w >> 8); b[n++] = (unsigned char)w;
    for (int i = 0; i < 9; i++) b[n++] = 0x22;
    b[n++] = 0xff; b[n++] = 0xd9;
    return n;
}

static int accept(const unsigned char *b, unsigned int n, unsigned int w, unsigned int h)
{
    unsigned int aw = 0, ah = 0;
    if (a6400_jpeg_sof_dimensions(b, n, &aw, &ah)) return 0;
    return aw == w && ah == h;
}

static int reject(const unsigned char *b, unsigned int n)
{
    unsigned int w = 0, h = 0;
    return a6400_jpeg_sof_dimensions(b, n, &w, &h) < 0;
}

int main(void)
{
    unsigned char b[256];
    unsigned int n, w, h;

    n = build(b, 1280, 720, 0xc0, 1, 0); assert(accept(b, n, 1280, 720));
    n = build(b, 1024, 680, 0xc2, 1, 0); assert(accept(b, n, 1024, 680));
    n = build(b, 640, 480, 0xc1, 0, 0); assert(accept(b, n, 640, 480));
    n = build(b, 1920, 1080, 0xc0, 1, 3); assert(accept(b, n, 1920, 1080));

    { /* zero width */
        n = build(b, 0, 720, 0xc0, 1, 0); assert(reject(b, n));
    }
    { /* zero height */
        n = build(b, 1280, 0, 0xc0, 1, 0); assert(reject(b, n));
    }
    { /* no SOI */
        n = build(b, 1280, 720, 0xc0, 1, 0); b[0] = 0x00; assert(reject(b, n));
    }
    { /* EOI before SOF */
        const unsigned char eoi[] = {0xff, 0xd8, 0xff, 0xd9};
        assert(reject(eoi, sizeof(eoi)));
    }
    { /* SOS before SOF */
        const unsigned char sos[] = {0xff, 0xd8, 0xff, 0xda, 0x00, 0x02};
        assert(reject(sos, sizeof(sos)));
    }
    { /* truncated SOF segment */
        n = build(b, 1280, 720, 0xc0, 1, 0); assert(reject(b, n - 12));
    }
    { /* segment length below the SOF header size */
        unsigned char s[] = {0xff, 0xd8, 0xff, 0xc0, 0x00, 0x06, 0x08, 0x02, 0xd0, 0x05, 0x00};
        assert(reject(s, sizeof(s)));
    }
    { /* segment length one */
        unsigned char s[] = {0xff, 0xd8, 0xff, 0xe0, 0x00, 0x01, 0x00};
        assert(reject(s, sizeof(s)));
    }
    { /* length 0xffff overflow */
        unsigned char s[] = {0xff, 0xd8, 0xff, 0xe0, 0xff, 0xff, 0x00, 0x00};
        assert(reject(s, sizeof(s)));
    }
    { /* empty and null inputs */
        assert(a6400_jpeg_sof_dimensions(NULL, 0, &w, &h) < 0);
        assert(reject(b, 0));
        n = build(b, 1280, 720, 0xc0, 1, 0);
        assert(a6400_jpeg_sof_dimensions(b, n, NULL, &h) < 0);
        assert(a6400_jpeg_sof_dimensions(b, n, &w, NULL) < 0);
    }
    { /* single trailing 0xff without a marker */
        unsigned char s[] = {0xff, 0xd8, 0xff};
        assert(reject(s, sizeof(s)));
    }
    puts("Fifteen JPEG SOF dimension cases passed; host fixture, not a decoded image or sensor frame");
    return 0;
}
