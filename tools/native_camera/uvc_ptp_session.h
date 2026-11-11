/* Offline orchestration candidate. The hardware backend is not supplied here.
 * Caller serializes all operations and pins source/reference/ops lifetime.
 * Reference must be the verified wire1/2 + endpoint84 MOD, not legacy code. */
#ifndef A6400_UVC_PTP_SESSION_H
#define A6400_UVC_PTP_SESSION_H
#include "uvc_callback_bridge.h"
#include "uvc_ptp_descriptor_lease.h"
#include "uvc_ptp_soft_disconnect.h"
struct a6400_uvc_ptp_ops {
    /* quiesce must stop/disconnect AND drain native PTP/UVC/EP0 consumers. */
    int (*quiesce)(void *);
    /* Optional end-path original clear-configuration (0x602b90cc). Called only
     * when A6400_UVC_TEARDOWN_UNCONFIGURE_FIRST is compiled in. */
    int (*unconfigure)(void *);
    int (*resume)(void *);
    /* unbind must be idempotent, including after a partially failed bind. */
    int (*bind_ep0)(void *,struct a6400_uvc_ptp_candidate *);
    int (*unbind_ep0)(void *);
    uvc_register_fn reg;
    uvc_unregister_fn unreg;
    struct a6400_descriptor_ops descriptor;
    /* Report failures from void/ignored callback results before releasing ownership. */
    int (*check_error)(void *);
};
enum { A6400_SESSION_IDLE,A6400_SESSION_PREPARING,A6400_SESSION_ACTIVE,A6400_SESSION_HELD };
struct a6400_uvc_ptp_session {
    unsigned int phase,stopped,prepared,registered,hook_attempted;
    void *gc,*original_root;
    unsigned int original_flags;
    unsigned char original_mode,original_speed,reserved[2];
    int last_error;
    struct a6400_uvc_ptp_ops ops;
    struct uvc_bridge bridge;
    struct a6400_descriptor_lease lease;
    /* Ordered-teardown record, kept after a held end so the stopped phase is
     * still observable. Appended (not inserted) so every earlier offset and
     * the existing fixtures stay ABI-compatible. */
    struct a6400_uvc_teardown_trace teardown;
};
int a6400_uvc_ptp_session_begin(struct a6400_uvc_ptp_session *,void *,
                               struct uvc_reference_descriptor *,
                               const struct a6400_descriptor_arg *,
                               const struct a6400_uvc_ptp_ops *);
int a6400_uvc_ptp_session_end(struct a6400_uvc_ptp_session *);
int a6400_uvc_ptp_session_releasable(const struct a6400_uvc_ptp_session *);
#endif
