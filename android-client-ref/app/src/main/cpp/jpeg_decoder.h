#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>

namespace a6400 {

// Failure codes used by this class and by Pipeline/JNI.  Keep the numeric
// values stable: Kotlin logs them and the host tests assert them.
enum JpegError : int {
    kOk = 0,
    kErrInvalidHandle = -1,
    kErrInvalidArgument = -2,
    kErrJpegInvalid = -3,
    kErrJpegDimensions = -4,
    kErrJpegDecode = -5,
    kErrNoSlot = -6,
    kErrOutOfMemory = -7,
    kErrNoGlContext = -8,
    kErrGl = -9,
    kErrNotConfigured = -10,
    kErrUnsupported = -11,
    kErrBusy = -12,
    kErrAhb = -13,
    kErrInternal = -14
};

struct JpegFrameInfo {
    int width = 0;
    int height = 0;
    int components = 0;
    int precision = 0;
    int subsampling = 0;  // libjpeg-turbo TJSAMP_* value, -1 when unknown
    int colorspace = 0;   // libjpeg-turbo TJCS_* value, 0 when unknown
};

// A reusable libjpeg-turbo decompressor.  One instance must not be used from
// two threads at once; Pipeline serialises all decode calls.
class JpegDecoder {
public:
    JpegDecoder();
    ~JpegDecoder();

    JpegDecoder(const JpegDecoder&) = delete;
    JpegDecoder& operator=(const JpegDecoder&) = delete;

    bool init(std::string* error);
    bool ready() const;

    // Decodes a complete SOI..EOI JPEG into RGBA_8888 at dst.  dstStride is in
    // bytes and must be >= info.width * 4.  maxWidth/maxHeight bound the
    // destination allocation; a larger JPEG is rejected, never cropped.
    //
    // Returns kOk or a negative JpegError.  On failure *info is left zeroed
    // (unless validateJpegStructure succeeded, in which case it is filled in
    // for diagnostics) and dst contents are undefined.
    int decode(const uint8_t* jpeg, size_t length,
               uint8_t* dst, int dstStride,
               int maxWidth, int maxHeight,
               JpegFrameInfo* info, uint64_t* decodeUs,
               std::string* error);

    // Structural validation that does not require libjpeg-turbo.  It checks
    // SOI, every marker segment length before reading it, exactly one SOF with
    // 8-bit precision and 1 or 3 components, SOS presence, and a final EOI.
    // Entropy bytes are not interpreted; libjpeg-turbo does that afterwards.
    static bool validateJpegStructure(const uint8_t* jpeg, size_t length,
                                      JpegFrameInfo* info, std::string* error);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace a6400
