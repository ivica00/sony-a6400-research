// COMPILE-ONLY HOST STUB -- NOT libjpeg-turbo.
// It only understands the synthetic SOF markers produced by tests/host_main.cpp.
#include <turbojpeg.h>

#include <cstdint>
#include <cstring>

namespace {

uint16_t be16(const unsigned char* p)
{
    return static_cast<uint16_t>((static_cast<uint16_t>(p[0]) << 8) | p[1]);
}

bool readSof(const unsigned char* data, unsigned long size, int* width, int* height)
{
    if (data == nullptr || size < 4 || data[0] != 0xFF || data[1] != 0xD8) {
        return false;
    }
    unsigned long pos = 2;
    while (pos + 1 < size) {
        if (data[pos] != 0xFF) {
            return false;
        }
        while (pos < size && data[pos] == 0xFF) {
            ++pos;
        }
        if (pos >= size) {
            return false;
        }
        const unsigned char marker = data[pos++];
        if (marker == 0xD9 || marker == 0xDA) {
            return false;
        }
        if ((marker >= 0xD0 && marker <= 0xD7) || marker == 0x01) {
            continue;
        }
        if (pos + 2 > size) {
            return false;
        }
        const uint16_t len = be16(data + pos);
        if (len < 2 || pos + len > size) {
            return false;
        }
        if (marker == 0xC0 || marker == 0xC1 || marker == 0xC2) {
            if (len < 8) {
                return false;
            }
            *height = be16(data + pos + 3);
            *width = be16(data + pos + 5);
            return *width > 0 && *height > 0;
        }
        pos += len;
    }
    return false;
}

}  // namespace

extern "C" {

tjhandle tjInitDecompress(void)
{
    return reinterpret_cast<tjhandle>(static_cast<uintptr_t>(1));
}

int tjDestroy(tjhandle)
{
    return 0;
}

int tjDecompressHeader3(tjhandle, const unsigned char* jpegBuf,
                        unsigned long jpegSize, int* width, int* height,
                        int* jpegSubsamp, int* jpegColorspace)
{
    if (width == nullptr || height == nullptr || jpegSubsamp == nullptr ||
        jpegColorspace == nullptr) {
        return -1;
    }
    if (!readSof(jpegBuf, jpegSize, width, height)) {
        return -1;
    }
    *jpegSubsamp = 0;   // 4:4:4
    *jpegColorspace = 0; // unknown/gray/RGB family
    return 0;
}

int tjDecompress2(tjhandle, const unsigned char* jpegBuf, unsigned long jpegSize,
                  unsigned char* dstBuf, int width, int pitch, int height,
                  int pixelFormat, int)
{
    int sourceWidth = 0;
    int sourceHeight = 0;
    int subsamp = 0;
    int colorspace = 0;
    if (dstBuf == nullptr || pixelFormat != TJPF_RGBA ||
        tjDecompressHeader3(nullptr, jpegBuf, jpegSize, &sourceWidth, &sourceHeight,
                            &subsamp, &colorspace) != 0) {
        return -1;
    }
    (void)subsamp;
    (void)colorspace;
    if (sourceWidth != width || sourceHeight != height || pitch < width * 4) {
        return -1;
    }
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            unsigned char* p = dstBuf + static_cast<size_t>(y) * static_cast<size_t>(pitch)
                             + static_cast<size_t>(x) * 4u;
            p[0] = static_cast<unsigned char>((x * 17 + y * 31) & 0xFF);
            p[1] = static_cast<unsigned char>((x * 7 + y * 13) & 0xFF);
            p[2] = static_cast<unsigned char>((x * 3 + y * 5) & 0xFF);
            p[3] = 0xFF;
        }
    }
    return 0;
}

char* tjGetErrorStr2(tjhandle)
{
    return const_cast<char*>("host turbojpeg stub");
}

int tjGetErrorCode(tjhandle)
{
    return 2;  // TJERR_FATAL
}

}  // extern "C"
