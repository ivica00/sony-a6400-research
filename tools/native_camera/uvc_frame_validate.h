/* Bounded JPEG SOF dimension parser for the UVC frame contract.
 * Pure functions: no allocation, no I/O, no DMA, no state. */
#ifndef A6400_UVC_FRAME_VALIDATE_H
#define A6400_UVC_FRAME_VALIDATE_H

/* Reads width/height from the first SOF marker (SOF0-SOF3, SOF5-SOF7,
 * SOF9-SOF11, SOF13-SOF15). Returns 0 on success, -1 on any malformed,
 * truncated or zero-dimension input. Never reads past len bytes. */
int a6400_jpeg_sof_dimensions(const unsigned char *data, unsigned int len,
                              unsigned int *width, unsigned int *height);

#endif
