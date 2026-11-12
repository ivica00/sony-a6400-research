/* Internal interfaces shared between the daemon's translation units.
 *
 * This is NOT one of the Lead's contract headers and it is NOT a wire ABI.
 * It exists so that src/runner.c and the control FIFO re-framer in
 * src/control.c can be tested and linked without pulling in main.c. Every
 * declaration here was added by the camera-daemon implementation and is
 * reported in README.md ("Files added beyond the deliverable list").
 *
 * Nothing here may be used by host tooling as a protocol definition: the wire
 * definitions live in a6400_control.h only.
 */
#ifndef A6400_INTERNAL_H
#define A6400_INTERNAL_H

#include <signal.h>
#include <stdint.h>

#include "a6400_control.h"
#include "a6400_daemon.h"

/* ---- ptrace freeze / entry-hook lifecycle (src/runner.c) ----------------- */
/* The freeze algorithm is a transcription of tools/native_camera/native_freeze.h
 * (bounded 512-TID capture barrier for PID 149's CPU threads, not for DMA) and
 * the publish/retire sequence of uvc_ptp_feed_runner.c:160-297. */
struct a6400_runner {
    int      uvc_fd;      /* borrowed descriptor; owned by the daemon core    */
    int      target_pid;  /* default 149 (A6400_DAEMON_TARGET_PID)            */
    int      frozen;      /* 1 between a successful freeze and resume         */
    int      published;   /* 1 once the entry hook publish was attested       */
    uint32_t tid_count;
    uint32_t tids[A6400_DAEMON_MAX_TIDS];
    uint8_t  owned[A6400_DAEMON_MAX_TIDS];    /* PTRACE_ATTACH succeeded    */
    uint8_t  stopped[A6400_DAEMON_MAX_TIDS];  /* waitpid saw WIFSTOPPED     */
    uint32_t last_freeze_ms;
    uint32_t attest_completed; /* out: TIDs the module verified last time   */
    int32_t  attest_error;     /* out: module-side error, 0 when clean      */
};

/* Session status words {phase, pin, hooks, error}; all zero means IDLE /
 * unpinned / no descriptor hooks / no retained error, which is the only state
 * that permits hook retirement (uvc_ptp_runner_stop.h:7-19). This is the
 * ioctl the physically run runner used at uvc_ptp_feed_runner.c:66; it is a
 * session state query, distinct from A6400_UVC_IOCTL_QUERY_USB_STATE. */
#define A6400_UVC_IOCTL_QUERY_SESSION_STATE 0x8010f022u

void a6400_runner_init(struct a6400_runner *r, int uvc_fd, int target_pid);
int  a6400_runner_freeze(struct a6400_runner *r);
int  a6400_runner_resume(struct a6400_runner *r);
int  a6400_runner_publish_hook(struct a6400_runner *r);
int  a6400_runner_retire_hook(struct a6400_runner *r);

/* STOP + state-query attestation. Returns 1 only when STOP succeeded and all
 * four state words are zero; 0 otherwise. Never retries. */
int  a6400_runner_stop_verified(int uvc_fd, int32_t state[4]);

/* Read-only session status query (0x8010f022), no side effect. Returns 1 and
 * fills `state` when the ioctl answered; 0 otherwise (state stays -1..-1 so a
 * caller can never mistake an unanswered read for an all-zero session). This is
 * the only module-supplied diagnostic available after a failed STOP (E0358). */
int  a6400_runner_query_session_state(int uvc_fd, int32_t state[4]);

/* Bounded recovery primitive for a failed stop attestation: exactly ONE retry
 * of STOP (0x0000e001), which re-enters the module's ordered 9-phase teardown,
 * followed by the same status query the clean gate uses. Returns 1 only when
 * the retry returned 0 AND the follow-up state is all zero. `stop_rc` receives
 * the ioctl result (0 or -errno) and `state_valid` whether the query answered.
 * A refused retry is reported, never retried again. */
int  a6400_runner_retry_stop(int uvc_fd, int32_t state[4], int *stop_rc,
                             int *state_valid);

/* Parks the caller without retrying cleanup. Returns 1 when *stop_flag became
 * non-zero (a signal handler asked us to leave), 0 only if stop_flag is NULL
 * (then this call does not return). */
int  a6400_runner_park(volatile sig_atomic_t *stop_flag);

/* ---- control request re-framing (src/control.c) -------------------------- */
/* Requests arrive on the control FIFO as a byte stream: each request is
 * exactly A6400_CTL_HEADER_SIZE + payload_len bytes written atomically
 * (<= PIPE_BUF), but a read() may return a partial frame or several frames
 * coalesced. This reader rebuilds frames without allocating. */
struct a6400_ctl_frame_reader {
    uint8_t  buf[A6400_CTL_HEADER_SIZE + A6400_CTL_MAX_PAYLOAD];
    uint32_t len;
    uint32_t framed;   /* complete frames produced                        */
    uint32_t errors;   /* frames/bytes discarded by resynchronisation      */
};

void a6400_ctl_reader_reset(struct a6400_ctl_frame_reader *r);

/* Appends up to `n` bytes. Bytes that cannot fit while no complete frame is
 * present are discarded and counted as an error (framing is fail-closed). */
void a6400_ctl_reader_feed(struct a6400_ctl_frame_reader *r,
                           const uint8_t *data, uint32_t n);

/* Extracts one complete frame. Returns 1 and writes the frame to `out`
 * (requires out_cap >= frame length), 0 when more bytes are needed, and -1
 * when a malformed frame was discarded (the caller may call again). */
int a6400_ctl_reader_next(struct a6400_ctl_frame_reader *r,
                          uint8_t *out, uint32_t out_cap, uint32_t *out_len);

/* Processes one complete request frame: parse, route, write the ack frame to
 * the configured ack path and fill `action`. Returns 1 when handled, or a
 * negative A6400_CTL_STATUS_* value when the reply path is unavailable.
 * a6400_control_poll() is the FIFO wrapper around this; it is exposed so host
 * tests can drive the routing table without a FIFO. */
int a6400_control_handle_frame(struct a6400_control_ctx *c,
                               const uint8_t *frame, uint32_t len,
                               struct a6400_ctl_action *action);

/* Reply payload produced by the last handled frame (a6400_ctl_stats_reply /
 * a6400_ctl_caps_reply / empty). Exposed for host tests. */
uint32_t a6400_control_last_reply(const struct a6400_control_ctx *c,
                                  const uint8_t **payload);

/* Size of struct a6400_ctl_ack on the wire (packed: 18 bytes). */
#define A6400_CTL_ACK_SIZE 18u

#endif /* A6400_INTERNAL_H */
