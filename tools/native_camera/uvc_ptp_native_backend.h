/* Guarded native kernel wrappers. OFFLINE candidate, not a deployable module.
 * Caller must serialize native USB mode changes and pin this backend/session.
 * Fingerprints are selected instructions, not a full live kernel hash check. */
#ifndef A6400_UVC_PTP_NATIVE_BACKEND_H
#define A6400_UVC_PTP_NATIVE_BACKEND_H
#include "uvc_ptp_session.h"
struct a6400_uvc_ptp_native_backend {
    struct a6400_uvc_ptp_session *session;
    struct a6400_uvc_ptp_candidate *source;
    void *gc;
    unsigned int hook_mask,branch[4];
    volatile unsigned int descriptor_users;
    int last_error;
};
int a6400_uvc_ptp_native_backend_init(struct a6400_uvc_ptp_native_backend *,
                                    struct a6400_uvc_ptp_session *,
                                    struct a6400_uvc_ptp_candidate *,
                                    struct a6400_uvc_ptp_ops *);
int a6400_uvc_ptp_native_backend_retire(struct a6400_uvc_ptp_native_backend *);
int a6400_uvc_ptp_native_kernel_preflight(void);
int a6400_uvc_ptp_native_runtime(unsigned int state[4]);
#endif
