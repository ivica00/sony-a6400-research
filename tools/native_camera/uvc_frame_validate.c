/* Bounded JPEG SOF dimension parser. Offline building block for the UVC
 * producer's decoded-dimension validation; the source buffer is read by the
 * caller, never by this parser. */
#include "uvc_frame_validate.h"

static unsigned int be16(const unsigned char *p)
{
    return ((unsigned int)p[0] << 8) | (unsigned int)p[1];
}

static int is_sof(unsigned int marker)
{
    return (marker >= 0xc0 && marker <= 0xc3) ||
           (marker >= 0xc5 && marker <= 0xc7) ||
           (marker >= 0xc9 && marker <= 0xcb) ||
           (marker >= 0xcd && marker <= 0xcf);
}

int a6400_jpeg_sof_dimensions(const unsigned char *data, unsigned int len,
                              unsigned int *width, unsigned int *height)
{
    unsigned int i;
    if (!data || !width || !height || len < 4) return -1;
    if (data[0] != 0xff || data[1] != 0xd8) return -1;
    i = 2;
    while (i + 1 < len) {
        unsigned int marker, segment;
        if (data[i] != 0xff) { i++; continue; }
        while (i < len && data[i] == 0xff) i++;
        if (i >= len) return -1;
        marker = data[i++];
        if (marker == 0xd9 || marker == 0xda) return -1;
        if (i + 2 > len) return -1;
        segment = be16(data + i);
        if (segment < 2 || segment > len - i) return -1;
        if (is_sof(marker)) {
            unsigned int w, h;
            if (segment < 7) return -1;
            h = be16(data + i + 3);
            w = be16(data + i + 5);
            if (!w || !h) return -1;
            *width = w;
            *height = h;
            return 0;
        }
        i += segment;
    }
    return -1;
}
