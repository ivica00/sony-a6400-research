/* Bounded park recovery for a failed stop attestation (E0358).
 *
 * WHY THIS EXISTS (E0357 Run B3): the module's STOP ioctl `0x0000e001` runs
 * `cleanup() -> a6400_uvc_ptp_session_end() -> a6400_uvc_soft_disconnect()` (the
 * unconfigure-first 9-phase teardown, tools/native_camera/uvc_ptp_soft_disconnect.c).
 * When a phase refuses, `session_end()` holds the session and `cleanup()` returns
 * the error, so STOP returns non-zero. `a6400_runner_stop_verified()` then returns
 * 0 *without ever issuing the status query*, leaving its `-1` sentinels in the
 * receipt: `state=-1,-1,-1,-1` means "STOP failed, no module state was read", not
 * "the module reported -1". The pre-E0358 daemon parked on that, kept 181 threads'
 * publish scope closed, held the fd and never retried, so the camera stayed as
 * `USB\VID_0000&PID_0002` until a battery pull.
 *
 * WHAT IS AND IS NOT RECOVERABLE FROM USERSPACE (source-verified)
 *   - `0x8010f022` QUERY_SESSION_STATE is a READ-ONLY status copy
 *     (`{phase, pinned, hook_mask, last_error}`). It is safe after a failed STOP
 *     and is the only module-supplied diagnostic that exists.
 *   - `0xc020f027` HOOK_RETIRE retires the ENTRY hook (the 4-byte branch at
 *     `0x602b8844`); it does NOT run the 9-phase teardown. The module refuses it
 *     while the session is held (`dryrun_retirable()` requires `!pinned`,
 *     `!backend.gc` and a releasable session), so it can only succeed AFTER a
 *     verified STOP.
 *   - The only userspace recovery primitive for a held session is therefore ONE
 *     bounded retry of STOP `0x0000e001` (which re-enters the ordered teardown),
 *     followed by the normal freeze -> HOOK_RETIRE -> resume release once the
 *     session is idle again.
 *
 * ORDER AND SAFETY RULES (the camera-facing executor in src/main.c enforces
 * them; the pure helpers here are what the host tests pin):
 *   1. durable evidence FIRST: flush the kernel `[a6400_*]` trace to
 *      A6400K.LOG and rewrite A6400RCPT.JSON with status `degraded_teardown`.
 *      This step is mandatory: a recovery outcome is never `recovered` without
 *      it, so a later wedge cannot lose the evidence (E0350/E0357).
 *   2. read-only session status (no side effect).
 *   3. at most one STOP retry.
 *   4. freeze -> HOOK_RETIRE -> resume. The attestation set is resumed on every
 *      path, including a failed retire, so the firmware is never left frozen.
 *   5. close. Success requires the module-reported state to be all zero, the
 *      entry hook retired, the resume to have succeeded and the close to have
 *      happened.
 * A failed step parks exactly as before (fail closed); the SD evidence is never
 * skipped.
 *
 * The clean path (`stop_verified == 1`) is unchanged and never touches this
 * code: `a6400_recovery_needed(1) == 0`.
 */
#ifndef A6400_RECOVERY_H
#define A6400_RECOVERY_H

#include <stdint.h>

/* New receipt status / exit code for a stop that was recovered by the bounded
 * retry. Exit codes 0 (clean), 2 (stage), 3 (refused) and 4 (fatal) keep their
 * meanings. */
#define A6400_EXIT_DEGRADED 5

/* Fixed steps, in order. `A6400_REC_NONE` is not a step. */
enum a6400_recovery_step {
    A6400_REC_NONE = 0,
    A6400_REC_EVIDENCE,      /* SD trace flush + degraded receipt          */
    A6400_REC_STATE_QUERY,   /* read-only 0x8010f022 after the failed STOP */
    A6400_REC_STOP_RETRY,    /* exactly one retry of STOP 0x0000e001       */
    A6400_REC_FREEZE,        /* ptrace stopped scope for HOOK_RETIRE       */
    A6400_REC_HOOK_RETIRE,   /* retire the entry hook (0xc020f027)         */
    A6400_REC_RESUME,        /* always resume the attestation set          */
    A6400_REC_CLOSE,         /* close ctl/uipc/mem/video descriptors       */
    A6400_REC_STEP_COUNT
};

enum a6400_recovery_status {
    A6400_RECOVERY_NOT_ATTEMPTED = 0, /* clean path or recovery disabled */
    A6400_RECOVERY_PENDING,           /* attempted, not finished          */
    A6400_RECOVERY_RECOVERED,         /* every gate passed                */
    A6400_RECOVERY_FAILED             /* a step errored -> park           */
};

/* Everything the receipt needs. Plain ints so the host tests need no clock,
 * no syscall and no camera ABI. */
struct a6400_recovery {
    int      attempted;
    int      status;              /* enum a6400_recovery_status              */
    int      evidence_written;    /* trace flush + receipt write succeeded   */
    int      state_before_valid;  /* 0x8010f022 answered after failed STOP   */
    int32_t  state_before[4];     /* {phase,pinned,hook_mask,error}          */
    int      stop_retry_rc;       /* STOP retry ioctl result (0 or -errno)   */
    int      state_after_valid;   /* status query after the retry answered   */
    int32_t  state_after[4];
    int      stop_retry_verified; /* retry returned 0 and state_after == 0   */
    int      freeze_rc;
    uint32_t frozen_tids;
    int      retire_rc;
    int      hook_retired;
    int      resume_rc;
    int      closed;
    int      failed_step;         /* enum a6400_recovery_step                */
    char     detail[64];          /* short machine-readable failure tag      */
};

/* ---- pure decision helpers (host-tested in test/host_test.c) ------------- */

/* 1 only when the stop attestation did not verify. */
int a6400_recovery_needed(int stop_verified);

/* 1 only when a valid status read is all zero (IDLE / unpinned / no descriptor
 * hooks / no retained error). An invalid read is never "verified". */
int a6400_recovery_state_verified(int valid, const int32_t state[4]);

/* 1 when the single bounded STOP retry must run. A status read that already
 * proves the session clean suppresses the extra destructive call; a failed or
 * unavailable read does not, because the retry is the only userspace recovery
 * primitive and its own status query re-verifies. */
int a6400_recovery_retry_allowed(int valid, const int32_t state[4]);

/* Classifies the recorded attempt. Returns A6400_RECOVERY_NOT_ATTEMPTED when no
 * attempt was recorded, A6400_RECOVERY_RECOVERED only when every gate passed,
 * and A6400_RECOVERY_FAILED otherwise. A success claim without the durable
 * evidence step is impossible. */
int a6400_recovery_outcome(const struct a6400_recovery *rec);

/* Fixed step order (EVIDENCE first, CLOSE last). Returns the step count and,
 * when `steps` is non-NULL, the array pointer. */
uint32_t a6400_recovery_step_order(const int **steps);

const char *a6400_recovery_step_name(int step);
const char *a6400_recovery_status_name(int status);

#endif /* A6400_RECOVERY_H */
