/* Diagnostic only: no route publication and no full-owner certificate.
 * Native sys_ptrace checks that the CURRENT caller is each TID's tracer.
 * Each TID is also checked through native proc task membership/status.
 * No full task-set completeness or immutable publication token is issued. */
#ifndef A6400_UVC_PTP_STOP_ATTEST_H
#define A6400_UVC_PTP_STOP_ATTEST_H
#define A6400_UVC_ATTEST_STOPS 0xc020f023u
struct a6400_stop_request {
    unsigned int version,owner,count,tids,registers,siginfo,completed;
    int error;
};
/* Version2 reserves registers/siginfo as zero: native snapshots stay in kernel
 * memory. Scope is valid only inside this synchronous consumer callback and
 * is NOT a certificate of global ingress exclusion or VFS/DMA quiescence. */
struct a6400_verified_stops {
    unsigned int owner,count;
    const unsigned int *tids;
};
typedef int (*a6400_stop_consumer)(void *,const struct a6400_verified_stops *);
long a6400_uvc_with_stops(unsigned long,a6400_stop_consumer,void *);
long a6400_uvc_attest_stops(unsigned long);
#endif
