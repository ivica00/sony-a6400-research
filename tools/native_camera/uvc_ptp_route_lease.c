#include "uvc_ptp_route_lease.h"

static int valid(struct a6400_route_lease *r)
{
    return r && r->slot && !((unsigned long)r->slot&3u) &&
        r->original && r->wrapper && r->original!=r->wrapper &&
        r->ops.pin && r->ops.unpin && r->ops.barrier_enter &&
        r->ops.barrier_leave && r->ops.retirable;
}

static int leave(struct a6400_route_lease *r,int result)
{
    int ret=r->ops.barrier_leave(r->context);
    if(ret) { r->phase=A6400_ROUTE_HELD;return ret; }
    r->barrier_held=0;
    return result;
}

int a6400_route_publish(struct a6400_route_lease *r)
{
    int ret;
    if(!valid(r))return -22;
    if(r->phase!=A6400_ROUTE_IDLE || r->pinned || r->barrier_held || r->published)return -16;
    ret=r->ops.pin(r->context);if(ret)return ret;
    r->pinned=1;
    ret=r->ops.barrier_enter(r->context);
    if(ret)goto unpin;
    r->barrier_held=1;
    if(!__sync_bool_compare_and_swap(r->slot,r->original,r->wrapper)) {
        /* An unexpected wrapper may already have callers. Preserve our code
         * lifetime rather than infer ownership from route equality. */
        r->phase=A6400_ROUTE_HELD;
        return leave(r,-116);
    }
    r->phase=A6400_ROUTE_PUBLISHED;
    r->published=1;
    return leave(r,0);
unpin:
    r->pinned=0;
    r->ops.unpin(r->context);
    return ret;
}

int a6400_route_retire(struct a6400_route_lease *r)
{
    int ret;
    if(!valid(r))return -22;
    if(r->phase!=A6400_ROUTE_PUBLISHED || !r->pinned || !r->published || r->barrier_held)return -16;
    ret=r->ops.barrier_enter(r->context);if(ret)return ret;
    r->barrier_held=1;
    ret=r->ops.retirable(r->context);
    if(ret)return leave(r,ret);
    if(!__sync_bool_compare_and_swap(r->slot,r->wrapper,r->original)) {
        r->phase=A6400_ROUTE_HELD;
        return leave(r,-116);
    }
    ret=leave(r,0);if(ret)return ret;
    r->phase=A6400_ROUTE_IDLE;
    r->published=0;
    r->pinned=0;
    r->ops.unpin(r->context);
    return 0;
}

int a6400_route_recover(struct a6400_route_lease *r)
{
    unsigned int observed;
    int ret;
    if(!valid(r))return -22;
    if(r->phase!=A6400_ROUTE_HELD || !r->pinned)return -16;
    if(!r->ops.barrier_recover)return -95;
    /* Never trust barrier_held after a failed leave: some callers may already
     * be running. The provider must independently rebuild the full barrier. */
    ret=r->ops.barrier_recover(r->context);if(ret)return ret;
    r->barrier_held=1;
    ret=r->ops.retirable(r->context);if(ret)return leave(r,ret);
    observed=*r->slot;
    if(observed==r->wrapper && !r->published)return leave(r,-116);
    if(observed!=r->original && observed!=r->wrapper)return leave(r,-116);
    if(!__sync_bool_compare_and_swap(r->slot,observed,r->original))return leave(r,-116);
    ret=leave(r,0);if(ret)return ret;
    r->phase=A6400_ROUTE_IDLE;r->published=0;r->pinned=0;
    r->ops.unpin(r->context);
    return 0;
}
