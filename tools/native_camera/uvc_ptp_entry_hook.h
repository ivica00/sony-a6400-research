#ifndef A6400_UVC_PTP_ENTRY_HOOK_H
#define A6400_UVC_PTP_ENTRY_HOOK_H
#include "uvc_ptp_stop_attest.h"
#include "uvc_ptp_ioctl_guard.h"
#include "uvc_ptp_route_lease.h"

/* Verified entry hook lifecycle for native gadgetcore ioctl at 0x602b8844.
 * Integrates:
 * 1. Verified stop scope barrier (guaranteeing zero callers inside or approaching entry)
 * 2. Route lease state machine (IDLE -> PUBLISHED -> IDLE, retaining HELD on error)
 * 3. Module self-pinning (a6400_module_self_get / put)
 * 4. Bounded mode gate tracking active callers, claiming HELD during MOD operation
 * 5. Native entry bypass (a6400_uvc_native_ioctl_tail) preserving stack frame and saved PC
 * 6. Four-core coherent cache sync (a6400_uvc_sync_code) across D-clean PoU, I-inval, BP-inval, DSB/ISB
 */

#define A6400_UVC_ENTRY_HOOK_CYCLE   0xc020f025u
#define A6400_UVC_ENTRY_HOOK_PUBLISH 0xc020f026u
#define A6400_UVC_ENTRY_HOOK_RETIRE  0xc020f027u
#define A6400_UVC_QUERY_IDENTITY     0x8010f028u
#define A6400_UVC_QUERY_USB_STATE    0x8010f029u

int a6400_uvc_entry_hook_publish(const struct a6400_verified_stops *scope);
int a6400_uvc_entry_hook_retire(const struct a6400_verified_stops *scope);
int a6400_uvc_entry_hook_recover(const struct a6400_verified_stops *scope);
unsigned int a6400_uvc_entry_hook_phase(void);
struct a6400_uvc_ioctl_guard *a6400_uvc_entry_guard(void);
long a6400_uvc_native_entry_wrapper(void *file,unsigned int command,unsigned long arg);

#endif
