/* MOD-only offline route ownership policy. Not wired to native fops.
 * barrier_enter MUST establish complete caller quiescence, including cached
 * VFS targets; a stopped userspace PC or zero guard count alone is insufficient.
 * Failed barrier_enter MUST restore all stopped callers before returning.
 * Failed barrier_leave MUST report failure without claiming callers resumed;
 * this policy retains its pin and enters HELD for external recovery.
 * retirable must reject any live session, hook, callback or guard reservation.
 * Caller serializes every operation and pins ops/context for the lease. */
#ifndef A6400_UVC_PTP_ROUTE_LEASE_H
#define A6400_UVC_PTP_ROUTE_LEASE_H
struct a6400_route_ops {
    int (*pin)(void *);
    void (*unpin)(void *);
    int (*barrier_enter)(void *);
    int (*barrier_leave)(void *);
    int (*retirable)(void *);
    /* Re-establish complete quiescence after a possibly partial leave. Must
     * work from running, stopped or mixed caller states; failure retains pin. */
    int (*barrier_recover)(void *);
};
enum { A6400_ROUTE_IDLE, A6400_ROUTE_PUBLISHED, A6400_ROUTE_HELD };
struct a6400_route_lease {
    unsigned int phase, pinned, barrier_held, published;
    volatile unsigned int *slot;
    unsigned int original, wrapper;
    void *context;
    struct a6400_route_ops ops;
};
int a6400_route_publish(struct a6400_route_lease *);
int a6400_route_retire(struct a6400_route_lease *);
int a6400_route_recover(struct a6400_route_lease *);
#endif
