/* Minimal bounded logger for the a6400 daemon and probe helpers.
 *
 * Constraints that shaped it:
 *  - /tmp_bt is a 1 MiB tmpfs (reports/a6400_hw_dump.txt:234): every log file
 *    must be capped, and the writer must never block the frame loop.
 *  - On-camera stdout/stderr go to /dev/console; a file log is the only
 *    channel that survives until the host can read it back, and it does not
 *    survive a reboot (E0342:24-26). Receipts must therefore be complete before
 *    any mode change.
 *  - E0350: a battery pull wipes /tmp_bt, so an optional SECOND sink on the SD
 *    card (`--sd-log`) mirrors every completed line with O_SYNC. It is bounded
 *    (128 KiB + one rotated 128 KiB file, 8.3 names per E0236) and a failed SD
 *    write drops the sink, counts the error and never stops RAM logging.
 *  - No libc printf dependency is assumed: this file uses vsnprintf only when
 *    available and always formats through a fixed stack buffer.
 */
#ifndef A6400_LOG_H
#define A6400_LOG_H

#include <stdint.h>
#include <stdarg.h>

enum a6400_log_level {
    A6400_LOG_ERROR = 0,
    A6400_LOG_WARN  = 1,
    A6400_LOG_INFO  = 2,
    A6400_LOG_DEBUG = 3,
};

#define A6400_LOG_MAX_BYTES (256u * 1024u)   /* cap of one log file */
#define A6400_LOG_LINE_MAX  512u
#define A6400_LOG_SD_DIR_MAX 128u

struct a6400_log {
    int      fd;          /* -1 when file logging is disabled             */
    int      level;       /* threshold                                     */
    int      to_stderr;   /* 1 = mirror to stderr                         */
    uint32_t written;     /* bytes written to the file                    */
    uint32_t truncated;   /* 1 once the cap was reached                   */

    /* Optional second sink: a vfat SD file opened O_SYNC. Only valid after
     * a6400_log_sd_open(); sd_fd is -1 otherwise. */
    int      sd_fd;
    int      sd_sync;     /* 1 = O_SYNC, 0 = fsync after every line        */
    uint32_t sd_written;  /* bytes in the current SD file                 */
    uint32_t sd_lines;    /* completed lines mirrored                     */
    uint32_t sd_errors;   /* failed SD opens/writes/rotations             */
    uint32_t sd_rotations;
    uint32_t sd_dropped;  /* 1 once the SD sink was dropped after a fail  */
    char     sd_dir[A6400_LOG_SD_DIR_MAX];
    char     sd_path[A6400_LOG_SD_DIR_MAX + 24u];
};

struct a6400_log_sd_stats {
    int      open;        /* 1 when the SD fd is live                     */
    int      sync_mode;   /* 1 = O_SYNC, 0 = fsync per line, -1 unknown    */
    uint32_t lines;
    uint32_t errors;
    uint32_t rotations;
    uint32_t dropped;
    uint32_t bytes;       /* bytes in the current SD file                 */
};

/* Opens/creates the log file (append, mode 0600, /tmp_bt only by policy).
 * Returns 0 on success; a failure leaves logging on stderr only. */
int  a6400_log_open(struct a6400_log *l, const char *path, int level);
void a6400_log_close(struct a6400_log *l);

/* Opens the SD sink under `dir` (the verified mount point) as A6400LD.LOG,
 * O_WRONLY|O_CREAT|O_APPEND|O_SYNC (fsync per line when O_SYNC is unavailable).
 * The caller must have mounted and verified the filesystem first. Returns 0 on
 * success; a failure counts an error and leaves RAM logging untouched. */
int  a6400_log_sd_open(struct a6400_log *l, const char *dir);

/* Closes the SD sink. Safe when it was never opened. */
void a6400_log_sd_close(struct a6400_log *l);

/* Fills the SD sink counters used by the receipt. `sync_mode` is -1 when no SD
 * sink was ever opened. */
void a6400_log_sd_get(const struct a6400_log *l, struct a6400_log_sd_stats *out);

/* Plain formatted line. Never allocates, never blocks on a full pipe: if the
 * write would exceed the cap the line is dropped and `truncated` is set. */
void a6400_logf(struct a6400_log *l, enum a6400_log_level level,
                const char *fmt, ...) __attribute__((format(printf, 3, 4)));

/* Emits a complete JSON object (the caller owns formatting). Used for the
 * machine-readable event stream that survives a session. */
void a6400_log_json(struct a6400_log *l, const char *json);

/* Escapes `in` into `out` as a JSON string body (no quotes added); returns the
 * number of bytes written (0 when the buffer is too small). */
uint32_t a6400_log_json_escape(char *out, uint32_t cap, const char *in);

#endif /* A6400_LOG_H */
