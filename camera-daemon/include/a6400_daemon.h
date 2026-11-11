/* a6400 live-view daemon: configuration, runtime statistics and lifecycle.
 *
 * The daemon is the camera-side half of the composite UVC track (E0346 track
 * B). It merges the two pieces that have only ever been run separately:
 *   - the session runner (freeze -> entry-hook publish -> INIT -> hold -> STOP
 *     -> freeze -> retire): tools/native_camera/uvc_ptp_feed_runner.c:160-297
 *   - the 30 fps sensor feeder (OSAL -> DMM rule 5 -> SET_PATH -> GET_JPEG ->
 *     DMM open -> copy -> WAIT -> UPDATE): tools/native_camera/uvc_sensor_feeder_30fps.c
 *
 * The single-fd constraint is the whole point: the second open() of the video
 * node failed with -12/ENOMEM (E0339:52-57), so the feeder must run inside the
 * process that owns the fd - this daemon.
 *
 * STATUS: offline implementation. It has NOT been run on a camera. It is gated
 * on (a) a transport-enabled composite module that is auditable and streams,
 * (b) the E0346 stage-2/3 physical tests, (c) explicit user authorization for
 * any camera-module session. The PTP path (Android track A) needs none of it.
 */
#ifndef A6400_DAEMON_H
#define A6400_DAEMON_H

#include <stdint.h>
#include <stddef.h>

#include "a6400_control.h"

#define A6400_DAEMON_MAX_TIDS 512
#define A6400_DAEMON_TARGET_PID 149

enum a6400_daemon_phase {
    A6400_PHASE_IDLE = 0,
    A6400_PHASE_WAIT_PCREMOTE,
    A6400_PHASE_FREEZE,
    A6400_PHASE_HOOK_PUBLISHED,
    A6400_PHASE_INIT,
    A6400_PHASE_BUFFER_READY,
    A6400_PHASE_STREAMING,
    A6400_PHASE_STOPPING,
    A6400_PHASE_RETIRED,
    A6400_PHASE_FAILED,
};

struct a6400_daemon_config {
    const char *device_path;      /* default /tmp_bt/video */
    const char *log_path;         /* default /tmp_bt/a6400_lived.jsonl */
    const char *receipt_path;     /* default /tmp_bt/a6400_lived_receipt.json */
    const char *control_fifo;     /* default /tmp_bt/a6400_ctrl.fifo */
    const char *control_ack;      /* default /tmp_bt/a6400_ctrl.ack */
    int         wait_pcremote;    /* 1 = require 0x054c:0x0caa before INIT */
    int         wait_timeout_s;   /* default 120 */
    int         duration_s;       /* 0 = until SIGINT */
    int         target_pid;       /* default 149 */
    int         expected_width;   /* 0 = accept the first frame's dimensions */
    int         expected_height;
    int         fps;              /* pacing hint, default 30 */
    int         comp_level;       /* SET_PATH component level, default 5 */
    int         path_width;       /* SET_PATH width hint, default 1280 */
    int         dry_run;          /* discover + validate, never INIT/UPDATE   */
    int         verbose;
    /* Optional crash-safe SD log (E0350). Both flags default OFF; mounting also
     * requires explicit consent (--sd-mount) and the PC Remote window. */
    int         sd_log;           /* --sd-log: mirror JSONL + receipt to SD   */
    int         sd_mount;         /* --sd-mount: explicit mount consent       */
    const char *sd_dev;           /* default /dev/mmca1 (SD partition)        */
    const char *sd_mountpoint;    /* default /tmp_bt/sd; must be under /tmp_bt/ */
};

struct a6400_daemon_stats {
    uint64_t started_monotonic_ns;
    uint32_t phase;
    uint32_t session_active;
    uint32_t frames_captured;
    uint32_t frames_submitted;
    uint32_t frames_dropped;
    uint32_t frames_rejected;
    uint32_t transport_errors;
    uint32_t get_jpeg_polls;
    uint32_t get_jpeg_empty;
    uint32_t last_frame_size;
    uint32_t last_frame_seq;
    uint32_t last_width;
    uint32_t last_height;
    uint32_t slot_size;
    uint32_t max_frame_payload;
    uint32_t upload_errors;
    uint32_t wait_ms_max;
    uint32_t accept_geometry;   /* 0 = not yet discovered */
};

/* Runs the whole lifecycle; blocks until done. Returns 0 on a clean stop,
 * positive when a bounded stage failed, negative on a fatal internal error.
 * The receipt file is written before returning in every path. */
int a6400_daemon_run(const struct a6400_daemon_config *cfg);

/* Fills the receipt JSON (phase, stats, module presence, stop attestation
 * result, monotonic uptime) into buf; returns length or 0 when it does not fit.
 * Exposed so the control bridge and host tooling can fetch it. */
uint32_t a6400_daemon_receipt(const struct a6400_daemon_stats *st,
                              const struct a6400_daemon_config *cfg,
                              char *buf, uint32_t cap);

/* Monotonic milliseconds; never uses wall-clock time for pacing. */
uint64_t a6400_now_ms(void);
int64_t  a6400_now_ns(void);

#endif /* A6400_DAEMON_H */
