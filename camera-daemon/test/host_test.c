/* Host unit tests for the a6400 daemon's pure logic.
 *
 * No hardware, no camera node, no /dev/uipc, no ptrace: only src/frame_hook.c and
 * src/control_bridge.c are linked, plus the two clock stubs below. Every assertion is
 * an expected behaviour transcribed from the contract headers and the evidence
 * cited in those files.
 *
 * Build/run through test/run_host_tests.py (which selects a host compiler and
 * passes a writable working directory for the ack-file test).
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "a6400_control.h"
#include "a6400_daemon.h"
#include "a6400_frame.h"
#include "a6400_internal.h"
#include "a6400_sdlog.h"

/* ---- clock stubs (control.c asks the daemon core for monotonic time) ------ */

static uint64_t g_fake_ms = 1000;

uint64_t a6400_now_ms(void)
{
    return g_fake_ms;
}

int64_t a6400_now_ns(void)
{
    return (int64_t)g_fake_ms * 1000000LL;
}

/* ---- tiny test harness ---------------------------------------------------- */

static int g_checks;
static int g_failures;

#define CHECK(cond)                                                          \
    do {                                                                     \
        g_checks++;                                                          \
        if (!(cond)) {                                                       \
            g_failures++;                                                    \
            printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);           \
        }                                                                    \
    } while (0)

#define CHECK_EQ(actual, expected)                                           \
    do {                                                                     \
        long long a_ = (long long)(actual);                                  \
        long long e_ = (long long)(expected);                                \
        g_checks++;                                                          \
        if (a_ != e_) {                                                      \
            g_failures++;                                                    \
            printf("FAIL %s:%d: %s == %lld, expected %lld\n", __FILE__,      \
                   __LINE__, #actual, a_, e_);                               \
        }                                                                    \
    } while (0)

#define CHECK_NE(actual, unexpected)                                         \
    do {                                                                     \
        long long a_ = (long long)(actual);                                  \
        long long u_ = (long long)(unexpected);                              \
        g_checks++;                                                          \
        if (a_ == u_) {                                                      \
            g_failures++;                                                    \
            printf("FAIL %s:%d: %s unexpectedly == %lld\n", __FILE__,        \
                   __LINE__, #actual, u_);                                   \
        }                                                                    \
    } while (0)

/* ---- JPEG fixture --------------------------------------------------------- */

/* Builds a bounded JPEG prefix: SOI, one APP0 segment, the requested SOF
 * marker, then harmless filler. Returns the number of bytes produced. */
static uint32_t make_jpeg(uint8_t *buf, uint32_t cap, uint32_t width,
                          uint32_t height, uint8_t sof_marker)
{
    uint32_t i = 0;
    int k;

    if (cap < 64u)
        return 0;
    buf[i++] = 0xffu;
    buf[i++] = 0xd8u; /* SOI */

    buf[i++] = 0xffu;
    buf[i++] = 0xe0u; /* APP0 */
    buf[i++] = 0x00u;
    buf[i++] = 0x10u; /* segment length 16 (2 length bytes + 14 content) */
    for (k = 0; k < 14; k++)
        buf[i++] = 0x00;

    buf[i++] = 0xffu;
    buf[i++] = sof_marker;
    buf[i++] = 0x00u;
    buf[i++] = 0x11u; /* segment length 17 */
    buf[i++] = 0x08u; /* precision */
    buf[i++] = (uint8_t)(height >> 8);
    buf[i++] = (uint8_t)(height & 0xffu);
    buf[i++] = (uint8_t)(width >> 8);
    buf[i++] = (uint8_t)(width & 0xffu);
    buf[i++] = 0x03u; /* components */
    for (k = 0; k < 9; k++)
        buf[i++] = 0x00;

    while (i < 64u && i < cap)
        buf[i++] = 0x00;
    return i;
}

/* ---- shared control fixtures ---------------------------------------------- */

static struct a6400_daemon_stats g_host_stats;

static void host_get_stats(void *ctx, struct a6400_daemon_stats *out)
{
    (void)ctx;
    *out = g_host_stats;
}

static void host_get_caps(void *ctx, struct a6400_ctl_caps_reply *out)
{
    (void)ctx;
    out->protocol_version = A6400_CTL_VERSION;
    out->camera_setting_route = (uint32_t)A6400_CTL_ROUTE_PTP;
    out->uvc_transport = 1;
    out->max_payload = A6400_CTL_MAX_PAYLOAD;
}

static int host_session_active(void *ctx)
{
    (void)ctx;
    return 1;
}

static struct a6400_control_ctx *make_ctx(const char *ack_path)
{
    struct a6400_control_config cfg;
    struct a6400_control_host host;

    memset(&cfg, 0, sizeof cfg);
    memset(&host, 0, sizeof host);
    cfg.fifo_path = NULL;
    cfg.ack_path = ack_path;
    cfg.video_node = NULL;
    cfg.enable_ring = 0;
    cfg.verbose = 0;
    host.get_stats = host_get_stats;
    host.get_caps = host_get_caps;
    host.session_active = host_session_active;
    return a6400_control_create(&cfg, &host);
}

/* One request round trip through the public build/parse/apply path. */
static int route(uint8_t opcode, const void *payload, uint16_t payload_len,
                 struct a6400_ctl_header *hdr_out, struct a6400_ctl_ack *ack_out,
                 struct a6400_ctl_action *action)
{
    uint8_t frame[A6400_CTL_HEADER_SIZE + A6400_CTL_MAX_PAYLOAD];
    struct a6400_ctl_header hdr;
    struct a6400_control_ctx *ctx;
    const uint8_t *payload_view = NULL;
    uint32_t payload_view_len = 0;
    uint32_t total;
    int rc;

    total = a6400_ctl_build_request(frame, (uint32_t)sizeof frame, opcode, 0x4242u,
                                    payload, payload_len);
    if (!total)
        return -1000;
    rc = a6400_ctl_parse_request(frame, total, &hdr, &payload_view,
                                 &payload_view_len);
    if (rc != 0)
        return rc;
    ctx = make_ctx(NULL);
    if (!ctx)
        return -1001;
    rc = a6400_control_apply(ctx, &hdr, payload_view, payload_view_len, ack_out,
                             action);
    a6400_control_destroy(ctx);
    if (hdr_out)
        *hdr_out = hdr;
    return rc;
}

/* ---- tests: JPEG SOF parser ----------------------------------------------- */

static void test_sof_parser(void)
{
    uint8_t jpeg[64];
    struct a6400_jpeg_dims dims;
    uint32_t n;

    n = make_jpeg(jpeg, sizeof jpeg, 1280, 720, 0xc0);
    memset(&dims, 0, sizeof dims);
    CHECK_EQ(a6400_jpeg_parse_dimensions(jpeg, n, &dims), 0);
    CHECK_EQ(dims.width, 1280);
    CHECK_EQ(dims.height, 720);

    n = make_jpeg(jpeg, sizeof jpeg, 1024, 680, 0xc2); /* progressive SOF2 */
    memset(&dims, 0, sizeof dims);
    CHECK_EQ(a6400_jpeg_parse_dimensions(jpeg, n, &dims), 0);
    CHECK_EQ(dims.width, 1024);
    CHECK_EQ(dims.height, 680);

    /* A quantisation segment before the SOF must be skipped, not misread. */
    {
        uint8_t buf[64];
        uint32_t i = 0;
        int k;

        buf[i++] = 0xff; buf[i++] = 0xd8;
        buf[i++] = 0xff; buf[i++] = 0xdb; buf[i++] = 0x00; buf[i++] = 0x06;
        for (k = 0; k < 4; k++) buf[i++] = 0x11;
        buf[i++] = 0xff; buf[i++] = 0xc0; buf[i++] = 0x00; buf[i++] = 0x11;
        buf[i++] = 0x08; buf[i++] = 0x02; buf[i++] = 0xd0;
        buf[i++] = 0x05; buf[i++] = 0x00; buf[i++] = 0x03;
        for (k = 0; k < 9; k++) buf[i++] = 0x00;
        while (i < sizeof buf) buf[i++] = 0x00;
        memset(&dims, 0, sizeof dims);
        CHECK_EQ(a6400_jpeg_parse_dimensions(buf, 48, &dims), 0);
        CHECK_EQ(dims.width, 1280);
        CHECK_EQ(dims.height, 720);
    }

    /* Invalid / truncated inputs. */
    dims.width = 7;
    dims.height = 7;
    CHECK_EQ(a6400_jpeg_parse_dimensions(NULL, 64, &dims), -1);
    CHECK_EQ(a6400_jpeg_parse_dimensions(jpeg, 0, &dims), -1);
    CHECK_EQ(a6400_jpeg_parse_dimensions(jpeg, 3, &dims), -1);
    CHECK_EQ(a6400_jpeg_parse_dimensions(jpeg, 64, NULL), -1);
    CHECK_EQ(dims.width, 7); /* untouched on failure */
    CHECK_EQ(dims.height, 7);

    {
        uint8_t bad[8] = {0x00, 0x00, 0xff, 0xd8, 0xff, 0xc0, 0x00, 0x11};
        CHECK_EQ(a6400_jpeg_parse_dimensions(bad, sizeof bad, &dims), -1);
    }
    {
        /* SOI only. */
        uint8_t soi[2] = {0xff, 0xd8};
        CHECK_EQ(a6400_jpeg_parse_dimensions(soi, sizeof soi, &dims), -1);
    }
    {
        /* SOF segment claims more bytes than the prefix holds. */
        uint8_t trunc[16] = {0xff, 0xd8, 0xff, 0xc0, 0x00, 0x40, 0x08,
                             0x02, 0xd0, 0x05, 0x00, 0x03, 0, 0, 0, 0};
        CHECK_EQ(a6400_jpeg_parse_dimensions(trunc, sizeof trunc, &dims), -1);
    }
    {
        /* Zero width. */
        uint8_t zero[40];
        uint32_t m = make_jpeg(zero, sizeof zero, 0, 720, 0xc0);
        CHECK_EQ(a6400_jpeg_parse_dimensions(zero, m, &dims), -1);
    }
    {
        /* SOS before any SOF. */
        uint8_t sos[10] = {0xff, 0xd8, 0xff, 0xda, 0x00, 0x02, 0xff, 0xd9, 0, 0};
        CHECK_EQ(a6400_jpeg_parse_dimensions(sos, sizeof sos, &dims), -1);
    }
    {
        /* SOF1 (0xC1) is deliberately not accepted by this contract. */
        uint8_t sof1[64];
        uint32_t m = make_jpeg(sof1, sizeof sof1, 640, 480, 0xc1);
        CHECK_EQ(a6400_jpeg_parse_dimensions(sof1, m, &dims), -1);
    }
    {
        /* A valid 4-byte payload is enough for the parser. */
        uint8_t tiny[8] = {0xff, 0xd8, 0xff, 0xc0, 0x00, 0x11, 0x08, 0x00};
        CHECK_EQ(a6400_jpeg_parse_dimensions(tiny, sizeof tiny, &dims), -1);
    }
}

/* ---- tests: frame queue / admission --------------------------------------- */

static void init_meta(struct a6400_uvc_dma_meta *meta)
{
    meta->phys_addr = 0x30000000u;
    meta->total_size = 2u * 65536u;
    meta->slot_size = 65536u;
    meta->max_frame_payload = 65536u - A6400_UVC_HEADER_SIZE;
}

static void init_cand(struct a6400_frame_candidate *cand, const uint8_t *prefix,
                      uint32_t prefix_len, uint32_t size_shift)
{
    memset(cand, 0, sizeof *cand);
    cand->handle1 = 1;
    cand->handle2 = 2;
    cand->phys_addr = 0x40000000u;
    cand->mapped_size = 200000u;
    cand->size_shift = size_shift;
    cand->frame_seq = 1;
    cand->prefix = prefix;
    cand->prefix_len = prefix_len;
}

static void test_frame_queue(void)
{
    struct a6400_frame_queue q;
    struct a6400_uvc_dma_meta meta;
    struct a6400_frame_candidate cand;
    uint8_t jpeg[64];
    uint32_t jlen = make_jpeg(jpeg, sizeof jpeg, 1280, 720, 0xc0);
    const uint32_t shift_128 = 1;    /* 1 << 7 == 128 bytes */
    const uint32_t shift_131072 = 1024;

    init_meta(&meta);
    init_cand(&cand, jpeg, jlen, shift_128);

    /* Queue starts with both halves ready and nothing in flight. */
    a6400_frame_queue_init(&q);
    CHECK_EQ(q.slot[0].ready, 1);
    CHECK_EQ(q.slot[1].ready, 1);
    CHECK_EQ(q.pending, 0);
    CHECK_EQ(q.generation, 0);

    /* Argument validation. */
    CHECK_EQ(a6400_frame_admit(NULL, &cand, &meta, 1280, 720), A6400_FRAME_ERR_ARG);
    CHECK_EQ(a6400_frame_admit(&q, NULL, &meta, 1280, 720), A6400_FRAME_ERR_ARG);
    CHECK_EQ(a6400_frame_admit(&q, &cand, NULL, 1280, 720), A6400_FRAME_ERR_ARG);
    CHECK_EQ(q.rejected, 0);

    /* Capacity: 131072 + 12 > 65536. */
    a6400_frame_queue_init(&q);
    {
        struct a6400_frame_candidate c = cand;
        c.size_shift = shift_131072;
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720),
                 A6400_FRAME_ERR_CAPACITY);
        CHECK_EQ(q.rejected, 1);
        CHECK_EQ(q.slot[0].ready, 1);

        /* A shift that would wrap <<7. */
        c.size_shift = 0x02000000u;
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720),
                 A6400_FRAME_ERR_CAPACITY);
    }
    {
        struct a6400_uvc_dma_meta m = meta;
        struct a6400_frame_candidate c = cand;

        m.slot_size = 0;
        CHECK_EQ(a6400_frame_admit(&q, &c, &m, 1280, 720),
                 A6400_FRAME_ERR_CAPACITY);
        m.slot_size = A6400_UVC_HEADER_SIZE - 1u;
        CHECK_EQ(a6400_frame_admit(&q, &c, &m, 1280, 720),
                 A6400_FRAME_ERR_CAPACITY);
    }

    /* Source address: zero and wrapping. */
    a6400_frame_queue_init(&q);
    {
        struct a6400_frame_candidate c = cand;

        c.phys_addr = 0;
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720), A6400_FRAME_ERR_ADDR);
        CHECK_EQ(q.rejected, 1);
        c.phys_addr = 0xffffffffu - 64u; /* 128-byte frame wraps */
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720), A6400_FRAME_ERR_ADDR);
        CHECK_EQ(q.rejected, 2);
    }

    /* Destination window itself must be representable. */
    a6400_frame_queue_init(&q);
    {
        struct a6400_uvc_dma_meta m = meta;
        struct a6400_frame_candidate c = cand;

        m.phys_addr = 0;
        CHECK_EQ(a6400_frame_admit(&q, &c, &m, 1280, 720), A6400_FRAME_ERR_ADDR);
        m.phys_addr = 0xfffff000u;
        m.slot_size = 0x1000u; /* two halves would wrap */
        CHECK_EQ(a6400_frame_admit(&q, &c, &m, 1280, 720), A6400_FRAME_ERR_ADDR);
    }

    /* Overlap with either destination half (the E0143 aliasing fix). */
    a6400_frame_queue_init(&q);
    {
        struct a6400_frame_candidate c = cand;

        c.phys_addr = 0x30000000u;
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720),
                 A6400_FRAME_ERR_OVERLAP);
        c.phys_addr = 0x30000000u + 65536u;
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720),
                 A6400_FRAME_ERR_OVERLAP);
        c.phys_addr = 0x30000000u + 65536u - 64u; /* straddles the boundary */
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720),
                 A6400_FRAME_ERR_OVERLAP);
        c.phys_addr = 0x30000000u;                /* inside slot 0 */
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720),
                 A6400_FRAME_ERR_OVERLAP);
        CHECK_EQ(q.rejected, 4);
        CHECK_EQ(q.slot[0].ready, 1);
        /* Just past both halves is legal. */
        c.phys_addr = 0x30000000u + 2u * 65536u;
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720), 0);
        a6400_frame_release(&q, 0);
    }

    /* Slot readiness. */
    a6400_frame_queue_init(&q);
    {
        struct a6400_frame_candidate c = cand;

        q.slot[0].ready = 0;
        q.slot[1].ready = 0;
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720),
                 A6400_FRAME_ERR_NOT_READY);
        CHECK_EQ(q.rejected, 1);
        /* Only slot 1 ready selects slot 1. */
        q.slot[1].ready = 1;
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720), 1);
        CHECK_EQ(q.pending_slot, 1);
        CHECK_EQ(q.slot[1].ready, 0);
        CHECK_EQ(q.slot[0].ready, 0);
    }

    /* JPEG prefix: missing while geometry is known, and malformed. */
    a6400_frame_queue_init(&q);
    {
        struct a6400_frame_candidate c = cand;

        c.prefix = NULL;
        c.prefix_len = 0;
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720), A6400_FRAME_ERR_JPEG);
        c.prefix_len = 1;
        c.prefix = jpeg;
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720), A6400_FRAME_ERR_JPEG);
        c.prefix = (const uint8_t *)"\x00\x00\x00\x00";
        c.prefix_len = 4;
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720), A6400_FRAME_ERR_JPEG);
        CHECK_EQ(q.rejected, 3);
    }

    /* Dimension mismatch (valid SOF, wrong expected pair). */
    a6400_frame_queue_init(&q);
    {
        struct a6400_frame_candidate c = cand;

        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1024, 680),
                 A6400_FRAME_ERR_DIMENSION);
        CHECK_EQ(q.rejected, 1);
    }

    /* mapped_size must cover the upper-bound length. */
    a6400_frame_queue_init(&q);
    {
        struct a6400_frame_candidate c = cand;

        c.mapped_size = 64u; /* < 128 */
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720), A6400_FRAME_ERR_SIZE);
        c.mapped_size = 0;
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 1280, 720), A6400_FRAME_ERR_SIZE);
        CHECK_EQ(q.rejected, 2);
    }

    /* Success consumes a slot. */
    a6400_frame_queue_init(&q);
    CHECK_EQ(a6400_frame_admit(&q, &cand, &meta, 1280, 720), 0);
    CHECK_EQ(q.slot[0].ready, 0);
    CHECK_EQ(q.slot[0].last_len, 128);
    CHECK_EQ(q.pending, 1);
    CHECK_EQ(q.pending_slot, 0);
    CHECK_EQ(q.generation, 1);

    /* Depth-1: a second frame is DROPPED, never queued. */
    CHECK_EQ(a6400_frame_admit(&q, &cand, &meta, 1280, 720), A6400_FRAME_ERR_BUSY);
    CHECK_EQ(q.dropped, 1);
    CHECK_EQ(q.generation, 1);
    CHECK_EQ(q.pending_slot, 0);

    /* Release returns the slot and clears the in-flight marker. */
    a6400_frame_release(&q, 0);
    CHECK_EQ(q.slot[0].ready, 1);
    CHECK_EQ(q.pending, 0);

    /* Releasing the wrong slot must not clear pending. */
    CHECK_EQ(a6400_frame_admit(&q, &cand, &meta, 1280, 720), 0);
    CHECK_EQ(q.pending, 1);
    a6400_frame_release(&q, 1);
    CHECK_EQ(q.pending, 1);
    CHECK_EQ(q.slot[1].ready, 1);
    a6400_frame_abort(&q);
    CHECK_EQ(q.pending, 0);
    CHECK_EQ(q.slot[0].ready, 0); /* abort never touches readiness */
    a6400_frame_release(&q, 0);
    CHECK_EQ(q.slot[0].ready, 1);

    /* Documented byte-free discovery admission: no prefix AND no expected
     * geometry. This is the only path that admits without SOI validation. */
    a6400_frame_queue_init(&q);
    {
        struct a6400_frame_candidate c = cand;

        c.prefix = NULL;
        c.prefix_len = 0;
        CHECK_EQ(a6400_frame_admit(&q, &c, &meta, 0, 0), 0);
        CHECK_EQ(q.pending, 1);
        a6400_frame_abort(&q);
        a6400_frame_release(&q, 0);
    }

    /* Unknown geometry with a valid prefix also admits (the caller records the
     * discovered dimensions separately). */
    CHECK_EQ(a6400_frame_admit(&q, &cand, &meta, 0, 0), 0);
    a6400_frame_abort(&q);
    a6400_frame_release(&q, 0);
    CHECK_EQ(q.dropped, 0);

    /* Defensive no-ops. */
    a6400_frame_release(&q, 2);
    a6400_frame_release(NULL, 0);
    a6400_frame_abort(NULL);
    a6400_frame_queue_init(NULL);
    CHECK_EQ(q.pending, 0);
}

/* ---- tests: control protocol ---------------------------------------------- */

static void test_crc_and_header(void)
{
    static const uint8_t digits[] = "123456789";
    uint8_t frame[80];
    struct a6400_ctl_header hdr;
    const uint8_t *payload = NULL;
    uint32_t payload_len = 0;
    uint32_t total;

    CHECK_EQ(a6400_ctl_crc16(digits, 9), 0x29b1); /* CCITT-FALSE check value */
    CHECK_EQ(a6400_ctl_crc16(NULL, 9), 0);
    CHECK_EQ(a6400_ctl_crc16(digits, 0), 0);

    total = a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_PING, 0x1234, NULL, 0);
    CHECK_EQ(total, 12);
    CHECK_EQ(frame[0], 0x40); /* magic LE */
    CHECK_EQ(frame[1], 0xa6);
    CHECK_EQ(frame[2], 1);    /* version */
    CHECK_EQ(frame[3], 0x00); /* PING */
    CHECK_EQ(frame[4], 0x34); /* seq LE */
    CHECK_EQ(frame[5], 0x12);
    CHECK_EQ(a6400_ctl_parse_request(frame, total, &hdr, &payload, &payload_len), 0);
    CHECK_EQ(hdr.seq, 0x1234);
    CHECK_EQ(hdr.opcode, A6400_CTL_PING);
    CHECK_EQ(hdr.payload_len, 0);
    CHECK_EQ(payload_len, 0);

    /* Payload round trip. */
    {
        struct a6400_ctl_set_value sv;
        uint8_t *view;

        sv.code = 0xd20du;
        sv.value = 0x00010064u;
        total = a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_SET_SHUTTER,
                                        7, &sv, (uint16_t)sizeof sv);
        CHECK_EQ(total, 20);
        CHECK_EQ(a6400_ctl_parse_request(frame, total, &hdr, &payload, &payload_len), 0);
        CHECK_EQ(payload_len, 8);
        CHECK_NE(payload, NULL);
        view = (uint8_t *)payload;
        CHECK_EQ(view[0], 0x0d);
        CHECK_EQ(view[1], 0xd2);
        CHECK_EQ(view[4], 0x64);
        CHECK_EQ(view[5], 0x00);
        CHECK_NE(hdr.crc16, 0);
    }

    /* Wrong magic. */
    total = a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_PING, 1, NULL, 0);
    frame[0] = 0x00;
    CHECK_EQ(a6400_ctl_parse_request(frame, total, &hdr, NULL, NULL),
             -A6400_CTL_STATUS_BAD_LENGTH);

    /* Wrong version. */
    total = a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_PING, 1, NULL, 0);
    frame[2] = 2;
    CHECK_EQ(a6400_ctl_parse_request(frame, total, &hdr, NULL, NULL),
             -A6400_CTL_STATUS_BAD_VERSION);

    /* Truncated and over-long frames. */
    total = a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_PING, 1, NULL, 0);
    CHECK_EQ(a6400_ctl_parse_request(frame, total - 1u, &hdr, NULL, NULL),
             -A6400_CTL_STATUS_BAD_LENGTH);
    CHECK_EQ(a6400_ctl_parse_request(frame, total + 1u, &hdr, NULL, NULL),
             -A6400_CTL_STATUS_BAD_LENGTH);
    CHECK_EQ(a6400_ctl_parse_request(NULL, total, &hdr, NULL, NULL),
             -A6400_CTL_STATUS_BAD_LENGTH);
    CHECK_EQ(a6400_ctl_parse_request(frame, total, NULL, NULL, NULL),
             -A6400_CTL_STATUS_BAD_LENGTH);

    /* payload_len above the contract maximum. */
    total = a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_PING, 1, NULL, 0);
    frame[6] = 0x41; /* 65 */
    frame[7] = 0x00;
    CHECK_EQ(a6400_ctl_parse_request(frame, total, &hdr, NULL, NULL),
             -A6400_CTL_STATUS_BAD_LENGTH);

    /* Corrupted CRC is rejected; a zero CRC disables the check. */
    {
        struct a6400_ctl_set_value sv;
        uint16_t saved;

        sv.code = 0x5010u;
        sv.value = 300;
        total = a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_SET_EXPOSURE,
                                        9, &sv, (uint16_t)sizeof sv);
        memcpy(&saved, frame + 10, sizeof saved);
        frame[10] ^= 0xffu;
        CHECK_EQ(a6400_ctl_parse_request(frame, total, &hdr, NULL, NULL),
                 -A6400_CTL_STATUS_BAD_LENGTH);
        frame[10] = 0;
        frame[11] = 0;
        CHECK_EQ(a6400_ctl_parse_request(frame, total, &hdr, NULL, NULL), 0);
        memcpy(frame + 10, &saved, sizeof saved);
        CHECK_EQ(a6400_ctl_parse_request(frame, total, &hdr, NULL, NULL), 0);
    }

    /* Builder refusals. */
    CHECK_EQ(a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_PING, 1, NULL,
                                     (uint16_t)(A6400_CTL_MAX_PAYLOAD + 1u)), 0);
    CHECK_EQ(a6400_ctl_build_request(frame, 8, A6400_CTL_PING, 1, NULL, 0), 0);
    CHECK_EQ(a6400_ctl_build_request(NULL, 80, A6400_CTL_PING, 1, NULL, 0), 0);
    CHECK_EQ(a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_PING, 1, NULL, 4), 0);
}

static void test_ack_builder(void)
{
    struct a6400_ctl_header hdr;
    uint8_t ackbuf[32];
    uint32_t n, n2;
    uint32_t crc_a, crc_b;

    memset(&hdr, 0, sizeof hdr);
    hdr.opcode = A6400_CTL_GET_STATS;
    hdr.seq = 0xbeef;

    n = a6400_ctl_build_ack(ackbuf, sizeof ackbuf, &hdr, A6400_CTL_STATUS_OK, 3, 7);
    CHECK_EQ(n, A6400_CTL_ACK_SIZE);
    CHECK_EQ(ackbuf[0], 0x40);
    CHECK_EQ(ackbuf[1], 0xa6);
    CHECK_EQ(ackbuf[2], 1);
    CHECK_EQ(ackbuf[3], A6400_CTL_GET_STATS);
    CHECK_EQ(ackbuf[4], 0xef);
    CHECK_EQ(ackbuf[5], 0xbe);
    CHECK_EQ(ackbuf[6], 0);
    CHECK_EQ(ackbuf[7], 0);
    CHECK_EQ(ackbuf[8], 3);
    CHECK_EQ(ackbuf[9], 0);
    CHECK_EQ(ackbuf[10], 7);
    memcpy(&crc_a, ackbuf + 14, sizeof crc_a);
    CHECK_NE(crc_a, 0);

    n2 = a6400_ctl_build_ack(ackbuf, sizeof ackbuf, &hdr, A6400_CTL_STATUS_OK, 3, 7);
    memcpy(&crc_b, ackbuf + 14, sizeof crc_b);
    CHECK_EQ(n, n2);
    CHECK_EQ(crc_a, crc_b);

    n2 = a6400_ctl_build_ack(ackbuf, sizeof ackbuf, &hdr, A6400_CTL_STATUS_OK, 3, 8);
    memcpy(&crc_b, ackbuf + 14, sizeof crc_b);
    CHECK_NE(crc_a, crc_b);

    CHECK_EQ(a6400_ctl_build_ack(ackbuf, 10, &hdr, 0, 0, 0), 0);
    CHECK_EQ(a6400_ctl_build_ack(NULL, sizeof ackbuf, &hdr, 0, 0, 0), 0);
    CHECK_EQ(a6400_ctl_build_ack(ackbuf, sizeof ackbuf, NULL, 0, 0, 0), 0);
}

static void test_routing(void)
{
    struct a6400_ctl_ack ack;
    struct a6400_ctl_action action;
    struct a6400_ctl_set_value sv;
    struct a6400_ctl_stream_config sc;
    struct a6400_ctl_af_trigger af;
    struct a6400_ctl_touch_focus tf;
    uint32_t latency = 33;
    const uint8_t *reply = NULL;
    uint32_t reply_len = 0;
    struct a6400_control_ctx *ctx;
    int rc;

    g_host_stats.frames_captured = 11;
    g_host_stats.frames_submitted = 9;
    g_host_stats.frames_dropped = 4;
    g_host_stats.frames_rejected = 2;
    g_host_stats.transport_errors = 1;
    g_host_stats.get_jpeg_polls = 40;
    g_host_stats.slot_size = 65536;
    g_host_stats.last_frame_size = 12345;
    g_host_stats.last_frame_seq = 77;

    memset(&ack, 0, sizeof ack);
    memset(&action, 0, sizeof action);

    /* -- session opcodes ---------------------------------------------------- */
    rc = route(A6400_CTL_PING, NULL, 0, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_OK);
    CHECK_EQ(ack.status, A6400_CTL_STATUS_OK);
    CHECK_EQ(ack.value, A6400_CTL_VERSION);
    CHECK_EQ(action.kind, A6400_CTL_ACTION_NONE);

    rc = route(A6400_CTL_DAEMON_INFO, NULL, 0, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_OK);
    CHECK_EQ(ack.detail, 1);

    rc = route(A6400_CTL_GET_CAPS, NULL, 0, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_OK);
    CHECK_EQ(ack.status, A6400_CTL_STATUS_OK);

    rc = route(A6400_CTL_GET_STATE, NULL, 0, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_OK);
    CHECK_EQ(ack.detail, 1); /* session_active host hook returns 1 */

    rc = route(A6400_CTL_GET_STATS, NULL, 0, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_OK);

    rc = route(A6400_CTL_SET_LATENCY, &latency, 4, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_OK);
    CHECK_EQ(ack.detail, 1); /* recorded only, not enforceable */
    CHECK_EQ(ack.value, 33);

    rc = route(A6400_CTL_DROP_STATS_RESET, NULL, 0, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_OK);
    CHECK_EQ(ack.value, 5);

    rc = route(A6400_CTL_STREAM_START, NULL, 0, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_OK);
    CHECK_EQ(action.kind, A6400_CTL_ACTION_STREAM_START);

    rc = route(A6400_CTL_STREAM_STOP, NULL, 0, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_OK);
    CHECK_EQ(action.kind, A6400_CTL_ACTION_STREAM_STOP);

    memset(&sc, 0, sizeof sc);
    sc.width = 1024;
    sc.height = 680;
    sc.fps = 30;
    sc.quality = 80;
    rc = route(A6400_CTL_STREAM_CONFIG, &sc, (uint16_t)sizeof sc, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_OK);
    CHECK_EQ(action.kind, A6400_CTL_ACTION_STREAM_CONFIG);
    CHECK_EQ(action.config.width, 1024);
    CHECK_EQ(action.config.height, 680);
    CHECK_EQ(action.config.fps, 30);
    CHECK_EQ(action.config.quality, 80);

    /* -- setting opcodes route to the host's PTP session, never applied ----- */
    sv.code = 0xd21eu; /* ISO */
    sv.value = 1000;
    rc = route(A6400_CTL_SET_ISO, &sv, (uint16_t)sizeof sv, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_ROUTE_PTP_HOST);
    CHECK_EQ(ack.status, A6400_CTL_STATUS_ROUTE_PTP_HOST);
    CHECK_EQ(ack.detail, 0x9207);
    CHECK_EQ(ack.value, 0xd21eu);

    sv.code = 0xd20du; /* shutter */
    sv.value = 0x00010064u;
    rc = route(A6400_CTL_SET_SHUTTER, &sv, (uint16_t)sizeof sv, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_ROUTE_PTP_HOST);
    CHECK_EQ(ack.value, 0xd20du);

    sv.code = 0x5007u; /* aperture */
    sv.value = 280;
    rc = route(A6400_CTL_SET_APERTURE, &sv, (uint16_t)sizeof sv, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_ROUTE_PTP_HOST);
    CHECK_EQ(ack.value, 0x5007u);

    sv.code = 0x5010u; /* exposure */
    sv.value = 300;
    rc = route(A6400_CTL_SET_EXPOSURE, &sv, (uint16_t)sizeof sv, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_ROUTE_PTP_HOST);
    CHECK_EQ(ack.value, 0x5010u);

    sv.code = 0x5005u; /* white balance */
    sv.value = 4;
    rc = route(A6400_CTL_SET_WB, &sv, (uint16_t)sizeof sv, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_ROUTE_PTP_HOST);
    CHECK_EQ(ack.value, 0x5005u);

    sv.code = 0x500au; /* focus mode */
    sv.value = 2;
    rc = route(A6400_CTL_SET_AF_MODE, &sv, (uint16_t)sizeof sv, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_ROUTE_PTP_HOST);
    CHECK_EQ(ack.value, 0x500au);

    /* STEP: signed notch, only the three physically confirmed codes. */
    sv.code = 0xd20du;
    sv.value = 0x00000001u;
    rc = route(A6400_CTL_STEP, &sv, (uint16_t)sizeof sv, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_ROUTE_PTP_HOST);
    CHECK_EQ(ack.detail, 0x9207);
    CHECK_EQ(ack.value, 0xd20du);

    sv.code = 0x5007u;
    sv.value = 0xffffffffu; /* -1 notch in the low byte */
    rc = route(A6400_CTL_STEP, &sv, (uint16_t)sizeof sv, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_ROUTE_PTP_HOST);
    CHECK_EQ(ack.value, 0x5007u);

    sv.code = 0xd200u; /* not a confirmed notch code */
    rc = route(A6400_CTL_STEP, &sv, (uint16_t)sizeof sv, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_BAD_VALUE);
    CHECK_NE(ack.status, A6400_CTL_STATUS_OK);

    /* Wrong property code for the opcode. */
    sv.code = 0xd20du;
    rc = route(A6400_CTL_SET_ISO, &sv, (uint16_t)sizeof sv, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_BAD_VALUE);

    /* -- no contract: AF trigger and touch focus --------------------------- */
    memset(&af, 0, sizeof af);
    af.half_press = 1;
    rc = route(A6400_CTL_AF_TRIGGER, &af, (uint16_t)sizeof af, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_CONTRACT_UNKNOWN);
    CHECK_EQ(ack.status, A6400_CTL_STATUS_CONTRACT_UNKNOWN);
    CHECK_EQ(ack.value, 0);

    memset(&tf, 0, sizeof tf);
    tf.x = 16000;
    tf.y = 16000;
    tf.width = 1024;
    tf.height = 680;
    rc = route(A6400_CTL_TOUCH_FOCUS, &tf, (uint16_t)sizeof tf, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_CONTRACT_UNKNOWN);

    /* -- unknown opcode ---------------------------------------------------- */
    sv.code = 0;
    sv.value = 0;
    rc = route(0x7f, &sv, (uint16_t)sizeof sv, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_UNKNOWN_OPCODE);
    CHECK_EQ(ack.status, A6400_CTL_STATUS_UNKNOWN_OPCODE);

    /* -- malformed payloads ------------------------------------------------ */
    rc = route(A6400_CTL_PING, &latency, 4, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_BAD_LENGTH);

    rc = route(A6400_CTL_SET_ISO, &latency, 4, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_BAD_LENGTH);

    sc.fps = 0;
    rc = route(A6400_CTL_STREAM_CONFIG, &sc, (uint16_t)sizeof sc, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_BAD_VALUE);

    sc.fps = 30;
    sc.quality = 101;
    rc = route(A6400_CTL_STREAM_CONFIG, &sc, (uint16_t)sizeof sc, NULL, &ack, &action);
    CHECK_EQ(rc, A6400_CTL_STATUS_BAD_VALUE);

    /* -- the invariant: a setting opcode can never report OK (applied) ----- */
    {
        static const uint8_t setting_ops[] = {
            A6400_CTL_SET_ISO, A6400_CTL_SET_SHUTTER, A6400_CTL_SET_APERTURE,
            A6400_CTL_SET_EXPOSURE, A6400_CTL_SET_WB, A6400_CTL_SET_AF_MODE,
            A6400_CTL_STEP, A6400_CTL_AF_TRIGGER, A6400_CTL_TOUCH_FOCUS
        };
        size_t i;

        for (i = 0; i < sizeof setting_ops; i++) {
            uint8_t op = setting_ops[i];

            sv.code = (op == A6400_CTL_SET_ISO)      ? 0xd21eu
                    : (op == A6400_CTL_SET_SHUTTER)  ? 0xd20du
                    : (op == A6400_CTL_SET_APERTURE) ? 0x5007u
                    : (op == A6400_CTL_SET_EXPOSURE) ? 0x5010u
                    : (op == A6400_CTL_SET_WB)       ? 0x5005u
                    : (op == A6400_CTL_SET_AF_MODE)  ? 0x500au
                    : 0xd20du;
            sv.value = 1;
            if (op == A6400_CTL_AF_TRIGGER) {
                rc = route(op, &af, (uint16_t)sizeof af, NULL, &ack, &action);
            } else if (op == A6400_CTL_TOUCH_FOCUS) {
                rc = route(op, &tf, (uint16_t)sizeof tf, NULL, &ack, &action);
            } else {
                rc = route(op, &sv, (uint16_t)sizeof sv, NULL, &ack, &action);
            }
            CHECK_NE(rc, A6400_CTL_STATUS_OK);
            CHECK_NE(ack.status, A6400_CTL_STATUS_OK);
        }
    }

    /* -- reply payloads ---------------------------------------------------- */
    ctx = make_ctx(NULL);
    CHECK_NE(ctx, NULL);
    if (ctx) {
        uint8_t frame[32];
        struct a6400_ctl_header hdr;
        uint32_t total;

        total = a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_GET_STATS, 1,
                                        NULL, 0);
        rc = a6400_ctl_parse_request(frame, total, &hdr, NULL, NULL);
        CHECK_EQ(rc, 0);
        rc = a6400_control_apply(ctx, &hdr, NULL, 0, &ack, &action);
        CHECK_EQ(rc, A6400_CTL_STATUS_OK);
        reply_len = a6400_control_last_reply(ctx, &reply);
        CHECK_EQ(reply_len, (uint32_t)sizeof(struct a6400_ctl_stats_reply));
        CHECK_NE(reply, NULL);
        if (reply && reply_len == sizeof(struct a6400_ctl_stats_reply)) {
            struct a6400_ctl_stats_reply stats;

            memcpy(&stats, reply, sizeof stats);
            CHECK_EQ(stats.frames_captured, 11);
            CHECK_EQ(stats.frames_submitted, 9);
            CHECK_EQ(stats.frames_dropped, 4);
            CHECK_EQ(stats.frames_rejected, 2);
            CHECK_EQ(stats.transport_errors, 1);
            CHECK_EQ(stats.last_frame_size, 12345);
            CHECK_EQ(stats.last_frame_seq, 77);
            CHECK_EQ(stats.slot_size, 65536);
        }

        /* DROP_STATS_RESET keeps the absolute counters but re-baselines the
         * control view. */
        total = a6400_ctl_build_request(frame, sizeof frame,
                                        A6400_CTL_DROP_STATS_RESET, 2, NULL, 0);
        rc = a6400_ctl_parse_request(frame, total, &hdr, NULL, NULL);
        CHECK_EQ(rc, 0);
        rc = a6400_control_apply(ctx, &hdr, NULL, 0, &ack, &action);
        CHECK_EQ(rc, A6400_CTL_STATUS_OK);
        g_host_stats.frames_dropped = 6;
        g_host_stats.frames_rejected = 5;
        g_host_stats.transport_errors = 3;

        total = a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_GET_STATS, 3,
                                        NULL, 0);
        rc = a6400_ctl_parse_request(frame, total, &hdr, NULL, NULL);
        CHECK_EQ(rc, 0);
        rc = a6400_control_apply(ctx, &hdr, NULL, 0, &ack, &action);
        CHECK_EQ(rc, A6400_CTL_STATUS_OK);
        reply_len = a6400_control_last_reply(ctx, &reply);
        CHECK_EQ(reply_len, (uint32_t)sizeof(struct a6400_ctl_stats_reply));
        if (reply && reply_len == sizeof(struct a6400_ctl_stats_reply)) {
            struct a6400_ctl_stats_reply stats;

            memcpy(&stats, reply, sizeof stats);
            CHECK_EQ(stats.frames_dropped, 2);   /* 6 - 4 */
            CHECK_EQ(stats.frames_rejected, 3);  /* 5 - 2 */
            CHECK_EQ(stats.transport_errors, 2); /* 3 - 1 */
        }

        reply_len = a6400_control_last_reply(NULL, &reply);
        CHECK_EQ(reply_len, 0);
        CHECK_EQ(reply, NULL);

        a6400_control_destroy(ctx);
    }

    a6400_control_destroy(NULL);
}

/* ---- tests: FIFO framing -------------------------------------------------- */

static void test_framing(void)
{
    struct a6400_ctl_frame_reader reader;
    uint8_t frame_a[16];
    uint8_t frame_b[16];
    uint8_t out[80];
    uint32_t out_len = 0;
    uint32_t a, b;

    a = a6400_ctl_build_request(frame_a, sizeof frame_a, A6400_CTL_PING, 1, NULL, 0);
    {
        uint32_t latency = 5;
        b = a6400_ctl_build_request(frame_b, sizeof frame_b, A6400_CTL_SET_LATENCY, 2,
                                    &latency, 4);
    }
    CHECK_EQ(a, 12);
    CHECK_EQ(b, 16);

    /* Split delivery: no frame until the header is complete. */
    a6400_ctl_reader_reset(&reader);
    a6400_ctl_reader_feed(&reader, frame_a, 6);
    CHECK_EQ(a6400_ctl_reader_next(&reader, out, sizeof out, &out_len), 0);
    a6400_ctl_reader_feed(&reader, frame_a + 6, a - 6);
    CHECK_EQ(a6400_ctl_reader_next(&reader, out, sizeof out, &out_len), 1);
    CHECK_EQ(out_len, 12);
    CHECK_EQ(out[3], A6400_CTL_PING);
    CHECK_EQ(a6400_ctl_reader_next(&reader, out, sizeof out, &out_len), 0);

    /* Two frames coalesced in one read. */
    a6400_ctl_reader_reset(&reader);
    {
        uint8_t both[32];

        memcpy(both, frame_a, a);
        memcpy(both + a, frame_b, b);
        a6400_ctl_reader_feed(&reader, both, a + b);
    }
    CHECK_EQ(a6400_ctl_reader_next(&reader, out, sizeof out, &out_len), 1);
    CHECK_EQ(out_len, 12);
    CHECK_EQ(a6400_ctl_reader_next(&reader, out, sizeof out, &out_len), 1);
    CHECK_EQ(out_len, 16);
    CHECK_EQ(out[3], A6400_CTL_SET_LATENCY);
    CHECK_EQ(a6400_ctl_reader_next(&reader, out, sizeof out, &out_len), 0);
    CHECK_EQ(reader.framed, 2);
    CHECK_EQ(reader.errors, 0);

    /* Garbage before a valid frame: one error, then resynchronise. */
    a6400_ctl_reader_reset(&reader);
    a6400_ctl_reader_feed(&reader, (const uint8_t *)"\xaa", 1);
    a6400_ctl_reader_feed(&reader, frame_a, a);
    CHECK_EQ(a6400_ctl_reader_next(&reader, out, sizeof out, &out_len), -1);
    CHECK_EQ(a6400_ctl_reader_next(&reader, out, sizeof out, &out_len), 1);
    CHECK_EQ(out_len, 12);
    CHECK_EQ(reader.errors, 1);

    /* An impossible payload length is discarded, not truncated. */
    a6400_ctl_reader_reset(&reader);
    {
        uint8_t bad[12];

        memcpy(bad, frame_a, sizeof bad);
        bad[6] = 0x41; /* 65 > A6400_CTL_MAX_PAYLOAD */
        bad[7] = 0x00;
        a6400_ctl_reader_feed(&reader, bad, sizeof bad);
    }
    CHECK_EQ(a6400_ctl_reader_next(&reader, out, sizeof out, &out_len), -1);
    CHECK_EQ(reader.errors, 1);
    CHECK_EQ(reader.len, 0);

    /* A caller buffer that is too small drops the frame explicitly. */
    a6400_ctl_reader_reset(&reader);
    a6400_ctl_reader_feed(&reader, frame_b, b);
    CHECK_EQ(a6400_ctl_reader_next(&reader, out, 8, &out_len), -1);
    CHECK_EQ(reader.errors, 1);

    /* A stream of non-magic bytes never grows without bound. */
    a6400_ctl_reader_reset(&reader);
    {
        uint8_t junk[128];
        int steps = 0;

        memset(junk, 0xff, sizeof junk);
        a6400_ctl_reader_feed(&reader, junk, sizeof junk);
        CHECK(reader.len <= (uint32_t)sizeof reader.buf);
        while (a6400_ctl_reader_next(&reader, out, sizeof out, &out_len) < 0 &&
               steps < 200) {
            steps++;
            if (reader.len == 0)
                break;
        }
        CHECK(steps < 200);
        CHECK(reader.errors > 0);
    }

    a6400_ctl_reader_reset(&reader);
    CHECK_EQ(reader.len, 0);
    CHECK_EQ(reader.framed, 0);
    CHECK_EQ(reader.errors, 0);
    a6400_ctl_reader_reset(NULL);
    a6400_ctl_reader_feed(NULL, frame_a, a);
    CHECK_EQ(a6400_ctl_reader_next(NULL, out, sizeof out, &out_len), -1);
}

/* ---- tests: end-to-end handle_frame + ack file --------------------------- */

static int read_file(const char *path, uint8_t *buf, uint32_t cap)
{
    FILE *f = fopen(path, "rb");
    size_t n;

    if (!f)
        return -1;
    n = fread(buf, 1, cap, f);
    (void)fclose(f);
    return (int)n;
}

static void test_handle_frame(const char *ack_path)
{
    struct a6400_control_ctx *ctx;
    struct a6400_ctl_action action;
    uint8_t frame[32];
    uint8_t ackfile[128];
    uint32_t total;
    int rc, n;

    if (!ack_path) {
        printf("SKIP handle_frame: no ack path supplied\n");
        return;
    }
    (void)remove(ack_path);
    ctx = make_ctx(ack_path);
    CHECK_NE(ctx, NULL);
    if (!ctx)
        return;

    total = a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_PING, 0x0102, NULL, 0);
    rc = a6400_control_handle_frame(ctx, frame, total, &action);
    CHECK_EQ(rc, 1);
    n = read_file(ack_path, ackfile, sizeof ackfile);
    CHECK_EQ(n, (int)A6400_CTL_ACK_SIZE);
    if (n >= (int)A6400_CTL_ACK_SIZE) {
        CHECK_EQ(ackfile[0], 0x40);
        CHECK_EQ(ackfile[1], 0xa6);
        CHECK_EQ(ackfile[3], A6400_CTL_PING);
        CHECK_EQ(ackfile[4], 0x02);
        CHECK_EQ(ackfile[5], 0x01);
        CHECK_EQ(ackfile[6], 0); /* status OK */
        CHECK_EQ(ackfile[7], 0);
    }

    total = a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_GET_CAPS, 0x0103,
                                    NULL, 0);
    rc = a6400_control_handle_frame(ctx, frame, total, &action);
    CHECK_EQ(rc, 1);
    n = read_file(ack_path, ackfile, sizeof ackfile);
    CHECK_EQ(n, (int)(A6400_CTL_ACK_SIZE + sizeof(struct a6400_ctl_caps_reply)));

    /* A malformed frame still gets an ack, with a specific status. */
    total = a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_PING, 0x0104, NULL, 0);
    frame[2] = 9; /* version */
    rc = a6400_control_handle_frame(ctx, frame, total, &action);
    CHECK_EQ(rc, 1);
    n = read_file(ack_path, ackfile, sizeof ackfile);
    CHECK_EQ(n, (int)A6400_CTL_ACK_SIZE);
    if (n >= (int)A6400_CTL_ACK_SIZE) {
        CHECK_EQ(ackfile[6], A6400_CTL_STATUS_BAD_VERSION);
        CHECK_EQ(ackfile[4], 0x04); /* seq echoed even on rejection */
    }

    /* Unknown opcode round trip through the file. */
    total = a6400_ctl_build_request(frame, sizeof frame, 0x7e, 0x0105, NULL, 0);
    rc = a6400_control_handle_frame(ctx, frame, total, &action);
    CHECK_EQ(rc, 1);
    n = read_file(ack_path, ackfile, sizeof ackfile);
    CHECK_EQ(n, (int)A6400_CTL_ACK_SIZE);
    if (n >= (int)A6400_CTL_ACK_SIZE)
        CHECK_EQ(ackfile[6], A6400_CTL_STATUS_UNKNOWN_OPCODE);

    /* Too-short frame is rejected without a crash and without an ack. */
    rc = a6400_control_handle_frame(ctx, frame, 4, &action);
    CHECK_EQ(rc, -A6400_CTL_STATUS_BAD_LENGTH);

    a6400_control_destroy(ctx);

    /* With no ack path, a request is refused explicitly rather than silently
     * dropped. */
    ctx = make_ctx(NULL);
    CHECK_NE(ctx, NULL);
    if (ctx) {
        total = a6400_ctl_build_request(frame, sizeof frame, A6400_CTL_PING, 1, NULL, 0);
        rc = a6400_control_handle_frame(ctx, frame, total, &action);
        CHECK_EQ(rc, -A6400_CTL_STATUS_NO_SPACE);

        /* Poll with no FIFO reports NO_SPACE, as documented. */
        rc = a6400_control_poll(ctx, &action);
        CHECK_EQ(rc, -A6400_CTL_STATUS_NO_SPACE);
        a6400_control_destroy(ctx);
    }
    CHECK_EQ(a6400_control_poll(NULL, &action), -A6400_CTL_STATUS_INTERNAL);
    (void)remove(ack_path);
}

/* ---- SD log policy (E0350) ----------------------------------------------- */

/* A realistic /proc/mounts excerpt from MSC: only internal-flash vfat mounts and
 * the /tmp_bt tmpfs, plus the SD partition already mounted at /tmp_bt/sd. */
static const char *const k_mounts =
    "rootfs / rootfs rw 0 0\n"
    "/dev/root / ext2 ro,relatime 0 0\n"
    "/dev/nflasha1 /tmp vfat rw,relatime 0 0\n"
    "/dev/nflasha2 /setting vfat rw,relatime 0 0\n"
    "tmpfs /tmp_bt tmpfs rw,size=1024k 0 0\n"
    "/dev/mmca1 /tmp_bt/sd vfat rw,relatime 0 0\n";

static const char *const k_mounts_escaped =
    "/dev/mmca1 /tmp_bt/card\\040one vfat rw 0 0\n"
    "/dev/mmca1 /tmp_bt/other vfat rw 0 0\n";

static void test_sd_policy(void)
{
    struct a6400_sd_window w;
    char dev[A6400_SD_PATH_MAX];
    char mp[A6400_SD_PATH_MAX];
    char small[4];

    /* Device: only the SD data partition (/dev/mmca1, block 250:11). The whole
     * card and every internal-flash node are refused, never mountable. */
    CHECK_EQ(a6400_sd_device_policy("/dev/mmca1"), A6400_SD_OK);
    CHECK_EQ(a6400_sd_device_policy("/dev/mmca"), A6400_SD_ERR_WRONG_DEVICE);
    CHECK_EQ(a6400_sd_device_policy("/dev/mmcblk0p1"), A6400_SD_ERR_WRONG_DEVICE);
    CHECK_EQ(a6400_sd_device_policy("/dev/sda1"), A6400_SD_ERR_WRONG_DEVICE);
    CHECK_EQ(a6400_sd_device_policy("/dev/nflasha"), A6400_SD_ERR_INTERNAL_FLASH);
    CHECK_EQ(a6400_sd_device_policy("/dev/nflasha1"), A6400_SD_ERR_INTERNAL_FLASH);
    CHECK_EQ(a6400_sd_device_policy("/dev/nflasha4"), A6400_SD_ERR_INTERNAL_FLASH);
    CHECK_EQ(a6400_sd_device_policy("mmca1"), A6400_SD_ERR_NOT_ABSOLUTE);
    CHECK_EQ(a6400_sd_device_policy("/dev/mmca1/"), A6400_SD_ERR_UNSAFE_PATH);
    CHECK_EQ(a6400_sd_device_policy("/dev//mmca1"), A6400_SD_ERR_UNSAFE_PATH);
    CHECK_EQ(a6400_sd_device_policy("/dev/../dev/mmca1"), A6400_SD_ERR_UNSAFE_PATH);
    CHECK_EQ(a6400_sd_device_policy(""), A6400_SD_ERR_ARG);
    CHECK_EQ(a6400_sd_device_policy(NULL), A6400_SD_ERR_ARG);

    /* Mount point: a child of the writable /tmp_bt tmpfs only. /tmp_bt itself is
     * refused because mounting over it hides the RAM log/receipt. */
    CHECK_EQ(a6400_sd_mountpoint_policy("/tmp_bt/sd"), A6400_SD_OK);
    CHECK_EQ(a6400_sd_mountpoint_policy("/tmp_bt"), A6400_SD_ERR_OUTSIDE_TMP_BT);
    CHECK_EQ(a6400_sd_mountpoint_policy("/mnt/sd"), A6400_SD_ERR_OUTSIDE_TMP_BT);
    CHECK_EQ(a6400_sd_mountpoint_policy("/setting"), A6400_SD_ERR_FORBIDDEN_MOUNT);
    CHECK_EQ(a6400_sd_mountpoint_policy("/etc"), A6400_SD_ERR_FORBIDDEN_MOUNT);
    CHECK_EQ(a6400_sd_mountpoint_policy("/system"), A6400_SD_ERR_FORBIDDEN_MOUNT);
    CHECK_EQ(a6400_sd_mountpoint_policy("/log"), A6400_SD_ERR_FORBIDDEN_MOUNT);
    CHECK_EQ(a6400_sd_mountpoint_policy("/tmp"), A6400_SD_ERR_FORBIDDEN_MOUNT);
    CHECK_EQ(a6400_sd_mountpoint_policy("/"), A6400_SD_ERR_FORBIDDEN_MOUNT);
    CHECK_EQ(a6400_sd_mountpoint_policy("/tmp_bt/sd/"), A6400_SD_ERR_UNSAFE_PATH);
    CHECK_EQ(a6400_sd_mountpoint_policy("/tmp_bt//sd"), A6400_SD_ERR_UNSAFE_PATH);
    CHECK_EQ(a6400_sd_mountpoint_policy("/tmp_bt/../etc"), A6400_SD_ERR_UNSAFE_PATH);
    CHECK_EQ(a6400_sd_mountpoint_policy("/tmp_bt/.sd"), A6400_SD_ERR_UNSAFE_PATH);
    CHECK_EQ(a6400_sd_mountpoint_policy("tmp_bt/sd"), A6400_SD_ERR_NOT_ABSOLUTE);
    CHECK_EQ(a6400_sd_mountpoint_policy(""), A6400_SD_ERR_ARG);
    CHECK_EQ(a6400_sd_mountpoint_policy(NULL), A6400_SD_ERR_ARG);

    /* 8.3 names (E0236): log, rotation and sentinel are strict 8.3. */
    CHECK_EQ(a6400_sd_name_is_83("A6400LD.LOG"), 1);
    CHECK_EQ(a6400_sd_name_is_83("A6400LD.1"), 1);
    CHECK_EQ(a6400_sd_name_is_83("A6400SNT.TMP"), 1);
    CHECK_EQ(a6400_sd_name_is_83("a6400ld.log"), 1);
    CHECK_EQ(a6400_sd_name_is_83("A6400LD"), 1);
    CHECK_EQ(a6400_sd_name_is_83("ABCDEFGHI.LOG"), 0);
    CHECK_EQ(a6400_sd_name_is_83("A6400LD.LOGX"), 0);
    CHECK_EQ(a6400_sd_name_is_83("A6400LD.LOG.LOG"), 0);
    CHECK_EQ(a6400_sd_name_is_83("A6400LD."), 0);
    CHECK_EQ(a6400_sd_name_is_83(".LOG"), 0);
    CHECK_EQ(a6400_sd_name_is_83("A6400 LD.LOG"), 0);
    CHECK_EQ(a6400_sd_name_is_83("A6400/LD.LOG"), 0);
    CHECK_EQ(a6400_sd_name_is_83(""), 0);
    CHECK_EQ(a6400_sd_name_is_83(NULL), 0);

    /* Mount window: consent requires BOTH flags; the window is PC Remote
     * confirmed and before INIT; a dry run and MSC are always refused. */
    memset(&w, 0, sizeof w);
    CHECK_EQ(a6400_sd_mount_window(&w), A6400_SD_ERR_NO_CONSENT);
    w.sd_log = 1;
    CHECK_EQ(a6400_sd_mount_window(&w), A6400_SD_ERR_NO_CONSENT);
    w.sd_mount = 1;
    CHECK_EQ(a6400_sd_mount_window(&w), A6400_SD_ERR_PCREMOTE_UNCONFIRMED);
    w.pcremote_confirmed = 1;
    CHECK_EQ(a6400_sd_mount_window(&w), A6400_SD_OK);
    w.dry_run = 1;
    CHECK_EQ(a6400_sd_mount_window(&w), A6400_SD_ERR_DRY_RUN);
    w.dry_run = 0;
    w.msc_mode = 1;
    CHECK_EQ(a6400_sd_mount_window(&w), A6400_SD_ERR_MSC);
    w.msc_mode = 0;
    w.init_started = 1;
    CHECK_EQ(a6400_sd_mount_window(&w), A6400_SD_ERR_AFTER_INIT);
    w.init_started = 0;
    w.streaming = 1;
    CHECK_EQ(a6400_sd_mount_window(&w), A6400_SD_ERR_STREAMING);
    w.streaming = 0;
    w.pcremote_confirmed = 0;
    CHECK_EQ(a6400_sd_mount_window(&w), A6400_SD_ERR_PCREMOTE_UNCONFIRMED);
    CHECK_EQ(a6400_sd_mount_window(NULL), A6400_SD_ERR_ARG);

    /* Rotation is bounded: 128 KiB per file, one rotated generation. */
    CHECK_EQ(a6400_sd_should_rotate(0, 100, 128), 0);
    CHECK_EQ(a6400_sd_should_rotate(100, 28, 128), 0);
    CHECK_EQ(a6400_sd_should_rotate(100, 29, 128), 1);
    CHECK_EQ(a6400_sd_should_rotate(128, 1, 128), 1);
    CHECK_EQ(a6400_sd_should_rotate(0, 129, 128), 1);
    CHECK_EQ(a6400_sd_should_rotate(0, 1, 0), 1);
    CHECK_EQ(a6400_sd_should_rotate(UINT32_MAX, 1, 128), 1);

    /* Sentinel round-trip is byte-exact; a short read can never pass. */
    CHECK_EQ(a6400_sd_sentinel_matches("A6400SD\n", 8, "A6400SD\n", 8), 1);
    CHECK_EQ(a6400_sd_sentinel_matches("A6400SD\n", 7, "A6400SD\n", 8), 0);
    CHECK_EQ(a6400_sd_sentinel_matches("A6400SD", 7, "A6400SD\n", 8), 0);
    CHECK_EQ(a6400_sd_sentinel_matches("A6400SD\n", 8, "A6400SD\n", 7), 0);
    CHECK_EQ(a6400_sd_sentinel_matches(NULL, 8, "A6400SD\n", 8), 0);
    CHECK_EQ(a6400_sd_sentinel_matches("A6400SD\n", 0, "A6400SD\n", 8), 0);

    /* /proc/mounts parsing: octal-escaped mount points are decoded, and every
     * comparison is exact (no substring match on the device). */
    memset(dev, 0, sizeof dev);
    memset(mp, 0, sizeof mp);
    CHECK_EQ(a6400_sd_parse_mount_line(
                 "/dev/mmca1 /tmp_bt/sd vfat rw 0 0", dev, sizeof dev,
                 mp, sizeof mp), 1);
    CHECK_EQ(strcmp(dev, "/dev/mmca1"), 0);
    CHECK_EQ(strcmp(mp, "/tmp_bt/sd"), 0);
    CHECK_EQ(a6400_sd_parse_mount_line("", dev, sizeof dev, mp, sizeof mp), 0);
    CHECK_EQ(a6400_sd_parse_mount_line("/dev/mmca1", dev, sizeof dev,
                                       mp, sizeof mp), 0);
    CHECK_EQ(a6400_sd_parse_mount_line(
                 "/dev/mmca1 /tmp_bt/card\\040one vfat rw 0 0", dev, sizeof dev,
                 mp, sizeof mp), 1);
    CHECK_EQ(strcmp(mp, "/tmp_bt/card one"), 0);
    CHECK_EQ(a6400_sd_parse_mount_line(
                 "/dev/mmca1 /tmp_bt/sd vfat rw 0 0", small, sizeof small,
                 mp, sizeof mp), A6400_SD_ERR_ARG);

    CHECK_EQ(a6400_sd_mounts_contains(k_mounts, "/dev/mmca1", "/tmp_bt/sd"), 1);
    CHECK_EQ(a6400_sd_mounts_contains(k_mounts, "/dev/mmca", "/tmp_bt/sd"), 0);
    CHECK_EQ(a6400_sd_mounts_contains(k_mounts, "/dev/mmca1", "/tmp_bt"), 0);
    CHECK_EQ(a6400_sd_mounts_contains(k_mounts, "/dev/mmca2", "/tmp_bt/sd"), 0);
    CHECK_EQ(a6400_sd_mounts_contains(k_mounts_escaped, "/dev/mmca1",
                                      "/tmp_bt/card one"), 1);
    CHECK_EQ(a6400_sd_mounts_contains(k_mounts_escaped, "/dev/mmca1",
                                      "/tmp_bt/card"), 0);
    CHECK_EQ(a6400_sd_mounts_contains(NULL, "/dev/mmca1", "/tmp_bt/sd"),
             A6400_SD_ERR_ARG);

    /* Conflict mask: 1 = device mounted somewhere, 2 = mount point taken. */
    CHECK_EQ(a6400_sd_mounts_conflict(k_mounts, "/dev/mmca1", "/tmp_bt/sd"), 3);
    CHECK_EQ(a6400_sd_mounts_conflict(k_mounts, "/dev/mmca1", "/tmp_bt/new"), 1);
    CHECK_EQ(a6400_sd_mounts_conflict(k_mounts, "/dev/mmca2", "/tmp_bt/sd"), 2);
    CHECK_EQ(a6400_sd_mounts_conflict(k_mounts, "/dev/mmca2", "/tmp_bt/new"), 0);
    CHECK_EQ(a6400_sd_mounts_conflict(k_mounts, "/dev/nflasha1", "/tmp_bt/new"), 1);
    CHECK_EQ(a6400_sd_mounts_conflict(k_mounts, "/dev/mmca2", "/tmp"), 2);
    CHECK_EQ(a6400_sd_mounts_conflict(NULL, "/dev/mmca1", "/tmp_bt/sd"),
             A6400_SD_ERR_ARG);

    /* Status initialisation keeps the documented defaults and never claims a
     * mount before one was verified. */
    {
        struct a6400_sd_status st;

        memset(&st, 0xff, sizeof st);
        a6400_sd_status_init(&st, 0, 0, NULL, NULL);
        CHECK_EQ(st.enabled, 0);
        CHECK_EQ(st.mount_requested, 0);
        CHECK_EQ(st.mounted, 0);
        CHECK_EQ(st.verified, 0);
        CHECK_EQ(st.sentinel_ok, 0);
        CHECK_EQ(st.sync_mode, -1);
        CHECK_EQ(st.unmount_rc, 1);
        CHECK_EQ(strcmp(st.device, "/dev/mmca1"), 0);
        CHECK_EQ(strcmp(st.mountpoint, "/tmp_bt/sd"), 0);
        a6400_sd_status_init(&st, 1, 1, "/dev/mmca1", "/tmp_bt/sd");
        CHECK_EQ(st.enabled, 1);
        CHECK_EQ(st.mount_requested, 1);
        CHECK_EQ(st.mounted, 0); /* init never fabricates a mount */
    }
}

/* ---- main ---------------------------------------------------------------- */

int main(int argc, char **argv)
{
    char ack_path[512];

    if (argc > 1)
        snprintf(ack_path, sizeof ack_path, "%s/host_ack.bin", argv[1]);
    else
        snprintf(ack_path, sizeof ack_path, "host_ack.bin");

    printf("a6400 daemon host tests\n");

    test_sof_parser();
    test_frame_queue();
    test_crc_and_header();
    test_ack_builder();
    test_routing();
    test_framing();
    test_handle_frame(ack_path);
    test_sd_policy();

    printf("checks: %d\n", g_checks);
    printf("failures: %d\n", g_failures);
    if (g_failures) {
        printf("RESULT: FAIL\n");
        return 1;
    }
    if (g_checks < 40) {
        printf("RESULT: FAIL (fewer than 40 assertions)\n");
        return 1;
    }
    printf("RESULT: PASS\n");
    return 0;
}
