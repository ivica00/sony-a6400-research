/* Pure park-recovery decisions (E0358). No syscalls, no clock, no camera ABI.
 *
 * The camera-facing executor lives in src/main.c; this file is what the host
 * tests can pin without a camera. See include/a6400_recovery.h for the source
 * evidence behind the ordering rules.
 */
#include "a6400_recovery.h"

/* Fixed order: evidence is always written before anything destructive, and the
 * attestation set is always resumed before the descriptors are closed. */
static const int k_step_order[] = {
    A6400_REC_EVIDENCE,
    A6400_REC_STATE_QUERY,
    A6400_REC_STOP_RETRY,
    A6400_REC_FREEZE,
    A6400_REC_HOOK_RETIRE,
    A6400_REC_RESUME,
    A6400_REC_CLOSE
};

int a6400_recovery_needed(int stop_verified)
{
    return stop_verified ? 0 : 1;
}

int a6400_recovery_state_verified(int valid, const int32_t state[4])
{
    int i;

    if (!valid || !state)
        return 0;
    for (i = 0; i < 4; i++) {
        if (state[i] != 0)
            return 0;
    }
    return 1;
}

int a6400_recovery_retry_allowed(int valid, const int32_t state[4])
{
    /* Only a *verified clean* read suppresses the retry. A failed read is not
     * evidence of a clean session, and the retry is bounded to one attempt. */
    return a6400_recovery_state_verified(valid, state) ? 0 : 1;
}

int a6400_recovery_outcome(const struct a6400_recovery *rec)
{
    if (!rec || !rec->attempted)
        return A6400_RECOVERY_NOT_ATTEMPTED;
    /* Mandatory durable evidence. Nothing may be claimed recovered without it;
     * the SD trace flush + degraded receipt is the whole point of E0358. */
    if (!rec->evidence_written)
        return A6400_RECOVERY_FAILED;
    if (rec->failed_step != A6400_REC_NONE)
        return A6400_RECOVERY_FAILED;
    /* The module must have attested the idle session after the retry. */
    if (!rec->stop_retry_verified)
        return A6400_RECOVERY_FAILED;
    /* The entry hook must be retired or the firmware's native USB ioctl path
     * is still routed through the module. */
    if (!rec->hook_retired || rec->retire_rc != 0)
        return A6400_RECOVERY_FAILED;
    /* A freeze that was taken must have been resumed. */
    if (rec->freeze_rc != 0 || rec->resume_rc != 0)
        return A6400_RECOVERY_FAILED;
    if (!rec->closed)
        return A6400_RECOVERY_FAILED;
    return A6400_RECOVERY_RECOVERED;
}

uint32_t a6400_recovery_step_order(const int **steps)
{
    if (steps)
        *steps = k_step_order;
    return (uint32_t)(sizeof k_step_order / sizeof k_step_order[0]);
}

const char *a6400_recovery_step_name(int step)
{
    switch (step) {
    case A6400_REC_NONE:        return "none";
    case A6400_REC_EVIDENCE:    return "evidence";
    case A6400_REC_STATE_QUERY: return "state_query";
    case A6400_REC_STOP_RETRY:  return "stop_retry";
    case A6400_REC_FREEZE:      return "freeze";
    case A6400_REC_HOOK_RETIRE: return "hook_retire";
    case A6400_REC_RESUME:      return "resume";
    case A6400_REC_CLOSE:       return "close";
    default:                    return "unknown";
    }
}

const char *a6400_recovery_status_name(int status)
{
    switch (status) {
    case A6400_RECOVERY_NOT_ATTEMPTED: return "not_attempted";
    case A6400_RECOVERY_PENDING:       return "pending";
    case A6400_RECOVERY_RECOVERED:     return "recovered";
    case A6400_RECOVERY_FAILED:        return "failed";
    default:                           return "unknown";
    }
}
