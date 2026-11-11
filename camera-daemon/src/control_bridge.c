/* a6400 control bridge: 12-byte request header, opcode routing, FIFO source.
 *
 * WIRE FORMAT (a6400_control.h:34-37)
 *   request = [12-byte header][payload_len bytes], little-endian.
 *   ack     = [18-byte ack header][opcode-specific reply payload].
 * Every request gets exactly one ack with the same seq.
 *
 * REQUEST SOURCE
 *   The control FIFO carries a byte stream. The contract for writers is:
 *   each request is written with ONE write() of exactly header+payload bytes
 *   (<= PIPE_BUF = 4096, and payload <= A6400_CTL_MAX_PAYLOAD so a frame is at
 *   most 76 bytes). Records are therefore never interleaved; a reader may
 *   still see partial frames or several frames in one read(), so the daemon
 *   re-frames by the payload_len field (a6400_ctl_frame_reader, fail-closed on
 *   a bad magic/length).
 *
 * REPLY PATH
 *   Acks are not multiplexed onto the FIFO. They are written to `ack_path`
 *   (a regular file) as one frame per rewrite: lseek(0), write, ftruncate.
 *   That keeps reply framing trivial and matches the contract's "optional ack
 *   file rewrite" (a6400_control.h:188-190). The write is not fsync'ed: on the
 *   camera the path is tmpfs and durability across a reboot is not a property
 *   the protocol claims.
 *
 * ROUTING (a6400_control.h:20-33)
 *   Session opcodes are handled locally. Camera-setting opcodes are NOT applied
 *   here; they are answered A6400_CTL_STATUS_ROUTE_PTP_HOST because absolute
 *   0x9205 writes are acknowledged but not effective on this camera, while the
 *   signed notch 0x9207 is physically confirmed (CONTROL_IPC.md:16-20,
 *   docs/CINEMAHUD_STOCK_PTP.md:38-46). AF trigger and touch focus have no
 *   decoded code/property/mechanism in the evidence base and are answered
 *   A6400_CTL_STATUS_CONTRACT_UNKNOWN. Unknown opcodes are answered
 *   A6400_CTL_STATUS_UNKNOWN_OPCODE, never ignored: silent acceptance is how
 *   the stock absolute-write failure stayed hidden.
 *
 * "applied" IS NOT A FIELD
 *   There is no applied flag on the wire. The invariant enforced here is
 *   narrower and testable: ack.status == A6400_CTL_STATUS_OK is the only thing
 *   that can mean "carried out", and no setting opcode can ever produce it.
 *   `applied=1` would additionally require a real property readback
 *   (0x9209), which this daemon cannot perform today, so it is never claimed.
 *
 * PAYLOAD UNITS (mirrored from PTP, do not rescale anywhere)
 *   struct a6400_ctl_set_value { uint32_t code; uint32_t value; } is the
 *   payload of SET_ISO / SET_SHUTTER / SET_APERTURE / SET_EXPOSURE / SET_WB /
 *   AF_MODE / STEP. `code` is the firmware property code the host would have
 *   sent in PTP 0x9205/0x9207 and `value` is that property's own raw unit:
 *
 *     shutter   0xD20D  (numerator << 16) | denominator   (0x00010064 = 1/100)
 *     aperture  0x5007  f-number * 100                    (280 = f/2.8)
 *     EV        0x5010  millistop                         (300 = +0.3 EV)
 *     ISO       0xD21E  absolute ISO, 0xFFFFFF = Auto
 *     WB        0x5005  camera enumeration value (2 Auto, 4 Daylight, ...)
 *     AF mode   0x500A  camera enumeration value (1 MF, 2 AF-S, 3 AF-C, ...)
 *
 *   STEP carries the same 8-byte payload; the low byte of `value` is the
 *   signed one-byte notch and only the three physically confirmed notch codes
 *   are accepted (0xD20D, 0x5007, 0x5010). detail always carries the PTP
 *   opcode to use for the change (0x9207). The readback opcode is 0x9209; it
 *   is not returned in detail because detail is a single u16, and it is
 *   therefore documented here and in README.md instead of being smuggled into
 *   another field.
 */
#include "a6400_control.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

#include "a6400_daemon.h"
#include "a6400_internal.h"

/* Host-test portability: the Windows host build has no O_NONBLOCK/O_CLOEXEC.
 * The FIFO source is never opened by host tests (framing is exercised through
 * a6400_ctl_reader_*), so mapping them to 0 changes no tested behaviour and no
 * camera behaviour: the ARM build always uses the real flags. */
#ifdef _WIN32
#ifndef O_NONBLOCK
#define O_NONBLOCK 0
#endif
#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif
#endif

/* CCITT-FALSE PTP opcodes the host must use for camera settings. */
#define A6400_PTP_OP_NOTCH   0x9207u
#define A6400_PTP_OP_READBACK 0x9209u

#define A6400_PROP_SHUTTER   0xD20Du
#define A6400_PROP_APERTURE  0x5007u
#define A6400_PROP_EV        0x5010u
#define A6400_PROP_ISO       0xD21Eu
#define A6400_PROP_WB        0x5005u
#define A6400_PROP_AF_MODE   0x500Au

#define A6400_CTL_PATH_MAX   200u

/* The wire layout is fixed by a6400_control.h. Assert every size that is
 * encoded in the header comment so a future header edit cannot silently shift
 * a field position. */
_Static_assert(sizeof(struct a6400_ctl_header) == A6400_CTL_HEADER_SIZE,
               "a6400_ctl_header must be 12 bytes");
_Static_assert(sizeof(struct a6400_ctl_ack) == A6400_CTL_ACK_SIZE,
               "a6400_ctl_ack must be 18 bytes");
_Static_assert(sizeof(struct a6400_ctl_set_value) == 8u,
               "a6400_ctl_set_value must be 8 bytes");
_Static_assert(sizeof(struct a6400_ctl_af_trigger) == 4u,
               "a6400_ctl_af_trigger must be 4 bytes");
_Static_assert(sizeof(struct a6400_ctl_touch_focus) == 8u,
               "a6400_ctl_touch_focus must be 8 bytes");
_Static_assert(sizeof(struct a6400_ctl_stream_config) == 8u,
               "a6400_ctl_stream_config must be 8 bytes");
_Static_assert(sizeof(struct a6400_ctl_stats_reply) == 40u,
               "a6400_ctl_stats_reply must be 40 bytes");
_Static_assert(sizeof(struct a6400_ctl_caps_reply) == 16u,
               "a6400_ctl_caps_reply must be 16 bytes");

struct a6400_control_ctx {
    char  fifo_path[A6400_CTL_PATH_MAX];
    char  ack_path[A6400_CTL_PATH_MAX];
    int   fifo_configured;
    int   fifo_fd;
    int   fifo_open_rc;      /* 0 ok, negative errno when the open failed    */
    int   ack_fd;
    int   ring_requested;
    int   verbose;

    struct a6400_control_host host;
    struct a6400_ctl_frame_reader reader;

    uint32_t requests;
    uint32_t framing_errors;
    uint32_t ack_errors;
    uint32_t reply_len;
    uint8_t  reply[A6400_CTL_MAX_PAYLOAD];

    uint32_t latency_hint_ms;
    uint32_t resets;
    uint64_t start_ms;

    /* DROP_STATS_RESET baseline. The daemon's absolute counters keep running
     * (the receipt must stay cumulative); the control view reports deltas. */
    uint32_t base_dropped;
    uint32_t base_rejected;
    uint32_t base_transport_errors;
    uint32_t base_upload_errors;
    uint32_t base_polls;
};

/* ---- little-endian helpers (the wire is LE on every target) --------------- */

static uint16_t get16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void put16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xffu);
    p[1] = (uint8_t)(v >> 8);
}

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v & 0xffu);
    p[1] = (uint8_t)((v >> 8) & 0xffu);
    p[2] = (uint8_t)((v >> 16) & 0xffu);
    p[3] = (uint8_t)((v >> 24) & 0xffu);
}

/* ---- CRC-16/CCITT-FALSE --------------------------------------------------- */

static uint16_t crc16_update(uint16_t crc, const uint8_t *data, uint32_t len)
{
    uint32_t i;
    int bit;

    for (i = 0; i < len; i++) {
        crc ^= (uint16_t)((uint16_t)data[i] << 8);
        for (bit = 0; bit < 8; bit++) {
            if (crc & 0x8000u)
                crc = (uint16_t)((uint16_t)(crc << 1) ^ 0x1021u);
            else
                crc = (uint16_t)(crc << 1);
        }
    }
    return crc;
}

/* CRC over header bytes 0..9 followed by the payload. A stored value of 0
 * disables the check (a6400_control.h:97). */
static uint16_t request_crc(const uint8_t *buf, const uint8_t *payload,
                            uint16_t payload_len)
{
    uint16_t crc = crc16_update(0xffffu, buf, 10u);
    if (payload && payload_len)
        crc = crc16_update(crc, payload, payload_len);
    return crc;
}

uint16_t a6400_ctl_crc16(const uint8_t *data, uint32_t len)
{
    if (!data || !len)
        return 0;
    return crc16_update(0xffffu, data, len);
}

/* ---- request build / parse ------------------------------------------------ */

uint32_t a6400_ctl_build_request(uint8_t *buf, uint32_t cap, uint8_t opcode,
                                 uint16_t seq, const void *payload,
                                 uint16_t payload_len)
{
    if (!buf)
        return 0;
    if (payload_len > A6400_CTL_MAX_PAYLOAD)
        return 0;
    if (payload_len && !payload)
        return 0;
    if (cap < A6400_CTL_HEADER_SIZE + (uint32_t)payload_len)
        return 0;

    put16(buf + 0, (uint16_t)A6400_CTL_MAGIC);
    buf[2] = (uint8_t)A6400_CTL_VERSION;
    buf[3] = opcode;
    put16(buf + 4, seq);
    put16(buf + 6, payload_len);
    put16(buf + 8, 0u);   /* flags: unused by this daemon */
    put16(buf + 10, 0u);  /* CRC field starts zeroed; computed over the frame below */
    if (payload_len)
        memcpy(buf + A6400_CTL_HEADER_SIZE, payload, payload_len);
    put16(buf + 10, request_crc(buf, buf + A6400_CTL_HEADER_SIZE, payload_len));
    return A6400_CTL_HEADER_SIZE + (uint32_t)payload_len;
}

/* Returns 0 or a NEGATIVE A6400_CTL_STATUS_* value. The enum has no
 * BAD_MAGIC/BAD_CRC members, so a wrong magic or CRC is reported as
 * A6400_CTL_STATUS_BAD_LENGTH: it is a framing failure, and inventing a new
 * status value would break host implementations that only know the enum. */
int a6400_ctl_parse_request(const uint8_t *buf, uint32_t len,
                            struct a6400_ctl_header *hdr,
                            const uint8_t **payload, uint32_t *payload_len)
{
    uint16_t plen, stored, computed;

    if (payload)
        *payload = NULL;
    if (payload_len)
        *payload_len = 0;
    if (!buf || !hdr || len < A6400_CTL_HEADER_SIZE)
        return -A6400_CTL_STATUS_BAD_LENGTH;
    if (get16(buf) != (uint16_t)A6400_CTL_MAGIC)
        return -A6400_CTL_STATUS_BAD_LENGTH;
    if (buf[2] != (uint8_t)A6400_CTL_VERSION)
        return -A6400_CTL_STATUS_BAD_VERSION;

    plen = get16(buf + 6);
    if (plen > A6400_CTL_MAX_PAYLOAD)
        return -A6400_CTL_STATUS_BAD_LENGTH;
    if (len != A6400_CTL_HEADER_SIZE + (uint32_t)plen)
        return -A6400_CTL_STATUS_BAD_LENGTH;

    stored = get16(buf + 10);
    if (stored) {
        computed = request_crc(buf, buf + A6400_CTL_HEADER_SIZE, plen);
        if (stored != computed)
            return -A6400_CTL_STATUS_BAD_LENGTH;
    }

    hdr->magic = get16(buf);
    hdr->version = buf[2];
    hdr->opcode = buf[3];
    hdr->seq = get16(buf + 4);
    hdr->payload_len = plen;
    hdr->flags = get16(buf + 8);
    hdr->crc16 = stored;
    if (payload && plen)
        *payload = buf + A6400_CTL_HEADER_SIZE;
    if (payload_len)
        *payload_len = plen;
    return 0;
}

/* ---- ack build ------------------------------------------------------------ */

uint32_t a6400_ctl_build_ack(uint8_t *buf, uint32_t cap,
                             const struct a6400_ctl_header *hdr,
                             uint16_t status, uint16_t detail, uint32_t value)
{
    if (!buf || !hdr)
        return 0;
    if (cap < A6400_CTL_ACK_SIZE)
        return 0;

    put16(buf + 0, (uint16_t)A6400_CTL_MAGIC);
    buf[2] = (uint8_t)A6400_CTL_VERSION;
    buf[3] = hdr->opcode;
    put16(buf + 4, hdr->seq);
    put16(buf + 6, status);
    put16(buf + 8, detail);
    put32(buf + 10, value);
    /* crc_state is documented as "optional rolling stats word"; this daemon
     * uses it as an integrity word over the preceding 14 ack bytes so a host
     * can detect a torn rewrite of the ack file. 0 is not used: the field
     * would then be indistinguishable from "not computed". */
    put32(buf + 14, (uint32_t)crc16_update(0xffffu, buf, 14u));
    return A6400_CTL_ACK_SIZE;
}

/* ---- reply payloads ------------------------------------------------------- */

static void fill_stats_reply(struct a6400_control_ctx *c,
                             struct a6400_ctl_stats_reply *out)
{
    struct a6400_daemon_stats st;

    memset(&st, 0, sizeof st);
    if (c->host.get_stats)
        c->host.get_stats(c->host.ctx, &st);
    memset(out, 0, sizeof *out);
    out->frames_captured = st.frames_captured;
    out->frames_submitted = st.frames_submitted;
    /* Delta view since the last DROP_STATS_RESET. Unsigned wrap is impossible
     * for a monotonic counter, and a wrap would only understate a delta. */
    out->frames_dropped = st.frames_dropped - c->base_dropped;
    out->frames_rejected = st.frames_rejected - c->base_rejected;
    out->last_frame_size = st.last_frame_size;
    out->last_frame_seq = st.last_frame_seq;
    out->slot_size = st.slot_size;
    out->max_frame_payload = st.max_frame_payload;
    out->transport_errors = st.transport_errors - c->base_transport_errors;
    out->uptime_ms = (uint32_t)(a6400_now_ms() - c->start_ms);
}

static void fill_caps_reply(struct a6400_control_ctx *c,
                            struct a6400_ctl_caps_reply *out)
{
    memset(out, 0, sizeof *out);
    if (c->host.get_caps) {
        c->host.get_caps(c->host.ctx, out);
        return;
    }
    out->protocol_version = A6400_CTL_VERSION;
    out->camera_setting_route = (uint32_t)A6400_CTL_ROUTE_PTP;
    out->uvc_transport = 0;
    out->max_payload = A6400_CTL_MAX_PAYLOAD;
}

static int session_active(const struct a6400_control_ctx *c)
{
    if (!c->host.session_active)
        return 0;
    return c->host.session_active(c->host.ctx) ? 1 : 0;
}

/* ---- routing table -------------------------------------------------------- */

static uint32_t expected_setting_code(uint8_t opcode)
{
    switch (opcode) {
    case A6400_CTL_SET_ISO:      return A6400_PROP_ISO;
    case A6400_CTL_SET_SHUTTER:  return A6400_PROP_SHUTTER;
    case A6400_CTL_SET_APERTURE: return A6400_PROP_APERTURE;
    case A6400_CTL_SET_EXPOSURE: return A6400_PROP_EV;
    case A6400_CTL_SET_WB:       return A6400_PROP_WB;
    case A6400_CTL_SET_AF_MODE:  return A6400_PROP_AF_MODE;
    default:                     return 0;
    }
}

static int is_notch_code(uint32_t code)
{
    return code == A6400_PROP_SHUTTER || code == A6400_PROP_APERTURE ||
           code == A6400_PROP_EV;
}

static void ack_reset(struct a6400_ctl_ack *ack,
                      const struct a6400_ctl_header *hdr)
{
    memset(ack, 0, sizeof *ack);
    ack->magic = (uint16_t)A6400_CTL_MAGIC;
    ack->version = (uint8_t)A6400_CTL_VERSION;
    ack->opcode = hdr->opcode;
    ack->seq = hdr->seq;
}

/* Returns the ack status as a non-negative value (0..A6400_CTL_STATUS_INTERNAL)
 * or -1 on an internal argument error. Fills c->reply/reply_len when the
 * opcode has a reply payload. */
int a6400_control_apply(struct a6400_control_ctx *c,
                        const struct a6400_ctl_header *hdr,
                        const uint8_t *payload, uint32_t payload_len,
                        struct a6400_ctl_ack *ack,
                        struct a6400_ctl_action *action)
{
    uint32_t expected, code;
    struct a6400_ctl_set_value sv;

    if (!c || !hdr || !ack)
        return -1;
    ack_reset(ack, hdr);
    c->reply_len = 0;
    if (action) {
        memset(action, 0, sizeof *action);
        action->kind = A6400_CTL_ACTION_NONE;
    }
    if (payload_len > A6400_CTL_MAX_PAYLOAD || (payload_len && !payload)) {
        ack->status = (uint16_t)A6400_CTL_STATUS_BAD_LENGTH;
        return (int)ack->status;
    }

    switch ((enum a6400_ctl_opcode)hdr->opcode) {
    case A6400_CTL_PING:
        if (payload_len) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_LENGTH;
            break;
        }
        ack->status = (uint16_t)A6400_CTL_STATUS_OK;
        ack->detail = 0;
        ack->value = A6400_CTL_VERSION;
        break;

    case A6400_CTL_DAEMON_INFO:
        if (payload_len) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_LENGTH;
            break;
        }
        ack->status = (uint16_t)A6400_CTL_STATUS_OK;
        ack->detail = 1; /* reply layout revision */
        ack->value = (uint32_t)(a6400_now_ms() - c->start_ms);
        break;

    case A6400_CTL_GET_CAPS: {
        struct a6400_ctl_caps_reply caps;

        if (payload_len) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_LENGTH;
            break;
        }
        fill_caps_reply(c, &caps);
        /* c->reply is a byte array with alignment 1; copy through a naturally
         * aligned local instead of casting it to a struct pointer. */
        memcpy(c->reply, &caps, sizeof caps);
        c->reply_len = (uint32_t)sizeof caps;
        ack->status = (uint16_t)A6400_CTL_STATUS_OK;
        ack->value = A6400_CTL_VERSION;
        break;
    }

    case A6400_CTL_GET_STATE:
    case A6400_CTL_GET_STATS: {
        struct a6400_ctl_stats_reply stats;

        if (payload_len) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_LENGTH;
            break;
        }
        fill_stats_reply(c, &stats);
        memcpy(c->reply, &stats, sizeof stats);
        c->reply_len = (uint32_t)sizeof stats;
        ack->status = (uint16_t)A6400_CTL_STATUS_OK;
        ack->detail = (uint16_t)session_active(c);
        ack->value = (uint32_t)(a6400_now_ms() - c->start_ms);
        break;
    }

    case A6400_CTL_SET_LATENCY:
        if (payload_len != 4u) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_LENGTH;
            break;
        }
        if (c->verbose)
            fprintf(stderr, "[a6400_ctrl] latency hint received (recorded only)\n");
        c->latency_hint_ms = get32(payload);
        ack->status = (uint16_t)A6400_CTL_STATUS_OK;
        /* detail 1 = the hint was recorded. It does NOT bound transport
         * latency: nothing in this daemon can control glass-to-glass delay. */
        ack->detail = 1;
        ack->value = c->latency_hint_ms;
        break;

    case A6400_CTL_DROP_STATS_RESET: {
        struct a6400_daemon_stats st;

        if (payload_len) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_LENGTH;
            break;
        }
        memset(&st, 0, sizeof st);
        if (c->host.get_stats)
            c->host.get_stats(c->host.ctx, &st);
        c->base_dropped = st.frames_dropped;
        c->base_rejected = st.frames_rejected;
        c->base_transport_errors = st.transport_errors;
        c->base_upload_errors = st.upload_errors;
        c->base_polls = st.get_jpeg_polls;
        c->resets++;
        ack->status = (uint16_t)A6400_CTL_STATUS_OK;
        ack->detail = 0;
        ack->value = 5u; /* number of counters re-baselined */
        break;
    }

    case A6400_CTL_STREAM_START:
        if (payload_len) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_LENGTH;
            break;
        }
        ack->status = (uint16_t)A6400_CTL_STATUS_OK;
        ack->detail = 0;
        ack->value = 1u;
        if (action)
            action->kind = A6400_CTL_ACTION_STREAM_START;
        break;

    case A6400_CTL_STREAM_STOP:
        if (payload_len) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_LENGTH;
            break;
        }
        ack->status = (uint16_t)A6400_CTL_STATUS_OK;
        ack->detail = 0;
        ack->value = 1u;
        if (action)
            action->kind = A6400_CTL_ACTION_STREAM_STOP;
        break;

    case A6400_CTL_STREAM_CONFIG: {
        struct a6400_ctl_stream_config cfg;

        if (payload_len != (uint32_t)sizeof cfg) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_LENGTH;
            break;
        }
        memcpy(&cfg, payload, sizeof cfg);
        if (!cfg.fps || cfg.fps > 240u ||
            (cfg.width && cfg.width > 8192u) ||
            (cfg.height && cfg.height > 8192u) || cfg.quality > 100u) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_VALUE;
            break;
        }
        ack->status = (uint16_t)A6400_CTL_STATUS_OK;
        ack->detail = 0;
        ack->value = ((uint32_t)cfg.width << 16) | cfg.height;
        if (action) {
            action->kind = A6400_CTL_ACTION_STREAM_CONFIG;
            action->config = cfg;
        }
        break;
    }

    case A6400_CTL_SET_ISO:
    case A6400_CTL_SET_SHUTTER:
    case A6400_CTL_SET_APERTURE:
    case A6400_CTL_SET_EXPOSURE:
    case A6400_CTL_SET_WB:
    case A6400_CTL_SET_AF_MODE:
        if (payload_len != (uint32_t)sizeof sv) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_LENGTH;
            break;
        }
        memcpy(&sv, payload, sizeof sv);
        expected = expected_setting_code(hdr->opcode);
        if (sv.code != expected) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_VALUE;
            ack->detail = (uint16_t)A6400_PTP_OP_NOTCH;
            ack->value = sv.code; /* echo what the host actually sent */
            break;
        }
        /* Not applied here, and never reported as applied. */
        ack->status = (uint16_t)A6400_CTL_STATUS_ROUTE_PTP_HOST;
        ack->detail = (uint16_t)A6400_PTP_OP_NOTCH;
        ack->value = sv.code;
        break;

    case A6400_CTL_STEP:
        if (payload_len != (uint32_t)sizeof sv) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_LENGTH;
            break;
        }
        memcpy(&sv, payload, sizeof sv);
        code = sv.code;
        if (!is_notch_code(code)) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_VALUE;
            ack->detail = (uint16_t)A6400_PTP_OP_NOTCH;
            ack->value = code;
            break;
        }
        ack->status = (uint16_t)A6400_CTL_STATUS_ROUTE_PTP_HOST;
        ack->detail = (uint16_t)A6400_PTP_OP_NOTCH;
        ack->value = code;
        break;

    case A6400_CTL_AF_TRIGGER:
        /* No decoded code, property or mechanism exists (CONTROL_IPC.md:227-255,
         * USB_GADGET.md B9). Length is still validated so a malformed frame is
         * reported as such rather than as an unknown contract. */
        if (payload_len != (uint32_t)sizeof(struct a6400_ctl_af_trigger)) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_LENGTH;
            break;
        }
        ack->status = (uint16_t)A6400_CTL_STATUS_CONTRACT_UNKNOWN;
        ack->detail = 0;
        ack->value = 0;
        break;

    case A6400_CTL_TOUCH_FOCUS:
        if (payload_len != (uint32_t)sizeof(struct a6400_ctl_touch_focus)) {
            ack->status = (uint16_t)A6400_CTL_STATUS_BAD_LENGTH;
            break;
        }
        ack->status = (uint16_t)A6400_CTL_STATUS_CONTRACT_UNKNOWN;
        ack->detail = 0;
        ack->value = 0;
        break;

    default:
        ack->status = (uint16_t)A6400_CTL_STATUS_UNKNOWN_OPCODE;
        ack->detail = 0;
        ack->value = hdr->opcode;
        break;
    }

    return (int)ack->status;
}

/* ---- frame re-framing ----------------------------------------------------- */

void a6400_ctl_reader_reset(struct a6400_ctl_frame_reader *r)
{
    if (!r)
        return;
    memset(r, 0, sizeof *r);
}

void a6400_ctl_reader_feed(struct a6400_ctl_frame_reader *r,
                           const uint8_t *data, uint32_t n)
{
    uint32_t space;

    if (!r || !data || !n)
        return;
    space = (uint32_t)sizeof r->buf - r->len;
    if (n > space) {
        /* No complete frame fits any more: the stream is not the documented
         * one-write-per-request stream. Discard the excess and let next()
         * fail-closed on the malformed prefix. */
        r->errors++;
        n = space;
    }
    memcpy(r->buf + r->len, data, n);
    r->len += n;
}

int a6400_ctl_reader_next(struct a6400_ctl_frame_reader *r,
                          uint8_t *out, uint32_t out_cap, uint32_t *out_len)
{
    uint16_t payload_len;
    uint32_t total;

    if (!r)
        return -1;
    if (r->len < A6400_CTL_HEADER_SIZE)
        return 0;

    if (get16(r->buf) != (uint16_t)A6400_CTL_MAGIC) {
        /* Drop one byte and let the caller resynchronise on the next magic.
         * Never guess where the frame really started. */
        r->errors++;
        r->len--;
        memmove(r->buf, r->buf + 1, r->len);
        return -1;
    }

    payload_len = get16(r->buf + 6);
    if (payload_len > A6400_CTL_MAX_PAYLOAD) {
        r->errors++;
        r->len = 0;
        return -1;
    }
    total = A6400_CTL_HEADER_SIZE + (uint32_t)payload_len;
    if (r->len < total)
        return 0;

    if (!out || out_cap < total) {
        r->errors++;
        r->len -= total;
        memmove(r->buf, r->buf + total, r->len);
        return -1;
    }

    memcpy(out, r->buf, total);
    r->len -= total;
    memmove(r->buf, r->buf + total, r->len);
    if (out_len)
        *out_len = total;
    r->framed++;
    return 1;
}

/* ---- bridge lifecycle ----------------------------------------------------- */

static int copy_path(char *dst, size_t cap, const char *src)
{
    size_t n;

    if (!dst || !cap || !src)
        return -1;
    n = strlen(src);
    if (!n || n >= cap)
        return -1;
    memcpy(dst, src, n + 1u);
    return 0;
}

struct a6400_control_ctx *a6400_control_create(const struct a6400_control_config *cfg,
                                               const struct a6400_control_host *host)
{
    struct a6400_control_ctx *c;

    if (!cfg)
        return NULL;
    c = (struct a6400_control_ctx *)calloc(1, sizeof *c);
    if (!c)
        return NULL;

    c->fifo_fd = -1;
    c->ack_fd = -1;
    c->fifo_open_rc = 1; /* "not configured" */
    c->start_ms = a6400_now_ms();
    c->verbose = cfg->verbose;
    if (host)
        c->host = *host;
    a6400_ctl_reader_reset(&c->reader);

    if (cfg->fifo_path && cfg->fifo_path[0]) {
        if (copy_path(c->fifo_path, sizeof c->fifo_path, cfg->fifo_path) != 0) {
            free(c);
            return NULL;
        }
        c->fifo_configured = 1;
        /* O_NONBLOCK is mandatory: the frame loop must never block here. A
         * FIFO with no writer yet reads as 0, which poll() treats as "no
         * request" rather than as EOF. */
        c->fifo_fd = open(c->fifo_path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
        if (c->fifo_fd < 0) {
            c->fifo_open_rc = -errno;
            if (c->verbose)
                fprintf(stderr, "[a6400_ctrl] FIFO open failed: %s (errno=%d)\n",
                        c->fifo_path, errno);
        } else {
            c->fifo_open_rc = 0;
        }
    }

    if (cfg->ack_path && cfg->ack_path[0]) {
        if (copy_path(c->ack_path, sizeof c->ack_path, cfg->ack_path) != 0) {
            if (c->fifo_fd >= 0)
                close(c->fifo_fd);
            free(c);
            return NULL;
        }
        c->ack_fd = open(c->ack_path, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
        if (c->ack_fd < 0 && c->verbose)
            fprintf(stderr, "[a6400_ctrl] ack file open failed: %s (errno=%d)\n",
                    c->ack_path, errno);
    }

    if (cfg->enable_ring) {
        /* There is no decoded control-ring ioctl. Opening `video_node` here
         * would also be a SECOND open of the video node, which is exactly what
         * failed with -12/ENOMEM (E0339:52-57) and what the single-fd design
         * forbids. Refuse the ring explicitly instead of pretending. */
        c->ring_requested = 1;
        if (c->verbose)
            fprintf(stderr, "[a6400_ctrl] control ring requested but unsupported: "
                            "no decoded ioctl and the video fd is owned by the core\n");
    }

    return c;
}

void a6400_control_destroy(struct a6400_control_ctx *c)
{
    if (!c)
        return;
    if (c->fifo_fd >= 0)
        close(c->fifo_fd);
    if (c->ack_fd >= 0)
        close(c->ack_fd);
    free(c);
}

/* One whole frame in, one ack out. Exposed for host tests. */
int a6400_control_handle_frame(struct a6400_control_ctx *c,
                               const uint8_t *frame, uint32_t len,
                               struct a6400_ctl_action *action)
{
    struct a6400_ctl_header hdr;
    struct a6400_ctl_ack ack;
    const uint8_t *payload = NULL;
    uint32_t payload_len = 0;
    uint32_t ack_len, total;
    uint8_t out[A6400_CTL_ACK_SIZE + A6400_CTL_MAX_PAYLOAD];
    int rc;

    if (action) {
        memset(action, 0, sizeof *action);
        action->kind = A6400_CTL_ACTION_NONE;
    }
    if (!c || !frame || len < A6400_CTL_HEADER_SIZE)
        return -A6400_CTL_STATUS_BAD_LENGTH;

    /* Best-effort header for the ack even when the frame is rejected: seq and
     * opcode are the only fields a host needs to match the reply. */
    memset(&hdr, 0, sizeof hdr);
    hdr.magic = get16(frame);
    hdr.version = frame[2];
    hdr.opcode = frame[3];
    hdr.seq = get16(frame + 4);
    hdr.payload_len = get16(frame + 6);
    hdr.flags = get16(frame + 8);

    c->requests++;
    rc = a6400_ctl_parse_request(frame, len, &hdr, &payload, &payload_len);
    if (rc == 0) {
        rc = a6400_control_apply(c, &hdr, payload, payload_len, &ack, action);
        if (rc < 0) {
            ack_reset(&ack, &hdr);
            ack.status = (uint16_t)A6400_CTL_STATUS_INTERNAL;
            c->reply_len = 0;
        }
    } else {
        ack_reset(&ack, &hdr);
        ack.status = (uint16_t)(-rc);
        ack.detail = 0;
        ack.value = 0;
        c->reply_len = 0;
    }

    ack_len = a6400_ctl_build_ack(out, (uint32_t)sizeof out, &hdr, ack.status,
                                  ack.detail, ack.value);
    if (!ack_len)
        return -A6400_CTL_STATUS_INTERNAL;
    total = ack_len + c->reply_len;
    if (total > (uint32_t)sizeof out) {
        c->reply_len = 0;
        total = ack_len;
    }
    if (c->reply_len)
        memcpy(out + ack_len, c->reply, c->reply_len);

    if (c->ack_fd < 0) {
        c->ack_errors++;
        return -A6400_CTL_STATUS_NO_SPACE;
    }
    if (lseek(c->ack_fd, 0, SEEK_SET) != 0) {
        c->ack_errors++;
        return -A6400_CTL_STATUS_NO_SPACE;
    }
    {
        uint32_t written = 0;

        while (written < total) {
            ssize_t n = write(c->ack_fd, out + written, total - written);

            if (n < 0 && errno == EINTR)
                continue;
            if (n <= 0) {
                c->ack_errors++;
                return -A6400_CTL_STATUS_NO_SPACE;
            }
            written += (uint32_t)n;
        }
    }
    if (ftruncate(c->ack_fd, (off_t)total) != 0) {
        c->ack_errors++;
        return -A6400_CTL_STATUS_NO_SPACE;
    }
    return 1;
}

int a6400_control_poll(struct a6400_control_ctx *c, struct a6400_ctl_action *action)
{
    uint8_t frame[A6400_CTL_HEADER_SIZE + A6400_CTL_MAX_PAYLOAD];
    uint32_t frame_len = 0;

    if (action) {
        memset(action, 0, sizeof *action);
        action->kind = A6400_CTL_ACTION_NONE;
    }
    if (!c)
        return -A6400_CTL_STATUS_INTERNAL;

    for (;;) {
        int got = a6400_ctl_reader_next(&c->reader, frame, (uint32_t)sizeof frame,
                                        &frame_len);

        if (got == 1)
            return a6400_control_handle_frame(c, frame, frame_len, action);
        if (got < 0) {
            c->framing_errors++;
            continue; /* discard and try the next candidate frame */
        }
        if (c->fifo_fd < 0)
            return -A6400_CTL_STATUS_NO_SPACE;
        {
            uint8_t chunk[256];
            ssize_t n = read(c->fifo_fd, chunk, sizeof chunk);

            if (n < 0) {
                if (errno == EINTR)
                    continue;
                if (errno == EAGAIN || errno == EWOULDBLOCK)
                    return 0;
                return -A6400_CTL_STATUS_INTERNAL;
            }
            if (n == 0)
                return 0; /* no writer attached yet, or writer closed */
            a6400_ctl_reader_feed(&c->reader, chunk, (uint32_t)n);
        }
    }
}

uint32_t a6400_control_last_reply(const struct a6400_control_ctx *c,
                                  const uint8_t **payload)
{
    if (payload)
        *payload = c ? c->reply : NULL;
    return c ? c->reply_len : 0;
}
