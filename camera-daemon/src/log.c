/* Bounded JSONL logger with an optional O_SYNC SD second sink.
 *
 * Constraints:
 *  - /tmp_bt is a 1 MiB tmpfs (reports/a6400_hw_dump.txt:234), so one log file
 *    is capped at A6400_LOG_MAX_BYTES (256 KiB) and a line that would cross the
 *    cap is dropped, never written partially.
 *  - The writer must never block the frame loop: all writes are plain write()
 *    calls to an O_NONBLOCK regular file (a no-op flag for regular files, but
 *    it documents the intent and keeps behaviour uniform if the path is ever a
 *    FIFO), no allocation, no buffering, no retry on EAGAIN.
 *  - A file log is the only channel that survives until the host reads it back,
 *    and it does NOT survive a reboot (E0342:24-26); the receipt written by the
 *    daemon core is the durable record and must be complete before any mode
 *    change.
 *  - E0350: a battery pull is the only recovery from a wedged session and it
 *    wipes /tmp_bt. When the daemon mounted an SD card (`--sd-log --sd-mount`),
 *    every COMPLETED line is also appended to A6400LD.LOG on that card with
 *    O_SYNC (or fsync per line when O_SYNC is unavailable), capped at 128 KiB
 *    and rotated once to A6400LD.1 (8.3 names, E0236). A failed SD write drops
 *    the SD sink, counts the error and leaves RAM logging fully functional: the
 *    stream is never lost because of the log.
 *
 * Every line is a complete JSON object, so the whole file is valid JSONL:
 *   {"t":<monotonic_ms>,"lvl":"info","msg":"..."}
 * a6400_log_json() writes a caller-formatted object verbatim (plus newline) and
 * is what structured events use.
 */
#include "a6400_log.h"
#include "a6400_sdlog.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif
#ifndef O_NONBLOCK
#define O_NONBLOCK 0
#endif

/* O_SYNC is the durability primitive the brief requires. It is present on the
 * camera's Linux headers; if a build ever lacks it, the sink falls back to an
 * explicit fsync() after every line and reports sync_mode 0. */
#if defined(O_SYNC) && (O_SYNC != 0)
#define A6400_LOG_SD_OPEN_FLAGS \
    (O_WRONLY | O_CREAT | O_APPEND | O_SYNC | O_CLOEXEC)
#define A6400_LOG_SD_SYNC_MODE 1
#else
#define A6400_LOG_SD_OPEN_FLAGS (O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC)
#define A6400_LOG_SD_SYNC_MODE 0
#endif

#define A6400_LOG_PATH_PREFIX "/tmp_bt/"

static const char *level_name(int level)
{
    switch (level) {
    case A6400_LOG_ERROR: return "error";
    case A6400_LOG_WARN:  return "warn";
    case A6400_LOG_INFO:  return "info";
    case A6400_LOG_DEBUG: return "debug";
    default:              return "info";
    }
}

static uint64_t monotonic_ms(void)
{
    struct timespec ts;

    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0)
        return 0;
    return (uint64_t)ts.tv_sec * 1000u + (uint64_t)(ts.tv_nsec / 1000000);
}

/* Closes the SD fd and marks the sink dropped. RAM logging is untouched. */
static void sd_drop(struct a6400_log *l)
{
    if (l->sd_fd >= 0)
        (void)close(l->sd_fd);
    l->sd_fd = -1;
    l->sd_dropped = 1;
}

/* Rotates A6400LD.LOG -> A6400LD.1 (one generation, bounded). Returns 0 on
 * success; on failure the caller drops the SD sink and counts the error. */
static int sd_rotate(struct a6400_log *l)
{
    char rotated[A6400_LOG_SD_DIR_MAX + 24u];
    int fd;

    if (l->sd_fd >= 0) {
        (void)close(l->sd_fd);
        l->sd_fd = -1;
    }
    if (snprintf(rotated, sizeof rotated, "%s/%s", l->sd_dir,
                 A6400_SD_LOG_ROTATED) <= 0)
        return -ENAMETOOLONG;
    (void)unlink(rotated); /* bounded: at most one generation is retained */
    if (rename(l->sd_path, rotated) != 0)
        return -errno;
    fd = open(l->sd_path, A6400_LOG_SD_OPEN_FLAGS, 0600);
    if (fd < 0)
        return -errno;
    l->sd_fd = fd;
    l->sd_written = 0;
    l->sd_rotations++;
    return 0;
}

/* Mirrors one completed line. Bounded by A6400_LOG_LINE_MAX*2+64 bytes, so an
 * O_SYNC write cannot become an unbounded stall. */
static void sd_mirror(struct a6400_log *l, const char *buf, uint32_t len)
{
    uint32_t done = 0;

    if (!l || !buf || !len)
        return;
    if (l->sd_fd < 0 || l->sd_dropped)
        return;
    if (a6400_sd_should_rotate(l->sd_written, len, A6400_SD_LOG_ROTATE_BYTES)) {
        if (sd_rotate(l) != 0) {
            l->sd_errors++;
            sd_drop(l);
            return;
        }
    }
    while (done < len) {
        ssize_t n = write(l->sd_fd, buf + done, (size_t)(len - done));

        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            break;
        done += (uint32_t)n;
    }
    if (done != len) {
        l->sd_errors++;
        sd_drop(l);
        return;
    }
    if (!l->sd_sync && fsync(l->sd_fd) != 0) {
        l->sd_errors++;
        sd_drop(l);
        return;
    }
    l->sd_written += done;
    l->sd_lines++;
}

static void write_all(struct a6400_log *l, const char *buf, uint32_t len)
{
    uint32_t done = 0;

    if (!l || !buf || !len)
        return;
    if (l->to_stderr) {
        uint32_t off = 0;

        while (off < len) {
            ssize_t n = write(STDERR_FILENO, buf + off, (size_t)(len - off));

            if (n <= 0)
                break;
            off += (uint32_t)n;
        }
    }
    if (l->fd >= 0) {
        if (l->truncated)
            return;
        if (l->written > A6400_LOG_MAX_BYTES ||
            len > A6400_LOG_MAX_BYTES - l->written) {
            /* Never write a partial line: the file must stay valid JSONL. */
            l->truncated = 1;
            return;
        }
        while (done < len) {
            ssize_t n = write(l->fd, buf + done, (size_t)(len - done));

            if (n < 0 && errno == EINTR)
                continue;
            if (n <= 0)
                break; /* dropped: never spin on a full/failed sink */
            done += (uint32_t)n;
        }
        l->written += done;
    }
    /* The SD copy is independent of the RAM cap: the whole point is surviving a
     * battery pull that erases the RAM file. It is still bounded by its own
     * 128 KiB rotation. */
    sd_mirror(l, buf, len);
}

int a6400_log_open(struct a6400_log *l, const char *path, int level)
{
    if (!l)
        return -EINVAL;
    l->fd = -1;
    l->level = level;
    l->to_stderr = 1; /* stderr mirror stays on: on-camera it is /dev/console */
    l->written = 0;
    l->truncated = 0;
    /* The SD sink is opt-in via a6400_log_sd_open(), which must run after the
     * mount has been verified. Reset it so a reused struct cannot inherit fds. */
    l->sd_fd = -1;
    l->sd_sync = -1;
    l->sd_written = 0;
    l->sd_lines = 0;
    l->sd_errors = 0;
    l->sd_rotations = 0;
    l->sd_dropped = 0;
    l->sd_dir[0] = '\0';
    l->sd_path[0] = '\0';

    if (!path || !path[0])
        return -EINVAL;
    /* The project is confined to /tmp_bt. A log path anywhere else is refused
     * rather than silently written outside the allowed namespace. */
    if (strncmp(path, A6400_LOG_PATH_PREFIX,
                sizeof A6400_LOG_PATH_PREFIX - 1u) != 0)
        return -EPERM;

    l->fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_NONBLOCK | O_CLOEXEC, 0600);
    if (l->fd < 0) {
        int e = -errno;

        l->fd = -1;
        return e;
    }
    return 0;
}

void a6400_log_close(struct a6400_log *l)
{
    if (!l)
        return;
    a6400_log_sd_close(l);
    if (l->fd >= 0)
        (void)close(l->fd);
    l->fd = -1;
}

int a6400_log_sd_open(struct a6400_log *l, const char *dir)
{
    int fd;

    if (!l || !dir || !dir[0])
        return -EINVAL;
    if (strlen(dir) + 1u > sizeof l->sd_dir)
        return -ENAMETOOLONG;
    if (snprintf(l->sd_dir, sizeof l->sd_dir, "%s", dir) <= 0)
        return -EINVAL;
    if (snprintf(l->sd_path, sizeof l->sd_path, "%s/%s", dir,
                 A6400_SD_LOG_NAME) <= 0)
        return -ENAMETOOLONG;
    fd = open(l->sd_path, A6400_LOG_SD_OPEN_FLAGS, 0600);
    if (fd < 0) {
        l->sd_errors++;
        return -errno;
    }
    l->sd_fd = fd;
    l->sd_sync = A6400_LOG_SD_SYNC_MODE;
    l->sd_written = 0;
    l->sd_lines = 0;
    l->sd_rotations = 0;
    l->sd_dropped = 0;
    return 0;
}

void a6400_log_sd_close(struct a6400_log *l)
{
    if (!l)
        return;
    if (l->sd_fd >= 0)
        (void)close(l->sd_fd);
    l->sd_fd = -1;
}

void a6400_log_sd_get(const struct a6400_log *l, struct a6400_log_sd_stats *out)
{
    if (!out)
        return;
    memset(out, 0, sizeof *out);
    out->sync_mode = -1;
    if (!l)
        return;
    out->open = l->sd_fd >= 0 ? 1 : 0;
    out->sync_mode = l->sd_sync;
    out->lines = l->sd_lines;
    out->errors = l->sd_errors;
    out->rotations = l->sd_rotations;
    out->dropped = l->sd_dropped;
    out->bytes = l->sd_written;
}

uint32_t a6400_log_json_escape(char *out, uint32_t cap, const char *in)
{
    uint32_t o = 0;
    const unsigned char *p;

    if (!out || !cap || !in)
        return 0;
    p = (const unsigned char *)in;
    while (*p) {
        unsigned char c = *p++;
        const char *esc = NULL;
        char ubuf[7];
        uint32_t need;
        int i;

        switch (c) {
        case '"':  esc = "\\\""; break;
        case '\\': esc = "\\\\"; break;
        case '\b': esc = "\\b";  break;
        case '\f': esc = "\\f";  break;
        case '\n': esc = "\\n";  break;
        case '\r': esc = "\\r";  break;
        case '\t': esc = "\\t";  break;
        default:
            if (c < 0x20u) {
                static const char hex[] = "0123456789abcdef";

                ubuf[0] = '\\';
                ubuf[1] = 'u';
                ubuf[2] = '0';
                ubuf[3] = '0';
                ubuf[4] = hex[(c >> 4) & 0x0fu];
                ubuf[5] = hex[c & 0x0fu];
                ubuf[6] = '\0';
                esc = ubuf;
            }
            break;
        }
        if (esc) {
            need = (uint32_t)strlen(esc);
            if (o + need + 1u > cap)
                return 0;
            for (i = 0; i < (int)need; i++)
                out[o++] = esc[i];
        } else {
            if (o + 2u > cap)
                return 0;
            out[o++] = (char)c;
        }
    }
    out[o] = '\0';
    return o;
}

void a6400_log_json(struct a6400_log *l, const char *json)
{
    char line[A6400_LOG_LINE_MAX + 2u];
    size_t n;

    if (!l || !json)
        return;
    n = strlen(json);
    if (n > A6400_LOG_LINE_MAX)
        return; /* refuse to emit a torn object */
    memcpy(line, json, n);
    line[n++] = '\n';
    write_all(l, line, (uint32_t)n);
}

void a6400_logf(struct a6400_log *l, enum a6400_log_level level,
                const char *fmt, ...)
{
    char msg[A6400_LOG_LINE_MAX];
    char esc[A6400_LOG_LINE_MAX];
    char line[A6400_LOG_LINE_MAX * 2u + 64u];
    char head[96];
    uint64_t ts;
    va_list ap;
    int n, h;
    uint32_t elen, total;

    if (!l || !fmt)
        return;
    if ((int)level > l->level)
        return;

    va_start(ap, fmt);
    n = vsnprintf(msg, sizeof msg, fmt, ap);
    va_end(ap);
    if (n < 0)
        return;

    elen = a6400_log_json_escape(esc, (uint32_t)sizeof esc, msg);
    if (!elen && msg[0]) {
        /* The escaped body does not fit. Emit an explicit marker rather than a
         * silently empty message: a log line that lies about its content is
         * worse than one that admits it lost the payload. */
        static const char omitted[] = "(message omitted: escape buffer full)";

        memcpy(esc, omitted, sizeof omitted - 1u);
        elen = (uint32_t)(sizeof omitted - 1u);
    }

    ts = monotonic_ms();
    h = snprintf(head, sizeof head, "{\"t\":%llu,\"lvl\":\"%s\",\"msg\":\"",
                 (unsigned long long)ts, level_name((int)level));
    if (h < 0 || (size_t)h >= sizeof head)
        return;

    total = (uint32_t)h + elen + 2u; /* closing quote + newline */
    if (total >= sizeof line)
        return;
    memcpy(line, head, (uint32_t)h);
    if (elen)
        memcpy(line + h, esc, elen);
    line[(uint32_t)h + elen] = '"';
    line[(uint32_t)h + elen + 1u] = '\n';
    write_all(l, line, total);
}
