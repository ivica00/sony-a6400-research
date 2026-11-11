#include "uvc_frame_parser.h"

#include <algorithm>

namespace a6400 {
namespace uvc {
namespace {

uint32_t le32(const uint8_t* p)
{
    return static_cast<uint32_t>(p[0]) |
           (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) |
           (static_cast<uint32_t>(p[3]) << 24);
}

void setError(ParseError* error, ParseCode code, size_t offset, const char* detail)
{
    if (error != nullptr) {
        error->code = code;
        error->offset = offset;
        error->detail = detail != nullptr ? detail : "";
    }
}

}  // namespace

Parser::Parser(HeaderMode mode, size_t maxFrameBytes, size_t maxHeaderBytes)
    : mode_(mode),
      maxFrameBytes_(maxFrameBytes == 0 ? 2 * 1024 * 1024 : maxFrameBytes),
      maxHeaderBytes_(maxHeaderBytes == 0 ? 64 : maxHeaderBytes)
{
    frame_.reserve(maxFrameBytes_ + 2);
}

void Parser::reset()
{
    frame_.clear();
    inFrame_ = false;
    fid_ = 0;
    pts_ = 0;
    ptsValid_ = false;
}

size_t Parser::bufferedBytes() const
{
    return frame_.size();
}

HeaderMode Parser::headerMode() const
{
    return mode_;
}

int Parser::fail(ParseCode code, size_t offset, const char* detail, ParseError* error)
{
    setError(error, code, offset, detail);
    reset();
    return static_cast<int>(code);
}

bool Parser::findEoi(const uint8_t* data, size_t begin, size_t end, size_t* at)
{
    if (end < begin + 2) {
        return false;
    }
    for (size_t i = begin; i + 1 < end; ++i) {
        if (data[i] == 0xFF && data[i + 1] == 0xD9) {
            *at = i;
            return true;
        }
    }
    return false;
}

bool Parser::parseHeader(const uint8_t* data, size_t length, Header* header,
                         ParseError* error)
{
    if (data == nullptr || length < 2) {
        setError(error, ParseCode::kTruncatedHeader, 0, "fewer than 2 header bytes");
        return false;
    }

    Header h;
    if (mode_ == HeaderMode::UvcStandard) {
        h.length = data[0];
        if (h.length < 2 || h.length > maxHeaderBytes_) {
            setError(error, ParseCode::kInvalidHeaderLength, 0,
                     "standard bHeaderLength outside 2..maxHeaderBytes");
            return false;
        }
        if (h.length > length) {
            setError(error, ParseCode::kTruncatedHeader, 0, "bHeaderLength exceeds transfer");
            return false;
        }
        const uint8_t bm = data[1];
        h.fid = static_cast<uint8_t>(bm & 0x01);
        h.eof = ((bm >> 1) & 0x01) != 0;
        h.ptsValid = ((bm >> 2) & 0x01) != 0;
        if (h.ptsValid) {
            if (h.length < 6) {
                setError(error, ParseCode::kInvalidHeaderLength, 0,
                         "PTS flag set but bHeaderLength < 6");
                return false;
            }
            h.pts = le32(data + 2);
        }
    } else {
        // Composite daemon variant: byte 0 is the bmHeaderInfo; bits 0-1 are
        // the header-length code (2 + 4*code) and FID/EOF/PTS are bits 2/3/4.
        const uint8_t bm = data[0];
        h.length = 2 + 4 * static_cast<size_t>(bm & 0x03);
        if (h.length > maxHeaderBytes_) {
            setError(error, ParseCode::kInvalidHeaderLength, 0,
                     "composite header length code exceeds maxHeaderBytes");
            return false;
        }
        if (h.length > length) {
            setError(error, ParseCode::kTruncatedHeader, 0, "composite header exceeds transfer");
            return false;
        }
        h.fid = static_cast<uint8_t>((bm >> 2) & 0x01);
        h.eof = ((bm >> 3) & 0x01) != 0;
        h.ptsValid = ((bm >> 4) & 0x01) != 0;
        if (h.ptsValid) {
            if (h.length < 6) {
                setError(error, ParseCode::kInvalidHeaderLength, 0,
                         "composite PTS flag set but header shorter than 6 bytes");
                return false;
            }
            h.pts = le32(data + 2);
        }
    }

    *header = h;
    return true;
}

int Parser::feed(const uint8_t* data, size_t length,
                 const FrameCallback& onFrame, ParseError* error)
{
    if (error != nullptr) {
        *error = ParseError{};
    }
    if (data == nullptr || length == 0) {
        return fail(ParseCode::kNullData, 0, "null or empty UVC transfer", error);
    }

    size_t offset = 0;
    while (offset < length) {
        Header header;
        if (!parseHeader(data + offset, length - offset, &header, error)) {
            reset();
            return static_cast<int>(error != nullptr ? error->code : ParseCode::kTruncatedHeader);
        }
        const size_t headerOffset = offset;
        offset += header.length;

        if (inFrame_) {
            if (header.fid != fid_) {
                return fail(ParseCode::kFidChanged, headerOffset,
                            "FID changed inside one JPEG frame", error);
            }
        } else {
            fid_ = header.fid;
        }
        if (header.ptsValid) {
            pts_ = header.pts;
            ptsValid_ = true;
        }

        if (offset > length) {
            return fail(ParseCode::kTruncatedHeader, headerOffset,
                        "header consumed past transfer", error);
        }

        size_t eoiAt = 0;
        const bool haveEoi = findEoi(data, offset, length, &eoiAt);
        const size_t payloadEnd = haveEoi ? (eoiAt + 2) : length;
        const size_t payloadBytes = payloadEnd - offset;

        if (frame_.empty()) {
            if (payloadBytes < 2 || data[offset] != 0xFF || data[offset + 1] != 0xD8) {
                return fail(ParseCode::kMissingSoi, offset,
                            "first payload of a frame does not start with JPEG SOI", error);
            }
            inFrame_ = true;
        }
        if (frame_.size() + payloadBytes > maxFrameBytes_) {
            return fail(ParseCode::kMaxFrameExceeded, offset,
                        "assembled frame exceeds maxFrameBytes", error);
        }
        frame_.insert(frame_.end(), data + offset, data + payloadEnd);

        if (!haveEoi) {
            if (header.eof) {
                return fail(ParseCode::kTruncatedFrame, payloadEnd,
                            "EOF payload has no JPEG EOI", error);
            }
            // The rest of this transfer belongs to the in-progress frame.
            return static_cast<int>(ParseCode::kOk);
        }

        FrameInfo info;
        info.sequence = ++sequence_;
        info.pts = pts_;
        info.fid = fid_;
        info.eof = header.eof;
        info.ptsValid = ptsValid_;
        if (onFrame) {
            onFrame(frame_.data(), frame_.size(), info);
        }

        frame_.clear();
        inFrame_ = false;
        fid_ = 0;
        pts_ = 0;
        ptsValid_ = false;

        offset = payloadEnd;
        if (offset < length && (length - offset) < 2) {
            return fail(ParseCode::kTrailingBytes, offset,
                        "fewer than 2 bytes remain after EOI", error);
        }
    }
    return static_cast<int>(ParseCode::kOk);
}

int Parser::flush(ParseError* error)
{
    if (!frame_.empty() || inFrame_) {
        return fail(ParseCode::kTruncatedFrame, frame_.size(),
                    "stream ended inside a JPEG frame", error);
    }
    if (error != nullptr) {
        *error = ParseError{};
    }
    return static_cast<int>(ParseCode::kOk);
}

}  // namespace uvc
}  // namespace a6400
