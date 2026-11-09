#ifndef A6400_UVC_PTP_ROUTE_DRYRUN_H
#define A6400_UVC_PTP_ROUTE_DRYRUN_H
#include "uvc_ptp_stop_attest.h"
#define A6400_UVC_ROUTE_DRYRUN 0xc020f024u
/* Only a module-owned test word is changed. No native fops/text publication. */
int a6400_uvc_route_dryrun(void *,const struct a6400_verified_stops *);
#endif
