/* MOD wrapper for an already-routed native ioctl. This does not install hooks.
 * The guard and original target must remain pinned for every possible caller. */
#ifndef A6400_UVC_PTP_IOCTL_GUARD_H
#define A6400_UVC_PTP_IOCTL_GUARD_H
#include "uvc_ptp_mode_gate.h"
typedef long (*a6400_native_ioctl_fn)(void *,unsigned int,unsigned long);
struct a6400_uvc_ioctl_guard {
    struct a6400_uvc_mode_gate gate;
    a6400_native_ioctl_fn original;
    volatile int fault;
};
long a6400_uvc_guard_dispatch(struct a6400_uvc_ioctl_guard *,void *,unsigned int,unsigned long);
int a6400_uvc_guard_claim(struct a6400_uvc_ioctl_guard *);
int a6400_uvc_guard_release(struct a6400_uvc_ioctl_guard *);
#endif
