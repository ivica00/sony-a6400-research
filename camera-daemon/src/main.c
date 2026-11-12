/* a6400 live-view daemon core: one process, one video fd.
 *
 * This is the merge of the two pieces that have only ever been run separately:
 * the composite session runner (freeze PID 149 -> publish entry hook -> INIT ->
 * hold -> STOP -> freeze -> retire) and the 30 fps sensor feeder (OSAL -> DMM
 * rule 5 -> SET_PATH -> GET_JPEG -> DMM open -> WAIT -> UPDATE). The single-fd
 * constraint is the reason for the merge: a second open() of the video node
 * failed with -12/ENOMEM (E0339:52-57).
 *
 * STATUS: offline implementation. It has never been executed on a camera. It is
 * gated on a transport-enabled composite module that is auditable and actually
 * streams (open boundaries B3/B5), on the physical test plan in README.md, and
 * on explicit authorization for any camera-module session.
 *
 * SAFETY SHAPE
 *   - Every destructive step (ptrace freeze, INIT, REG_BUF, ENABLE, UPDATE,
 *     SET_PATH start, DMM rule 5) is refused unless --arm-transport is given,
 *     and each one is logged BEFORE it happens.
 *   - --dry-run performs discovery only: open + identity + usb state + DMA
 *     query. It never freezes, initialises, registers, enables or updates.
 *   - Unknown values fail closed with an explicit code; nothing is fabricated.
 *   - Exit codes: 0 clean, 2 stage failure, 3 refused, 4 fatal.
 */
#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#include "a6400_daemon.h"
#include "a6400_frame.h"
#include "a6400_internal.h"
#include "a6400_log.h"
#include "a6400_osal.h"
#include "a6400_recovery.h"
#include "a6400_sdlog.h"
#include "a6400_uvc.h"

#define A6400_EXIT_CLEAN    0
#define A6400_EXIT_STAGE    2
#define A6400_EXIT_REFUSED  3
#define A6400_EXIT_FATAL    4

#define A6400_GET_JPEG_TIMEOUT_MS 50u
#define A6400_MAX_CONSECUTIVE_ERRORS 30u
#define A6400_PREFIX_MAX 64u
#define A6400_PATH_MAX 200u

/* ---- process state ------------------------------------------------------- */

static volatile sig_atomic_t g_stop;
static volatile sig_atomic_t g_alarm_fired;
static struct a6400_log g_log;
static struct a6400_daemon_config g_cfg;
static struct a6400_daemon_stats g_stats;
static struct a6400_sd_status g_sd;
static const char *g_stage = "init";
static int g_exit_code = A6400_EXIT_FATAL;
static char g_fail_reason[192];

/* Receipt-only lifecycle/discovery facts. These live here (not in the structs
 * owned by other translation units) so that a6400_daemon_receipt() can render
 * them without exposing internal handles to the control layer. */
static int g_rc_init_attempted;
static int g_rc_session_active;
static int g_rc_hook_published;
static int g_rc_hook_retired;
static int g_rc_stop_verified;
static int g_rc_teardown_verified; /* clean gate OR a verified bounded retry */
static uint32_t g_rc_stop_attempts;
static uint32_t g_rc_tid_count;
static uint32_t g_rc_freeze_ms;
static uint32_t g_rc_attest_completed;
static int32_t g_rc_attest_error;
static int g_rc_dma_query_rc;
static int g_rc_meta_source; /* 0 none, 1 MOD_QUERY_DMA, 2 REG_BUF-acknowledged */
static uint32_t g_rc_dma_phys;
static uint32_t g_rc_dma_total;
static uint32_t g_rc_slot_size;
static uint32_t g_rc_max_payload;
static int g_rc_reg_buf_rc;
static int g_rc_enable_rc;
static uint32_t g_control_errors;
static uint32_t g_control_requests;
static uint32_t g_loop_ticks;
static uint32_t g_deadline_misses;
static uint32_t g_prefix_reads;
static uint32_t g_prefix_unavailable;
static uint32_t g_get_jpeg_errors;
static uint32_t g_wait_timeouts;

/* Operator-supplied fallbacks that a6400_daemon_config does not carry. */
static uint32_t g_dma_phys_opt;
static uint32_t g_dma_size_opt;
static uint32_t g_stats_interval_s;
static int g_dmesg_sd;
static uint32_t g_wait_bound_ms = 1000u;
static int g_read_prefix;
static int g_arm_transport;
/* E0358: bounded recovery after a failed stop attestation. On by default
 * because the alternative is a guaranteed battery pull; --no-park-recovery
 * restores the old fail-closed park for a conservative run. */
static int g_park_recovery = 1;
static struct a6400_recovery g_recovery;

struct daemon_rt {
    struct a6400_uvc uvc;
    struct a6400_uipc uipc;
    struct a6400_dmm dmm;
    struct a6400_runner runner;
    struct a6400_frame_queue q;
    struct a6400_uvc_dma_meta meta;
    struct a6400_control_ctx *ctl;
    int uvc_open;
    int uipc_open;
    int init_attempted;
    int reg_buf_ok;
    int enable_ok;
    int mem_fd;
    int session_active;
    int hook_retired;
    uint32_t exp_w;
    uint32_t exp_h;
    uint32_t frame_seq;
    uint32_t consecutive_errors;
    uint32_t admit_rejects;
};

/* ---- clock --------------------------------------------------------------- */

int64_t a6400_now_ns(void)
{
    struct timespec ts;

    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0)
        return 0;
    return (int64_t)ts.tv_sec * 1000000000LL + (int64_t)ts.tv_nsec;
}

uint64_t a6400_now_ms(void)
{
    int64_t ns = a6400_now_ns();

    return ns <= 0 ? 0u : (uint64_t)(ns / 1000000LL);
}

/* ---- logging / failure helpers ------------------------------------------- */

static void sig_handler(int sig)
{
    (void)sig;
    g_stop = 1;
}

static void alarm_handler(int sig)
{
    (void)sig;
    g_alarm_fired = 1;
}

static const char *status_name(int code)
{
    switch (code) {
    case A6400_EXIT_CLEAN:    return "clean";
    case A6400_EXIT_STAGE:    return "stage_failed";
    case A6400_EXIT_REFUSED:  return "refused";
    case A6400_EXIT_FATAL:    return "fatal";
    case A6400_EXIT_DEGRADED: return "degraded_teardown";
    default:                  return "unknown";
    }
}

static int stage_fail(const char *stage_name, int code, const char *fmt, ...)
{
    va_list ap;

    g_stage = stage_name;
    g_exit_code = code;
    va_start(ap, fmt);
    vsnprintf(g_fail_reason, sizeof g_fail_reason, fmt, ap);
    va_end(ap);
    a6400_logf(&g_log, A6400_LOG_ERROR, "stage_failed stage=%s code=%d reason=%s",
               stage_name, code, g_fail_reason);
    return code;
}

/* Emits one structured event line. `fields` is a caller-formatted JSON fragment
 * without the enclosing braces, or NULL for no extra fields. */
static void log_event(const char *event, const char *fields_fmt, ...)
{
    char fields[384];
    char line[512];
    va_list ap;
    int n;

    fields[0] = '\0';
    if (fields_fmt) {
        va_start(ap, fields_fmt);
        vsnprintf(fields, sizeof fields, fields_fmt, ap);
        va_end(ap);
    }
    if (fields[0])
        n = snprintf(line, sizeof line, "{\"event\":\"%s\",%s}", event, fields);
    else
        n = snprintf(line, sizeof line, "{\"event\":\"%s\"}", event);
    if (n < 0 || (size_t)n >= sizeof line)
        return;
    a6400_log_json(&g_log, line);
}

/* ---- JSON string builder for the receipt --------------------------------- */

struct sbuf {
    char    *buf;
    uint32_t cap;
    uint32_t len;
    int      overflow;
};

static void sb_init(struct sbuf *s, char *buf, uint32_t cap)
{
    s->buf = buf;
    s->cap = cap;
    s->len = 0;
    s->overflow = 0;
    if (cap)
        buf[0] = '\0';
}

static void sb_add(struct sbuf *s, const char *fmt, ...)
{
    va_list ap;
    int n;

    if (!s || s->overflow || s->len >= s->cap) {
        if (s)
            s->overflow = 1;
        return;
    }
    va_start(ap, fmt);
    n = vsnprintf(s->buf + s->len, s->cap - s->len, fmt, ap);
    va_end(ap);
    if (n < 0 || (uint32_t)n >= s->cap - s->len) {
        s->overflow = 1;
        return;
    }
    s->len += (uint32_t)n;
}

static void sb_path(struct sbuf *s, const char *path)
{
    char esc[2048];

    if (!path) {
        sb_add(s, "null");
        return;
    }
    if (!a6400_log_json_escape(esc, (uint32_t)sizeof esc, path)) {
        sb_add(s, "\"\"");
        return;
    }
    sb_add(s, "\"%s\"", esc);
}

/* ---- receipt ------------------------------------------------------------- */

uint32_t a6400_daemon_receipt(const struct a6400_daemon_stats *st,
                              const struct a6400_daemon_config *cfg,
                              char *buf, uint32_t cap)
{
    struct sbuf s;
    struct a6400_log_sd_stats sdstats;
    uint64_t uptime = 0;

    if (!st || !cfg || !buf || !cap)
        return 0;
    memset(&sdstats, 0, sizeof sdstats);
    a6400_log_sd_get(&g_log, &sdstats);
    if (st->started_monotonic_ns)
        uptime = (uint64_t)(a6400_now_ns() - (int64_t)st->started_monotonic_ns) / 1000000ull;

    sb_init(&s, buf, cap);
    sb_add(&s, "{\"schema\":\"a6400-lived-receipt/1\",");
    sb_add(&s, "\"build_status\":\"offline_unverified\",");
    sb_add(&s, "\"status\":\"%s\",\"exit_code\":%d,", status_name(g_exit_code), g_exit_code);
    sb_add(&s, "\"stage\":\"%s\",", g_stage ? g_stage : "unknown");
    sb_add(&s, "\"fail_reason\":");
    sb_path(&s, g_fail_reason[0] ? g_fail_reason : NULL);
    sb_add(&s, ",\"uptime_ms\":%llu,", (unsigned long long)uptime);
    sb_add(&s, "\"started_monotonic_ns\":%lld,",
           (long long)st->started_monotonic_ns);

    sb_add(&s, "\"config\":{\"device\":");
    sb_path(&s, cfg->device_path);
    sb_add(&s, ",\"log\":");
    sb_path(&s, cfg->log_path);
    sb_add(&s, ",\"receipt\":");
    sb_path(&s, cfg->receipt_path);
    sb_add(&s, ",\"control_fifo\":");
    sb_path(&s, cfg->control_fifo);
    sb_add(&s, ",\"control_ack\":");
    sb_path(&s, cfg->control_ack);
    sb_add(&s, ",\"wait_pcremote\":%d,\"wait_timeout_s\":%d,\"duration_s\":%d,",
           cfg->wait_pcremote, cfg->wait_timeout_s, cfg->duration_s);
    sb_add(&s, "\"target_pid\":%d,\"expected_width\":%d,\"expected_height\":%d,",
           cfg->target_pid, cfg->expected_width, cfg->expected_height);
    sb_add(&s, "\"fps\":%d,\"comp_level\":%d,\"path_width\":%d,",
           cfg->fps, cfg->comp_level, cfg->path_width);
    sb_add(&s, "\"dry_run\":%d,\"verbose\":%d,\"arm_transport\":%d,\"read_prefix\":%d,",
           cfg->dry_run, cfg->verbose, g_arm_transport, g_read_prefix);
    sb_add(&s, "\"park_recovery\":%d,", g_park_recovery);
    sb_add(&s, "\"stats_interval_s\":%u,\"wait_bound_ms\":%u,",
           g_stats_interval_s, g_wait_bound_ms);
    sb_add(&s, "\"dma_phys_opt\":%u,\"dma_size_opt\":%u,", g_dma_phys_opt, g_dma_size_opt);
    sb_add(&s, "\"sd_log\":%d,\"sd_mount\":%d,\"dmesg_sd\":%d,\"sd_dev\":",
           cfg->sd_log, cfg->sd_mount, cfg->dmesg_sd);
    sb_path(&s, cfg->sd_dev);
    sb_add(&s, ",\"sd_mountpoint\":");
    sb_path(&s, cfg->sd_mountpoint);
    sb_add(&s, "},");

    sb_add(&s, "\"lifecycle\":{\"init_attempted\":%d,\"session_active\":%d,",
           g_rc_init_attempted, g_rc_session_active);
    sb_add(&s, "\"hook_published\":%d,\"hook_retired\":%d,\"stop_verified\":%d,",
           g_rc_hook_published, g_rc_hook_retired, g_rc_stop_verified);
    sb_add(&s, "\"stop_attempts\":%u,\"teardown_verified\":%d,",
           g_rc_stop_attempts, g_rc_teardown_verified);
    sb_add(&s, "\"freeze_tid_count\":%u,\"freeze_ms\":%u,",
           g_rc_tid_count, g_rc_freeze_ms);
    sb_add(&s, "\"attest_version\":2,\"attest_owner\":%d,"
               "\"attest_completed\":%u,\"attest_error\":%d},",
           cfg->target_pid, g_rc_attest_completed, g_rc_attest_error);

    sb_add(&s, "\"discovery\":{\"dma_query_rc\":%d,\"dma_meta_source\":%d,",
           g_rc_dma_query_rc, g_rc_meta_source);
    sb_add(&s, "\"dma_phys\":%u,\"dma_total\":%u,\"slot_size\":%u,\"max_frame_payload\":%u,",
           g_rc_dma_phys, g_rc_dma_total, g_rc_slot_size, g_rc_max_payload);
    sb_add(&s, "\"reg_buf_rc\":%d,\"enable_rc\":%d},", g_rc_reg_buf_rc, g_rc_enable_rc);

    sb_add(&s, "\"stats\":{\"phase\":%u,\"session_active\":%u,"
               "\"frames_captured\":%u,\"frames_submitted\":%u,"
               "\"frames_dropped\":%u,\"frames_rejected\":%u,",
           st->phase, st->session_active, st->frames_captured, st->frames_submitted,
           st->frames_dropped, st->frames_rejected);
    sb_add(&s, "\"transport_errors\":%u,\"upload_errors\":%u,"
               "\"get_jpeg_polls\":%u,\"get_jpeg_empty\":%u,",
           st->transport_errors, st->upload_errors, st->get_jpeg_polls, st->get_jpeg_empty);
    sb_add(&s, "\"last_frame_size\":%u,\"last_frame_seq\":%u,"
               "\"last_width\":%u,\"last_height\":%u,",
           st->last_frame_size, st->last_frame_seq, st->last_width, st->last_height);
    sb_add(&s, "\"wait_ms_max\":%u,\"accept_geometry\":%u},", st->wait_ms_max, st->accept_geometry);

    sb_add(&s, "\"diagnostics\":{\"loop_ticks\":%u,\"deadline_misses\":%u,",
           g_loop_ticks, g_deadline_misses);
    sb_add(&s, "\"prefix_reads\":%u,\"prefix_unavailable\":%u,"
               "\"get_jpeg_errors\":%u,\"wait_timeouts\":%u,",
           g_prefix_reads, g_prefix_unavailable, g_get_jpeg_errors, g_wait_timeouts);
    sb_add(&s, "\"control_requests\":%u,\"control_errors\":%u},",
           g_control_requests, g_control_errors);

    /* Bounded park recovery (E0358). `status` is not_attempted on every clean
     * path and on a run that never reached teardown; `pending` is what the
     * durable pre-recovery receipt records, so a battery pull in the middle of
     * the attempt cannot present it as recovered. `state_before/after` are the
     * module's own {phase,pinned,hook_mask,error} words, -1 filled when the
     * status query did not answer (never invented). */
    sb_add(&s, "\"recovery\":{\"enabled\":%d,\"attempted\":%d,\"status\":",
           g_park_recovery, g_recovery.attempted);
    sb_path(&s, a6400_recovery_status_name(g_recovery.status));
    sb_add(&s, ",\"evidence_written\":%d,\"state_before_valid\":%d,",
           g_recovery.evidence_written, g_recovery.state_before_valid);
    sb_add(&s, "\"state_before\":[%d,%d,%d,%d],",
           g_recovery.state_before[0], g_recovery.state_before[1],
           g_recovery.state_before[2], g_recovery.state_before[3]);
    sb_add(&s, "\"stop_retry_rc\":%d,\"state_after_valid\":%d,",
           g_recovery.stop_retry_rc, g_recovery.state_after_valid);
    sb_add(&s, "\"state_after\":[%d,%d,%d,%d],",
           g_recovery.state_after[0], g_recovery.state_after[1],
           g_recovery.state_after[2], g_recovery.state_after[3]);
    sb_add(&s, "\"stop_retry_verified\":%d,\"freeze_rc\":%d,\"frozen_tids\":%u,",
           g_recovery.stop_retry_verified, g_recovery.freeze_rc,
           g_recovery.frozen_tids);
    sb_add(&s, "\"hook_retire_rc\":%d,\"hook_retired\":%d,\"resume_rc\":%d,"
               "\"closed\":%d,\"failed_step\":",
           g_recovery.retire_rc, g_recovery.hook_retired, g_recovery.resume_rc,
           g_recovery.closed);
    sb_path(&s, a6400_recovery_step_name(g_recovery.failed_step));
    sb_add(&s, ",\"detail\":");
    sb_path(&s, g_recovery.detail[0] ? g_recovery.detail : NULL);
    sb_add(&s, "},");

    /* Durable crash-safe SD status (E0350): every field is the observed value,
     * including refusals and failures. `mounted` is 1 only after mount(2), an
     * exact /proc/mounts match and a sentinel round-trip. */
    sb_add(&s, "\"sd_log\":{\"enabled\":%d,\"mount_requested\":%d,\"attempted\":%d,",
           g_sd.enabled, g_sd.mount_requested, g_sd.attempted);
    sb_add(&s, "\"mounted\":%d,\"device_ok\":%d,\"verified\":%d,\"sentinel_ok\":%d,",
           g_sd.mounted, g_sd.device_ok, g_sd.verified, g_sd.sentinel_ok);
    sb_add(&s, "\"mount_rc\":%d,\"unmount_rc\":%d,\"open_rc\":%d,\"sync_mode\":%d,",
           g_sd.mount_rc, g_sd.unmount_rc, g_sd.open_rc, g_sd.sync_mode);
    sb_add(&s, "\"receipt_written\":%d,\"errors\":%u,\"rotations\":%u,",
           g_sd.receipt_written, g_sd.errors, g_sd.rotations);
    sb_add(&s, "\"trace_lines\":%u,\"trace_errors\":%u,\"device\":",
           g_sd.trace_lines, g_sd.trace_errors);
    sb_path(&s, g_sd.device);
    sb_add(&s, ",\"mountpoint\":");
    sb_path(&s, g_sd.mountpoint);
    sb_add(&s, ",\"reason\":");
    sb_path(&s, g_sd.reason[0] ? g_sd.reason : NULL);
    sb_add(&s, "},\"log_sd_lines\":%u,\"log_sd_errors\":%u}\n",
           sdstats.lines, sdstats.errors);

    if (s.overflow)
        return 0;
    return s.len;
}

static int write_receipt(void)
{
    /* Sized for the full schema plus the sd_log block; an overflow would lose
     * the durable receipt entirely, so the margin is deliberate. */
    char buf[6144];
    uint32_t n;
    int fd, rc = 0;
    uint32_t done = 0;

    if (!g_cfg.receipt_path || !g_cfg.receipt_path[0])
        return -EINVAL;
    n = a6400_daemon_receipt(&g_stats, &g_cfg, buf, (uint32_t)sizeof buf);
    if (!n) {
        a6400_logf(&g_log, A6400_LOG_ERROR, "receipt_serialize_failed cap=%u",
                   (unsigned)sizeof buf);
        return -ENOSPC;
    }

    fd = open(g_cfg.receipt_path, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    if (fd < 0) {
        a6400_logf(&g_log, A6400_LOG_ERROR, "receipt_open_failed path=%s errno=%d",
                   g_cfg.receipt_path, errno);
        return -errno;
    }
    while (done < n) {
        ssize_t w = write(fd, buf + done, (size_t)(n - done));

        if (w < 0 && errno == EINTR)
            continue;
        if (w <= 0) {
            rc = -EIO;
            break;
        }
        done += (uint32_t)w;
    }
    if (rc == 0 && fsync(fd) != 0)
        rc = -EIO;
    (void)close(fd);
    /* E0350: when the SD card is mounted and verified, copy the same receipt to
     * A6400RCPT.JSON with O_SYNC. This copy is what survives a battery pull; a
     * failure here is counted in g_sd.errors, never hidden. */
    if (rc == 0 && g_sd.enabled && g_sd.mounted)
        (void)a6400_sd_write_receipt(&g_sd, buf, n);
    a6400_logf(&g_log, A6400_LOG_INFO, "receipt_written path=%s bytes=%u rc=%d",
               g_cfg.receipt_path, done, rc);
    return rc;
}

/* ---- /dev/mem bounded prefix read --------------------------------------- */

/* Reads at most A6400_PREFIX_MAX bytes of the frame at `phys`. Never fabricates
 * a byte: on any failure the caller must treat the prefix as unavailable. */
static int read_frame_prefix(int mem_fd, uint32_t phys, uint32_t mapped,
                             uint8_t *out, uint32_t *out_len)
{
    uint32_t want;

    if (!out || !out_len || mem_fd < 0)
        return -1;
    *out_len = 0;
    want = mapped < A6400_PREFIX_MAX ? mapped : A6400_PREFIX_MAX;
    if (want < 2u || phys > 0xffffffffu - want)
        return -1;

    if (g_read_prefix) {
        /* Opt-in: mmap the page range of the DMM window and copy the prefix. */
        uint32_t page = phys & ~0xfffu;
        uint32_t off = phys - page;
        uint32_t map_len = (off + want + 0xfffu) & ~0xfffu;
        void *m = mmap(NULL, map_len, PROT_READ, MAP_SHARED, mem_fd, (off_t)page);

        if (m == MAP_FAILED)
            return -1;
        memcpy(out, (const uint8_t *)m + off, want);
        (void)munmap(m, map_len);
        *out_len = want;
        return 0;
    }

    {
        /* Default: one bounded pread. The frame is at a physical address, so
         * /dev/mem is the only reader; the read is capped at 64 bytes. */
        ssize_t n = pread(mem_fd, out, want, (off_t)phys);

        if (n < 2)
            return -1;
        *out_len = (uint32_t)n;
    }
    return 0;
}

/* ---- bounded WAIT -------------------------------------------------------- */

/* WAIT (0xf002) is a blocking ioctl whose kernel-side maximum is unknown
 * (open boundary B4). Bound it from userspace with an interval timer that is
 * allowed to interrupt the ioctl, and report the measured duration. If the
 * driver sleeps uninterruptibly this bound cannot help; that limitation is
 * documented in README.md and is a physical-test variable. */
static int bounded_wait(struct a6400_uvc *uvc, uint32_t timeout_ms,
                        uint32_t *elapsed_ms)
{
    struct sigaction sa, old_sa;
    struct itimerval it, old_it;
    uint64_t t0, t1;
    int rc;

    if (elapsed_ms)
        *elapsed_ms = 0;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = alarm_handler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0; /* no SA_RESTART: the ioctl must see EINTR */
    if (sigaction(SIGALRM, &sa, &old_sa) != 0)
        return -1;

    memset(&it, 0, sizeof it);
    it.it_value.tv_sec = (time_t)(timeout_ms / 1000u);
    it.it_value.tv_usec = (suseconds_t)((timeout_ms % 1000u) * 1000u);
    g_alarm_fired = 0;
    if (setitimer(ITIMER_REAL, &it, &old_it) != 0) {
        (void)sigaction(SIGALRM, &old_sa, NULL);
        return -1;
    }

    t0 = (uint64_t)a6400_now_ns();
    rc = a6400_uvc_wait(uvc);
    t1 = (uint64_t)a6400_now_ns();

    memset(&it, 0, sizeof it);
    (void)setitimer(ITIMER_REAL, &it, NULL);
    (void)sigaction(SIGALRM, &old_sa, NULL);

    if (elapsed_ms)
        *elapsed_ms = (uint32_t)((t1 - t0) / 1000000ull);
    /* Only a real EINTR is a bound hit. `g_alarm_fired` alone is not enough:
     * the timer can fire between the ioctl returning and the disarm, and a
     * completed wait must not be turned into a false timeout. */
    if (rc == -EINTR)
        return -ETIMEDOUT;
    return rc;
}


/* Resolves the destination window. probe_only=1 never fails and never invents a
 * window: it is the dry-run discovery probe. probe_only=0 either takes
 * MOD_QUERY_DMA or requires the operator-supplied --dma-phys/--dma-size
 * fallback; a fabricated fixed window is refused. */
static int resolve_dma_window(struct daemon_rt *rt, int probe_only)
{
    g_rc_dma_query_rc = a6400_uvc_query_dma(&rt->uvc, &rt->meta);
    if (g_rc_dma_query_rc == 0) {
        /* Slot capacity is total/2 and the driver writes a 12-byte header, so
         * max_frame_payload must be slot-12 (uvc_composite_shim.c:1002-1020). */
        if (rt->meta.max_frame_payload > rt->meta.slot_size) {
            a6400_logf(&g_log, A6400_LOG_WARN,
                       "dma_query_inconsistent slot=%u max_payload=%u",
                       rt->meta.slot_size, rt->meta.max_frame_payload);
            rt->meta.max_frame_payload = rt->meta.slot_size >
                                                 A6400_UVC_HEADER_SIZE
                                             ? rt->meta.slot_size - A6400_UVC_HEADER_SIZE
                                             : 0;
        }
        g_rc_meta_source = 1;
        g_rc_dma_phys = rt->meta.phys_addr;
        g_rc_dma_total = rt->meta.total_size;
        g_rc_slot_size = rt->meta.slot_size;
        g_rc_max_payload = rt->meta.max_frame_payload;
        log_event("dma_window",
                  "\"source\":\"mod_query_dma\",\"phys\":%u,\"total\":%u,"
                  "\"slot\":%u,\"max_payload\":%u",
                  rt->meta.phys_addr, rt->meta.total_size, rt->meta.slot_size,
                  rt->meta.max_frame_payload);
        return 0;
    }
    if (g_rc_dma_query_rc == -ENOTTY) {
        /* Stock driver: no such ioctl (E0340:9-11). A REG_BUF-acknowledged
         * window needs operator-supplied geometry; inventing one would be a
         * fabricated address. */
        a6400_logf(&g_log, A6400_LOG_WARN,
                   "mod_query_dma_unavailable rc=%d (ENOTTY); "
                   "fallback requires --dma-phys/--dma-size",
                   g_rc_dma_query_rc);
    } else {
        a6400_logf(&g_log, A6400_LOG_WARN, "mod_query_dma_failed rc=%d",
                   g_rc_dma_query_rc);
    }
    if (probe_only)
        return -1;

    if (!g_dma_phys_opt || !g_dma_size_opt) {
        (void)stage_fail("dma_window", A6400_EXIT_STAGE,
                         "no DMA window: MOD_QUERY_DMA rc=%d and "
                         "--dma-phys/--dma-size were not supplied",
                         g_rc_dma_query_rc);
        return -1;
    }
    rt->meta.phys_addr = g_dma_phys_opt;
    rt->meta.total_size = g_dma_size_opt;
    rt->meta.slot_size = g_dma_size_opt / 2u;
    if (rt->meta.slot_size <= A6400_UVC_HEADER_SIZE) {
        (void)stage_fail("dma_window", A6400_EXIT_STAGE,
                         "--dma-size %u leaves no room after the %u-byte header",
                         g_dma_size_opt, A6400_UVC_HEADER_SIZE);
        return -1;
    }
    rt->meta.max_frame_payload = rt->meta.slot_size - A6400_UVC_HEADER_SIZE;
    g_rc_meta_source = 2;
    g_rc_dma_phys = rt->meta.phys_addr;
    g_rc_dma_total = rt->meta.total_size;
    g_rc_slot_size = rt->meta.slot_size;
    g_rc_max_payload = rt->meta.max_frame_payload;
    log_event("dma_window",
              "\"source\":\"reg_buf_acknowledged\",\"phys\":%u,\"total\":%u,"
              "\"slot\":%u,\"max_payload\":%u",
              rt->meta.phys_addr, rt->meta.total_size, rt->meta.slot_size,
              rt->meta.max_frame_payload);
    return 0;
}

/* ---- frame loop ---------------------------------------------------------- */

static void release_units(struct daemon_rt *rt, uint32_t handle1, uint32_t handle2)
{
    /* Close then free, both handles (feeder:673-694). The DMM unit must be
     * closed before it is freed; freeing first would be an unmodelled order. */
    if (handle1) {
        (void)a6400_dmm_close_unit(&rt->dmm, handle1);
        (void)a6400_dmm_free_unit(&rt->dmm, handle1);
    }
    if (handle2)
        (void)a6400_dmm_free_unit(&rt->dmm, handle2);
}

/* 0 = continue, 1 = fatal (stage already recorded). */
static int stream_tick(struct daemon_rt *rt, const struct a6400_daemon_config *cfg)
{
    struct a6400_jpeg_result jr;
    struct a6400_frame_candidate cand;
    struct a6400_jpeg_dims dims;
    uint8_t prefix[A6400_PREFIX_MAX];
    uint32_t prefix_len = 0;
    uint32_t phys = 0, mapped = 0;
    int rc, slot;

    (void)cfg;

    g_stats.get_jpeg_polls++;
    rc = a6400_scalar_get_jpeg(&rt->dmm, A6400_GET_JPEG_TIMEOUT_MS, &jr);
    if (rc < 0) {
        g_stats.transport_errors++;
        g_get_jpeg_errors++;
        rt->consecutive_errors++;
        a6400_logf(&g_log, A6400_LOG_WARN, "get_jpeg_transport_error rc=%d consecutive=%u",
                   rc, rt->consecutive_errors);
        if (rt->consecutive_errors >= A6400_MAX_CONSECUTIVE_ERRORS) {
            (void)stage_fail("stream", A6400_EXIT_STAGE,
                             "get_jpeg failed %u times in a row (last rc=%d)",
                             rt->consecutive_errors, rc);
            return 1;
        }
        return 0;
    }
    if (rc == 1) {
        g_stats.get_jpeg_empty++;
        return 0;
    }
    rt->consecutive_errors = 0;

    if (!jr.handle1 || jr.handle1 == 0xffffu || !jr.size_upper_bound) {
        a6400_logf(&g_log, A6400_LOG_WARN,
                   "jpeg_rejected reason=empty_handle handle1=%u size_bound=%u",
                   jr.handle1, jr.size_upper_bound);
        release_units(rt, 0, jr.handle2);
        g_stats.frames_rejected++;
        return 0;
    }

    rc = a6400_dmm_open_unit(&rt->dmm, jr.handle1, &phys, &mapped);
    if (rc != 0) {
        a6400_logf(&g_log, A6400_LOG_WARN, "dmm_open_failed handle=%u rc=%d",
                   jr.handle1, rc);
        release_units(rt, jr.handle1, jr.handle2);
        g_stats.transport_errors++;
        return 0;
    }

    if (rt->mem_fd >= 0 &&
        read_frame_prefix(rt->mem_fd, phys, mapped, prefix, &prefix_len) == 0) {
        g_prefix_reads++;
    } else {
        prefix_len = 0;
        g_prefix_unavailable++;
        if (g_prefix_unavailable == 1u || (g_prefix_unavailable % 300u) == 0u) {
            /* Never fabricate an SOI. The admission gate decides what a frame
             * without a prefix is allowed to be. */
            a6400_logf(&g_log, A6400_LOG_WARN,
                       "prefix_unavailable count=%u phys=%u mapped=%u",
                       g_prefix_unavailable, phys, mapped);
        }
    }

    memset(&cand, 0, sizeof cand);
    cand.handle1 = jr.handle1;
    cand.handle2 = jr.handle2;
    cand.phys_addr = phys;
    cand.mapped_size = mapped;
    cand.size_shift = jr.size_shift;
    cand.frame_seq = ++rt->frame_seq;
    cand.capture_ns = a6400_now_ns();
    cand.prefix = prefix_len ? prefix : NULL;
    cand.prefix_len = prefix_len;

    slot = a6400_frame_admit(&rt->q, &cand, &rt->meta, rt->exp_w, rt->exp_h);
    g_stats.frames_dropped = rt->q.dropped;
    g_stats.frames_rejected = rt->q.rejected;
    if (slot < 0) {
        /* A persistently rejected stream would otherwise log at 30 Hz and burn
         * the 256 KiB cap; keep the first rejection and then every 300th. */
        if (rt->admit_rejects++ == 0u || (rt->admit_rejects % 300u) == 0u) {
            if (slot == A6400_FRAME_ERR_JPEG && !prefix_len)
                a6400_logf(&g_log, A6400_LOG_WARN,
                           "admit_rejected rc=%d seq=%u reason=prefix_unavailable",
                           slot, cand.frame_seq);
            else
                a6400_logf(&g_log, A6400_LOG_WARN,
                           "admit_rejected rc=%d seq=%u size_bound=%u phys=%u mapped=%u",
                           slot, cand.frame_seq, jr.size_upper_bound, phys, mapped);
        }
        release_units(rt, jr.handle1, jr.handle2);
        return 0;
    }
    g_stats.frames_captured++;

    if (prefix_len &&
        a6400_jpeg_parse_dimensions(prefix, prefix_len, &dims) == 0) {
        g_stats.last_width = dims.width;
        g_stats.last_height = dims.height;
        if (!rt->exp_w) {
            /* Geometry is discovered from the first real frame, never assumed
             * from the SET_PATH request (LIVEVIEW_DMA.md:691-697). */
            rt->exp_w = dims.width;
            rt->exp_h = dims.height;
            g_stats.accept_geometry = 1u;
            g_stats.last_frame_size = jr.size_upper_bound;
            log_event("geometry_discovered", "\"width\":%u,\"height\":%u",
                      dims.width, dims.height);
        }
    }

    {
        uint32_t wait_ms = 0;

        rc = bounded_wait(&rt->uvc, g_wait_bound_ms, &wait_ms);
        if (wait_ms > g_stats.wait_ms_max)
            g_stats.wait_ms_max = wait_ms;
        if (rc != 0) {
            if (rc == -EBUSY) {
                /* Tolerated by the physically run feeder (line 718): no UPDATE
                 * for this frame, slot returned, loop continues. */
                a6400_logf(&g_log, A6400_LOG_INFO,
                           "wait_busy seq=%u elapsed_ms=%u", cand.frame_seq, wait_ms);
                g_stats.upload_errors++;
                a6400_frame_abort(&rt->q);
                a6400_frame_release(&rt->q, (uint32_t)slot);
                release_units(rt, jr.handle1, jr.handle2);
                return 0;
            }
            g_stats.transport_errors++;
            g_stats.upload_errors++;
            g_wait_timeouts++;
            rt->consecutive_errors++;
            a6400_logf(&g_log, A6400_LOG_WARN,
                       "wait_failed rc=%d elapsed_ms=%u consecutive=%u",
                       rc, wait_ms, rt->consecutive_errors);
            a6400_frame_abort(&rt->q);
            a6400_frame_release(&rt->q, (uint32_t)slot);
            release_units(rt, jr.handle1, jr.handle2);
            if (rt->consecutive_errors >= A6400_MAX_CONSECUTIVE_ERRORS) {
                (void)stage_fail("stream", A6400_EXIT_STAGE, "WAIT failed repeatedly");
                return 1;
            }
            return 0;
        }
    }

    {
        uint32_t frame_len = jr.size_upper_bound;
        uint32_t slot_phys = rt->meta.phys_addr + (uint32_t)slot * rt->meta.slot_size;

        /* The exact JPEG length is not reported by the camera: size_shift<<7 is
         * an upper bound within 127 bytes (E0144:21). Upload the bound, clamped
         * to the mapped unit so the driver never reads past it. */
        if (!frame_len || frame_len > mapped)
            frame_len = mapped;

        rc = a6400_uvc_update(&rt->uvc, frame_len, slot_phys);
        if (rc == 0) {
            g_stats.frames_submitted++;
            g_stats.last_frame_size = frame_len;
            g_stats.last_frame_seq = cand.frame_seq;
            a6400_frame_release(&rt->q, (uint32_t)slot);
            /* Progress event every 300 submitted frames (~10 s at 30 fps).
             * Never per frame: the log is capped at 256 KiB. */
            if ((g_stats.frames_submitted % 300u) == 1u) {
                log_event("frame_progress",
                          "\"seq\":%u,\"size\":%u,\"slot\":%d,\"phys\":%u,"
                          "\"submitted\":%u",
                          cand.frame_seq, frame_len, slot, slot_phys,
                          g_stats.frames_submitted);
            }
        } else {
            g_stats.transport_errors++;
            g_stats.upload_errors++;
            rt->consecutive_errors++;
            a6400_logf(&g_log, A6400_LOG_WARN,
                       "update_failed rc=%d size=%u phys=%u consecutive=%u",
                       rc, frame_len, slot_phys, rt->consecutive_errors);
            a6400_frame_abort(&rt->q);
            a6400_frame_release(&rt->q, (uint32_t)slot);
            release_units(rt, jr.handle1, jr.handle2);
            if (rt->consecutive_errors >= A6400_MAX_CONSECUTIVE_ERRORS) {
                (void)stage_fail("stream", A6400_EXIT_STAGE, "UPDATE failed repeatedly");
                return 1;
            }
            return 0;
        }
    }

    release_units(rt, jr.handle1, jr.handle2);
    return 0;
}

static void handle_stream_config(struct daemon_rt *rt,
                                 const struct a6400_ctl_stream_config *cfg)
{
    if (cfg->width && cfg->height &&
        (rt->exp_w != cfg->width || rt->exp_h != cfg->height)) {
        /* Retuning geometry means re-issuing SET_PATH, whose accepted width
         * gate for selector 0x50 is NOT decoded (LIVEVIEW_DMA.md:691-697).
         * Refuse to pretend: keep the discovered geometry and say so. */
        a6400_logf(&g_log, A6400_LOG_WARN,
                   "stream_config_geometry_ignored requested=%ux%u accepted=%ux%u",
                   cfg->width, cfg->height, rt->exp_w, rt->exp_h);
    }
    log_event("stream_config", "\"width\":%u,\"height\":%u,\"fps\":%u,\"quality\":%u",
              (unsigned)cfg->width, (unsigned)cfg->height, (unsigned)cfg->fps,
              (unsigned)cfg->quality);
}

static int poll_control(struct daemon_rt *rt)
{
    int i;

    if (!rt->ctl)
        return 0;
    for (i = 0; i < 4; i++) {
        struct a6400_ctl_action act;
        int rc = a6400_control_poll(rt->ctl, &act);

        if (rc == 0)
            return 0;
        if (rc < 0) {
            g_control_errors++;
            a6400_logf(&g_log, A6400_LOG_WARN, "control_poll_error rc=%d", rc);
            return 0;
        }
        g_control_requests++;
        if (act.kind == A6400_CTL_ACTION_STREAM_STOP ||
            act.kind == A6400_CTL_ACTION_SHUTDOWN_REQUEST) {
            a6400_logf(&g_log, A6400_LOG_INFO, "control_stop_request kind=%d",
                       (int)act.kind);
            g_stop = 1;
            return 0;
        }
        if (act.kind == A6400_CTL_ACTION_STREAM_START)
            log_event("control_stream_start", NULL);
        else if (act.kind == A6400_CTL_ACTION_STREAM_CONFIG)
            handle_stream_config(rt, &act.config);
    }
    return 0;
}

static int stream_loop(struct daemon_rt *rt, const struct a6400_daemon_config *cfg)
{
    uint64_t period_ns = 1000000000ull / (uint64_t)cfg->fps;
    uint64_t deadline = (uint64_t)a6400_now_ns();
    uint64_t end_ns = 0;
    uint64_t next_report = 0;

    if (cfg->duration_s > 0)
        end_ns = deadline + (uint64_t)cfg->duration_s * 1000000000ull;
    if (g_stats_interval_s)
        next_report = deadline + (uint64_t)g_stats_interval_s * 1000000000ull;

    for (;;) {
        struct timespec ts;

        if (g_stop)
            break;
        if (end_ns && (uint64_t)a6400_now_ns() >= end_ns)
            break;

        if (stream_tick(rt, cfg))
            return 1;
        (void)poll_control(rt);
        g_loop_ticks++;
        /* E0356: mirror the kernel [a6400_*] trace to the SD card every ~150
         * ticks (about 5 s at 30 fps) so a later hang/power cycle cannot lose
         * the CLASS/START evidence. Bounded; failures are counted. */
        if (g_dmesg_sd && g_sd.mounted && (g_loop_ticks % 150u) == 0u)
            (void)a6400_sd_flush_kernel_trace(&g_sd);

        if (g_stats_interval_s && (uint64_t)a6400_now_ns() >= next_report) {
            log_event("stats",
                      "\"captured\":%u,\"submitted\":%u,\"dropped\":%u,"
                      "\"rejected\":%u,\"transport_errors\":%u,\"polls\":%u,"
                      "\"empty\":%u,\"wait_max_ms\":%u",
                      g_stats.frames_captured, g_stats.frames_submitted,
                      g_stats.frames_dropped, g_stats.frames_rejected,
                      g_stats.transport_errors, g_stats.get_jpeg_polls,
                      g_stats.get_jpeg_empty, g_stats.wait_ms_max);
            if (g_dmesg_sd && g_sd.mounted)
                (void)a6400_sd_flush_kernel_trace(&g_sd);
            (void)write_receipt();
            next_report += (uint64_t)g_stats_interval_s * 1000000000ull;
        }

        /* Absolute CLOCK_MONOTONIC deadlines only; never a relative sleep. */
        deadline += period_ns;
        {
            uint64_t now = (uint64_t)a6400_now_ns();

            if (now >= deadline) {
                uint64_t missed = 1u + (now - deadline) / period_ns;
                uint32_t add = missed > 0xffffffffu ? 0xffffffffu : (uint32_t)missed;

                g_deadline_misses += add;
                deadline = now; /* re-base instead of bursting to catch up */
            }
        }
        ts.tv_sec = (time_t)(deadline / 1000000000ull);
        ts.tv_nsec = (long)(deadline % 1000000000ull);
        while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL) == EINTR) {
            if (g_stop)
                break;
        }
    }
    return 0;
}

/* ---- control host hooks -------------------------------------------------- */

static void host_get_stats(void *ctx, struct a6400_daemon_stats *out)
{
    (void)ctx;
    if (out)
        *out = g_stats;
}

static void host_get_caps(void *ctx, struct a6400_ctl_caps_reply *out)
{
    (void)ctx;
    if (!out)
        return;
    out->protocol_version = A6400_CTL_VERSION;
    /* Absolute writes are not effective on this camera, so settings are routed
     * to the host's PTP session (CONTROL_IPC.md:16-20). */
    out->camera_setting_route = (uint32_t)A6400_CTL_ROUTE_PTP;
    out->uvc_transport = (uint32_t)(g_rc_session_active ? 1u : 0u);
    out->max_payload = A6400_CTL_MAX_PAYLOAD;
}

static int host_session_active(void *ctx)
{
    (void)ctx;
    return g_rc_session_active;
}

/* ---- config / argv ------------------------------------------------------- */

static int path_under_tmp_bt(const char *path)
{
    return path && strncmp(path, "/tmp_bt/", 8u) == 0;
}

static int validate_config(const struct a6400_daemon_config *cfg)
{
    if (!cfg->device_path || !cfg->log_path || !cfg->receipt_path)
        return -1;
    if (!path_under_tmp_bt(cfg->device_path))
        return -2; /* the video node lives in /tmp_bt only */
    if (cfg->control_fifo && cfg->control_fifo[0] &&
        !path_under_tmp_bt(cfg->control_fifo))
        return -3;
    if (cfg->control_ack && cfg->control_ack[0] &&
        !path_under_tmp_bt(cfg->control_ack))
        return -4;
    if (strlen(cfg->device_path) >= A6400_PATH_MAX ||
        strlen(cfg->receipt_path) >= A6400_PATH_MAX)
        return -5;
    if (cfg->fps < 1 || cfg->fps > 240)
        return -6;
    if (cfg->comp_level < 1 || cfg->comp_level > 100)
        return -7;
    if (cfg->path_width < 1 || cfg->path_width > 4096)
        return -8;
    if (cfg->target_pid <= 0)
        return -9;
    if (cfg->wait_timeout_s < 0 || cfg->wait_timeout_s > 3600)
        return -10;
    if (cfg->duration_s < 0 || cfg->duration_s > 86400)
        return -11;
    if ((cfg->expected_width == 0) != (cfg->expected_height == 0))
        return -12; /* both zero (discover) or both set */
    if (cfg->expected_width < 0 || cfg->expected_height < 0 ||
        cfg->expected_width > 8192 || cfg->expected_height > 8192)
        return -13;
    if (g_wait_bound_ms < 1u || g_wait_bound_ms > 60000u)
        return -15;
    if (g_stats_interval_s > 3600u)
        return -16;
    if (cfg->dmesg_sd && (!cfg->sd_log || !cfg->sd_mount))
        return -20; /* --dmesg-sd requires --sd-log --sd-mount */
    if (cfg->sd_mount && !cfg->sd_log)
        return -17; /* mounting without the SD sink is never useful */
    if (cfg->sd_log) {
        const char *dev = cfg->sd_dev ? cfg->sd_dev : A6400_SD_DEV_DEFAULT;
        const char *mp = cfg->sd_mountpoint ? cfg->sd_mountpoint
                                            : A6400_SD_MOUNT_DEFAULT;

        if (a6400_sd_device_policy(dev) != A6400_SD_OK)
            return -18; /* internal flash / wrong node / unsafe path */
        if (a6400_sd_mountpoint_policy(mp) != A6400_SD_OK)
            return -19; /* not under /tmp_bt, or a forbidden mount */
    }
    if (!cfg->dry_run && !g_arm_transport)
        return -14; /* conservative default: refuse destructive work */
    /* A DMA window is not required here: MOD_QUERY_DMA may supply it. If it is
     * absent the daemon refuses with an explicit message at that point instead
     * of guessing a physical address. */
    return 0;
}

static void usage(const char *argv0)
{
    fprintf(stderr,
        "usage: %s [options]\n"
        "\n"
        "Discovery / safety:\n"
        "  --device PATH         video node (default /tmp_bt/video)\n"
        "  --log PATH            JSONL log (default /tmp_bt/a6400_lived.jsonl, /tmp_bt only)\n"
        "  --receipt PATH        receipt JSON (default /tmp_bt/a6400_lived_receipt.json)\n"
        "  --control-fifo PATH   request FIFO (default /tmp_bt/a6400_ctrl.fifo)\n"
        "  --control-ack PATH    ack file (default /tmp_bt/a6400_ctrl.ack)\n"
        "  --dry-run             discovery/validation only; no destructive step\n"
        "  --arm-transport       REQUIRED for freeze/INIT/REG_BUF/ENABLE/UPDATE/SET_PATH\n"
        "  --verbose             debug logging\n"
        "\n"
        "Session:\n"
        "  --wait-pcremote       require 0x054c:0x0caa before INIT\n"
        "  --timeout SEC         PC Remote wait bound (default 120)\n"
        "  --duration SEC        stop after SEC, 0 = until SIGINT (default 0)\n"
        "  --pid N               target process (default 149)\n"
        "  --fps N               pacing hint (default 30)\n"
        "  --comp-level N        SET_PATH component level (default 5)\n"
        "  --path-width N        SET_PATH width hint (default 1280)\n"
        "  --width N             expected frame width, 0 = discover (default 0)\n"
        "  --height N            expected frame height, 0 = discover (default 0)\n"
        "\n"
        "Transport fallback and diagnostics:\n"
        "  --dma-phys HEX        window physical address when MOD_QUERY_DMA is absent\n"
        "  --dma-size N          window size when MOD_QUERY_DMA is absent\n"
        "  --read-prefix         mmap the DMM window for the prefix instead of pread\n"
        "  --wait-ms N           bound on the WAIT ioctl (default 1000)\n"
        "  --stats-interval SEC  log stats and rewrite the receipt every SEC (0 = off)\n"
        "\n"
        "Crash-safe SD logging (E0350; both flags default OFF):\n"
        "  --sd-log              mirror every JSONL line + the receipt to the SD card\n"
        "  --dmesg-sd            mirror kernel [a6400_*] trace to SD every ~5 s\n"
        "                        (requires --sd-log --sd-mount; O_SYNC A6400K.LOG)\n"
        "  --sd-mount            explicit consent to mount the SD (requires --sd-log;\n"
        "                        only after PC Remote 054c:0caa, before INIT, never in MSC)\n"
        "  --sd-dev PATH         block device (default /dev/mmca1; only that node is accepted)\n"
        "  --sd-mountpoint PATH  mount point (default /tmp_bt/sd; must be under /tmp_bt/)\n"
        "\n"
        "Degraded teardown (E0358):\n"
        "  --no-park-recovery    disable the bounded recovery; a failed stop\n"
        "                        attestation parks immediately (default: write the SD\n"
        "                        evidence, retry STOP once, retire/resume, then park\n"
        "                        only if a recovery step fails)\n"
        "  --help\n",
        argv0);
}

static int parse_argv(int argc, char **argv, struct a6400_daemon_config *cfg)
{
    int i;

    for (i = 1; i < argc; i++) {
        const char *a = argv[i];

        if (!strcmp(a, "--help") || !strcmp(a, "-h")) {
            usage(argv[0]);
            return 1;
        } else if (!strcmp(a, "--verbose")) {
            cfg->verbose = 1;
        } else if (!strcmp(a, "--dry-run")) {
            cfg->dry_run = 1;
        } else if (!strcmp(a, "--arm-transport")) {
            g_arm_transport = 1;
        } else if (!strcmp(a, "--wait-pcremote")) {
            cfg->wait_pcremote = 1;
        } else if (!strcmp(a, "--read-prefix")) {
            g_read_prefix = 1;
        } else if (!strcmp(a, "--device") && i + 1 < argc) {
            cfg->device_path = argv[++i];
        } else if (!strcmp(a, "--log") && i + 1 < argc) {
            cfg->log_path = argv[++i];
        } else if (!strcmp(a, "--receipt") && i + 1 < argc) {
            cfg->receipt_path = argv[++i];
        } else if (!strcmp(a, "--control-fifo") && i + 1 < argc) {
            cfg->control_fifo = argv[++i];
        } else if (!strcmp(a, "--control-ack") && i + 1 < argc) {
            cfg->control_ack = argv[++i];
        } else if (!strcmp(a, "--timeout") && i + 1 < argc) {
            cfg->wait_timeout_s = atoi(argv[++i]);
        } else if (!strcmp(a, "--duration") && i + 1 < argc) {
            cfg->duration_s = atoi(argv[++i]);
        } else if (!strcmp(a, "--pid") && i + 1 < argc) {
            cfg->target_pid = atoi(argv[++i]);
        } else if (!strcmp(a, "--fps") && i + 1 < argc) {
            cfg->fps = atoi(argv[++i]);
        } else if (!strcmp(a, "--comp-level") && i + 1 < argc) {
            cfg->comp_level = atoi(argv[++i]);
        } else if (!strcmp(a, "--path-width") && i + 1 < argc) {
            cfg->path_width = atoi(argv[++i]);
        } else if (!strcmp(a, "--width") && i + 1 < argc) {
            cfg->expected_width = atoi(argv[++i]);
        } else if (!strcmp(a, "--height") && i + 1 < argc) {
            cfg->expected_height = atoi(argv[++i]);
        } else if (!strcmp(a, "--dma-phys") && i + 1 < argc) {
            g_dma_phys_opt = (uint32_t)strtoul(argv[++i], NULL, 0);
        } else if (!strcmp(a, "--dma-size") && i + 1 < argc) {
            g_dma_size_opt = (uint32_t)strtoul(argv[++i], NULL, 0);
        } else if (!strcmp(a, "--stats-interval") && i + 1 < argc) {
            g_stats_interval_s = (uint32_t)strtoul(argv[++i], NULL, 0);
        } else if (!strcmp(a, "--wait-ms") && i + 1 < argc) {
            g_wait_bound_ms = (uint32_t)strtoul(argv[++i], NULL, 0);
        } else if (!strcmp(a, "--sd-log")) {
            cfg->sd_log = 1;
        } else if (!strcmp(a, "--dmesg-sd")) {
            cfg->dmesg_sd = 1;
            g_dmesg_sd = 1;
        } else if (!strcmp(a, "--no-park-recovery")) {
            g_park_recovery = 0;
        } else if (!strcmp(a, "--sd-mount")) {
            cfg->sd_mount = 1;
        } else if (!strcmp(a, "--sd-dev") && i + 1 < argc) {
            cfg->sd_dev = argv[++i];
        } else if (!strcmp(a, "--sd-mountpoint") && i + 1 < argc) {
            cfg->sd_mountpoint = argv[++i];
        } else {
            fprintf(stderr, "unknown or incomplete option: %s\n", a);
            usage(argv[0]);
            return -1;
        }
    }
    return 0;
}

/* ---- teardown ------------------------------------------------------------ */

/* Destructive steps are logged before they happen. */
static void log_destructive(const char *what)
{
    log_event("destructive_step", "\"what\":\"%s\"", what);
}

/* Final SD shutdown for EVERY teardown path (E0350):
 *   1. while the filesystem is still mounted, rewrite the receipt so the
 *      durable copy exists before the process can be killed;
 *   2. close the SD log sink;
 *   3. umount2(), tolerating failure with an explicit status. A failed unmount
 *      leaves mounted=1, so no receipt ever claims a clean unmount it did not
 *      observe.
 * Idempotent: a second call after an attempted unmount does nothing. */
static void sd_teardown(void)
{
    if (!g_sd.enabled || g_sd.unmount_attempted)
        return;
    if (g_sd.mounted) {
        (void)write_receipt();
        log_event("sd_log_teardown", "\"mounted\":1,\"receipt_written\":%d",
                  g_sd.receipt_written);
    }
    a6400_log_sd_close(&g_log);
    if (g_sd.mounted) {
        if (g_dmesg_sd && g_sd.mounted)
        (void)a6400_sd_flush_kernel_trace(&g_sd);
    (void)a6400_sd_unmount(&g_sd);
        log_event("sd_log_unmount",
                  "\"rc\":%d,\"still_mounted\":%d,\"errors\":%u",
                  g_sd.unmount_rc, g_sd.mounted, g_sd.errors);
    }
}

/* ---- bounded park recovery (E0358) --------------------------------------- */

/* (a) Durable evidence, ALWAYS before any recovery step. The kernel trace is
 * the only record of which teardown gate refused, and the SD copy of
 * A6400RCPT.JSON is what a battery pull cannot destroy (E0350/E0357). */
static void recovery_evidence(void)
{
    if (g_sd.enabled && g_sd.mounted) {
        int rc = a6400_sd_flush_kernel_trace(&g_sd);

        log_event("recovery_sd_trace",
                  "\"rc\":%d,\"dmesg_sd\":%d,\"trace_lines\":%u,\"trace_errors\":%u",
                  rc, g_dmesg_sd, g_sd.trace_lines, g_sd.trace_errors);
    } else {
        log_event("recovery_sd_trace", "\"mounted\":0,\"durable\":0");
    }
    g_recovery.evidence_written = write_receipt() == 0 ? 1 : 0;
    if (!g_recovery.evidence_written)
        a6400_logf(&g_log, A6400_LOG_ERROR,
                   "recovery_evidence_failed reason=receipt_write_failed");
}

/* (c) Freeze -> HOOK_RETIRE -> resume. The attestation set is resumed on every
 * path, including a failed retire, so the firmware is never left frozen (the
 * publish path follows the same rule). */
static int recovery_retire_hook(struct daemon_rt *rt)
{
    int rc;

    log_destructive("ptrace_freeze_for_recovery_retire");
    rc = a6400_runner_freeze(&rt->runner);
    g_recovery.freeze_rc = rc;
    g_recovery.frozen_tids = rt->runner.tid_count;
    g_rc_tid_count = rt->runner.tid_count;
    g_rc_freeze_ms = rt->runner.last_freeze_ms;
    a6400_logf(&g_log, A6400_LOG_INFO, "recovery_freeze rc=%d tids=%u",
               rc, rt->runner.tid_count);
    if (rc != 0)
        return rc; /* the freeze failure path already resumed a partial attach */

    log_destructive("hook_retire_recovery");
    rc = a6400_runner_retire_hook(&rt->runner);
    g_recovery.retire_rc = rc;
    g_rc_attest_completed = rt->runner.attest_completed;
    g_rc_attest_error = rt->runner.attest_error;
    a6400_logf(&g_log, A6400_LOG_INFO,
               "recovery_hook_retire rc=%d completed=%u error=%d",
               rc, rt->runner.attest_completed, rt->runner.attest_error);
    if (rc == 0) {
        g_recovery.hook_retired = 1;
        g_rc_hook_retired = 1;
        g_rc_hook_published = 0;
        rt->hook_retired = 1;
    }

    log_destructive("ptrace_resume");
    g_recovery.resume_rc = a6400_runner_resume(&rt->runner);
    a6400_logf(&g_log, A6400_LOG_INFO, "recovery_resume rc=%d",
               g_recovery.resume_rc);
    return rc;
}

/* Closes every descriptor the daemon owns. Used by the recovered path so the
 * camera re-enumerates from a released owner, exactly like a clean teardown. */
static void recovery_close(struct daemon_rt *rt)
{
    if (rt->ctl) {
        a6400_control_destroy(rt->ctl);
        rt->ctl = NULL;
    }
    if (rt->mem_fd >= 0) {
        (void)close(rt->mem_fd);
        rt->mem_fd = -1;
    }
    if (rt->uipc_open) {
        a6400_uipc_close(&rt->uipc);
        rt->uipc_open = 0;
    }
    if (rt->uvc_open) {
        a6400_uvc_close(&rt->uvc);
        rt->uvc_open = 0;
    }
    g_recovery.closed = 1;
}

static int recovery_fail(int step, const char *detail)
{
    g_recovery.failed_step = step;
    g_recovery.status = A6400_RECOVERY_FAILED;
    if (detail)
        snprintf(g_recovery.detail, sizeof g_recovery.detail, "%s", detail);
    a6400_logf(&g_log, A6400_LOG_ERROR, "recovery_step_failed step=%s detail=%s",
               a6400_recovery_step_name(step), detail ? detail : "");
    return 0;
}

/* Runs the bounded recovery after a failed STOP attestation (E0358).
 * Returns 1 when every gate passed (the caller finishes with degraded_teardown
 * and the descriptors have already been closed), 0 when a step errored (the
 * caller parks as the last resort; the durable evidence was written first). */
static int recovery_attempt(struct daemon_rt *rt)
{
    int stop_rc = 0, state_valid = 0, verified, i;

    memset(&g_recovery, 0, sizeof g_recovery);
    g_recovery.attempted = 1;
    g_recovery.status = A6400_RECOVERY_PENDING;
    g_recovery.failed_step = A6400_REC_NONE;
    for (i = 0; i < 4; i++) {
        g_recovery.state_before[i] = -1;
        g_recovery.state_after[i] = -1;
    }
    log_event("recovery_begin", "\"reason\":\"stop_attestation_failed\"");

    /* (a) Evidence first: never skipped, even when every later step fails. */
    recovery_evidence();
    if (!g_recovery.evidence_written)
        return recovery_fail(A6400_REC_EVIDENCE, "receipt_write_failed");

    /* Step 2: read-only status. This is the module-supplied diagnostic the old
     * park path never had: state=-1,-1,-1,-1 only ever meant "STOP failed
     * before the query"; this call reports {phase,pinned,hooks,error}. */
    g_recovery.state_before_valid =
        a6400_runner_query_session_state(rt->uvc.fd, g_recovery.state_before);
    log_event("recovery_state",
              "\"source\":\"after_failed_stop\",\"valid\":%d,\"phase\":%d,"
              "\"pin\":%d,\"hooks\":%d,\"error\":%d",
              g_recovery.state_before_valid, g_recovery.state_before[0],
              g_recovery.state_before[1], g_recovery.state_before[2],
              g_recovery.state_before[3]);

    /* Step 3: one bounded STOP retry. The module's STOP runs the ordered
     * 9-phase unconfigure-first teardown (cleanup -> session_end ->
     * a6400_uvc_soft_disconnect); HOOK_RETIRE does not run it and the module
     * refuses HOOK_RETIRE while the session is held. */
    if (a6400_recovery_retry_allowed(g_recovery.state_before_valid,
                                     g_recovery.state_before)) {
        log_destructive("uvc_stop_retry");
        g_rc_stop_attempts = 2u;
        verified = a6400_runner_retry_stop(rt->uvc.fd, g_recovery.state_after,
                                           &stop_rc, &state_valid);
        g_recovery.stop_retry_rc = stop_rc;
        g_recovery.state_after_valid = state_valid;
        g_recovery.stop_retry_verified = verified;
        log_event("recovery_stop_retry",
                  "\"ioctl_rc\":%d,\"state_valid\":%d,\"phase\":%d,\"pin\":%d,"
                  "\"hooks\":%d,\"error\":%d,\"verified\":%d",
                  stop_rc, state_valid, g_recovery.state_after[0],
                  g_recovery.state_after[1], g_recovery.state_after[2],
                  g_recovery.state_after[3], verified);
        if (stop_rc != 0)
            return recovery_fail(A6400_REC_STOP_RETRY,
                                 "stop_retry_ioctl_failed");
        if (!verified)
            return recovery_fail(A6400_REC_STOP_RETRY,
                                 "state_not_zero_after_retry");
    } else {
        /* The read-only state already proved the session idle: no second
         * destructive STOP is issued. */
        for (i = 0; i < 4; i++)
            g_recovery.state_after[i] = g_recovery.state_before[i];
        g_recovery.state_after_valid = g_recovery.state_before_valid;
        g_recovery.stop_retry_verified = 1;
        log_event("recovery_stop_retry", "\"skipped\":\"state_already_zero\"");
    }

    /* Step 4: retire the entry hook under a verified ptrace stop scope and
     * always resume the attestation set (the 181 TIDs of E0357 are this set). */
    if (recovery_retire_hook(rt) != 0) {
        if (g_recovery.freeze_rc != 0)
            return recovery_fail(A6400_REC_FREEZE, "freeze_failed");
        return recovery_fail(A6400_REC_HOOK_RETIRE, "hook_retire_failed");
    }
    if (g_recovery.resume_rc != 0)
        return recovery_fail(A6400_REC_RESUME, "resume_failed");

    /* Step 5: close, then let the pure classifier decide. */
    log_destructive("recovery_close");
    recovery_close(rt);
    g_recovery.status = a6400_recovery_outcome(&g_recovery);
    if (g_recovery.status != A6400_RECOVERY_RECOVERED) {
        g_recovery.failed_step = A6400_REC_CLOSE;
        snprintf(g_recovery.detail, sizeof g_recovery.detail, "%s",
                 "close_incomplete");
        return 0;
    }
    return 1;
}

static void teardown(struct daemon_rt *rt, const struct a6400_daemon_config *cfg,
                     int *code)
{
    int32_t state[4];
    int rc;

    g_stage = "teardown";
    log_event("teardown_begin", NULL);

    /* 1. The stream is already stopped: the loop has returned. */
    if (rt->uipc_open) {
        struct a6400_scalar_path_cfg stop_cfg;

        log_destructive("set_path_stop");
        memset(&stop_cfg, 0, sizeof stop_cfg);
        stop_cfg.timeout_ms = 1500;
        rc = a6400_scalar_set_path(&rt->dmm, &stop_cfg);
        a6400_logf(&g_log, A6400_LOG_INFO, "set_path_stop status=%d", rc);

        /* 2. Restore the default DMM allocation rule. */
        log_destructive("dmm_rule_0");
        rc = a6400_dmm_set_rule(&rt->dmm, 0, 0);
        a6400_logf(&g_log, A6400_LOG_INFO, "dmm_rule_0 status=%d", rc);
    }

    if (rt->reg_buf_ok) {
        log_destructive("uvc_unreg");
        rc = a6400_uvc_unreg(&rt->uvc);
        a6400_logf(&g_log, A6400_LOG_INFO, "uvc_unreg rc=%d", rc);
    }

    /* 3. STOP plus the all-zero session-state attestation. This is the gate
     *    that permits hook retirement (uvc_ptp_runner_stop.h:7-19). A failure
     *    first runs the bounded E0358 recovery; only a recovery error parks. */
    if (rt->init_attempted) {
        log_destructive("uvc_stop");
        g_rc_stop_attempts = 1u;
        g_rc_stop_verified = a6400_runner_stop_verified(rt->uvc.fd, state);
        g_rc_session_active = 0;
        g_stats.session_active = 0;
        a6400_logf(&g_log, A6400_LOG_INFO,
                   "uvc_stop verified=%d state=%d,%d,%d,%d",
                   g_rc_stop_verified, state[0], state[1], state[2], state[3]);
        if (!g_rc_stop_verified) {
            int recovered = 0;

            /* `state` is the daemon's -1 sentinel here: STOP failed before the
             * status query, so no module state was read (E0358 analysis). */
            snprintf(g_fail_reason, sizeof g_fail_reason,
                     "stop attestation failed state=%d,%d,%d,%d",
                     state[0], state[1], state[2], state[3]);
            if (g_park_recovery) {
                /* (a)-(c): evidence first, then one bounded STOP retry that
                 * re-enters the 9-phase teardown, then retire/resume/close. */
                g_stage = "recovery";
                g_exit_code = A6400_EXIT_DEGRADED;
                recovered = recovery_attempt(rt);
            } else {
                a6400_logf(&g_log, A6400_LOG_WARN,
                           "recovery_disabled flag=--no-park-recovery");
            }
            if (recovered) {
                g_rc_teardown_verified = 1;
                g_exit_code = A6400_EXIT_DEGRADED;
                *code = A6400_EXIT_DEGRADED;
                g_stage = "teardown_degraded";
                snprintf(g_fail_reason, sizeof g_fail_reason,
                         "stop attestation failed state=%d,%d,%d,%d; "
                         "recovered by one bounded STOP retry",
                         state[0], state[1], state[2], state[3]);
                log_event("recovery_complete",
                          "\"status\":\"recovered\",\"stop_attempts\":%u",
                          g_rc_stop_attempts);
                (void)write_receipt();
                sd_teardown();
                return;
            }
            /* Fail closed: park remains the last resort. The durable evidence
             * was already written by the evidence step; this receipt records
             * which recovery step failed so a future run is diagnosable. */
            g_stage = "parked";
            g_exit_code = A6400_EXIT_FATAL;
            *code = A6400_EXIT_FATAL;
            if (g_recovery.attempted) {
                snprintf(g_fail_reason, sizeof g_fail_reason,
                         "stop attestation failed state=%d,%d,%d,%d; recovery "
                         "failed step=%s rc=%d detail=%s",
                         state[0], state[1], state[2], state[3],
                         a6400_recovery_step_name(g_recovery.failed_step),
                         g_recovery.stop_retry_rc,
                         g_recovery.detail[0] ? g_recovery.detail : "none");
            }
            a6400_logf(&g_log, A6400_LOG_ERROR,
                       "parked reason=stop_attestation_failed recovery=%s "
                       "failed_step=%s",
                       a6400_recovery_status_name(g_recovery.status),
                       a6400_recovery_step_name(g_recovery.failed_step));
            /* Defensive, before any slow SD work: never park while this process
             * holds a ptrace stop scope. The recovery path always resumes; this
             * catches a state the logic above believes impossible. */
            if (rt->runner.frozen) {
                int resume_rc = a6400_runner_resume(&rt->runner);

                a6400_logf(&g_log, A6400_LOG_WARN,
                           "park_resume_guard rc=%d", resume_rc);
            }
            (void)write_receipt();
            /* Make the durable receipt and unmount BEFORE parking: a parked
             * process can sit indefinitely and the camera may be battery-pulled
             * at any moment (E0350). */
            sd_teardown();
            /* Park: keep the descriptor and the hook state exactly as they are.
             * A signal is the operator's explicit decision to leave. */
            if (a6400_runner_park(&g_stop)) {
                a6400_logf(&g_log, A6400_LOG_WARN,
                           "park_released_by_signal; descriptor left open");
            }
            (void)write_receipt();
            return;
        }
    }

    if (g_rc_hook_published) {
        /* 4. Freeze, retire the entry hook, resume, then close. */
        log_destructive("ptrace_freeze_for_retire");
        rc = a6400_runner_freeze(&rt->runner);
        a6400_logf(&g_log, A6400_LOG_INFO, "retire_freeze rc=%d tids=%u",
                   rc, rt->runner.tid_count);
        g_rc_tid_count = rt->runner.tid_count;
        g_rc_freeze_ms = rt->runner.last_freeze_ms;
        if (rc != 0) {
            g_exit_code = A6400_EXIT_FATAL;
            *code = A6400_EXIT_FATAL;
            g_stage = "teardown";
            snprintf(g_fail_reason, sizeof g_fail_reason,
                     "freeze before retire failed rc=%d", rc);
            a6400_logf(&g_log, A6400_LOG_ERROR,
                       "retire_aborted reason=freeze_failed rc=%d", rc);
            (void)write_receipt();
            sd_teardown();
            return;
        }

        log_destructive("hook_retire");
        rc = a6400_runner_retire_hook(&rt->runner);
        g_rc_attest_completed = rt->runner.attest_completed;
        g_rc_attest_error = rt->runner.attest_error;
        a6400_logf(&g_log, A6400_LOG_INFO,
                   "hook_retire rc=%d completed=%u error=%d",
                   rc, rt->runner.attest_completed, rt->runner.attest_error);
        if (rc == 0) {
            g_rc_hook_retired = 1;
            g_rc_hook_published = 0;
        } else {
            g_exit_code = A6400_EXIT_FATAL;
            *code = A6400_EXIT_FATAL;
            g_stage = "teardown";
            snprintf(g_fail_reason, sizeof g_fail_reason,
                     "hook retire failed rc=%d", rc);
        }

        log_destructive("ptrace_resume");
        rc = a6400_runner_resume(&rt->runner);
        a6400_logf(&g_log, A6400_LOG_INFO, "retire_resume rc=%d", rc);
        if (rc != 0) {
            g_exit_code = A6400_EXIT_FATAL;
            *code = A6400_EXIT_FATAL;
            g_stage = "teardown";
            snprintf(g_fail_reason, sizeof g_fail_reason,
                     "resume after retire failed rc=%d", rc);
        }
        rt->hook_retired = g_rc_hook_retired;
        /* The clean path is verified only when the STOP gate AND the retire
         * both succeeded; the recovered (degraded) path sets the same field. */
        g_rc_teardown_verified = g_rc_hook_retired ? 1 : 0;
    }

    /* 5. Close everything. The node is not unlinked (see a6400_uvc_close). */
    if (rt->ctl) {
        a6400_control_destroy(rt->ctl);
        rt->ctl = NULL;
    }
    if (rt->mem_fd >= 0) {
        (void)close(rt->mem_fd);
        rt->mem_fd = -1;
    }
    if (rt->uipc_open) {
        a6400_uipc_close(&rt->uipc);
        rt->uipc_open = 0;
    }
    if (rt->uvc_open) {
        a6400_uvc_close(&rt->uvc);
        rt->uvc_open = 0;
    }
    (void)cfg;
    g_exit_code = *code;
    log_event("teardown_complete", "\"exit_code\":%d", *code);
    /* Durable receipt + unmount in the normal teardown path (E0350). */
    sd_teardown();
}

/* ---- run ----------------------------------------------------------------- */

static int open_control(struct daemon_rt *rt, const struct a6400_daemon_config *cfg)
{
    struct a6400_control_host host;
    struct a6400_control_config ccfg;

    if (!cfg->control_fifo || !cfg->control_fifo[0])
        return 0;

    /* Create the FIFO if absent. mkfifo is idempotent for our purposes: an
     * existing node (EEXIST) is reused, any other error is reported by the
     * control layer's open result and surfaced through poll(). */
    if (mkfifo(cfg->control_fifo, 0600) != 0 && errno != EEXIST) {
        a6400_logf(&g_log, A6400_LOG_WARN, "control_fifo_create_failed path=%s errno=%d",
                   cfg->control_fifo, errno);
    }

    memset(&host, 0, sizeof host);
    host.get_stats = host_get_stats;
    host.get_caps = host_get_caps;
    host.session_active = host_session_active;

    memset(&ccfg, 0, sizeof ccfg);
    ccfg.fifo_path = cfg->control_fifo;
    ccfg.ack_path = cfg->control_ack;
    ccfg.video_node = cfg->device_path;
    ccfg.enable_ring = 0; /* no decoded ring ioctl; a second open is forbidden */
    ccfg.verbose = cfg->verbose;

    rt->ctl = a6400_control_create(&ccfg, &host);
    if (!rt->ctl) {
        a6400_logf(&g_log, A6400_LOG_ERROR, "control_create_failed");
        return -1;
    }
    a6400_logf(&g_log, A6400_LOG_INFO, "control_ready fifo=%s ack=%s",
               cfg->control_fifo,
               (cfg->control_ack && cfg->control_ack[0]) ? cfg->control_ack : "(none)");
    return 0;
}

static int wait_for_pcremote(struct daemon_rt *rt,
                             const struct a6400_daemon_config *cfg)
{
    int waited = 0;
    uint16_t ids[2] = {0, 0};
    int rc = 0;

    while (waited < cfg->wait_timeout_s && !g_stop) {
        rc = a6400_uvc_query_identity(&rt->uvc, ids);
        if (rc == 0 && ids[0] == 0x054cu && ids[1] == 0x0caau) {
            struct timespec ts;

            a6400_logf(&g_log, A6400_LOG_INFO,
                       "pcremote_detected after_s=%d id=%04x:%04x (settling 2 s)",
                       waited, ids[0], ids[1]);
            /* Settle exactly like the physically run runner (line 146). */
            ts.tv_sec = 2;
            ts.tv_nsec = 0;
            while (nanosleep(&ts, &ts) != 0 && errno == EINTR && !g_stop) {
            }
            return 0;
        }
        {
            struct timespec ts;

            ts.tv_sec = 1;
            ts.tv_nsec = 0;
            while (nanosleep(&ts, &ts) != 0 && errno == EINTR && !g_stop) {
            }
        }
        waited++;
    }
    a6400_logf(&g_log, A6400_LOG_ERROR,
               "pcremote_timeout waited_s=%d last=%04x:%04x rc=%d",
               waited, ids[0], ids[1], rc);
    return -ETIMEDOUT;
}

int a6400_daemon_run(const struct a6400_daemon_config *cfg)
{
    struct daemon_rt rt;
    int code = A6400_EXIT_CLEAN;
    int pcremote_confirmed = 0;
    int rc;
    int log_rc;

    memset(&rt, 0, sizeof rt);
    memset(&g_stats, 0, sizeof g_stats);
    memset(&g_sd, 0, sizeof g_sd);
    g_stats.started_monotonic_ns = (uint64_t)a6400_now_ns();
    g_stats.phase = (uint32_t)A6400_PHASE_IDLE;
    g_stage = "init";
    g_fail_reason[0] = '\0';
    g_exit_code = A6400_EXIT_CLEAN;
    /* E0358: no recovery state exists unless a failed STOP created it. The
     * state arrays stay at -1 so the receipt can never present an unanswered
     * status read as an all-zero (verified) session. */
    memset(&g_recovery, 0, sizeof g_recovery);
    memset(g_recovery.state_before, 0xff, sizeof g_recovery.state_before);
    memset(g_recovery.state_after, 0xff, sizeof g_recovery.state_after);
    g_rc_teardown_verified = 0;
    g_rc_stop_attempts = 0;
    g_cfg = *cfg;
    /* Initialise the SD status even when the feature is off: the receipt then
     * says "enabled:0" instead of omitting the block. */
    a6400_sd_status_init(&g_sd, cfg->sd_log, cfg->sd_mount, cfg->sd_dev,
                         cfg->sd_mountpoint);
    rt.uvc.fd = -1;
    rt.uipc.fd = -1;
    rt.mem_fd = -1;
    a6400_frame_queue_init(&rt.q);
    a6400_runner_init(&rt.runner, -1, cfg->target_pid);
    rt.exp_w = (uint32_t)cfg->expected_width;
    rt.exp_h = (uint32_t)cfg->expected_height;

    rc = validate_config(cfg);
    if (rc != 0) {
        log_rc = a6400_log_open(&g_log, cfg->log_path,
                                cfg->verbose ? A6400_LOG_DEBUG : A6400_LOG_INFO);
        (void)log_rc;
        if (rc == -14)
            code = stage_fail("refused", A6400_EXIT_REFUSED,
                              "destructive steps require --arm-transport "
                              "(or use --dry-run)");
        else if (rc == -17)
            code = stage_fail("refused", A6400_EXIT_REFUSED,
                              "--sd-mount requires --sd-log (mounting without a "
                              "sink is never useful)");
        else if (rc == -18)
            code = stage_fail("refused", A6400_EXIT_REFUSED,
                              "--sd-dev refused: only /dev/mmca1 is allowed "
                              "(internal flash is never mountable)");
        else if (rc == -19)
            code = stage_fail("refused", A6400_EXIT_REFUSED,
                              "--sd-mountpoint refused: must be a child of /tmp_bt");
        else
            code = stage_fail("refused", A6400_EXIT_REFUSED,
                              "invalid configuration (validate rc=%d)", rc);
        (void)write_receipt();
        a6400_log_close(&g_log);
        return code;
    }

    log_rc = a6400_log_open(&g_log, cfg->log_path,
                            cfg->verbose ? A6400_LOG_DEBUG : A6400_LOG_INFO);
    if (log_rc != 0) {
        /* Logging failure is not fatal by contract (a6400_log.h:39-40); the
         * receipt still records the run because it is written separately. */
        fprintf(stderr, "a6400-lived: log open failed rc=%d path=%s\n",
                log_rc, cfg->log_path);
    }
    log_event("start",
              "\"pid\":%d,\"dry_run\":%d,\"arm_transport\":%d,\"read_prefix\":%d,"
              "\"fps\":%d,\"path_width\":%d,\"comp_level\":%d,\"duration_s\":%d",
              cfg->target_pid, cfg->dry_run, g_arm_transport, g_read_prefix,
              cfg->fps, cfg->path_width, cfg->comp_level, cfg->duration_s);

    {
        struct sigaction sa;

        memset(&sa, 0, sizeof sa);
        sa.sa_handler = sig_handler;
        sigemptyset(&sa.sa_mask);
        sa.sa_flags = 0;
        (void)sigaction(SIGINT, &sa, NULL);
        (void)sigaction(SIGTERM, &sa, NULL);
        (void)signal(SIGPIPE, SIG_IGN);
    }

    /* --- device open (always; read-only discovery is the whole point of
     *     --dry-run and the identity query needs the node) ------------------ */
    g_stage = "device_open";
    g_stats.phase = (uint32_t)A6400_PHASE_IDLE;
    rc = a6400_uvc_open(&rt.uvc, cfg->device_path);
    if (rc != 0) {
        code = stage_fail("device_open", A6400_EXIT_STAGE,
                          "open %s failed rc=%d", cfg->device_path, rc);
        goto finish;
    }
    rt.uvc_open = 1;
    rt.runner.uvc_fd = rt.uvc.fd;
    a6400_logf(&g_log, A6400_LOG_INFO, "device_open path=%s node_created=%d",
               rt.uvc.path, rt.uvc.node_created);

    {
        uint16_t ids[2] = {0, 0};
        uint32_t state[4] = {0, 0, 0, 0};
        int id_rc = a6400_uvc_query_identity(&rt.uvc, ids);
        int st_rc = a6400_uvc_query_usb_state(&rt.uvc, state);

        log_event("usb_identity",
                  "\"rc\":%d,\"vid\":%u,\"pid\":%u,\"state_rc\":%d,"
                  "\"flags\":%u,\"config\":%u,\"mode\":%u,\"speed\":%u",
                  id_rc, ids[0], ids[1], st_rc, state[0], state[1], state[2],
                  state[3]);
    }

    if (cfg->wait_pcremote) {
        g_stage = "wait_pcremote";
        g_stats.phase = (uint32_t)A6400_PHASE_WAIT_PCREMOTE;
        if (wait_for_pcremote(&rt, cfg) != 0) {
            code = stage_fail("wait_pcremote", A6400_EXIT_STAGE,
                              "PC Remote 0x054c:0x0caa not seen in %d s",
                              cfg->wait_timeout_s);
            goto finish;
        }
        pcremote_confirmed = 1;
    }

    /* --- optional crash-safe SD log (E0350) -------------------------------- */
    /* The camera app owns the SD card in Mass Storage. The only safe window is:
     * PC Remote confirmed (054c:0caa) AND before INIT/streaming. --sd-log alone
     * keeps the RAM log only; --sd-mount is the explicit mount(2) consent. A
     * refusal is recorded in the receipt's sd_log block - it is never silently
     * skipped and never retried outside the window. */
    if (cfg->sd_log) {
        struct a6400_sd_window w;

        memset(&w, 0, sizeof w);
        w.sd_log = cfg->sd_log;
        w.sd_mount = cfg->sd_mount;
        w.dry_run = cfg->dry_run;
        w.pcremote_confirmed = pcremote_confirmed;
        w.init_started = 0;
        w.streaming = 0;
        /* msc_mode is not guessed: unconfirmed PC Remote is refused by the
         * pcremote gate, which is the observable "camera app may own the SD"
         * condition. */
        w.msc_mode = 0;
        g_stage = "sd_log";
        if (!cfg->sd_mount) {
            g_sd.mount_rc = A6400_SD_ERR_NO_CONSENT;
            log_event("sd_log_ram_only",
                      "\"reason\":\"mount_consent_missing\"");
        } else {
            rc = a6400_sd_mount(&g_sd, &w);
            if (rc == A6400_SD_OK) {
                struct a6400_log_sd_stats sds;

                g_sd.open_rc = a6400_log_sd_open(&g_log, g_sd.mountpoint);
                memset(&sds, 0, sizeof sds);
                a6400_log_sd_get(&g_log, &sds);
                g_sd.sync_mode = sds.sync_mode;
                if (g_sd.open_rc != 0) {
                    a6400_logf(&g_log, A6400_LOG_WARN,
                               "sd_log_open_failed rc=%d path=%s/%s",
                               g_sd.open_rc, g_sd.mountpoint, A6400_SD_LOG_NAME);
                }
                log_event("sd_log_mounted",
                          "\"device\":\"%s\",\"mountpoint\":\"%s\","
                          "\"open_rc\":%d,\"sync_mode\":%d,\"verified\":%d,"
                          "\"sentinel_ok\":%d",
                          g_sd.device, g_sd.mountpoint, g_sd.open_rc,
                          g_sd.sync_mode, g_sd.verified, g_sd.sentinel_ok);
            } else {
                a6400_logf(&g_log, A6400_LOG_WARN,
                           "sd_log_mount_refused rc=%d reason=%s device=%s mountpoint=%s",
                           rc, g_sd.reason, g_sd.device, g_sd.mountpoint);
                log_event("sd_log_unavailable",
                          "\"rc\":%d,\"reason\":\"%s\",\"mounted\":0",
                          rc, g_sd.reason);
            }
        }
        g_stage = "init";
    }

    /* --- DMA window discovery --------------------------------------------- */
    /* Dry-run probes the read-only query before any session exists; the armed
     * path asks again after INIT, because the authored module's shared ioctl is
     * not guaranteed to answer before the session is up. */
    if (cfg->dry_run) {
        rc = resolve_dma_window(&rt, 1);
        g_stage = "dry_run";
        g_stats.phase = (uint32_t)A6400_PHASE_IDLE;
        log_event("dry_run_complete",
                  "\"dma_query_rc\":%d,\"dma_meta_source\":%d,"
                  "\"arm_transport_needed\":1",
                  g_rc_dma_query_rc, g_rc_meta_source);
        code = A6400_EXIT_CLEAN;
        (void)rc;
        goto finish;
    }

    /* --- everything below is destructive ---------------------------------- */
    /* --- freeze + entry hook publish ------------------------------------- */
    g_stage = "freeze";
    g_stats.phase = (uint32_t)A6400_PHASE_FREEZE;
    log_destructive("ptrace_freeze");
    rc = a6400_runner_freeze(&rt.runner);
    g_rc_tid_count = rt.runner.tid_count;
    g_rc_freeze_ms = rt.runner.last_freeze_ms;
    a6400_logf(&g_log, A6400_LOG_INFO, "freeze rc=%d tids=%u elapsed_ms=%u",
               rc, rt.runner.tid_count, rt.runner.last_freeze_ms);
    if (rc != 0) {
        code = stage_fail("freeze", A6400_EXIT_STAGE,
                          "freeze of pid %d failed rc=%d", cfg->target_pid, rc);
        goto finish;
    }

    g_stage = "hook_publish";
    log_destructive("hook_publish");
    rc = a6400_runner_publish_hook(&rt.runner);
    g_rc_attest_completed = rt.runner.attest_completed;
    g_rc_attest_error = rt.runner.attest_error;
    a6400_logf(&g_log, A6400_LOG_INFO,
               "hook_publish rc=%d completed=%u error=%d",
               rc, rt.runner.attest_completed, rt.runner.attest_error);
    {
        /* Resume even when publish failed: never leave the camera frozen. */
        int resume_rc = a6400_runner_resume(&rt.runner);

        a6400_logf(&g_log, A6400_LOG_INFO, "publish_resume rc=%d", resume_rc);
        if (resume_rc != 0) {
            code = stage_fail("hook_publish", A6400_EXIT_FATAL,
                              "resume after publish failed rc=%d", resume_rc);
            goto finish;
        }
    }
    if (rc != 0) {
        code = stage_fail("hook_publish", A6400_EXIT_STAGE,
                          "entry hook publish failed rc=%d", rc);
        goto finish;
    }
    g_rc_hook_published = 1;
    g_stats.phase = (uint32_t)A6400_PHASE_HOOK_PUBLISHED;

    /* --- INIT ------------------------------------------------------------- */
    g_stage = "uvc_init";
    g_stats.phase = (uint32_t)A6400_PHASE_INIT;
    {
        /* g_interfaces is the 4-byte list the physically run feeder and runner
         * both used; interface_count is 2 (uvc_sensor_feeder_30fps.c:91,599). */
        static const uint8_t interfaces[A6400_UVC_INTERFACE_LIST_LEN] =
            { 0, 0, 1, 1 };

        log_destructive("uvc_init");
        rt.init_attempted = 1;
        g_rc_init_attempted = 1;
        rc = a6400_uvc_init(&rt.uvc, interfaces, 2);
    }
    a6400_logf(&g_log, A6400_LOG_INFO, "uvc_init rc=%d", rc);
    if (rc != 0) {
        code = stage_fail("uvc_init", A6400_EXIT_STAGE,
                          "IOCTL_UVC_INIT failed rc=%d (EINVAL in Mass Storage)", rc);
        goto finish;
    }
    rt.session_active = 1;
    g_rc_session_active = 1;
    g_stats.session_active = 1;
    g_stats.phase = (uint32_t)A6400_PHASE_BUFFER_READY;

    /* --- DMA window (post-INIT: see the dry-run note above) --------------- */
    g_stage = "dma_query";
    if (resolve_dma_window(&rt, 0) != 0) {
        code = g_exit_code != A6400_EXIT_CLEAN ? g_exit_code : A6400_EXIT_STAGE;
        goto finish;
    }
    g_stats.slot_size = rt.meta.slot_size;
    g_stats.max_frame_payload = rt.meta.max_frame_payload;

    /* --- REG_BUF + ENABLE ------------------------------------------------- */
    g_stage = "uvc_reg_buf";
    log_destructive("uvc_reg_buf");
    rc = a6400_uvc_reg_buf(&rt.uvc, rt.meta.total_size, rt.meta.phys_addr);
    g_rc_reg_buf_rc = rc;
    a6400_logf(&g_log, A6400_LOG_INFO, "uvc_reg_buf rc=%d size=%u phys=%u",
               rc, rt.meta.total_size, rt.meta.phys_addr);
    if (rc != 0) {
        code = stage_fail("uvc_reg_buf", A6400_EXIT_STAGE,
                          "REG_BUF rejected rc=%d (window not acknowledged)", rc);
        goto finish;
    }
    rt.reg_buf_ok = 1;

    g_stage = "uvc_enable";
    log_destructive("uvc_enable");
    rc = a6400_uvc_enable(&rt.uvc);
    g_rc_enable_rc = rc;
    a6400_logf(&g_log, A6400_LOG_INFO, "uvc_enable rc=%d", rc);
    if (rc != 0) {
        code = stage_fail("uvc_enable", A6400_EXIT_STAGE,
                          "ENABLE failed rc=%d", rc);
        goto finish;
    }
    rt.enable_ok = 1;

    /* --- control FIFO ----------------------------------------------------- */
    g_stage = "control";
    if (open_control(&rt, cfg) != 0) {
        code = stage_fail("control", A6400_EXIT_STAGE, "control bridge unavailable");
        goto finish;
    }

    /* --- OSAL + DMM rule 5 ------------------------------------------------ */
    g_stage = "osal_open";
    rc = a6400_uipc_open(&rt.uipc);
    a6400_logf(&g_log, A6400_LOG_INFO, "osal_open rc=%d reply_qid=%u pool=%u",
               rc, rt.uipc.reply_qid, rt.uipc.pool_size);
    if (rc != 0) {
        code = stage_fail("osal_open", A6400_EXIT_STAGE, "OSAL open failed rc=%d", rc);
        goto finish;
    }
    rt.uipc_open = 1;
    rt.dmm.uipc = &rt.uipc;

    g_stage = "dmm_rule";
    log_destructive("dmm_rule_5");
    rc = a6400_dmm_set_rule(&rt.dmm, 5, 0);
    a6400_logf(&g_log, A6400_LOG_INFO, "dmm_rule_5 status=%d", rc);
    if (rc != 0) {
        code = stage_fail("dmm_rule", A6400_EXIT_STAGE,
                          "DMM rule 5 rejected status=%d", rc);
        goto finish;
    }

    /* --- SET_PATH --------------------------------------------------------- */
    g_stage = "set_path";
    {
        struct a6400_scalar_path_cfg sc;

        log_destructive("set_path_reset");
        memset(&sc, 0, sizeof sc);
        sc.timeout_ms = 1500;
        rc = a6400_scalar_set_path(&rt.dmm, &sc);
        a6400_logf(&g_log, A6400_LOG_INFO, "set_path_reset status=%d", rc);
    }
    {
        struct a6400_scalar_path_cfg sc;

        log_destructive("set_path_start");
        memset(&sc, 0, sizeof sc);
        sc.enable = 1;
        sc.rate_fps = (uint32_t)cfg->fps;
        sc.width = (uint32_t)cfg->path_width;
        sc.comp_level = (uint32_t)cfg->comp_level;
        sc.param_val = 300; /* feeder:465 */
        sc.timeout_ms = 5000;
        rc = a6400_scalar_set_path(&rt.dmm, &sc);
        a6400_logf(&g_log, A6400_LOG_INFO,
                   "set_path_start status=%d rate=%u width=%u comp=%u",
                   rc, sc.rate_fps, sc.width, sc.comp_level);
    }
    if (rc != 0) {
        code = stage_fail("set_path", A6400_EXIT_STAGE,
                          "SET_PATH start rejected status=%d", rc);
        goto finish;
    }

    /* --- /dev/mem reader (optional; never fabricated) --------------------- */
    rt.mem_fd = open("/dev/mem", O_RDONLY | O_CLOEXEC);
    if (rt.mem_fd < 0) {
        a6400_logf(&g_log, A6400_LOG_WARN,
                   "dev_mem_unavailable errno=%d; JPEG prefix cannot be read", errno);
    }

    /* --- stream ----------------------------------------------------------- */
    g_stage = "stream";
    g_stats.phase = (uint32_t)A6400_PHASE_STREAMING;
    log_event("stream_begin",
              "\"fps\":%d,\"slot\":%u,\"max_payload\":%u,\"duration_s\":%d,"
              "\"expected\":\"%ux%u\"",
              cfg->fps, rt.meta.slot_size, rt.meta.max_frame_payload,
              cfg->duration_s, rt.exp_w, rt.exp_h);
    if (stream_loop(&rt, cfg) != 0) {
        code = g_exit_code != A6400_EXIT_CLEAN ? g_exit_code : A6400_EXIT_STAGE;
        goto finish;
    }

    g_stats.phase = (uint32_t)A6400_PHASE_STOPPING;
    if (g_stop)
        log_event("stream_stopped", "\"reason\":\"signal_or_control\"");
    else
        log_event("stream_stopped", "\"reason\":\"duration_elapsed\"");
    code = A6400_EXIT_CLEAN;

finish:
    g_exit_code = code;
    teardown(&rt, cfg, &code);
    g_exit_code = code;
    if (code == A6400_EXIT_CLEAN)
        g_stage = g_rc_hook_published ? "teardown" : "complete";
    (void)write_receipt();
    log_event("exit", "\"status\":\"%s\",\"code\":%d", status_name(code), code);
    a6400_log_close(&g_log);
    return code;
}

int main(int argc, char **argv)
{
    struct a6400_daemon_config cfg;
    int rc;

    memset(&cfg, 0, sizeof cfg);
    cfg.device_path = A6400_UVC_NODE_PATH;
    cfg.log_path = "/tmp_bt/a6400_lived.jsonl";
    cfg.receipt_path = "/tmp_bt/a6400_lived_receipt.json";
    cfg.control_fifo = "/tmp_bt/a6400_ctrl.fifo";
    cfg.control_ack = "/tmp_bt/a6400_ctrl.ack";
    cfg.wait_pcremote = 0;
    cfg.wait_timeout_s = 120;
    cfg.duration_s = 0;
    cfg.target_pid = A6400_DAEMON_TARGET_PID;
    cfg.expected_width = 0;
    cfg.expected_height = 0;
    cfg.fps = 30;
    cfg.comp_level = 5;
    cfg.path_width = 1280;
    cfg.dry_run = 0;
    cfg.verbose = 0;
    cfg.sd_log = 0;                    /* E0350: opt-in, default OFF */
    cfg.sd_mount = 0;                  /* explicit consent, default OFF */
    cfg.sd_dev = A6400_SD_DEV_DEFAULT;
    cfg.sd_mountpoint = A6400_SD_MOUNT_DEFAULT;
    g_park_recovery = 1;               /* E0358: bounded recovery is the default */

    rc = parse_argv(argc, argv, &cfg);
    if (rc == 1)
        return A6400_EXIT_CLEAN;
    if (rc != 0)
        return A6400_EXIT_REFUSED;

    return a6400_daemon_run(&cfg);
}
