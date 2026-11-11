#include "jni_bridge.h"
#include "jpeg_decoder.h"
#include "uvc_frame_parser.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace {

int g_checks = 0;

#define CHECK(condition)                                                        \
    do {                                                                        \
        ++g_checks;                                                             \
        if (!(condition)) {                                                     \
            std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__,        \
                         #condition);                                           \
            std::exit(1);                                                       \
        }                                                                       \
    } while (0)

void append16(std::vector<uint8_t>& out, int value)
{
    out.push_back(static_cast<uint8_t>((value >> 8) & 0xFF));
    out.push_back(static_cast<uint8_t>(value & 0xFF));
}

std::vector<uint8_t> makeJpeg(int width = 2, int height = 3,
                              bool includeSof = true, int precision = 8,
                              bool includeEoi = true)
{
    std::vector<uint8_t> out;
    out.push_back(0xFF);
    out.push_back(0xD8);
    if (includeSof) {
        out.push_back(0xFF);
        out.push_back(0xC0);
        append16(out, 17);
        out.push_back(static_cast<uint8_t>(precision));
        append16(out, height);
        append16(out, width);
        out.push_back(3);
        out.push_back(1); out.push_back(0x11); out.push_back(0);
        out.push_back(2); out.push_back(0x11); out.push_back(1);
        out.push_back(3); out.push_back(0x11); out.push_back(1);
    }
    // SOS: 12-byte segment for 3 components, then two entropy bytes.
    const uint8_t sos[] = {
        0xFF, 0xDA, 0x00, 0x0C, 0x03,
        0x01, 0x00, 0x02, 0x11, 0x03, 0x11,
        0x00, 0x3F, 0x00, 0x11, 0x22
    };
    out.insert(out.end(), sos, sos + sizeof(sos));
    if (includeEoi) {
        out.push_back(0xFF);
        out.push_back(0xD9);
    }
    return out;
}

std::vector<uint8_t> wrapUvcStandard(const std::vector<uint8_t>& payload,
                                     bool eof, bool pts, uint32_t ptsValue,
                                     uint8_t fid = 0)
{
    std::vector<uint8_t> out;
    out.push_back(static_cast<uint8_t>(pts ? 6 : 2));
    uint8_t bm = static_cast<uint8_t>(fid & 0x01);
    if (eof) bm |= 0x02;
    if (pts) bm |= 0x04;
    out.push_back(bm);
    if (pts) {
        out.push_back(static_cast<uint8_t>(ptsValue & 0xFF));
        out.push_back(static_cast<uint8_t>((ptsValue >> 8) & 0xFF));
        out.push_back(static_cast<uint8_t>((ptsValue >> 16) & 0xFF));
        out.push_back(static_cast<uint8_t>((ptsValue >> 24) & 0xFF));
    }
    out.insert(out.end(), payload.begin(), payload.end());
    return out;
}

std::vector<uint8_t> wrapUvcComposite(const std::vector<uint8_t>& payload,
                                      bool eof, bool pts, uint32_t ptsValue,
                                      uint8_t fid = 0)
{
    std::vector<uint8_t> out;
    // header-length code 1 => 6 bytes; bits 2/3/4 carry FID/EOF/PTS.
    uint8_t bm = 0x01;
    if (fid != 0) bm |= 0x04;
    if (eof) bm |= 0x08;
    if (pts) bm |= 0x10;
    out.push_back(bm);
    out.push_back(0);  // reserved byte
    if (pts) {
        out.push_back(static_cast<uint8_t>(ptsValue & 0xFF));
        out.push_back(static_cast<uint8_t>((ptsValue >> 8) & 0xFF));
        out.push_back(static_cast<uint8_t>((ptsValue >> 16) & 0xFF));
        out.push_back(static_cast<uint8_t>((ptsValue >> 24) & 0xFF));
    } else {
        out.push_back(0); out.push_back(0); out.push_back(0); out.push_back(0);
    }
    out.insert(out.end(), payload.begin(), payload.end());
    return out;
}

size_t feedAndCollect(a6400::uvc::Parser& parser,
                      const std::vector<uint8_t>& bytes,
                      std::vector<uint8_t>* collected,
                      uint32_t* pts = nullptr,
                      uint8_t* fid = nullptr)
{
    a6400::uvc::ParseError error;
    const int rc = parser.feed(bytes.data(), bytes.size(),
        [&](const uint8_t* jpeg, size_t length, const a6400::uvc::FrameInfo& info) {
            collected->assign(jpeg, jpeg + length);
            if (pts != nullptr) *pts = info.pts;
            if (fid != nullptr) *fid = info.fid;
        }, &error);
    CHECK(rc == 0);
    return collected->size();
}

void testUvcParser()
{
    const std::vector<uint8_t> jpeg = makeJpeg();

    // Single complete payload with EOF.
    {
        a6400::uvc::Parser parser;
        std::vector<uint8_t> got;
        const std::vector<uint8_t> payload = wrapUvcStandard(jpeg, true, false, 0);
        CHECK(feedAndCollect(parser, payload, &got) == jpeg.size());
        CHECK(std::equal(got.begin(), got.end(), jpeg.begin()));
    }

    // Chunked frame: two payload headers, EOF only on the second.
    {
        a6400::uvc::Parser parser;
        std::vector<uint8_t> got;
        const size_t split = jpeg.size() / 2;
        const std::vector<uint8_t> first(jpeg.begin(), jpeg.begin() + static_cast<long>(split));
        const std::vector<uint8_t> second(jpeg.begin() + static_cast<long>(split), jpeg.end());
        CHECK(feedAndCollect(parser, wrapUvcStandard(first, false, false, 0), &got) == 0);
        CHECK(feedAndCollect(parser, wrapUvcStandard(second, true, false, 0), &got) == jpeg.size());
        CHECK(std::equal(got.begin(), got.end(), jpeg.begin()));
    }

    // PTS is little-endian and survives chunking.
    {
        a6400::uvc::Parser parser;
        std::vector<uint8_t> got;
        uint32_t pts = 0;
        const std::vector<uint8_t> payload = wrapUvcStandard(jpeg, true, true, 0x11223344U);
        CHECK(feedAndCollect(parser, payload, &got, &pts) == jpeg.size());
        CHECK(pts == 0x11223344U);
    }

    // Composite variant: length from bmHeaderInfo bits 0-1.
    {
        a6400::uvc::Parser parser(a6400::uvc::HeaderMode::CompositeBits01);
        std::vector<uint8_t> got;
        uint32_t pts = 0;
        uint8_t fid = 0xFF;
        const std::vector<uint8_t> payload =
            wrapUvcComposite(jpeg, true, true, 0x55667788U, 1);
        CHECK(feedAndCollect(parser, payload, &got, &pts, &fid) == jpeg.size());
        CHECK(pts == 0x55667788U);
        CHECK(fid == 1);
    }

    // Two complete frames in one transfer (the parser resumes after EOI).
    {
        a6400::uvc::Parser parser;
        std::vector<uint8_t> both = wrapUvcStandard(jpeg, true, false, 0);
        const std::vector<uint8_t> second = wrapUvcStandard(jpeg, true, false, 0);
        both.insert(both.end(), second.begin(), second.end());
        const std::vector<uint8_t> payload = both;
        a6400::uvc::ParseError error;
        int frames = 0;
        const int rc = parser.feed(payload.data(), payload.size(),
            [&](const uint8_t*, size_t, const a6400::uvc::FrameInfo&) { ++frames; }, &error);
        CHECK(rc == 0);
        CHECK(frames == 2);
    }

    // Truncated JPEG with EOF set is an explicit error, not a partial frame.
    {
        a6400::uvc::Parser parser;
        int callbacks = 0;
        const std::vector<uint8_t> first(jpeg.begin(), jpeg.begin() + 20);
        a6400::uvc::ParseError error;
        const std::vector<uint8_t> payload = wrapUvcStandard(first, true, false, 0);
        const int rc = parser.feed(payload.data(), payload.size(),
            [&](const uint8_t*, size_t, const a6400::uvc::FrameInfo&) { ++callbacks; },
            &error);
        CHECK(rc == static_cast<int>(a6400::uvc::ParseCode::kTruncatedFrame));
        CHECK(callbacks == 0);
    }

    // End-of-stream while a non-EOF chunk is outstanding.
    {
        a6400::uvc::Parser parser;
        int callbacks = 0;
        const std::vector<uint8_t> first(jpeg.begin(), jpeg.begin() + 20);
        a6400::uvc::ParseError error;
        const std::vector<uint8_t> payload = wrapUvcStandard(first, false, false, 0);
        CHECK(parser.feed(payload.data(), payload.size(),
            [&](const uint8_t*, size_t, const a6400::uvc::FrameInfo&) { ++callbacks; },
            &error) == 0);
        CHECK(parser.flush(&error) == static_cast<int>(a6400::uvc::ParseCode::kTruncatedFrame));
    }

    // FID change inside one frame is rejected.
    {
        a6400::uvc::Parser parser;
        int callbacks = 0;
        const size_t split = jpeg.size() / 2;
        const std::vector<uint8_t> first(jpeg.begin(), jpeg.begin() + static_cast<long>(split));
        const std::vector<uint8_t> second(jpeg.begin() + static_cast<long>(split), jpeg.end());
        const std::vector<uint8_t> firstPayload = wrapUvcStandard(first, false, false, 0, 0);
        a6400::uvc::ParseError error;
        CHECK(parser.feed(firstPayload.data(), firstPayload.size(),
                          [&](const uint8_t*, size_t, const a6400::uvc::FrameInfo&) {
                              ++callbacks;
                          }, &error) == 0);
        const std::vector<uint8_t> secondPayload = wrapUvcStandard(second, true, false, 0, 1);
        CHECK(parser.feed(secondPayload.data(), secondPayload.size(),
                          [&](const uint8_t*, size_t, const a6400::uvc::FrameInfo&) {
                              ++callbacks;
                          }, &error) == static_cast<int>(a6400::uvc::ParseCode::kFidChanged));
    }
}

void testJpegAndDecoder()
{
    a6400::JpegFrameInfo info;
    std::string error;
    const std::vector<uint8_t> jpeg = makeJpeg(2, 3);
    CHECK(a6400::JpegDecoder::validateJpegStructure(jpeg.data(), jpeg.size(), &info, &error));
    CHECK(info.width == 2);
    CHECK(info.height == 3);
    CHECK(info.components == 3);
    CHECK(info.precision == 8);

    const std::vector<uint8_t> noSof = makeJpeg(2, 3, false);
    CHECK(!a6400::JpegDecoder::validateJpegStructure(noSof.data(), noSof.size(), &info, &error));

    const std::vector<uint8_t> badPrecision = makeJpeg(2, 3, true, 12);
    CHECK(!a6400::JpegDecoder::validateJpegStructure(badPrecision.data(),
                                                     badPrecision.size(), &info, &error));

    std::vector<uint8_t> truncated = jpeg;
    truncated.resize(truncated.size() - 2);
    CHECK(!a6400::JpegDecoder::validateJpegStructure(truncated.data(), truncated.size(),
                                                     &info, &error));

    std::vector<uint8_t> trailing = jpeg;
    trailing.push_back(0);
    CHECK(!a6400::JpegDecoder::validateJpegStructure(trailing.data(), trailing.size(),
                                                     &info, &error));

    a6400::JpegDecoder decoder;
    CHECK(decoder.init(&error));
    CHECK(decoder.ready());

    const int pitch = 16;
    std::vector<uint8_t> rgba(static_cast<size_t>(pitch) * 3, 0);
    uint64_t decodeUs = 0;
    info = a6400::JpegFrameInfo{};
    CHECK(decoder.decode(jpeg.data(), jpeg.size(), rgba.data(), pitch, 2, 3,
                         &info, &decodeUs, &error) == a6400::kOk);
    CHECK(info.width == 2);
    CHECK(info.height == 3);
    CHECK(decodeUs < 1000000);
    CHECK(rgba[0] == 0);
    CHECK(rgba[1] == 0);
    CHECK(rgba[2] == 0);
    CHECK(rgba[3] == 0xFF);
    // Row 1 starts at pitch, not width*4, which proves the stride is honoured.
    CHECK(rgba[static_cast<size_t>(pitch) + 0] == 31);
    CHECK(rgba[static_cast<size_t>(pitch) + 1] == 13);
    CHECK(rgba[static_cast<size_t>(pitch) + 2] == 5);

    CHECK(decoder.decode(jpeg.data(), jpeg.size(), rgba.data(), pitch, 1, 3,
                         &info, &decodeUs, &error) == a6400::kErrJpegDimensions);
    CHECK(decoder.decode(nullptr, jpeg.size(), rgba.data(), pitch, 2, 3,
                         &info, &decodeUs, &error) == a6400::kErrInvalidArgument);
}

void testPipelineLifecycle()
{
    const int64_t handle = a6400::jniCreate();
    CHECK(handle > 0);

    a6400::jniConfigure(handle, 2670, 1200, 1024, 680);
    a6400::jniSetSharpness(handle, 0.42f);
    a6400::jniSetUpscaleMode(handle, 1);
    a6400::jniSetFocusPeaking(handle, 1, 0.7f);

    int64_t stats[14] = {};
    a6400::jniGetStats(handle, stats, 14);
    CHECK(stats[0] == 0);
    CHECK(stats[5] == 0);
    CHECK(stats[7] >= 0);

    const std::vector<uint8_t> jpeg = makeJpeg(2, 3);
    CHECK(a6400::jniPushJpeg(handle, jpeg.data(), jpeg.size(), 42, 123456789) == a6400::kOk);
    a6400::jniGetStats(handle, stats, 14);
    CHECK(stats[0] == 1);
    CHECK(stats[2] >= 0);
    CHECK(stats[3] < 1000000);
    CHECK(stats[5] == 0);
    CHECK(stats[10] == 42);
    CHECK((stats[7] & (int64_t{1} << 9)) != 0);  // decoder ready
    CHECK((stats[7] & (int64_t{1} << 6)) == 0);  // host AHB stub unavailable

    const std::vector<uint8_t> bad = makeJpeg(2, 3, false);
    CHECK(a6400::jniPushJpeg(handle, bad.data(), bad.size(), 43, 0) < 0);
    CHECK(a6400::jniPushJpeg(handle, nullptr, 1, 44, 0) == a6400::kErrInvalidArgument);

    // No EGL context on the host: the documented no-GL error is expected.
    CHECK(a6400::jniRender(handle) == a6400::kErrNoGlContext);

    a6400::jniGetStats(handle, stats, 14);
    CHECK(stats[6] >= 1);
    CHECK(stats[8] >= 1);

    a6400::jniDestroy(handle);
    CHECK(a6400::jniPushJpeg(handle, jpeg.data(), jpeg.size(), 45, 0) == a6400::kErrInvalidHandle);
    CHECK(a6400::jniRender(handle) == a6400::kErrInvalidHandle);
    a6400::jniDestroy(0);

    const int64_t second = a6400::jniCreate();
    CHECK(second > 0);
    a6400::jniDestroy(second);
}

}  // namespace

int main()
{
    std::fprintf(stdout, "A6400 host compile harness\n");
    std::fprintf(stdout, "  GL: unavailable by design (EGL_NO_CONTEXT)\n");
    std::fprintf(stdout, "  turbojpeg: compile-only stub\n");

    testUvcParser();
    testJpegAndDecoder();
    testPipelineLifecycle();

    std::fprintf(stdout, "HOST TESTS: %d assertions passed\n", g_checks);
    return 0;
}
