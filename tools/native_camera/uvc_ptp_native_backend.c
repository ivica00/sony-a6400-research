#include "uvc_ptp_native_backend.h"
#include "uvc_ptp_code_sync.h"
static struct a6400_uvc_ptp_native_backend *live;
#ifdef A6400_UVC_TRACE_CONTROL
extern int printk(const char *,...);
static unsigned int descriptor_trace_calls;
#endif
static const unsigned int sites[4]={0x602b958c,0x602b95ac,0x602b95cc,0x602b95e0};
static const unsigned int originals[4]={0xeb0008fd,0xeb000a8e,0xeb0009a0,0xeb000ab9};

static int fingerprints(void)
{
    static const unsigned int pairs[][3]={
        {0x602b8610,0xe1a0c00d,0xe92dd8f0},
        {0x602b8560,0xe1a0c00d,0xe92dd8f0},
        {0x602bc550,0xe1a0c00d,0xe92ddff0},
        {0x602bc3e4,0xe1a0c00d,0xe92dddf0},
        {0x602b9464,0xe1a0c00d,0xe92dd830},
        {0x602bd7f8,0xe1a0c00d,0xe92dd818},
        {0x602bd834,0xe1a0c00d,0xe92dd800},
        {0x602b05fc,0xe1a0c00d,0xe92dddf0},
        {0x602b2b40,0xe1a0c00d,0xe92dd800},
        {0x602b1d3c,0xe1a0c00d,0xe92dddf0},
        {0x60119c80,0xe3a00000,0xee070f11}
    };
    unsigned int i;
    for (i=0;i<sizeof(pairs)/sizeof(pairs[0]);++i) {
        const volatile unsigned int *p=(const volatile unsigned int *)pairs[i][0];
        if (p[0]!=pairs[i][1] || p[1]!=pairs[i][2]) return -116;
    }
    return 0;
}

static int valid_gc(void *gc)
{
    return live && live->gc==gc && *(void **)0x6051b17cu==gc && *(void **)gc;
}
static int registry_count(void *gc,const void *descriptor,int quiet)
{
    unsigned char *head=(unsigned char *)gc+0x78;
    unsigned char *node=*(unsigned char **)head;
    unsigned int steps=0,count=0;
    while(node!=head) {
        unsigned char *record;
        if(!node || ++steps>64) return -116;
        record=node-4;
        if(quiet && record[0x14]) return -16;
        if(descriptor && *(void **)record==descriptor) ++count;
        node=*(unsigned char **)node;
    }
    return (int)count;
}
static int stopped(void *gc)
{
    return valid_gc(gc) && !((unsigned char *)gc)[0x74] &&
        ((int (*)(void))0x602bd450u)()==1;
}
static unsigned int *address_limit(void)
{
    unsigned int sp;
    __asm__ volatile("mov %0, sp":"=r"(sp));
    return (unsigned int *)((sp&~0x1fffu)+8);
}
static int flush_code(void)
{
    return a6400_uvc_sync_code(sites[0],sites[3]+4);
}
static int descriptor_dispatch(void *gc,const unsigned char *setup,void *buffer)
{
    void *request;
    int ret;
    if (!valid_gc(gc) || !live->hook_mask || !setup) return -22;
    request=*(void **)((unsigned char *)gc+8);
    /* Original g_bind allocates 512 bytes and stores the buffer in request[0]. */
    if (!request || *(void **)request!=buffer) return -22;
    __sync_add_and_fetch(&live->descriptor_users,1);
    ret=a6400_uvc_ptp_candidate_descriptor_reply(live->source,gc,setup,buffer,512);
#ifdef A6400_UVC_TRACE_CONTROL
    if(__sync_fetch_and_add(&descriptor_trace_calls,1)<128)
        printk("[a6400_ep0] type=%u index=%u requested=%u ret=%d config=%u\n",
               (unsigned int)setup[3],(unsigned int)setup[2],
               (unsigned int)setup[6]|((unsigned int)setup[7]<<8),ret,
               (unsigned int)((unsigned char *)gc)[0x74]);
#endif
    __sync_sub_and_fetch(&live->descriptor_users,1);
    return ret;
}

int a6400_uvc_ptp_native_runtime(unsigned int state[4])
{
    unsigned char *gc;
    if(!state || !live || !valid_gc(live->gc))return -19;
    gc=live->gc;
    state[0]=*(volatile unsigned int *)(gc+0x68);
    state[1]=*(volatile unsigned char *)(gc+0x74);
    state[2]=*(volatile unsigned char *)(gc+0x84);
    state[3]=*(volatile unsigned char *)(gc+0x85);
    return 0;
}

static int bind_ep0(void *gc,struct a6400_uvc_ptp_candidate *source)
{
    unsigned int i;
    int ret;
    unsigned int target=(unsigned int)descriptor_dispatch;
    if (!stopped(gc) || source!=live->source || live->descriptor_users) return -16;
    if (live->hook_mask) return -16;
    for (i=0;i<4;++i) {
        long delta=(long)target-(long)(sites[i]+8);
        if (*(volatile unsigned int *)sites[i]!=originals[i]) return -116;
        if ((target&3u) || delta<-(1l<<25) || delta>((1l<<25)-4) || (delta&3)) return -34;
        live->branch[i]=0xeb000000u|(((unsigned int)(delta>>2))&0xffffffu);
    }
    for (i=0;i<4;++i) {
        live->hook_mask|=1u<<i;
        *(volatile unsigned int *)sites[i]=live->branch[i];
    }
    ret=flush_code();
    if (ret) return ret;
    for (i=0;i<4;++i)
        if (*(volatile unsigned int *)sites[i]!=live->branch[i]) return -116;
    return 0;
}
static int unbind_ep0(void *gc)
{
    unsigned int i;
    int ret;
    if (!stopped(gc) || live->descriptor_users) return -16;
    for (i=0;i<4;++i) {
        unsigned int word=*(volatile unsigned int *)sites[i];
        if (word!=originals[i] && (!(live->hook_mask&(1u<<i)) || word!=live->branch[i])) return -116;
    }
    for (i=0;i<4;++i)
        if (live->hook_mask&(1u<<i)) *(volatile unsigned int *)sites[i]=originals[i];
    ret=flush_code();
    if (ret) return ret;
    for (i=0;i<4;++i) if (*(volatile unsigned int *)sites[i]!=originals[i]) return -116;
    live->hook_mask=0;return 0;
}
static int save_descriptors(void *gc,const struct a6400_descriptor_arg *arg)
{
    unsigned int *limit,previous;
    int ret;
    if (!stopped(gc) || !arg || arg->table!=live->source || *(void **)((unsigned char *)gc+0x6c)) return -22;
    limit=address_limit();previous=*limit;*limit=0xffffffffu;
    ret=((int (*)(void *,const void *))0x602bc550u)(gc,arg);
    *limit=previous;return ret;
}
static void free_descriptors(void *gc)
{
    void *table;
    if (!stopped(gc)) { if(live)live->last_error=-16;return; }
    table=*(void **)((unsigned char *)gc+0x6c);
    if (!table || table!=live->session->lease.installed ||
        table==live->session->original_root || table==live->source) {
        live->last_error=-116;return;
    }
    ((void (*)(void *))0x602bc3e4u)(gc);
}
static int register_driver(struct uvc_old_descriptor *d)
{
    unsigned int *flags,previous;
    int ret;
    if (!live || !stopped(live->gc) || !d || d->config!=1 ||
        (d->interface_number!=1 && d->interface_number!=2)) return -22;
    if(registry_count(live->gc,d,0)!=0) return -116;
    flags=(unsigned int *)((unsigned char *)live->gc+0x68);previous=*flags;*flags=previous&~4u;
    ret=((int (*)(void *))0x602b8610u)(d);
    *flags=previous;
    if(!ret && registry_count(live->gc,d,0)!=1) {
        live->last_error=-116;return -116;
    }
    return ret;
}
static int unregister_driver(struct uvc_old_descriptor *d)
{
    unsigned int *flags,previous;
    int ret;
    if (!live || !stopped(live->gc) || !d || d->config!=1 ||
        (d->interface_number!=1 && d->interface_number!=2)) {
        if(live) live->last_error=-22;
        return -22;
    }
    flags=(unsigned int *)((unsigned char *)live->gc+0x68);previous=*flags;*flags=previous&~4u;
    ret=((int (*)(void *))0x602b8560u)(d);
    *flags=previous;
    if(!ret && registry_count(live->gc,d,0)!=0) ret=-116;
    if(ret) live->last_error=ret;
    return ret;
}
static int pullup_target(void *gc)
{
    void *gadget=*(void **)gc;
    void *ops;
    if(!gadget)return -22;
    ops=*(void **)((unsigned char *)gadget+0x10);
    if(!ops)return -22;
    return *(unsigned int *)((unsigned char *)ops+0x14)==0x602b1d3cu ? 0:-116;
}
static int pullup(void *gc,int enable)
{
    int ret=pullup_target(gc);
    if(ret)return ret;
    return ((int (*)(void *,int))0x602b1d3cu)(*(void **)gc,enable);
}
static int quiesce(void *gc)
{
    int ret;
    if (!valid_gc(gc)) return -116;
    ret=pullup(gc,0);if(ret)return ret;
    /* This original function is void. Do not interpret its residual r0 as ack. */
    ((void (*)(void *))0x602b9464u)(gc);
    if (((unsigned char *)gc)[0x74] || live->descriptor_users ||
        live->session->bridge.in_flight || live->session->bridge.started) return -16;
    ret=registry_count(gc,0,1);if(ret<0)return ret;
    /* GCW stop changes bookkeeping state only. Hardware teardown above belongs
     * to dwc3_gadget_pullup(0); neither operation alone proves callback drain. */
    ret=((int (*)(void))0x602bd834u)();
    return ret ? ret:(stopped(gc) ? 0:-16);
}
static int resume(void *gc)
{
    void *gadget,*dwc,*out,*in;
    int ret,mode;
    if (!stopped(gc)) return -16;
    mode=((unsigned char *)gc)[0x84];if(mode!=0 && mode!=1)return -22;
    gadget=*(void **)gc;dwc=(unsigned char *)gadget-0x150;
    out=*(void **)((unsigned char *)dwc+0xd0);in=*(void **)((unsigned char *)dwc+0xd4);
    if (!out || !in || out==in || *(void **)((unsigned char *)out+0x48)!=dwc ||
        *(void **)((unsigned char *)in+0x48)!=dwc) return -22;
    ret=((int (*)(unsigned int))0x602bd7f8u)((unsigned int)mode);if(ret)return ret;
    if (((int (*)(void))0x602bd450u)()!=(mode ? 3:2)) return -16;
    ret=((int (*)(void *,void *,unsigned int,unsigned int))0x602b05fcu)(out,(void *)0x604e4e24u,0,0);if(ret)return ret;
    ret=((int (*)(void *,void *,unsigned int,unsigned int))0x602b05fcu)(in,(void *)0x604e4e24u,0,0);if(ret)return ret;
    *(unsigned int *)((unsigned char *)dwc+0x2e0)=1;
    ((void (*)(void *))0x602b2b40u)(dwc);
    ret=pullup(gc,1);if(ret)return ret;
    *(unsigned int *)((unsigned char *)gc+0x68)|=4u;
    return 0;
}
static int check_error(void *gc)
{ return valid_gc(gc) ? live->last_error:-116; }
int a6400_uvc_ptp_native_kernel_preflight(void)
{
    unsigned int i;
    if(fingerprints()) return -116;
    for(i=0;i<4;++i) if(*(volatile unsigned int *)sites[i]!=originals[i]) return -116;
    return 0;
}

int a6400_uvc_ptp_native_backend_init(struct a6400_uvc_ptp_native_backend *b,
                                    struct a6400_uvc_ptp_session *s,
                                    struct a6400_uvc_ptp_candidate *p,
                                    struct a6400_uvc_ptp_ops *ops)
{
    void *gc;
    if (!b || !s || !p || !ops || b->gc) return -22;
    if (live || !a6400_uvc_ptp_session_releasable(s)) return -16;
    if (a6400_uvc_ptp_native_kernel_preflight()) return -116;
    gc=*(void **)0x6051b17cu;
    if (!gc || !*(void **)gc || !*(void **)((unsigned char *)gc+8) ||
        a6400_uvc_ptp_validate_native_copy(p,p)) return -22;
    { int ret=pullup_target(gc);if(ret)return ret; }
    if(registry_count(gc,0,0)<0) return -116;
    b->session=s;b->source=p;b->gc=gc;b->hook_mask=0;b->descriptor_users=0;b->last_error=0;
    live=b;
    ops->quiesce=quiesce;ops->resume=resume;ops->bind_ep0=bind_ep0;ops->unbind_ep0=unbind_ep0;
    ops->reg=register_driver;ops->unreg=unregister_driver;
    ops->descriptor.save=save_descriptors;ops->descriptor.free=free_descriptors;
    ops->check_error=check_error;
    return 0;
}
int a6400_uvc_ptp_native_backend_retire(struct a6400_uvc_ptp_native_backend *b)
{
    unsigned int i;
    if (!b || b!=live) return -22;
    if (b->hook_mask || b->descriptor_users || !a6400_uvc_ptp_session_releasable(b->session)) return -16;
    live=0;for(i=0;i<sizeof(*b);++i)((unsigned char *)b)[i]=0;
    return 0;
}
