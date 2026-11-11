#include "jpeg_decoder.h"

#include "log.h"

#include <chrono>
#include <cstring>
#include <turbojpeg.h>

namespace a6400 {
namespace {

void setError(std::string* error, const char* message)
{
    if (error != nullptr) {
        *error = message;
    }
}

bool isSofMarker(uint8_t marker)
{
    switch (marker) {
        case 0xC0: case 0xC1: case 0xC2: case 0xC3:
        case 0xC5: case 0xC6: case 0xC7:
        case 0xC9: case 0xCA: case 0xCB:
        case 0xCD: case 0xCE: case 0xCF:
            return true;
        default:
            return false;
    }
}

uint16_t readBe16(const uint8_t* p)
{
    return static_cast<uint16_t>((static_cast<uint16_t>(p[0]) << 8) | p[1]);
}

const char* tjErrorText(tjhandle handle)
{
    char* text = tjGetErrorStr2(handle);
    return text != nullptr ? text : "libjpeg-turbo error";
}

// The camera's frames are 52-141 KB.  This cap is far above any observed
// frame, keeps the size conversion to unsigned long safe on every ABI, and
// bounds the damage from a hostile/desynchronised JPEG.
constexpr size_t kMaxJpegBytes = 16u * 1024u * 1024u;

}  // namespace

struct JpegDecoder::Impl {
    tjhandle handle = nullptr;
    bool ready = false;
};

JpegDecoder::JpegDecoder() : impl_(new Impl()) {}

JpegDecoder::~JpegDecoder()
{
    if (impl_ && impl_->handle != nullptr) {
        tjDestroy(impl_->handle);
        impl_->handle = nullptr;
    }
}

bool JpegDecoder::ready() const
{
    return impl_ && impl_->ready;
}

bool JpegDecoder::init(std::string* error)
{
    if (!impl_) {
        setError(error, "decoder allocation failed");
        return false;
    }
    if (impl_->ready) {
        return true;
    }
    impl_->handle = tjInitDecompress();
    if (impl_->handle == nullptr) {
        setError(error, "tjInitDecompress failed");
        return false;
    }
    impl_->ready = true;
    return true;
}

bool JpegDecoder::validateJpegStructure(const uint8_t* jpeg, size_t length,
                                        JpegFrameInfo* info, std::string* error)
{
    if (info != nullptr) {
        *info = JpegFrameInfo{};
    }
    if (jpeg == nullptr || length < 4) {
        setError(error, "JPEG shorter than SOI + EOI");
        return false;
    }
    if (jpeg[0] != 0xFF || jpeg[1] != 0xD8) {
        setError(error, "missing JPEG SOI (FF D8)");
        return false;
    }

    bool haveSof = false;
    bool haveSos = false;
    JpegFrameInfo parsed{};

    size_t pos = 2;
    while (pos < length) {
        if (jpeg[pos] != 0xFF) {
            setError(error, "expected JPEG marker prefix outside entropy data");
            return false;
        }
        // JPEG permits any number of 0xFF fill bytes before a marker code.
        while (pos < length && jpeg[pos] == 0xFF) {
            ++pos;
        }
        if (pos >= length) {
            setError(error, "truncated JPEG marker");
            return false;
        }
        const uint8_t marker = jpeg[pos++];

        if (marker == 0xD9) {  // EOI
            if (pos != length) {
                setError(error, "bytes after JPEG EOI");
                return false;
            }
            if (!haveSof || !haveSos) {
                setError(error, "JPEG has no SOF or no SOS before EOI");
                return false;
            }
            if (info != nullptr) {
                *info = parsed;
            }
            return true;
        }
        if (marker == 0x00) {
            setError(error, "unexpected stuffed zero outside entropy data");
            return false;
        }
        if ((marker >= 0xD0 && marker <= 0xD7) || marker == 0x01) {
            continue;  // RSTn / TEM are stand-alone
        }
        if (marker == 0xDA) {  // SOS: entropy data follows; EOI must be final
            if (pos + 2 > length) {
                setError(error, "truncated SOS length");
                return false;
            }
            const uint16_t segmentLength = readBe16(jpeg + pos);
            if (segmentLength < 2 || pos + segmentLength > length) {
                setError(error, "SOS segment out of bounds");
                return false;
            }
            haveSos = true;
            if (length < 2 || jpeg[length - 2] != 0xFF || jpeg[length - 1] != 0xD9) {
                setError(error, "JPEG has no final EOI after SOS");
                return false;
            }
            if (!haveSof) {
                setError(error, "JPEG SOS before SOF");
                return false;
            }
            if (info != nullptr) {
                *info = parsed;
            }
            return true;
        }

        if (pos + 2 > length) {
            setError(error, "truncated JPEG segment length");
            return false;
        }
        const uint16_t segmentLength = readBe16(jpeg + pos);
        if (segmentLength < 2 || pos + segmentLength > length) {
            setError(error, "JPEG segment length exceeds input");
            return false;
        }

        if (isSofMarker(marker)) {
            if (haveSof) {
                setError(error, "multiple JPEG SOF markers");
                return false;
            }
            if (segmentLength < 8 || pos + 8 > length) {
                setError(error, "truncated SOF header");
                return false;
            }
            const int precision = jpeg[pos + 2];
            const int height = readBe16(jpeg + pos + 3);
            const int width = readBe16(jpeg + pos + 5);
            const int components = jpeg[pos + 7];
            if (precision != 8) {
                setError(error, "JPEG SOF precision is not 8 bits");
                return false;
            }
            if (width <= 0 || height <= 0) {
                setError(error, "JPEG SOF has zero dimension");
                return false;
            }
            if (components != 1 && components != 3) {
                setError(error, "JPEG SOF component count is neither 1 nor 3");
                return false;
            }
            if (segmentLength < 8 + 3 * components) {
                setError(error, "JPEG SOF component table is truncated");
                return false;
            }
            parsed.width = width;
            parsed.height = height;
            parsed.components = components;
            parsed.precision = precision;
            parsed.subsampling = -1;
            parsed.colorspace = 0;
            haveSof = true;
        }

        pos += segmentLength;
    }

    setError(error, "JPEG ended without EOI");
    return false;
}

int JpegDecoder::decode(const uint8_t* jpeg, size_t length,
                        uint8_t* dst, int dstStride,
                        int maxWidth, int maxHeight,
                        JpegFrameInfo* info, uint64_t* decodeUs,
                        std::string* error)
{
    if (decodeUs != nullptr) {
        *decodeUs = 0;
    }
    if (info != nullptr) {
        *info = JpegFrameInfo{};
    }
    if (!impl_ || !impl_->ready || impl_->handle == nullptr) {
        setError(error, "decoder is not initialised");
        return kErrJpegDecode;
    }
    if (jpeg == nullptr || dst == nullptr || length == 0) {
        setError(error, "null JPEG/destination or zero length");
        return kErrInvalidArgument;
    }
    if (length > kMaxJpegBytes) {
        setError(error, "JPEG length exceeds the 16 MiB safety cap");
        return kErrInvalidArgument;
    }
    if (maxWidth <= 0 || maxHeight <= 0 || dstStride <= 0) {
        setError(error, "invalid destination bounds");
        return kErrInvalidArgument;
    }

    JpegFrameInfo parsed{};
    if (!validateJpegStructure(jpeg, length, &parsed, error)) {
        return kErrJpegInvalid;
    }
    if (parsed.width > maxWidth || parsed.height > maxHeight) {
        setError(error, "JPEG dimensions exceed destination allocation");
        if (info != nullptr) {
            *info = parsed;
        }
        return kErrJpegDimensions;
    }
    if (static_cast<int64_t>(parsed.width) * 4 > dstStride) {
        setError(error, "destination stride is too small for RGBA row");
        return kErrInvalidArgument;
    }

    int jpegWidth = 0;
    int jpegHeight = 0;
    int jpegSubsampling = 0;
    int jpegColorspace = 0;
    if (tjDecompressHeader3(impl_->handle,
                            jpeg, static_cast<unsigned long>(length),
                            &jpegWidth, &jpegHeight,
                            &jpegSubsampling, &jpegColorspace) != 0) {
        setError(error, tjErrorText(impl_->handle));
        return kErrJpegInvalid;
    }
    if (jpegWidth != parsed.width || jpegHeight != parsed.height) {
        setError(error, "SOF dimensions disagree with libjpeg-turbo header");
        return kErrJpegInvalid;
    }
    if (jpegWidth > maxWidth || jpegHeight > maxHeight) {
        setError(error, "libjpeg-turbo dimensions exceed allocation");
        return kErrJpegDimensions;
    }

    const auto begin = std::chrono::steady_clock::now();
    const int rc = tjDecompress2(impl_->handle,
                                 jpeg, static_cast<unsigned long>(length),
                                 dst, jpegWidth, dstStride, jpegHeight,
                                 TJPF_RGBA, TJFLAG_FASTDCT);
    const auto end = std::chrono::steady_clock::now();

    if (rc != 0) {
        setError(error, tjErrorText(impl_->handle));
        return kErrJpegDecode;
    }

    parsed.subsampling = jpegSubsampling;
    parsed.colorspace = jpegColorspace;
    if (info != nullptr) {
        *info = parsed;
    }
    if (decodeUs != nullptr) {
        *decodeUs = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::microseconds>(end - begin).count());
    }
    return kOk;
}

}  // namespace a6400
