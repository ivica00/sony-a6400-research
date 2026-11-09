#include "uvc_ptp_mode_gate.h"
#define HELD 0x80000000u
#define BUSY (-16)
#define INVALID (-22)

/* One atomic word prevents a gap between checking active native calls and
 * reserving the MOD transaction. A failed bounded CAS returns busy. */
int a6400_uvc_mode_enter(struct a6400_uvc_mode_gate *g)
{
    unsigned int i,old;
    if(!g)return INVALID;
    for(i=0;i<8;++i) {
        old=g->word;
        if(old&HELD || old==HELD-1)return BUSY;
        if(__sync_bool_compare_and_swap(&g->word,old,old+1))return 0;
    }
    return BUSY;
}
int a6400_uvc_mode_leave(struct a6400_uvc_mode_gate *g)
{
    unsigned int i,old;
    if(!g)return INVALID;
    for(i=0;i<8;++i) {
        old=g->word;
        if(!old || old&HELD)return INVALID;
        if(__sync_bool_compare_and_swap(&g->word,old,old-1))return 0;
    }
    return BUSY;
}
int a6400_uvc_mode_claim(struct a6400_uvc_mode_gate *g)
{
    if(!g)return INVALID;
    return __sync_bool_compare_and_swap(&g->word,0,HELD) ? 0:BUSY;
}
int a6400_uvc_mode_release(struct a6400_uvc_mode_gate *g)
{
    if(!g)return INVALID;
    return __sync_bool_compare_and_swap(&g->word,HELD,0) ? 0:INVALID;
}
