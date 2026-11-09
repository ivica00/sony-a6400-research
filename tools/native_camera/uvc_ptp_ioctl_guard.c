#include "uvc_ptp_ioctl_guard.h"

long a6400_uvc_guard_dispatch(struct a6400_uvc_ioctl_guard *g,void *file,
                              unsigned int command,unsigned long arg)
{
    long result;
    int ret;
    if(!g || !g->original)return -22;
    if(g->fault)return g->fault;
    ret=a6400_uvc_mode_enter(&g->gate);if(ret)return ret;
    result=g->original(file,command,arg);
    ret=a6400_uvc_mode_leave(&g->gate);
    if(ret) {
        /* The original operation may already have run. Keep the guard faulted;
         * caller must not interpret this as a clean, reversible native error. */
        __sync_val_compare_and_swap(&g->fault,0,ret);
        return ret;
    }
    return result;
}
int a6400_uvc_guard_claim(struct a6400_uvc_ioctl_guard *g)
{
    if(!g || !g->original)return -22;
    if(g->fault)return g->fault;
    return a6400_uvc_mode_claim(&g->gate);
}
int a6400_uvc_guard_release(struct a6400_uvc_ioctl_guard *g)
{
    if(!g || !g->original)return -22;
    if(g->fault)return g->fault;
    return a6400_uvc_mode_release(&g->gate);
}
