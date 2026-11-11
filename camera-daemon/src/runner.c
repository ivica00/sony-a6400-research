/* ptrace freeze / entry-hook lifecycle for the composite UVC session.
 *
 * Transcribed from:
 *   - tools/native_camera/native_freeze.h (bounded 512-TID capture barrier,
 *     PTRACE_ATTACH + waitpid(__WALL|WNOHANG) with a 2000 ms bound, task-set
 *     re-validation, independent owned/stopped bookkeeping so a partial resume
 *     can never detach twice).
 *   - tools/native_camera/uvc_ptp_feed_runner.c:160-297 (phase A publish,
 *     phase E retire; attest v2 fields; resume after the ioctl even when the
 *     ioctl failed, so the process is never left frozen by us).
 *   - tools/native_camera/uvc_ptp_runner_stop.h:7-19 (permission to retire
 *     requires both a successful STOP and an all-zero state receipt).
 *
 * This file never retries a failed cleanup and never invents a "clean" state:
 * every failure is returned to the daemon core, which owns the receipt and the
 * park decision.
 */
#define _GNU_SOURCE

#include "a6400_internal.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/ptrace.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "a6400_uvc.h"

#define A6400_FREEZE_BOUND_MS 2000u

void a6400_runner_init(struct a6400_runner *r, int uvc_fd, int target_pid)
{
    if (!r)
        return;
    memset(r, 0, sizeof *r);
    r->uvc_fd = uvc_fd;
    r->target_pid = target_pid;
}

static uint64_t mono_ms(void)
{
    struct timespec ts;

    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0)
        return 0;
    return (uint64_t)ts.tv_sec * 1000u + (uint64_t)(ts.tv_nsec / 1000000);
}

static void sleep_1ms(void)
{
    struct timespec ts;

    ts.tv_sec = 0;
    ts.tv_nsec = 1000000L;
    (void)nanosleep(&ts, NULL);
}

/* Bounded TID enumeration. A process with more than 512 threads is refused
 * instead of being partially frozen. */
static int enumerate_tids(int pid, uint32_t *out, uint32_t cap, uint32_t *count)
{
    char path[64];
    DIR *dir;
    struct dirent *entry;
    uint32_t n = 0;

    if (!out || !count || !cap)
        return -EINVAL;
    *count = 0;
    if (snprintf(path, sizeof path, "/proc/%d/task", pid) >= (int)sizeof path)
        return -EINVAL;

    dir = opendir(path);
    if (!dir)
        return -errno;

    while ((entry = readdir(dir)) != NULL) {
        char *end = NULL;
        long id;

        if (!entry->d_name[0] || entry->d_name[0] == '.')
            continue;
        errno = 0;
        id = strtol(entry->d_name, &end, 10);
        if (errno || !end || *end || id <= 0)
            continue;
        if (n >= cap) {
            (void)closedir(dir);
            return -ENOSPC;
        }
        out[n++] = (uint32_t)id;
    }
    (void)closedir(dir);
    if (!n)
        return -ESRCH;
    *count = n;
    return 0;
}

int a6400_runner_freeze(struct a6400_runner *r)
{
    uint32_t i, check_count = 0;
    uint32_t *check = NULL;
    uint64_t start, deadline;
    int rc;

    if (!r || r->uvc_fd < 0 || r->target_pid <= 0)
        return -EINVAL;
    if (r->frozen)
        return -EBUSY;

    /* A fresh barrier: any stale ownership from an earlier attempt is a bug,
     * so refuse rather than overwrite it. */
    for (i = 0; i < A6400_DAEMON_MAX_TIDS; i++) {
        if (r->owned[i] || r->stopped[i])
            return -EBUSY;
    }
    r->tid_count = 0;

    start = mono_ms();
    if (!start)
        return -EIO;
    deadline = start + A6400_FREEZE_BOUND_MS;

    rc = enumerate_tids(r->target_pid, r->tids, A6400_DAEMON_MAX_TIDS,
                        &r->tid_count);
    if (rc != 0) {
        r->tid_count = 0;
        return rc;
    }

    for (i = 0; i < r->tid_count; i++) {
        if (ptrace(PTRACE_ATTACH, (pid_t)r->tids[i], NULL, NULL) != 0) {
            rc = -errno;
            goto fail;
        }
        r->owned[i] = 1;
        for (;;) {
            int status = 0;
            pid_t got = waitpid((pid_t)r->tids[i], &status, __WALL | WNOHANG);

            if (got == (pid_t)r->tids[i]) {
                if (WIFSTOPPED(status)) {
                    r->stopped[i] = 1;
                    break;
                }
                if (WIFEXITED(status) || WIFSIGNALED(status)) {
                    /* The thread left on its own; it needs no detach. */
                    r->owned[i] = 0;
                    break;
                }
            } else if (got < 0 && errno != EINTR) {
                rc = -errno;
                goto fail;
            }
            if (mono_ms() > deadline) {
                rc = -ETIMEDOUT;
                goto fail;
            }
            sleep_1ms();
        }
    }

    /* The task set must be identical before and after the attach walk; a
     * thread created or destroyed mid-barrier would make the attestation
     * incomplete, so treat that as a failure instead of proceeding. */
    check = (uint32_t *)calloc(A6400_DAEMON_MAX_TIDS, sizeof *check);
    if (!check) {
        rc = -ENOMEM;
        goto fail;
    }
    rc = enumerate_tids(r->target_pid, check, A6400_DAEMON_MAX_TIDS, &check_count);
    if (rc != 0)
        goto fail;
    if (check_count != r->tid_count) {
        rc = -EAGAIN;
        goto fail;
    }
    for (i = 0; i < check_count; i++) {
        uint32_t j;

        for (j = 0; j < r->tid_count; j++)
            if (check[i] == r->tids[j])
                break;
        if (j == r->tid_count) {
            rc = -EAGAIN;
            goto fail;
        }
    }

    free(check);
    r->frozen = 1;
    r->last_freeze_ms = (uint32_t)(mono_ms() - start);
    return 0;

fail:
    free(check);
    (void)a6400_runner_resume(r);
    return rc;
}

int a6400_runner_resume(struct a6400_runner *r)
{
    uint32_t i;
    int rc = 0;
    int still_owned = 0;

    if (!r)
        return -EINVAL;

    for (i = r->tid_count; i > 0; i--) {
        uint32_t n = i - 1;

        if (!r->owned[n])
            continue;
        if (!r->stopped[n]) {
            int status = 0;
            pid_t got = waitpid((pid_t)r->tids[n], &status, __WALL | WNOHANG);

            if (got == (pid_t)r->tids[n] && WIFSTOPPED(status)) {
                r->stopped[n] = 1;
            } else if (got == (pid_t)r->tids[n] &&
                       (WIFEXITED(status) || WIFSIGNALED(status))) {
                r->owned[n] = 0;
                continue;
            } else {
                rc = -ECHILD;
                still_owned = 1;
                continue;
            }
        }
        if (ptrace(PTRACE_DETACH, (pid_t)r->tids[n], NULL, NULL) != 0) {
            rc = -errno;
            still_owned = 1;
        } else {
            r->owned[n] = 0;
            r->stopped[n] = 0;
        }
    }
    r->frozen = still_owned ? 1 : 0;
    return rc;
}

/* Version-2 attestation request: {version==2, owner==target pid, count<=512,
 * tids[]}. registers/siginfo stay 0 because native snapshots never leave kernel
 * memory (uvc_ptp_stop_attest.h:10-14). */
static int hook_ioctl(struct a6400_runner *r, unsigned long command)
{
    struct a6400_uvc_stop_request att;
    int rc;

    if (!r || r->uvc_fd < 0)
        return -EINVAL;
    if (!r->frozen || !r->tid_count)
        return -EPERM; /* publication requires a verified stop scope */
    if (r->tid_count > A6400_DAEMON_MAX_TIDS)
        return -E2BIG;

    memset(&att, 0, sizeof att);
    att.version = 2;
    att.owner = (uint32_t)r->target_pid;
    att.count = r->tid_count;
    att.tids = (uint32_t)(uintptr_t)r->tids;
    att.registers = 0;
    att.siginfo = 0;
    att.completed = 0;
    att.error = 0;

    rc = ioctl(r->uvc_fd, command, &att);
    r->attest_completed = (uint32_t)att.completed;
    r->attest_error = att.error;
    if (rc != 0)
        return rc < 0 ? -errno : -EIO;
    if (att.error != 0)
        return -(int)att.error;
    if (att.completed != r->tid_count)
        return -EAGAIN;
    return 0;
}

int a6400_runner_publish_hook(struct a6400_runner *r)
{
    int rc;

    if (!r)
        return -EINVAL;
    rc = hook_ioctl(r, A6400_UVC_IOCTL_HOOK_PUBLISH);
    if (rc == 0)
        r->published = 1;
    return rc;
}

int a6400_runner_retire_hook(struct a6400_runner *r)
{
    int rc;

    if (!r)
        return -EINVAL;
    if (!r->published)
        return -EPERM;
    rc = hook_ioctl(r, A6400_UVC_IOCTL_HOOK_RETIRE);
    if (rc == 0)
        r->published = 0;
    return rc;
}

int a6400_runner_stop_verified(int uvc_fd, int32_t state[4])
{
    int i;

    if (!state)
        return 0;
    for (i = 0; i < 4; i++)
        state[i] = -1;
    if (uvc_fd < 0)
        return 0;
    if (ioctl(uvc_fd, A6400_UVC_IOCTL_STOP, NULL) != 0)
        return 0;
    if (ioctl(uvc_fd, A6400_UVC_IOCTL_QUERY_SESSION_STATE, state) != 0)
        return 0;
    /* phase IDLE, pin absent, descriptor hooks absent, no retained error. */
    for (i = 0; i < 4; i++)
        if (state[i])
            return 0;
    return 1;
}

int a6400_runner_park(volatile sig_atomic_t *stop_flag)
{
    for (;;) {
        if (stop_flag && *stop_flag)
            return 1;
        pause();
        if (stop_flag && *stop_flag)
            return 1;
    }
}
