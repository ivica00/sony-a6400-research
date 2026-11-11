#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace a6400 {
namespace uvc {

// Documented expectations for the SECONDARY / UNVERIFIED composite transport.
// They are useful for diagnostics and for the host fixtures, but the parser
// does not require them: endpoint address, resolution and frame interval are
// properties of the descriptor, not of the byte parser.
constexpr uint8_t kCompositeVsEndpoint = 0x84;
constexpr int kCompositeFrameWidth = 1280;
constexpr int kCompositeFrameHeight = 720;
constexpr uint32_t kCompositeDefaultFrameInterval100ns = 333333U;  // 30 fps

enum class HeaderMode {
    // Standard UVC payload header:
    //   byte 0 = bHeaderLength (2..12)
    //   byte 1 = bmHeaderInfo
    //            bit0 FID, bit1 EOF, bit2 PTS, bit3 SCR, ...
    //   optional PTS: 4 bytes little-endian at offset 2
    UvcStandard = 0,

    // Composite-daemon variant requested by the task brief: the header length
    // is encoded in bits 0-1 of bmHeaderInfo instead of a separate
    // bHeaderLength.  The two-bit code selects 2, 6, 10 or 14 bytes.  FID/EOF/
    // PTS move to bits 2/3/4 of byte 0.  This layout is NOT verified on
    // hardware; it exists so the parser can be exercised both ways.
    CompositeBits01 = 1
};

enum class ParseCode : int {
    kOk = 0,
    kNullData = -1,
    kTruncatedHeader = -2,
    kInvalidHeaderLength = -3,
    kMaxFrameExceeded = -4,
    kMissingSoi = -5,
    kTruncatedFrame = -6,
    kFidChanged = -7,
    kTrailingBytes = -8
};

struct ParseError {
    ParseCode code = ParseCode::kOk;
    size_t offset = 0;
    std::string detail;
};

struct FrameInfo {
    uint64_t sequence = 0;   // parser-local, starts at 1
    uint32_t pts = 0;
    uint8_t fid = 0;
    bool eof = false;
    bool ptsValid = false;
};

// The callback receives a pointer into the parser's internal frame buffer.  It
// is valid only for the duration of the callback; copy if the frame is to
// outlive it.  No allocation is performed per completed frame by the parser
// after warm-up.
using FrameCallback = std::function<void(const uint8_t* jpeg, size_t length,
                                          const FrameInfo& info)>;

// Reassembles complete JPEG frames from UVC bulk-IN transfers.
//
// Contract: each feed() call starts at a UVC payload header (this is true for a
// bulk transfer produced by the camera's UVC function).  A frame may span any
// number of feed() calls.  A single feed may also contain several complete
// frames back-to-back; the parser walks past each EOI and parses the next
// header.  feed() is not thread-safe: one USB reader thread owns it.
class Parser {
public:
    explicit Parser(HeaderMode mode = HeaderMode::UvcStandard,
                    size_t maxFrameBytes = 2 * 1024 * 1024,
                    size_t maxHeaderBytes = 64);

    void reset();

    int feed(const uint8_t* data, size_t length,
             const FrameCallback& onFrame, ParseError* error);

    // Reports kTruncatedFrame when a frame was in progress at end of stream.
    int flush(ParseError* error);

    size_t bufferedBytes() const;
    HeaderMode headerMode() const;

private:
    struct Header {
        size_t length = 0;
        uint8_t fid = 0;
        bool eof = false;
        bool ptsValid = false;
        uint32_t pts = 0;
    };

    bool parseHeader(const uint8_t* data, size_t length, Header* header,
                     ParseError* error);
    int fail(ParseCode code, size_t offset, const char* detail, ParseError* error);
    static bool findEoi(const uint8_t* data, size_t begin, size_t end, size_t* at);

    HeaderMode mode_;
    size_t maxFrameBytes_;
    size_t maxHeaderBytes_;
    std::vector<uint8_t> frame_;
    bool inFrame_ = false;
    uint8_t fid_ = 0;
    uint32_t pts_ = 0;
    bool ptsValid_ = false;
    uint64_t sequence_ = 0;
};

}  // namespace uvc
}  // namespace a6400
