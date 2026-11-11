/* Pure policy for the optional SD log sink.
 *
 * This translation unit is linked into the host test binary, so it must not use
 * a file descriptor, a clock, mount(2) or any other syscall. Everything here is
 * a decision about strings and counters. The syscall side lives in
 * src/sd_mount.c; the second log sink lives in src/log.c.
 *
 * The gates exist because the wrong answer is destructive:
 *   - internal flash (/dev/nflasha*, /setting, /etc, /system, /log) must be
 *     unreachable even with a typo or a hostile argument (fail closed);
 *   - the SD must never be mounted while the camera app owns it in Mass
 *     Storage, so the only window is "PC Remote confirmed, INIT not started";
 *   - mount verification uses the exact `/dev/mmca1` string plus a block-node
 *     identity check (E0222), never a substring or a drive letter.
 */
#include "a6400_sdlog.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define A6400_SD_FORBIDDEN_COUNT 8u

static const char *const forbidden_mounts[A6400_SD_FORBIDDEN_COUNT] = {
    "/setting",
    "/etc",
    "/system",
    "/log",
    "/tmp",
    "/lens",
    "/cert",
    "/",
};

static int is_83_char(unsigned char c)
{
    if (c >= 'A' && c <= 'Z')
        return 1;
    if (c >= 'a' && c <= 'z')
        return 1;
    if (c >= '0' && c <= '9')
        return 1;
    return c == '_' || c == '-';
}

int a6400_sd_name_is_83(const char *name)
{
    const char *dot;
    size_t n, base, ext, i;

    if (!name || !name[0])
        return 0;
    n = strlen(name);
    if (n > 12u) /* 8 + '.' + 3 */
        return 0;
    dot = strchr(name, '.');
    if (dot && strchr(dot + 1, '.'))
        return 0; /* one extension only */
    base = dot ? (size_t)(dot - name) : n;
    ext = dot ? n - base - 1u : 0u;
    if (base < 1u || base > 8u)
        return 0;
    if (dot && (ext < 1u || ext > 3u))
        return 0;
    for (i = 0; i < base; i++) {
        if (!is_83_char((unsigned char)name[i]))
            return 0;
    }
    for (i = 0; i < ext; i++) {
        if (!is_83_char((unsigned char)dot[1u + i]))
            return 0;
    }
    return 1;
}

int a6400_sd_device_policy(const char *dev)
{
    size_t n;

    if (!dev || !dev[0])
        return A6400_SD_ERR_ARG;
    /* Explicit internal-flash refusal before anything else, so the reason is
     * unambiguous even for a path that is also wrong in another way. */
    if (strncmp(dev, "/dev/nflasha", 12u) == 0)
        return A6400_SD_ERR_INTERNAL_FLASH;
    if (dev[0] != '/')
        return A6400_SD_ERR_NOT_ABSOLUTE;
    n = strlen(dev);
    if (n + 1u > A6400_SD_PATH_MAX)
        return A6400_SD_ERR_UNSAFE_PATH;
    if (strstr(dev, "..") || strstr(dev, "//") || dev[n - 1u] == '/')
        return A6400_SD_ERR_UNSAFE_PATH;
    /* Only the SD data partition is mountable. /dev/mmca is the whole card and
     * is not a vfat filesystem; every other node is unknown and refused. */
    if (strcmp(dev, A6400_SD_DEV_DEFAULT) == 0)
        return A6400_SD_OK;
    return A6400_SD_ERR_WRONG_DEVICE;
}

int a6400_sd_mountpoint_policy(const char *mountpoint)
{
    size_t n, i;

    if (!mountpoint || !mountpoint[0])
        return A6400_SD_ERR_ARG;
    for (i = 0; i < A6400_SD_FORBIDDEN_COUNT; i++) {
        if (strcmp(mountpoint, forbidden_mounts[i]) == 0)
            return A6400_SD_ERR_FORBIDDEN_MOUNT;
    }
    if (mountpoint[0] != '/')
        return A6400_SD_ERR_NOT_ABSOLUTE;
    n = strlen(mountpoint);
    if (n + 1u > A6400_SD_PATH_MAX)
        return A6400_SD_ERR_UNSAFE_PATH;
    if (strstr(mountpoint, "..") || strstr(mountpoint, "//") ||
        strstr(mountpoint, "/.") || mountpoint[n - 1u] == '/')
        return A6400_SD_ERR_UNSAFE_PATH;
    /* The rootfs is read-only ext2; only /tmp_bt is writable. Mounting over
     * /tmp_bt itself would hide the RAM log directory, so it is not a child. */
    if (strncmp(mountpoint, "/tmp_bt/", 8u) != 0)
        return A6400_SD_ERR_OUTSIDE_TMP_BT;
    if (strlen(mountpoint) <= 8u)
        return A6400_SD_ERR_UNSAFE_PATH;
    return A6400_SD_OK;
}

void a6400_sd_status_init(struct a6400_sd_status *st, int enabled,
                          int mount_requested, const char *dev,
                          const char *mountpoint)
{
    if (!st)
        return;
    memset(st, 0, sizeof *st);
    st->enabled = enabled ? 1 : 0;
    st->mount_requested = mount_requested ? 1 : 0;
    st->unmount_rc = 1;   /* not attempted yet */
    st->sync_mode = -1;
    snprintf(st->device, sizeof st->device, "%s",
             dev && dev[0] ? dev : A6400_SD_DEV_DEFAULT);
    snprintf(st->mountpoint, sizeof st->mountpoint, "%s",
             mountpoint && mountpoint[0] ? mountpoint : A6400_SD_MOUNT_DEFAULT);
}

int a6400_sd_mount_window(const struct a6400_sd_window *w)
{
    if (!w)
        return A6400_SD_ERR_ARG;
    if (!w->sd_log || !w->sd_mount)
        return A6400_SD_ERR_NO_CONSENT;
    if (w->dry_run)
        return A6400_SD_ERR_DRY_RUN;
    if (w->msc_mode)
        return A6400_SD_ERR_MSC;
    if (!w->pcremote_confirmed)
        return A6400_SD_ERR_PCREMOTE_UNCONFIRMED;
    if (w->init_started)
        return A6400_SD_ERR_AFTER_INIT;
    if (w->streaming)
        return A6400_SD_ERR_STREAMING;
    return A6400_SD_OK;
}

int a6400_sd_should_rotate(uint32_t written, uint32_t incoming, uint32_t cap)
{
    if (cap == 0u)
        return 1;
    if (incoming > cap)
        return 1;
    return written > 0u && written > cap - incoming;
}

int a6400_sd_sentinel_matches(const char *readback, uint32_t read_len,
                              const char *expect, uint32_t expect_len)
{
    if (!readback || !expect || read_len == 0u || expect_len == 0u)
        return 0;
    if (read_len != expect_len)
        return 0;
    return memcmp(readback, expect, (size_t)expect_len) == 0;
}

/* Copies one whitespace-delimited /proc/mounts field, decoding the octal
 * escapes the kernel uses for space/tab/newline/backslash (e.g. \040). */
static int decode_field(const char *src, const char *end, char *out, uint32_t cap)
{
    uint32_t o = 0;

    while (src < end) {
        unsigned char c = (unsigned char)*src++;

        if (c == '\\' && (size_t)(end - src) >= 3u &&
            src[0] >= '0' && src[0] <= '7' &&
            src[1] >= '0' && src[1] <= '7' &&
            src[2] >= '0' && src[2] <= '7') {
            c = (unsigned char)(((unsigned)(src[0] - '0') << 6) |
                                ((unsigned)(src[1] - '0') << 3) |
                                (unsigned)(src[2] - '0'));
            src += 3;
        }
        if (o + 1u >= cap)
            return -1;
        out[o++] = (char)c;
    }
    if (o >= cap)
        return -1;
    out[o] = '\0';
    return (int)o;
}

static const char *skip_spaces(const char *p, const char *end)
{
    while (p < end && (*p == ' ' || *p == '\t'))
        p++;
    return p;
}

int a6400_sd_parse_mount_line(const char *line, char *dev, uint32_t dev_cap,
                              char *mountpoint, uint32_t mountpoint_cap)
{
    const char *p, *end, *d0, *d1, *m0, *m1;

    if (!line || !dev || !mountpoint)
        return A6400_SD_ERR_ARG;
    end = line + strlen(line);
    p = skip_spaces(line, end);
    if (p >= end || *p == '\n')
        return 0; /* empty line */
    d0 = p;
    while (p < end && *p != ' ' && *p != '\t' && *p != '\n')
        p++;
    d1 = p;
    p = skip_spaces(p, end);
    if (p >= end || *p == '\n')
        return 0; /* one field only: not a mount entry */
    m0 = p;
    while (p < end && *p != ' ' && *p != '\t' && *p != '\n')
        p++;
    m1 = p;
    if (decode_field(d0, d1, dev, dev_cap) < 0)
        return A6400_SD_ERR_ARG;
    if (decode_field(m0, m1, mountpoint, mountpoint_cap) < 0)
        return A6400_SD_ERR_ARG;
    return 1;
}

int a6400_sd_mounts_contains(const char *mounts, const char *dev,
                             const char *mountpoint)
{
    const char *line;

    if (!mounts || !dev || !mountpoint)
        return A6400_SD_ERR_ARG;
    line = mounts;
    while (*line) {
        char d[A6400_SD_PATH_MAX];
        char m[A6400_SD_PATH_MAX];
        const char *next = strchr(line, '\n');
        size_t span = next ? (size_t)(next - line) : strlen(line);
        char buf[A6400_SD_PATH_MAX + 64u];
        int rc;

        if (span >= sizeof buf)
            return A6400_SD_ERR_ARG;
        memcpy(buf, line, span);
        buf[span] = '\0';
        rc = a6400_sd_parse_mount_line(buf, d, sizeof d, m, sizeof m);
        if (rc < 0)
            return rc;
        if (rc == 1 && strcmp(d, dev) == 0 && strcmp(m, mountpoint) == 0)
            return 1;
        line = next ? next + 1 : line + span;
    }
    return 0;
}

int a6400_sd_mounts_conflict(const char *mounts, const char *dev,
                             const char *mountpoint)
{
    const char *line;
    int mask = 0;

    if (!mounts || !dev || !mountpoint)
        return A6400_SD_ERR_ARG;
    line = mounts;
    while (*line) {
        char d[A6400_SD_PATH_MAX];
        char m[A6400_SD_PATH_MAX];
        const char *next = strchr(line, '\n');
        size_t span = next ? (size_t)(next - line) : strlen(line);
        char buf[A6400_SD_PATH_MAX + 64u];
        int rc;

        if (span >= sizeof buf)
            return A6400_SD_ERR_ARG;
        memcpy(buf, line, span);
        buf[span] = '\0';
        rc = a6400_sd_parse_mount_line(buf, d, sizeof d, m, sizeof m);
        if (rc < 0)
            return rc;
        if (rc == 1) {
            if (strcmp(d, dev) == 0)
                mask |= 1;
            if (strcmp(m, mountpoint) == 0)
                mask |= 2;
        }
        line = next ? next + 1 : line + span;
    }
    return mask;
}
