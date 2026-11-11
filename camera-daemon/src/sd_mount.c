/* Syscall side of the optional SD log sink: gate -> mount -> verify -> sentinel.
 *
 * Every step is fail-closed. A mount is reported as successful only when
 *   1. the window gate allows it (--sd-log + --sd-mount, PC Remote confirmed,
 *      not Mass Storage, not a dry run, INIT not started),
 *   2. the device string is exactly /dev/mmca1 and stat() proves block 250:11,
 *   3. /proc/mounts does not already contain the device or the mount point,
 *   4. /proc/mounts contains exactly /dev/mmca1 at the requested mount point
 *      after mount(), and
 *   5. a sentinel file under the mount point can be written with O_SYNC and read
 *      back byte-for-byte.
 * Anything else unmounts whatever this call mounted and records the exact
 * failure code. A sentinel short read is a failure, never a pass (no fabricated
 * mount success).
 *
 * E0222 is the reason for the double identity check: /proc/mounts is a name
 * table, and this camera's internal flashes are all `nflasha*` vfat mounts. The
 * stat() block-node check (250:11) is independent of the text table.
 */
#include "a6400_sdlog.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#ifndef O_SYNC
#define O_SYNC 0
#endif
#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif

#define A6400_SD_MOUNTS_MAX 8192u
#define A6400_SD_SENTINEL_BODY "A6400SD\n"

static void set_reason(struct a6400_sd_status *st, const char *reason)
{
    if (!st || !reason)
        return;
    snprintf(st->reason, sizeof st->reason, "%s", reason);
}

static void set_reason_rc(struct a6400_sd_status *st, const char *reason, int rc)
{
    if (!st || !reason)
        return;
    snprintf(st->reason, sizeof st->reason, "%s rc=%d", reason, rc);
}

static int read_mounts(char *buf, uint32_t cap, uint32_t *out_len)
{
    uint32_t done = 0;
    int fd;

    if (!buf || cap < 2u || !out_len)
        return A6400_SD_ERR_ARG;
    fd = open("/proc/mounts", O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return -errno;
    while (done + 1u < cap) {
        ssize_t n = read(fd, buf + done, (size_t)(cap - 1u - done));

        if (n < 0 && errno == EINTR)
            continue;
        if (n < 0) {
            int rc = -errno;

            (void)close(fd);
            return rc;
        }
        if (n == 0)
            break;
        done += (uint32_t)n;
    }
    (void)close(fd);
    if (done + 1u >= cap)
        return A6400_SD_ERR_IO; /* truncated table: fail closed, never parse half */
    buf[done] = '\0';
    *out_len = done;
    return 0;
}

static int write_all_fd(int fd, const char *buf, uint32_t len)
{
    uint32_t done = 0;

    while (done < len) {
        ssize_t n = write(fd, buf + done, (size_t)(len - done));

        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            return -EIO;
        done += (uint32_t)n;
    }
    return 0;
}

static int sentinel_roundtrip(struct a6400_sd_status *st)
{
    static const char body[] = A6400_SD_SENTINEL_BODY;
    char path[A6400_SD_PATH_MAX + 32u];
    char back[32];
    uint32_t want = (uint32_t)(sizeof body - 1u);
    ssize_t got;
    int fd, rc = 0;

    if (snprintf(path, sizeof path, "%s/%s", st->mountpoint,
                 A6400_SD_SENTINEL_NAME) <= 0)
        return A6400_SD_ERR_IO;
    fd = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_SYNC | O_CLOEXEC, 0600);
    if (fd < 0)
        return -errno;
    rc = write_all_fd(fd, body, want);
    if (rc == 0 && fsync(fd) != 0)
        rc = -errno;
    if (close(fd) != 0 && rc == 0)
        rc = -errno;
    if (rc != 0) {
        (void)unlink(path);
        return rc;
    }

    fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        (void)unlink(path);
        return -errno;
    }
    memset(back, 0, sizeof back);
    got = read(fd, back, sizeof back);
    if (got < 0)
        rc = -errno;
    else if (!a6400_sd_sentinel_matches(back, (uint32_t)got, body, want))
        rc = A6400_SD_ERR_SENTINEL;
    (void)close(fd);
    (void)unlink(path);
    return rc;
}

int a6400_sd_mount(struct a6400_sd_status *st, const struct a6400_sd_window *w)
{
    char mounts[A6400_SD_MOUNTS_MAX];
    char sentinel_path[A6400_SD_PATH_MAX + 32u];
    struct stat sb;
    uint32_t mounts_len = 0;
    int rc, urc;

    if (!st)
        return A6400_SD_ERR_ARG;
    st->attempted = 1;
    st->mount_rc = A6400_SD_ERR_ARG;
    if (!w) {
        set_reason(st, "no_window_state");
        return A6400_SD_ERR_ARG;
    }

    rc = a6400_sd_mount_window(w);
    if (rc != A6400_SD_OK) {
        st->mount_rc = rc;
        set_reason_rc(st, "window_refused", rc);
        return rc;
    }

    rc = a6400_sd_device_policy(st->device);
    if (rc != A6400_SD_OK) {
        st->mount_rc = rc;
        set_reason_rc(st, "device_policy_refused", rc);
        return rc;
    }
    rc = a6400_sd_mountpoint_policy(st->mountpoint);
    if (rc != A6400_SD_OK) {
        st->mount_rc = rc;
        set_reason_rc(st, "mountpoint_policy_refused", rc);
        return rc;
    }

    memset(&sb, 0, sizeof sb);
    if (stat(st->device, &sb) != 0) {
        rc = -errno;
        st->mount_rc = rc;
        set_reason_rc(st, "device_stat_failed", rc);
        return rc;
    }
    if (!S_ISBLK(sb.st_mode)) {
        st->mount_rc = A6400_SD_ERR_NOT_BLOCK;
        set_reason(st, "device_not_block");
        return A6400_SD_ERR_NOT_BLOCK;
    }
    if ((unsigned)major(sb.st_rdev) != A6400_SD_BLK_MAJOR ||
        (unsigned)minor(sb.st_rdev) != A6400_SD_BLK_MINOR) {
        st->mount_rc = A6400_SD_ERR_DEVICE_IDENTITY;
        set_reason(st, "device_identity_mismatch");
        return A6400_SD_ERR_DEVICE_IDENTITY;
    }
    st->device_ok = 1;

    rc = read_mounts(mounts, sizeof mounts, &mounts_len);
    if (rc != A6400_SD_OK) {
        st->mount_rc = rc;
        set_reason_rc(st, "proc_mounts_unreadable", rc);
        return rc;
    }
    (void)mounts_len;
    rc = a6400_sd_mounts_contains(mounts, st->device, st->mountpoint);
    if (rc < 0) {
        st->mount_rc = rc;
        set_reason_rc(st, "proc_mounts_parse_failed", rc);
        return rc;
    }
    if (rc == 1) {
        st->mount_rc = A6400_SD_ERR_ALREADY_MOUNTED;
        set_reason(st, "already_mounted_exact");
        return A6400_SD_ERR_ALREADY_MOUNTED;
    }
    rc = a6400_sd_mounts_conflict(mounts, st->device, st->mountpoint);
    if (rc < 0) {
        st->mount_rc = rc;
        set_reason_rc(st, "proc_mounts_parse_failed", rc);
        return rc;
    }
    if (rc != 0) {
        st->mount_rc = A6400_SD_ERR_ALREADY_MOUNTED;
        set_reason(st, (rc & 1) ? "device_already_mounted"
                                : "mountpoint_already_used");
        return A6400_SD_ERR_ALREADY_MOUNTED;
    }

    if (mkdir(st->mountpoint, 0777) != 0 && errno != EEXIST) {
        rc = -errno;
        st->mount_rc = rc;
        set_reason_rc(st, "mkdir_failed", rc);
        return rc;
    }
    memset(&sb, 0, sizeof sb);
    if (stat(st->mountpoint, &sb) != 0 || !S_ISDIR(sb.st_mode)) {
        st->mount_rc = A6400_SD_ERR_VERIFY;
        set_reason(st, "mountpoint_not_directory");
        return A6400_SD_ERR_VERIFY;
    }

    if (mount(st->device, st->mountpoint, "vfat", 0, NULL) != 0) {
        rc = -errno;
        st->mount_rc = rc;
        set_reason_rc(st, "mount_failed", rc);
        return rc;
    }
    st->mount_rc = 0;

    rc = read_mounts(mounts, sizeof mounts, &mounts_len);
    if (rc != A6400_SD_OK) {
        set_reason_rc(st, "verify_mounts_unreadable", rc);
        goto fail_verify;
    }
    rc = a6400_sd_mounts_contains(mounts, st->device, st->mountpoint);
    if (rc != 1) {
        if (rc == 0) {
            rc = A6400_SD_ERR_VERIFY;
            set_reason(st, "device_not_in_proc_mounts");
        } else {
            set_reason_rc(st, "verify_mounts_parse_failed", rc);
        }
        goto fail_verify;
    }
    st->verified = 1;

    if (snprintf(sentinel_path, sizeof sentinel_path, "%s/%s", st->mountpoint,
                 A6400_SD_SENTINEL_NAME) <= 0) {
        rc = A6400_SD_ERR_IO;
        set_reason(st, "sentinel_path_overflow");
        goto fail_verify;
    }
    rc = sentinel_roundtrip(st);
    if (rc != A6400_SD_OK) {
        set_reason_rc(st, "sentinel_failed", rc);
        goto fail_verify;
    }
    st->sentinel_ok = 1;

    st->mounted = 1;
    st->reason[0] = '\0';
    return A6400_SD_OK;

fail_verify:
    st->errors++;
    /* Tear down the mount this call created: leaving an unverified mount is how
     * a later teardown finds a filesystem it does not own. */
    urc = umount2(st->mountpoint, 0);
    st->unmount_attempted = 1;
    st->unmount_rc = urc == 0 ? 0 : -errno;    st->mounted = 0;
    st->verified = 0;
    st->sentinel_ok = 0;
    st->mount_rc = rc;
    return rc;
}

int a6400_sd_unmount(struct a6400_sd_status *st)
{
    if (!st)
        return A6400_SD_ERR_ARG;
    st->unmount_attempted = 1;
    if (!st->mounted) {
        if (st->unmount_rc == 0)
            st->unmount_rc = 1; /* nothing mounted: not attempted */
        return 1;
    }
    if (umount2(st->mountpoint, 0) != 0) {
        int rc = -errno;

        st->unmount_rc = rc;
        st->errors++;
        set_reason_rc(st, "umount_failed", rc);
        /* mounted stays 1: the kernel still has it, and the receipt must say
         * so. A failed unmount is never reported as clean. */
        return rc;
    }
    st->mounted = 0;
    st->unmount_rc = 0;
    st->reason[0] = '\0';
    return 0;
}

int a6400_sd_write_receipt(struct a6400_sd_status *st, const char *json,
                           uint32_t len)
{
    char path[A6400_SD_PATH_MAX + 32u];
    int fd, rc = 0;

    if (!st || !json || len == 0u)
        return A6400_SD_ERR_ARG;
    if (!st->mounted) {
        set_reason(st, "receipt_skipped_not_mounted");
        return A6400_SD_ERR_IO;
    }
    if (snprintf(path, sizeof path, "%s/%s", st->mountpoint,
                 A6400_SD_RECEIPT_NAME) <= 0)
        return A6400_SD_ERR_IO;
    fd = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_SYNC | O_CLOEXEC, 0600);
    if (fd < 0) {
        rc = -errno;
        st->errors++;
        set_reason_rc(st, "receipt_open_failed", rc);
        return rc;
    }
    rc = write_all_fd(fd, json, len);
    if (rc == 0 && fsync(fd) != 0)
        rc = -errno;
    if (close(fd) != 0 && rc == 0)
        rc = -errno;
    if (rc != 0) {
        st->errors++;
        set_reason_rc(st, "receipt_write_failed", rc);
        return rc;
    }
    st->receipt_written = 1;
    return 0;
}
