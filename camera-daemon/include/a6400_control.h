/* a6400 control protocol (host <-> camera-side daemon) and control bridge.
 *
 * STATUS OF THIS CHANNEL (important, do not oversell it):
 *   The only control path physically verified on this camera while images flow
 *   is standard PTP over the PC Remote link. CONTROL_IPC.md (E0348 recon)
 *   establishes the exact semantics from live evidence:
 *     - handshake: OpenSession(0x1002)[1] -> 0x9201[1,0,0] -> 0x9201[2,0,0]
 *       -> 0x9202[0xC8] -> 0x9201[3,0,0];
 *     - settings read: 0x9209 returns the full 1730-byte property set;
 *     - absolute write 0x9205 is acknowledged but is NOT reliable: the camera's
 *       PC-Remote handler maps those codes to directional UI keys
 *       (InfraRemoteUsb::CtrlCode2InputKey), so an absolute write can be
 *       accepted and have no effect;
 *     - signed notch 0x9207 IS effective and was physically confirmed for
 *       shutter (1/100->1/125->1/100), aperture (f/2.8->f/3.2->f/2.8) and EV
 *       (0->+0.3->0), from Windows and from Android.
 *   PTP control round-trip measured ~10.2 ms per fetch (p8-status2.json:898),
 *   i.e. a host-PTP control costs 10-30 ms - it does not meet a <10 ms target.
 *
 *   Therefore this protocol is split by ROUTE, not by wishful thinking:
 *     - session opcodes (stream start/stop/config/state/stats/ping) are handled
 *       locally by the daemon;
 *     - camera-setting opcodes are answered with
 *       A6400_CTL_STATUS_ROUTE_PTP_HOST and the host applies them over the
 *       verified PTP path (notch 0x9207 for changes, 0x9209 for readback).
 *       They are NOT silently acknowledged as applied - `applied=1` may only
 *       follow a real readback.
 *     - AF trigger and touch focus have NO decoded code/property/mechanism
 *       anywhere in the evidence base and are answered with
 *       A6400_CTL_STATUS_CONTRACT_UNKNOWN.
 *   A future internal apply contract plugs into a6400_control_apply() without
 *   changing the wire format. The two candidate internal routes from
 *   CONTROL_IPC.md are: setting-service ObjMsg category 0x3A4A (receiver not
 *   yet identified) and CtrlCode2InputKey -> SendEvtToInput key injection.
 *
 * Wire format: one 12-byte header followed by payload_len bytes, little-endian.
 * Every request gets exactly one A6400_CTL_ACK back with the same seq.
 */
#ifndef A6400_CONTROL_H
#define A6400_CONTROL_H

#include <stdint.h>
#include <stddef.h>

#define A6400_CTL_MAGIC        0xa640u
#define A6400_CTL_VERSION      1u
#define A6400_CTL_HEADER_SIZE  12u
#define A6400_CTL_MAX_PAYLOAD  64u
#define A6400_CTL_MAX_INFLIGHT 4u

/* Opcodes: 0x0X session, 0x1X camera setting, 0x2X stream, 0x3X telemetry,
 * 0x4X transport diagnostics. */
enum a6400_ctl_opcode {
    A6400_CTL_PING            = 0x00,
    A6400_CTL_DAEMON_INFO     = 0x01,
    A6400_CTL_SET_ISO         = 0x10,
    A6400_CTL_SET_SHUTTER     = 0x11,
    A6400_CTL_SET_APERTURE    = 0x12,
    A6400_CTL_SET_EXPOSURE    = 0x13,
    A6400_CTL_SET_AF_MODE     = 0x14,
    A6400_CTL_AF_TRIGGER      = 0x15,
    A6400_CTL_TOUCH_FOCUS     = 0x16,
    A6400_CTL_SET_WB          = 0x17,
    A6400_CTL_STEP            = 0x18, /* signed notch, mirrors PTP 0x9207 */
    A6400_CTL_STREAM_START    = 0x20,
    A6400_CTL_STREAM_STOP     = 0x21,
    A6400_CTL_STREAM_CONFIG   = 0x22,
    A6400_CTL_GET_STATE       = 0x30,
    A6400_CTL_GET_STATS       = 0x31,
    A6400_CTL_GET_CAPS        = 0x32,
    A6400_CTL_SET_LATENCY     = 0x40,
    A6400_CTL_DROP_STATS_RESET = 0x41,
};

/* Status values. 0 means the request was handled and carried out. */
enum a6400_ctl_status {
    A6400_CTL_STATUS_OK              = 0,
    A6400_CTL_STATUS_BAD_VERSION     = 1,
    A6400_CTL_STATUS_BAD_LENGTH      = 2,
    A6400_CTL_STATUS_UNKNOWN_OPCODE  = 3,
    A6400_CTL_STATUS_ROUTE_PTP_HOST  = 4, /* host must use PTP; not applied here */
    A6400_CTL_STATUS_CONTRACT_UNKNOWN = 5,/* no decoded internal apply contract */
    A6400_CTL_STATUS_BUSY            = 6,
    A6400_CTL_STATUS_NOT_READY       = 7,
    A6400_CTL_STATUS_BAD_VALUE       = 8,
    A6400_CTL_STATUS_NO_SPACE        = 9,
    A6400_CTL_STATUS_INTERNAL        = 10,
};

struct a6400_ctl_header {
    uint16_t magic;
    uint8_t  version;
    uint8_t  opcode;
    uint16_t seq;
    uint16_t payload_len;
    uint16_t flags;
    uint16_t crc16;      /* CCITT-16 over bytes 0..9 and the payload; 0 disables */
} __attribute__((packed));

struct a6400_ctl_ack {
    uint16_t magic;
    uint8_t  version;
    uint8_t  opcode;
    uint16_t seq;
    uint16_t status;
    uint16_t detail;     /* implementation-defined per status */
    uint32_t value;      /* e.g. applied property code / frame counter */
    uint32_t crc_state;  /* optional rolling stats word */
} __attribute__((packed));

/* Payload views; all little-endian, packed. */
struct a6400_ctl_set_value {
    uint32_t code;       /* firmware property code, as used by PTP 0x9205 */
    uint32_t value;      /* raw value in the property's own units        */
};
struct a6400_ctl_af {
    uint8_t  mode;       /* 0 = MF, 1 = AF-S, 2 = AF-C, 3 = DMF (host mapping) */
    uint8_t  reserved[3];
};
struct a6400_ctl_af_trigger {
    uint8_t  half_press; /* 1 = half press, 0 = release */
    uint8_t  reserved[3];
};
struct a6400_ctl_touch_focus {
    uint16_t x;          /* normalized 0..32767 over the liveview width  */
    uint16_t y;          /* normalized 0..32767 over the liveview height */
    uint16_t width;      /* liveview width used for normalization        */
    uint16_t height;     /* liveview height used for normalization       */
};
struct a6400_ctl_stream_config {
    uint16_t width;      /* requested geometry; accepted value is probed */
    uint16_t height;
    uint8_t  fps;
    uint8_t  quality;    /* 0 = default, 1..100 hinted JPEG quality */
    uint16_t reserved;
};
struct a6400_ctl_stats_reply {
    uint32_t frames_captured;
    uint32_t frames_submitted;
    uint32_t frames_dropped;
    uint32_t frames_rejected;
    uint32_t last_frame_size;
    uint32_t last_frame_seq;
    uint32_t slot_size;
    uint32_t max_frame_payload;
    uint32_t transport_errors;
    uint32_t uptime_ms;
};
struct a6400_ctl_caps_reply {
    uint32_t protocol_version;
    uint32_t camera_setting_route;  /* enum a6400_ctl_route */
    uint32_t uvc_transport;         /* 1 = UVC push armed, 0 = not */
    uint32_t max_payload;
};
enum a6400_ctl_route {
    A6400_CTL_ROUTE_PTP = 1,        /* camera settings are applied by the host over PTP */
    A6400_CTL_ROUTE_INTERNAL = 2,   /* decoded internal contract exists (future) */
};

/* ---- control bridge context --------------------------------------------- */

/* Session actions the daemon must carry out; returned by a6400_control_poll. */
enum a6400_ctl_action_kind {
    A6400_CTL_ACTION_NONE = 0,
    A6400_CTL_ACTION_STREAM_START,
    A6400_CTL_ACTION_STREAM_STOP,
    A6400_CTL_ACTION_STREAM_CONFIG,
    A6400_CTL_ACTION_SHUTDOWN_REQUEST,
};

struct a6400_ctl_action {
    enum a6400_ctl_action_kind kind;
    struct a6400_ctl_stream_config config;
};

struct a6400_daemon_stats; /* defined in a6400_daemon.h */

/* Host-facing hooks implemented by the daemon core. */
struct a6400_control_host {
    void  *ctx;
    void (*get_stats)(void *ctx, struct a6400_daemon_stats *out);
    void (*get_caps)(void *ctx, struct a6400_ctl_caps_reply *out);
    int  (*session_active)(void *ctx);
};

struct a6400_control_config {
    const char *fifo_path;   /* request FIFO; NULL disables the FIFO source  */
    const char *ack_path;    /* optional reply path (regular file rewrite)   */
    const char *video_node;  /* video node for the optional control ring    */
    int         enable_ring; /* 0 = FIFO only (default), 1 = try ring ioctl */
    int         verbose;
};

struct a6400_control_ctx;

/* Creates the bridge. Returns NULL on allocation failure. Missing FIFO/ring is
 * not fatal: the bridge stays usable and reports NO_SPACE when a source is
 * unavailable. */
struct a6400_control_ctx *a6400_control_create(const struct a6400_control_config *cfg,
                                               const struct a6400_control_host *host);

void a6400_control_destroy(struct a6400_control_ctx *c);

/* Non-blocking. Reads at most one pending request, validates it, replies and
 * fills `action` (ACTION_NONE when the request was purely informational).
 * Returns 0 when no request was pending, 1 when one was processed, and a
 * negative A6400_CTL_STATUS_* style code on a fatal source error. */
int a6400_control_poll(struct a6400_control_ctx *c, struct a6400_ctl_action *action);

/* Builds a request frame into `buf` (capacity `cap`); returns total length or
 * 0 when it does not fit. Used by unit tests and by on-camera tooling. */
uint32_t a6400_ctl_build_request(uint8_t *buf, uint32_t cap, uint8_t opcode,
                                 uint16_t seq, const void *payload, uint16_t payload_len);

/* Parses a request buffer. Returns 0 on success, negative status on error. */
int a6400_ctl_parse_request(const uint8_t *buf, uint32_t len,
                            struct a6400_ctl_header *hdr,
                            const uint8_t **payload, uint32_t *payload_len);

/* Builds the ack for a parsed request into `buf` (capacity `cap`). */
uint32_t a6400_ctl_build_ack(uint8_t *buf, uint32_t cap,
                             const struct a6400_ctl_header *hdr,
                             uint16_t status, uint16_t detail, uint32_t value);

/* CCITT-FALSE CRC-16 (poly 0x1021, init 0xffff) over `len` bytes; 0x0000 when
 * `data` is NULL or len is 0. */
uint16_t a6400_ctl_crc16(const uint8_t *data, uint32_t len);

/* Applies a request and produces the ack fields. Exposed for tests; the
 * routing table lives here. */
int a6400_control_apply(struct a6400_control_ctx *c,
                        const struct a6400_ctl_header *hdr,
                        const uint8_t *payload, uint32_t payload_len,
                        struct a6400_ctl_ack *ack,
                        struct a6400_ctl_action *action);

#endif /* A6400_CONTROL_H */
