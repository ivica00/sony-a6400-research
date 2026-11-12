/* Sony reference-to-a6400 descriptor/callback bridge. No USB enumeration,
 * registration success, frame contents, or encoder decisions are synthesized.
 * A single caller-owned context is reusable after complete retirement.
 * Native registration, quiescence and module-unload lifetime remain separate.
 */
#include "uvc_callback_bridge.h"

/* E0388: hot-path diagnostics are OFF in the default build. */
#ifndef A6400_UVC_TRACE
#define A6400_UVC_TRACE 0
#endif

/* E0356: setup-packet/return logging (kernel symbol, same as the other module files). */
extern int printk(const char *fmt, ...);

/* E0357: wire-to-native class setup translation (uvc_ptp_adapter.c). E0351
 * documents the reference class handler expects the native interface number
 * (wire wIndex 2 -> native 1); the Run B3 trace showed raw wIndex=2 arriving. */
extern int a6400_uvc_ptp_translate_setup(const unsigned char *wire,
                                          unsigned int wire_interface,
                                          unsigned char *native);
#define MAGIC 0x55425643u
#define EINVAL_ (-22)
#define EBUSY_ (-16)
#define ESTALE_ (-116)
#define NOT_HANDLED 2u
#define OFFSET(t,m) __builtin_offsetof(t,m)
_Static_assert(sizeof(void *)==4, "ARM32 ABI");
_Static_assert(sizeof(struct uvc_old_descriptor)==0x34, "old descriptor ABI");
_Static_assert(sizeof(struct uvc_reference_descriptor)==0x3c, "reference descriptor ABI");
_Static_assert(OFFSET(struct uvc_old_descriptor,callback)==0x10, "old callbacks");
_Static_assert(OFFSET(struct uvc_reference_descriptor,callback)==0x18, "reference callbacks");
_Static_assert(OFFSET(struct uvc_old_descriptor,alternate)==0x0c, "old state");
_Static_assert(OFFSET(struct uvc_reference_descriptor,alternate)==0x14, "reference state");

static struct uvc_bridge *volatile current;
enum { START, STOP, SET_HALT, CLEAR_HALT, SUSPEND, RESUME, DISCONNECT, CLASS, VENDOR };

/* E0358: read-only EP0 state probe for the CLASS path.
 *
 * The reference class handler queues its EP0 reply through ep->ops->queue
 * (ep->ops at +8, queue slot +0x10; verified in the linked reference fixture:
 * 5e001424 ldr r3,[r1,#8] / 5e001428 ldr r3,[r3,#8] for alloc_request and
 * 5e0014c4/5e0014c8 ldr r3,[r4,#8] / ldr r3,[r3,#0x10] for queue).  The
 * a6400 kernel's gadgetcore does NOT wrap ep0: gadgetcore's bind stores its
 * manager in ep0->driver_data and hands the UDC ep0 (gadget+0x14) to the class
 * callback, so that queue slot resolves to the built-in dwc3_gadget_ep0_queue
 * (preserved a6400 vmlinux.bin VA 0x602b2ad0 -> __dwc3_gadget_ep0_queue
 * 0x602b26ec).  That function returns 0 for several paths that arm NO
 * transfer, so a class-handler result of 0 does not prove the data phase was
 * queued.  Log the live UDC fields (offsets from the E0358 vmlinux
 * disassembly) before/after the reference handler.  Read-only: no pointer is
 * substituted and no kernel code/data is modified. */
#define A6400_EP_DESC     0x1cu   /* usb_ep.desc / dwc3_ep.desc            */
#define A6400_EP_DWC      0x48u   /* dwc3_ep.dwc                           */
#define A6400_EP_FLAGS    0x4cu   /* dwc3_ep.flags                         */
#define A6400_DWC_DEV     0x8cu   /* dwc3.dev (diagnostic only)            */
#define A6400_DWC_EPS     0xd0u   /* dwc3.eps[]: +0xd0 eps0 OUT, +0xd4 IN  */
#define A6400_DWC_DRIVER  0x170u  /* pointer checked non-null by ep0 queue */
#define A6400_DWC_CTRLPTR 0x2b0u  /* ctrl/gadget-driver-side pointer       */
#define A6400_DWC_STATE   0x2d8u  /* ep0 flag byte (bit0 bit2 bit4/5/6)    */
#define A6400_DWC_NEXT    0x2dcu  /* set by setup path / start_trans       */
#define A6400_DWC_EVENT   0x2e0u  /* compared with 2/3 in ep0 state machine*/
#define A6400_EP_LIST     0x24u   /* dwc3_ep.request_list (self-linked)    */
#define A6400_REQ_LIST    0x34u   /* usb_request.list (next at +0x34)      */

/* E0359: the Run B4 log showed ep0=68a1c9c0 rejected as no-udc-ep because the
 * guard only accepted 0x60000000..0x61000000, while the live a6400 module/
 * heap objects sit at 0x68xxxxxx (dwc 689e5810, dep 68a1c1c0, ep0 68a1c9c0).
 * Widen the read-only diagnostic bound to the kernel lowmem/vmalloc window. */
static uvc_u32 g_ep0_last;
static uvc_u32 g_class_lr; /* E0386: class-entry caller identity */
static int g_class_dir_out;
extern int a6400_uvc_restore_descriptors_bridge(void);
extern int schedule_work(void *work);
extern void msleep(unsigned int msecs);
static int g_disconnect_restored;
static uvc_u32 g_restore_work[8] __attribute__((aligned(4)));
static void a6400_uvc_restore_work_fn(void *work);

static int a6400_uvc_kernel_ptr(uvc_u32 p);
static uvc_u32 a6400_uvc_rd32(uvc_u32 address);
static uvc_u8 a6400_uvc_rd8(uvc_u32 address);
static uvc_u32 g_req_complete_orig;
struct a6400_ts { unsigned int sec, nsec; };
/* E0391: zero-printk in-RAM EP0 ring, dumped only once at STOP. */
struct a6400_ring_rec {
    uvc_u32 sec, nsec, hook, ep, req, bmrt, reqcode, wValue, wIndex, wLength;
    uvc_u32 lpos, cnt, evword, ep0state, next, fl, trb_ctl, trb_sz;
    uvc_u32 actual, status, buf0, buf1, bounce0, bounce1, result;
    uvc_u32 len, flags, lr;
};
static struct a6400_ring_rec g_ring[128];
static unsigned g_ring_n, g_ring_dropped, g_ring_dumped, g_ring_installed;
static uvc_u32 g_ring_ops_orig, g_ring_queue_orig, g_ring_ops_shadow[16], g_ring_ep;
static uvc_u32 g_start_count, g_class_call_count, g_get_cur_count, g_set_cur_count;
static uvc_u32 g_queue_count, g_complete_count;
static void a6400_uvc_ring_record(uvc_u32 hook, uvc_u32 ep, uvc_u32 req,
                                  const uvc_u8 *setup, uvc_u32 result);
static int a6400_uvc_ring_queue_wrap(void *ep, void *req, unsigned int gfp);
static void a6400_uvc_ring_complete_thunk(void *ep, void *req);

static void a6400_uvc_now(uvc_u32 *sec, uvc_u32 *ns)
{
    struct a6400_ts ts; ts.sec=0; ts.nsec=0;
    ((void (*)(void *))0x60157a14u)(&ts);
    *sec=ts.sec; *ns=ts.nsec;
}

static void a6400_uvc_ring_record(uvc_u32 hook, uvc_u32 ep, uvc_u32 req,
                                  const uvc_u8 *setup, uvc_u32 result)
{
    struct a6400_ring_rec *r;
    uvc_u32 dwc=0, ev=0, arr=0, buf=0, bv=0, trb=0, lpos=0, cnt=0;
    if (hook==0) g_start_count++; else if (hook==1) g_class_call_count++;
    else if (hook==2) g_queue_count++; else if (hook==3) g_complete_count++;
    if (g_ring_n >= 128u) { g_ring_dropped++; return; }
    r=&g_ring[g_ring_n++]; r->hook=hook; r->ep=ep; r->req=req; r->result=result; r->lr=0;
    a6400_uvc_now(&r->sec,&r->nsec);
    if (setup) { r->bmrt=setup[0]; r->reqcode=setup[1]; r->wValue=(uvc_u32)setup[2]|((uvc_u32)setup[3]<<8);
        r->wIndex=(uvc_u32)setup[4]|((uvc_u32)setup[5]<<8); r->wLength=(uvc_u32)setup[6]|((uvc_u32)setup[7]<<8); }
    if (ep && a6400_uvc_kernel_ptr(ep)) dwc=a6400_uvc_rd32(ep+0x48u);
    if (dwc && a6400_uvc_kernel_ptr(dwc)) {
        r->ep0state=a6400_uvc_rd8(dwc+0x2e0u); r->next=a6400_uvc_rd32(dwc+0x2dcu); r->fl=a6400_uvc_rd8(dwc+0x2d8u);
        arr=a6400_uvc_rd32(dwc+0xccu); ev=(arr && a6400_uvc_kernel_ptr(arr))?a6400_uvc_rd32(arr):0;
        if (ev && a6400_uvc_kernel_ptr(ev)) { lpos=a6400_uvc_rd32(ev+8u); cnt=a6400_uvc_rd32(ev+0xcu);
            buf=a6400_uvc_rd32(ev); if (buf && a6400_uvc_kernel_ptr(buf) && lpos<0x1000u) r->evword=a6400_uvc_rd32(buf+lpos); }
        r->lpos=lpos; r->cnt=cnt;
        trb=a6400_uvc_rd32(dwc+4u); if (trb && a6400_uvc_kernel_ptr(trb)) { r->trb_sz=a6400_uvc_rd32(trb+8u); r->trb_ctl=a6400_uvc_rd32(trb+0xcu); }
        bv=a6400_uvc_rd32(dwc+8u); if (bv && a6400_uvc_kernel_ptr(bv)) { r->bounce0=a6400_uvc_rd32(bv); r->bounce1=a6400_uvc_rd32(bv+4u); }
    }
    if (req && a6400_uvc_kernel_ptr(req)) {
        r->len=a6400_uvc_rd32(req+4u); r->flags=a6400_uvc_rd8(req+0x1au);
        r->actual=a6400_uvc_rd32(req+0x30u); r->status=a6400_uvc_rd32(req+0x2cu);
        buf=a6400_uvc_rd32(req); if (buf && a6400_uvc_kernel_ptr(buf)) { r->buf0=a6400_uvc_rd32(buf); r->buf1=a6400_uvc_rd32(buf+4u); }
    }
}

static int a6400_uvc_ring_queue_wrap(void *ep, void *req, unsigned int gfp)
{
    uvc_u32 r=(uvc_u32)req;
    /* E0395: match the standard setup_req request flag for short class IN. */
    if (!g_class_dir_out && r && a6400_uvc_kernel_ptr(r))
        *(volatile uvc_u8 *)(r+0x1au) |= 0x02u;
    a6400_uvc_ring_record(2u,(uvc_u32)ep,r,0,0);
    if (g_ring_n) g_ring[g_ring_n-1].lr=(uvc_u32)__builtin_return_address(0);
    if (r && a6400_uvc_kernel_ptr(r)) {
        uvc_u32 comp=a6400_uvc_rd32(r+0x1cu);
        if (comp && comp!=(uvc_u32)a6400_uvc_ring_complete_thunk) {
            g_req_complete_orig=comp;
            *(volatile uvc_u32 *)(r+0x1cu)=(uvc_u32)a6400_uvc_ring_complete_thunk;
        }
    }
    if (!g_ring_queue_orig) return -22;
    return ((int (*)(void *,void *,unsigned int))g_ring_queue_orig)(ep,req,gfp);
}

static void a6400_uvc_ring_complete_thunk(void *ep, void *req)
{
    uvc_u32 r=(uvc_u32)req, orig=g_req_complete_orig;
    a6400_uvc_ring_record(3u,(uvc_u32)ep,r,0,0);
    if (r && a6400_uvc_kernel_ptr(r) && orig) *(volatile uvc_u32 *)(r+0x1cu)=orig;
    if (orig && orig!=(uvc_u32)a6400_uvc_ring_complete_thunk)
        ((void (*)(void *,void *))orig)((void *)ep,(void *)req);
}

static void a6400_uvc_ring_install(uvc_u32 ep)
{
    uvc_u32 ops; unsigned i;
    if (g_ring_installed || !ep || !a6400_uvc_kernel_ptr(ep)) return;
    ops=a6400_uvc_rd32(ep+8u); if (!ops || !a6400_uvc_kernel_ptr(ops)) return;
    g_ring_ops_orig=ops;
    for (i=0;i<16u;i++) g_ring_ops_shadow[i]=a6400_uvc_rd32(ops+4u*i);
    g_ring_queue_orig=g_ring_ops_shadow[4];
    g_ring_ops_shadow[4]=(uvc_u32)a6400_uvc_ring_queue_wrap;
    *(volatile uvc_u32 *)(ep+8u)=(uvc_u32)g_ring_ops_shadow;
    g_ring_ep=ep; g_ring_installed=1;
}

static void a6400_uvc_ring_dump(void)
{
    unsigned i;
    if (g_ring_dumped) return;
    g_ring_dumped=1;
    printk("[a6400_uvc] RAMRING n=%u dropped=%u start=%u class=%u get=%u set=%u queue=%u complete=%u\n",
           g_ring_n,g_ring_dropped,g_start_count,g_class_call_count,g_get_cur_count,g_set_cur_count,g_queue_count,g_complete_count);
    for (i=0;i<g_ring_n;i++) {
        struct a6400_ring_rec *r=&g_ring[i];
        printk("[a6400_uvc] RR %u h=%u t=%u.%09u ep=%08x req=%08x bm=%02x rq=%02x v=%04x i=%04x l=%04x lpos=%x cnt=%x ev=%08x st=%02x nx=%x fl=%02x ctl=%08x sz=%08x act=%u sts=%d b0=%08x b1=%08x bo0=%08x bo1=%08x res=%d len=%u flg=%02x lr=%08x\n",
            i,(unsigned)r->hook,r->sec,r->nsec,(unsigned)r->ep,(unsigned)r->req,
            (unsigned)r->bmrt,(unsigned)r->reqcode,(unsigned)r->wValue,(unsigned)r->wIndex,(unsigned)r->wLength,
            (unsigned)r->lpos,(unsigned)r->cnt,(unsigned)r->evword,(unsigned)r->ep0state,
            (unsigned)r->next,(unsigned)r->fl,(unsigned)r->trb_ctl,(unsigned)r->trb_sz,
            (unsigned)r->actual,(int)r->status,(unsigned)r->buf0,(unsigned)r->buf1,
            (unsigned)r->bounce0,(unsigned)r->bounce1,(int)r->result,
            (unsigned)r->len,(unsigned)r->flags,(unsigned)r->lr);
    }
}

static void a6400_uvc_ring_install_early(void)
{
    uvc_u32 gc=a6400_uvc_rd32(0x6051b17cu);
    if (gc && a6400_uvc_kernel_ptr(gc)) {
        uvc_u32 ep=a6400_uvc_rd32(gc+4u);
        if (ep && a6400_uvc_kernel_ptr(ep)) a6400_uvc_ring_install(ep);
    }
}

static void a6400_uvc_ring_restore(void)
{
    if (g_ring_installed && g_ring_ep && a6400_uvc_kernel_ptr(g_ring_ep))
        *(volatile uvc_u32 *)(g_ring_ep+8u)=g_ring_ops_orig;
    g_ring_installed=0;
}


static int a6400_uvc_kernel_ptr(uvc_u32 p)
{ return p>=0x5f000000u && p<0x70000000u; }

static uvc_u32 a6400_uvc_rd32(uvc_u32 address);
static uvc_u32 g_gc_ep0, g_gc_ops_orig, g_gc_queue_orig, g_gc_ops_shadow[16];
static int g_gc_wrapped;

/* E0374: locate the gadgetcore context r4 used by setup_req: gadget = dwc+0x150;
 * gc = *( *(gadget+0x34) + 0x5c ) (g_setup -> 0x6029b1a0). */
static uvc_u32 a6400_uvc_gc_ctx(uvc_u32 ep)
{
    uvc_u32 dwc, gadget, a, gc;
    if (!ep || !a6400_uvc_kernel_ptr(ep)) return 0;
    dwc=a6400_uvc_rd32(ep+0x48u);
    if (!dwc || !a6400_uvc_kernel_ptr(dwc)) return 0;
    gadget=dwc+0x150u;
    a=a6400_uvc_rd32(gadget+0x34u);
    if (!a || !a6400_uvc_kernel_ptr(a)) return 0;
    gc=a6400_uvc_rd32(a+0x5cu);
    return (gc && a6400_uvc_kernel_ptr(gc)) ? gc : 0;
}

static int a6400_uvc_gc_queue_wrap(void *ep, void *req, unsigned int gfp);
__attribute__((unused)) static void a6400_uvc_gc_wrap_install(uvc_u32 ep)
{
    uvc_u32 gc, gc_ep, ops, i;
    if (g_gc_wrapped) return;
    gc=a6400_uvc_gc_ctx(ep);
    if (!gc) return;
    gc_ep=a6400_uvc_rd32(gc+4u);
    if (!gc_ep || !a6400_uvc_kernel_ptr(gc_ep)) return;
    ops=a6400_uvc_rd32(gc_ep+8u);
    if (!ops || !a6400_uvc_kernel_ptr(ops)) return;
    /* E0375: read-only GC observation only. Do NOT install a second ops shadow:
     * gc_ep0 == class ep0, nested shadows dangle ep0->ops during unload. */
    printk("[a6400_uvc] GCRO gc=%08x gc_ep=%08x ops=%08x class_ep=%08x eq=%d\n",
           (unsigned)gc,(unsigned)gc_ep,(unsigned)ops,(unsigned)ep,
           (unsigned)(gc_ep==ep));
    return;
    g_gc_ep0=gc_ep; g_gc_ops_orig=ops;
    for (i=0;i<16;i++) g_gc_ops_shadow[i]=a6400_uvc_rd32(ops+i*4u);
    g_gc_queue_orig=g_gc_ops_shadow[4];
    g_gc_ops_shadow[4]=(uvc_u32)a6400_uvc_gc_queue_wrap;
    *(volatile uvc_u32 *)(gc_ep+8u)=(uvc_u32)g_gc_ops_shadow;
    g_gc_wrapped=1;
    printk("[a6400_uvc] GCW gc=%08x gc_ep=%08x ops=%08x class_ep=%08x eq=%d\n",
           (unsigned)gc,(unsigned)gc_ep,(unsigned)ops,(unsigned)ep,
           (unsigned)(gc_ep==ep));
}
__attribute__((unused)) static void a6400_uvc_gc_wrap_restore(void)
{
    if (g_gc_wrapped && g_gc_ep0 && g_gc_ops_orig)
        *(volatile uvc_u32 *)(g_gc_ep0+8u)=g_gc_ops_orig;
    g_gc_wrapped=0;
}
static int a6400_uvc_gc_queue_wrap(void *ep, void *req, unsigned int gfp)
{
    uvc_u32 len=req?a6400_uvc_rd32((uvc_u32)req+4u):0;
    int ret;
    printk("[a6400_uvc] GC_EP0 queue ep=%08x req=%08x len=%u lr=%08x\n",
           (unsigned)(uvc_u32)ep,(unsigned)(uvc_u32)req,(unsigned)len,
           (unsigned)(uvc_u32)__builtin_return_address(0));
    if (!g_gc_queue_orig) return 0;
    ret=((int (*)(void *,void *,unsigned int))g_gc_queue_orig)(ep,req,gfp);
    printk("[a6400_uvc] GC_EP0 queue exit ret=%d\n",ret);
    return ret;
}


static uvc_u32 a6400_uvc_rd32(uvc_u32 address);

/* E0370: TRB diagnostics. dwc+4 = ep0_trb CPU virtual pointer (dma_alloc_coherent
 * virtual window, so it may lie outside the 0x5f..0x70 lowmem guard);
 * dwc+0x14 = ep0_trb_addr (DMA), dwc+8 = ep0_bounce virtual, dwc+0x18 = its DMA.
 * The kernel itself dereferences dwc+4, so reading it is safe; additionally try
 * the lowmem alias for addresses below 0x10000000. */
/* E0372: read-only GEVNT ring snapshot. dwc+0xcc = ev_buffs[] pointer array,
 * dwc+0x2c8 = number of event buffers; struct dwc3_event_buffer: +0 buf,
 * +4 length, +8 lpos, +0xc count, +0x10 flags (from dwc3_event_buffers_setup
 * 0x602ae5d8 and dwc3_thread_interrupt 0x602b1378). Dump the 8 words before and
 * 4 around lpos from the coherent ring, plus the counters. Read-only. */
static void a6400_uvc_log_events(const char *tag, uvc_u32 dwc)
{
    uvc_u32 n,arr,eb,buf,len,lpos,cnt,i,w,words,idx;
    if (!dwc || !a6400_uvc_kernel_ptr(dwc)) return;
    n=a6400_uvc_rd32(dwc+0x2c8u); arr=a6400_uvc_rd32(dwc+0xccu);
    if (!arr || n==0 || n>2) return;
    eb=a6400_uvc_rd32(arr);
    if (!eb) return;
    buf=a6400_uvc_rd32(eb); len=a6400_uvc_rd32(eb+4u);
    lpos=a6400_uvc_rd32(eb+8u); cnt=a6400_uvc_rd32(eb+0xcu);
    if (!buf || buf<0x40000000u || len<0x10u || len>0x1000u) return;
    words=len>>2; idx=(lpos>>2);
    printk("[a6400_uvc] %s gev n=%u eb=%08x buf=%08x len=%x lpos=%x cnt=%x "
           "w=%08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x\n",
           tag,(unsigned)n,(unsigned)eb,(unsigned)buf,(unsigned)len,(unsigned)lpos,
           (unsigned)cnt,
           (unsigned)a6400_uvc_rd32(buf+(((idx+words-8u)%words)<<2)),
           (unsigned)a6400_uvc_rd32(buf+(((idx+words-7u)%words)<<2)),
           (unsigned)a6400_uvc_rd32(buf+(((idx+words-6u)%words)<<2)),
           (unsigned)a6400_uvc_rd32(buf+(((idx+words-5u)%words)<<2)),
           (unsigned)a6400_uvc_rd32(buf+(((idx+words-4u)%words)<<2)),
           (unsigned)a6400_uvc_rd32(buf+(((idx+words-3u)%words)<<2)),
           (unsigned)a6400_uvc_rd32(buf+(((idx+words-2u)%words)<<2)),
           (unsigned)a6400_uvc_rd32(buf+(((idx+words-1u)%words)<<2)),
           (unsigned)a6400_uvc_rd32(buf+((idx%words)<<2)),
           (unsigned)a6400_uvc_rd32(buf+(((idx+1u)%words)<<2)),
           (unsigned)a6400_uvc_rd32(buf+(((idx+2u)%words)<<2)),
           (unsigned)a6400_uvc_rd32(buf+(((idx+3u)%words)<<2)));
    (void)i; (void)w;
}

static uvc_u32 a6400_uvc_rd32(uvc_u32 address);

/* E0383: read-only timestamps via a6400 ktime_get_ts 0x60157a14. */
static void a6400_uvc_tstamp(const char *tag)
{
    struct a6400_ts ts; ts.sec=0; ts.nsec=0;
    ((void (*)(void *))0x60157a14u)(&ts);
    printk("[a6400_uvc] TS %s sec=%u nsec=%u\n",tag,ts.sec,ts.nsec);
}

/* E0378: read-only controller snapshot: ctrl_req, single ep0_trb, bounce, dep
 * request lists, event ring, GEVNTCOUNT0, ep0 state. No writes. */
static uvc_u8 a6400_uvc_rd8(uvc_u32 address);
static void a6400_uvc_gcro(const char *tag, uvc_u32 ep, uvc_u32 ctrl)
{
    uvc_u32 dwc,regs,cr0=0,cr1=0,trb,ta,bv,ba,dep0,dep1,e0l,e1l,ev,lpos,cnt,flg,i,word;
    uvc_u32 gcnt=0,d0i=0,d1i=0,d0r=0,d1r=0,d0c=0,d1c=0;
    if (!ep || !a6400_uvc_kernel_ptr(ep)) return;
    dwc=a6400_uvc_rd32(ep+0x48u);
    if (!dwc || !a6400_uvc_kernel_ptr(dwc)) return;
    if (ctrl) { cr0=a6400_uvc_rd32(ctrl); cr1=a6400_uvc_rd32(ctrl+4u); }
    else { uvc_u32 cp=a6400_uvc_rd32(dwc); if (cp && a6400_uvc_kernel_ptr(cp)) { cr0=a6400_uvc_rd32(cp); cr1=a6400_uvc_rd32(cp+4u); } }
    regs=a6400_uvc_rd32(dwc+0x2b4u);
    if (regs) gcnt=a6400_uvc_rd32(regs+0xc30cu);
    trb=a6400_uvc_rd32(dwc+4u); ta=a6400_uvc_rd32(dwc+0x14u);
    bv=a6400_uvc_rd32(dwc+8u); ba=a6400_uvc_rd32(dwc+0x18u);
    dep0=a6400_uvc_rd32(dwc+0xd0u); dep1=a6400_uvc_rd32(dwc+0xd4u);
    e0l=dep0?a6400_uvc_rd32(dep0+0x24u):0; e1l=dep1?a6400_uvc_rd32(dep1+0x24u):0;
    /* E0386: dwc+0xcc is the ev_bufs[] POINTER ARRAY; the evt is [arr+0] (double dereference). */
    { uvc_u32 arr=a6400_uvc_rd32(dwc+0xccu);
      ev=(arr && a6400_uvc_kernel_ptr(arr))?a6400_uvc_rd32(arr):0; }
    if (ev && a6400_uvc_kernel_ptr(ev)) { lpos=a6400_uvc_rd32(ev+8u); cnt=a6400_uvc_rd32(ev+0xcu); flg=a6400_uvc_rd32(ev+0x10u); }
    else { lpos=0; cnt=0; flg=0; }
    /* E0386: dep->resource_index (dep+0x57), physical index (dep+0x55), live DEPCMD. */
    d0i=dep0?a6400_uvc_rd8(dep0+0x55u):0; d1i=dep1?a6400_uvc_rd8(dep1+0x55u):0;
    d0r=dep0?a6400_uvc_rd8(dep0+0x57u):0; d1r=dep1?a6400_uvc_rd8(dep1+0x57u):0;
    d0c=regs?a6400_uvc_rd32(regs+0x700u+0x10u*d0i+0xcu):0;
    d1c=regs?a6400_uvc_rd32(regs+0x700u+0x10u*d1i+0xcu):0;
    printk("[a6400_uvc] GCRO %s ctrl=%08x cr0=%08x cr1=%08x dma=%08x trb=%08x ta=%08x bpl=%08x bph=%08x sz=%08x ctl=%08x bv=%08x ba=%08x dep0=%08x/%08x dep1=%08x/%08x e0=%08x e1=%08x ev=%08x lpos=%x cnt=%x flg=%x gcnt=%x state=%x next=%x fl=%02x dep0i=%x dep0r=%x depcmd0=%08x cmdsts0=%x rsc0=%x dep1i=%x dep1r=%x depcmd1=%08x cmdsts1=%x rsc1=%x\n",
        tag,(unsigned)ctrl,(unsigned)cr0,(unsigned)cr1,(unsigned)a6400_uvc_rd32(dwc+0x10u),
        (unsigned)trb,(unsigned)ta,
        (unsigned)(trb?a6400_uvc_rd32(trb):0),(unsigned)(trb?a6400_uvc_rd32(trb+4u):0),
        (unsigned)(trb?a6400_uvc_rd32(trb+8u):0),(unsigned)(trb?a6400_uvc_rd32(trb+0xcu):0),
        (unsigned)bv,(unsigned)ba,
        (unsigned)dep0,(unsigned)(dep0?a6400_uvc_rd32(dep0+0x4cu):0),
        (unsigned)dep1,(unsigned)(dep1?a6400_uvc_rd32(dep1+0x4cu):0),
        (unsigned)e0l,(unsigned)e1l,(unsigned)ev,(unsigned)lpos,(unsigned)cnt,(unsigned)flg,(unsigned)gcnt,
        (unsigned)a6400_uvc_rd32(dwc+0x2e0u),(unsigned)a6400_uvc_rd32(dwc+0x2dcu),
        (unsigned)(a6400_uvc_rd32(dwc+0x2d8u)&0xffu),
        (unsigned)d0i,(unsigned)d0r,(unsigned)d0c,(unsigned)((d0c>>12)&0xfu),(unsigned)((d0c>>16)&0x7fu),
        (unsigned)d1i,(unsigned)d1r,(unsigned)d1c,(unsigned)((d1c>>12)&0xfu),(unsigned)((d1c>>16)&0x7fu));
    if (ev && a6400_uvc_kernel_ptr(ev)) {
        uvc_u32 buf=a6400_uvc_rd32(ev), len=a6400_uvc_rd32(ev+4u);
        if (buf && a6400_uvc_kernel_ptr(buf) && len>=0x10u && len<=0x1000u) {
            uvc_u32 idx=lpos>>2, words=len>>2;
            printk("[a6400_uvc] GCRO %s evw=",tag);
            for (i=0;i<6;i++) { word=a6400_uvc_rd32(buf+(((idx+words-1u+i)%words)<<2)); printk("%08x ",(unsigned)word); }
            printk("\n");
        }
    }
    if (e0l && dep0 && e0l!=dep0+0x24u && a6400_uvc_kernel_ptr(e0l)) {
        uvc_u32 r=e0l-0x34u, buf, len, act, st;
        if (a6400_uvc_kernel_ptr(r)) {
            buf=a6400_uvc_rd32(r); len=a6400_uvc_rd32(r+4u); act=a6400_uvc_rd32(r+0x30u); st=a6400_uvc_rd32(r+0x2cu);
            printk("[a6400_uvc] GCRO %s dep0_head req=%08x buf=%08x len=%u actual=%u status=%d\n",tag,(unsigned)r,(unsigned)buf,(unsigned)len,(unsigned)act,(int)st);
        }
    }
    if (e1l && dep1 && e1l!=dep1+0x24u && a6400_uvc_kernel_ptr(e1l)) {
        uvc_u32 r=e1l-0x34u, buf, len, act, st;
        if (a6400_uvc_kernel_ptr(r)) {
            buf=a6400_uvc_rd32(r); len=a6400_uvc_rd32(r+4u); act=a6400_uvc_rd32(r+0x30u); st=a6400_uvc_rd32(r+0x2cu);
            printk("[a6400_uvc] GCRO %s dep1_head req=%08x buf=%08x len=%u actual=%u status=%d\n",tag,(unsigned)r,(unsigned)buf,(unsigned)len,(unsigned)act,(int)st);
        }
    }
}

static void a6400_uvc_log_trb(const char *tag, uvc_u32 dwc)
{
    uvc_u32 tv=0, ta=0, bv=0, ba=0, bpl=0, bph=0, size=0, ctrl=0, b0=0, b1=0;
    uvc_u32 v;
    if (!dwc || !a6400_uvc_kernel_ptr(dwc)) return;
    tv=a6400_uvc_rd32(dwc+4u);
    ta=a6400_uvc_rd32(dwc+0x14u);
    bv=a6400_uvc_rd32(dwc+8u);
    ba=a6400_uvc_rd32(dwc+0x18u);
    v=0;
    if (tv>=0x40000000u) v=tv;
    else if (ta && ta<0x10000000u) v=ta+0x60000000u;
    if (v) {
        bpl=a6400_uvc_rd32(v);
        bph=a6400_uvc_rd32(v+4u);
        size=a6400_uvc_rd32(v+8u);
        ctrl=a6400_uvc_rd32(v+0xcu);
    }
    v=0;
    if (bv>=0x40000000u) v=bv;
    else if (ba && ba<0x10000000u) v=ba+0x60000000u;
    if (v) { b0=a6400_uvc_rd32(v); b1=a6400_uvc_rd32(v+4u); }
    printk("[a6400_uvc] %s trb_v=%08x trb_a=%08x bounce_v=%08x bounce_a=%08x "
           "bpl=%08x bph=%08x size=%08x ctrl=%08x trbsts=%x rem=%x hwo=%x "
           "bounce0=%08x bounce1=%08x\n",tag,(unsigned)tv,(unsigned)ta,
           (unsigned)bv,(unsigned)ba,(unsigned)bpl,(unsigned)bph,(unsigned)size,
           (unsigned)ctrl,(unsigned)(size>>28),(unsigned)(size&0xffffffu),
           (unsigned)(ctrl&1u),(unsigned)b0,(unsigned)b1);
}


/* E0361: EP0 queue wrapper for control-OUT data phases.
 *
 * Disassembly (reference.rebound.o): both request-prep paths explicitly zero
 * req->dma (GET helper 0x12fc, SET path 0x18ec) and then call ep->ops->queue
 * (+0x10). Live Run B5/B6: the UDC ep0 queue maps the IN request (GET post
 * dma=phys) but leaves an OUT request's dma 0 (SET post dma=0), so the OUT data
 * phase has no DMA target and the host times out. gadgetcore never wraps ep0;
 * the raw dwc3 ep0 queue does not map OUT buffers. Install a shadow ops table
 * whose queue slot maps req->dma from the direct map (buf - 0x60000000, the
 * same relation the IN mapping produced) for OUT requests before forwarding to
 * the original queue. Read-only for the request contents until the one dma
 * store; ep->ops is restored at STOP. */
static uvc_u32 a6400_uvc_rd32(uvc_u32 address);
static uvc_u8 a6400_uvc_rd8(uvc_u32 address);

static uvc_u32 g_ep0_ops_orig, g_ep0_queue_orig, g_ep0_ops_shadow[16];
static int g_ep0_wrapped;
static uvc_u32 g_gc_ep0, g_gc_ops_orig, g_gc_queue_orig, g_gc_ops_shadow[16];
static int g_gc_wrapped;


/* E0364: corrected EP0 completion observation. Linux gadget ABI:
 *   void (*complete)(struct usb_ep *ep, struct usb_request *req)
 * (dwc3_gadget_giveback 0x602affb8: mov r0,ep; ldr r3,[req+0x1c]; mov r1,req;
 *  blx r3). The E0362 thunk had a 1-arg signature and crashed. Log the request
 * at r1 (status +0x2c, actual +0x30) and the live ep0/UDC state, then call the
 * original with (ep,req) untouched. */
static void a6400_uvc_ep0_complete_thunk(void *ep, void *req)
{
    uvc_u32 r=(uvc_u32)req, e=(uvc_u32)ep, dwc=0, st=0, nx=0, ev=0;
    uvc_u32 orig;
    if (e && a6400_uvc_kernel_ptr(e)) {
        dwc=a6400_uvc_rd32(e+0x48u);
        if (dwc && a6400_uvc_kernel_ptr(dwc)) {
            st=a6400_uvc_rd8(dwc+0x2d8u);
            nx=a6400_uvc_rd32(dwc+0x2dcu);
            ev=a6400_uvc_rd32(dwc+0x2e0u);
        }
    }
    if (r && a6400_uvc_kernel_ptr(r)) {
        orig=g_req_complete_orig; /* E0366: req+0x1C now holds the thunk itself */
        {
            uvc_u32 e0=0,e1=0,f0=0,f1=0;
            if (dwc && a6400_uvc_kernel_ptr(dwc)) {
                e0=a6400_uvc_rd32(dwc+0xd0u);
                e1=a6400_uvc_rd32(dwc+0xd4u);
                if (e0 && a6400_uvc_kernel_ptr(e0)) f0=a6400_uvc_rd32(e0+0x4cu);
                if (e1 && a6400_uvc_kernel_ptr(e1)) f1=a6400_uvc_rd32(e1+0x4cu);
            }
            printk("[a6400_uvc] EP0 complete ep=%08x req=%08x status=%d actual=%u "
                   "state=%02x next=%08x event=%08x dep0=%08x dep1=%08x\n",
                   (unsigned)e,(unsigned)r,
                   (int)a6400_uvc_rd32(r+0x2cu),(unsigned)a6400_uvc_rd32(r+0x30u),
                   (unsigned)st,(unsigned)nx,(unsigned)ev,(unsigned)f0,(unsigned)f1);
        }
        printk("[a6400_uvc] EP0 complete lr=%08x state=%02x next=%08x fl=%02x\n",(unsigned)(uvc_u32)__builtin_return_address(0),(unsigned)(dwc?a6400_uvc_rd32(dwc+0x2e0u):0),(unsigned)(dwc?a6400_uvc_rd32(dwc+0x2dcu):0),(unsigned)(dwc?(a6400_uvc_rd32(dwc+0x2d8u)&0xffu):0));
        if (dwc) { a6400_uvc_gcro("complete",(uvc_u32)e,0); a6400_uvc_log_events("complete",dwc); a6400_uvc_log_trb("EP0 complete",dwc); }
        if (dwc && a6400_uvc_kernel_ptr(dwc)) {
            uvc_u32 e0=a6400_uvc_rd32(dwc+0xd0u), e1=a6400_uvc_rd32(dwc+0xd4u);
            printk("[a6400_uvc] EP0 list pre e0=%08x/%08x->%08x e1=%08x/%08x->%08x\n",
                   (unsigned)e0,(unsigned)(e0?a6400_uvc_rd32(e0+0x24u):0),(unsigned)(e0?a6400_uvc_rd32(e0+0x28u):0),
                   (unsigned)e1,(unsigned)(e1?a6400_uvc_rd32(e1+0x24u):0),(unsigned)(e1?a6400_uvc_rd32(e1+0x28u):0));
        }
        a6400_uvc_tstamp("complete-entry");
        if (orig && orig!=(uvc_u32)a6400_uvc_ep0_complete_thunk)
            ((void (*)(void *,void *))orig)((void *)e,(void *)r);
        return;
    }
    printk("[a6400_uvc] EP0 complete ep=%08x req=%08x (unmapped)\n",
           (unsigned)e,(unsigned)r);
}



static int a6400_uvc_ep0_queue_wrap(void *ep, void *req, unsigned int gfp)
{
    uvc_u32 r=(uvc_u32)req, buf=0, dma=0, len=0, dwc=0, next=0, event=0, state=0;
    unsigned int mapped=0;
    int ret;
    if (r && a6400_uvc_kernel_ptr(r)) {
        buf=a6400_uvc_rd32(r);
        len=a6400_uvc_rd32(r+4u);
        dma=a6400_uvc_rd32(r+8u);
        if (!dma && g_class_dir_out && buf>=0x60000000u && buf<0x70000000u) {
            dma=buf-0x60000000u;
            *(volatile uvc_u32 *)(r+8u)=dma;
            mapped=1;
        }
    }
    if (ep && a6400_uvc_kernel_ptr((uvc_u32)ep))
        dwc=a6400_uvc_rd32((uvc_u32)ep+0x48u);
    printk("[a6400_uvc] EP0 queue lr=%08x dir=%s req=%08x buf=%08x dma=%08x len=%u mapped=%u\n",(unsigned)(uvc_u32)__builtin_return_address(0),
           g_class_dir_out?"OUT":"IN",(unsigned)r,(unsigned)buf,(unsigned)dma,
           (unsigned)len,mapped);
    if (!g_ep0_queue_orig) return -22;
    a6400_uvc_tstamp("queue-before-orig");
    ret=((int (*)(void *,void *,unsigned int))g_ep0_queue_orig)(ep,req,gfp);
    a6400_uvc_tstamp("queue-after-orig");
    if (r && a6400_uvc_kernel_ptr(r)) {
        uvc_u32 comp=a6400_uvc_rd32(r+0x1cu);
        if (comp && comp!=(uvc_u32)a6400_uvc_ep0_complete_thunk) {
            g_req_complete_orig=comp;
            *(volatile uvc_u32 *)(r+0x1cu)=(uvc_u32)a6400_uvc_ep0_complete_thunk;
        }
    }
    if (dwc && a6400_uvc_kernel_ptr(dwc)) {
        state=a6400_uvc_rd8(dwc+0x2d8u);
        next=a6400_uvc_rd32(dwc+0x2dcu);
        event=a6400_uvc_rd32(dwc+0x2e0u);
    }
    printk("[a6400_uvc] EP0 queue exit ret=%d dma=%08x state=%02x next=%08x event=%08x\n",
           ret,(unsigned)(r?a6400_uvc_rd32(r+8u):0),(unsigned)state,
           (unsigned)next,(unsigned)event);
    /* E0370: unconditional TRB/bounce diagnostics (raw + aliases). */
    a6400_uvc_tstamp("queue-entry");
    if (dwc) { a6400_uvc_gcro("queue",(uvc_u32)ep,0); a6400_uvc_log_events("queue",dwc); a6400_uvc_log_trb("EP0 queue",dwc); }
    return ret;
}

__attribute__((unused)) static void a6400_uvc_ep0_wrap_install(void *ep)
{
    uvc_u32 ops, i;
    if (!ep || !a6400_uvc_kernel_ptr((uvc_u32)ep)) return;
    ops=a6400_uvc_rd32((uvc_u32)ep+8u);
    if (!ops || !a6400_uvc_kernel_ptr(ops) || g_ep0_wrapped) return;
    g_ep0_ops_orig=ops;
    for (i=0;i<16u;i++) g_ep0_ops_shadow[i]=a6400_uvc_rd32(ops+4u*i);
    g_ep0_queue_orig=g_ep0_ops_shadow[4];
    g_ep0_ops_shadow[4]=(uvc_u32)a6400_uvc_ep0_queue_wrap;
    *(volatile uvc_u32 *)((uvc_u32)ep+8u)=(uvc_u32)g_ep0_ops_shadow;
    g_ep0_wrapped=1;
    printk("[a6400_uvc] EP0 ops wrapped orig=%08x queue=%08x\n",
           (unsigned)g_ep0_ops_orig,(unsigned)g_ep0_queue_orig);
}

__attribute__((unused)) static void a6400_uvc_ep0_wrap_restore(void *ep)
{
    if (!g_ep0_wrapped || !ep) return;
    *(volatile uvc_u32 *)((uvc_u32)ep+8u)=g_ep0_ops_orig;
    g_ep0_wrapped=0;
    printk("[a6400_uvc] EP0 ops restored orig=%08x\n",(unsigned)g_ep0_ops_orig);
}


static uvc_u32 a6400_uvc_rd32(uvc_u32 address)
{ return *(volatile uvc_u32 *)address; }

static uvc_u8 a6400_uvc_rd8(uvc_u32 address)
{ return *(volatile uvc_u8 *)address; }

__attribute__((unused)) static void a6400_uvc_ep0_snapshot(const char *tag,uvc_u32 c)
{
    uvc_u32 ep=(uvc_u32)c,dwc,e0,e1,ops,next;
    if (ep && a6400_uvc_kernel_ptr(ep)) g_ep0_last=ep;
    if (!ep || !a6400_uvc_kernel_ptr(ep)) {
        uvc_u32 dw=(ep&&a6400_uvc_kernel_ptr(ep))?a6400_uvc_rd32(ep+0x48u):0;
        printk("[a6400_uvc] %s ep0=%08x no-udc-ep lr=%08x dwc=%08x\n",
               tag,(unsigned)ep,(unsigned)g_class_lr,(unsigned)dw);
        return;
    }
    ops=a6400_uvc_rd32(ep+8);
    printk("[a6400_uvc] %s ep0=%08x desc=%08x dep_flags=%08x ops=%08x "
           "queue=%08x\n",tag,(unsigned)ep,
           (unsigned)a6400_uvc_rd32(ep+A6400_EP_DESC),
           (unsigned)a6400_uvc_rd32(ep+A6400_EP_FLAGS),(unsigned)ops,
           (unsigned)(a6400_uvc_kernel_ptr(ops)?a6400_uvc_rd32(ops+0x10):0));
    dwc=a6400_uvc_rd32(ep+A6400_EP_DWC);
    if (!dwc || !a6400_uvc_kernel_ptr(dwc)) return;
    e0=a6400_uvc_rd32(dwc+A6400_DWC_EPS);
    e1=a6400_uvc_rd32(dwc+A6400_DWC_EPS+4u);
    printk("[a6400_uvc] %s dwc=%08x drv=%08x ctrl=%08x dev=%08x state=%02x "
           "next=%08x event=%08x eps0=%08x/%08x eps1=%08x/%08x\n",tag,
           (unsigned)dwc,(unsigned)a6400_uvc_rd32(dwc+A6400_DWC_DRIVER),
           (unsigned)a6400_uvc_rd32(dwc+A6400_DWC_CTRLPTR),
           (unsigned)a6400_uvc_rd32(dwc+A6400_DWC_DEV),
           (unsigned)a6400_uvc_rd8(dwc+A6400_DWC_STATE),
           (unsigned)a6400_uvc_rd32(dwc+A6400_DWC_NEXT),
           (unsigned)a6400_uvc_rd32(dwc+A6400_DWC_EVENT),
           (unsigned)e0,
           (unsigned)(e0&&a6400_uvc_kernel_ptr(e0)?a6400_uvc_rd32(e0+A6400_EP_FLAGS):0),
           (unsigned)e1,
           (unsigned)(e1&&a6400_uvc_kernel_ptr(e1)?a6400_uvc_rd32(e1+A6400_EP_FLAGS):0));
    if (!e0 || !a6400_uvc_kernel_ptr(e0)) return;
    next=a6400_uvc_rd32(e0+A6400_EP_LIST);
    if (next==e0+A6400_EP_LIST || !a6400_uvc_kernel_ptr(next)) {
        if (next!=e0+A6400_EP_LIST)
            printk("[a6400_uvc] %s eps0 list-head=%08x (expected %08x)\n",
                   tag,(unsigned)next,(unsigned)(e0+A6400_EP_LIST));
        return;
    }
    printk("[a6400_uvc] %s pending req=%08x buf=%08x len=%08x dma=%08x "
           "complete=%08x context=%08x status=%08x\n",tag,
           (unsigned)(next-A6400_REQ_LIST),
           (unsigned)a6400_uvc_rd32(next-A6400_REQ_LIST),
           (unsigned)a6400_uvc_rd32(next-A6400_REQ_LIST+4u),
           (unsigned)a6400_uvc_rd32(next-A6400_REQ_LIST+8u),
           (unsigned)a6400_uvc_rd32(next-A6400_REQ_LIST+0x1cu),
           (unsigned)a6400_uvc_rd32(next-A6400_REQ_LIST+0x20u),
           (unsigned)a6400_uvc_rd32(next-A6400_REQ_LIST+0x2cu));
}

static int stable(struct uvc_bridge *b)
{
    struct uvc_reference_descriptor *r=b->reference;
    uvc_u32 i;
    if (!r || r->name!=b->snapshot.name || r->config!=b->snapshot.config ||
        r->primary_interface!=b->snapshot.primary_interface ||
        r->interfaces!=b->snapshot.interfaces || r->interface_count!=2 ||
        r->private_data!=b->snapshot.private_data) return 0;
    for (i=0;i<2;i++) if (r->interfaces[i]!=b->interface_snapshot[i]) return 0;
    for (i=0;i<9;i++) if (r->callback[i]!=b->snapshot.callback[i]) return 0;
    return 1;
}

static struct uvc_bridge *owner(struct uvc_old_descriptor *d)
{
    struct uvc_bridge *b=current;
    if (!b || b->magic!=MAGIC || b->active!=1 ||
        (d!=&b->shadow[0] && d!=&b->shadow[1])) return (void *)0;
    if (!stable(b)) { b->last_error=ESTALE_; return (void *)0; }
    return b;
}

static void a6400_uvc_restore_work_fn(void *work)
{
    struct uvc_bridge *b=(struct uvc_bridge *)current;
    int i;
    (void)work;
    for (i=0;i<20;i++) {
        if (!b || b->in_flight==0) break;
        msleep(10u);
    }
    printk("[a6400_uvc] DEFERRED restore work start in_flight=%u\n",(unsigned)(b?b->in_flight:0));
    a6400_uvc_restore_descriptors_bridge();
    printk("[a6400_uvc] DEFERRED restore work done\n");
}

static void a6400_uvc_schedule_restore(void)
{
    g_restore_work[0]=0; g_restore_work[1]=0; g_restore_work[2]=0;
    g_restore_work[3]=(uvc_u32)a6400_uvc_restore_work_fn;
    schedule_work((void *)g_restore_work);
}

static uvc_u32 invoke(struct uvc_old_descriptor *d, uvc_u32 which,
                      uvc_u32 a1, uvc_u32 a2, uvc_u32 a3)
{
    struct uvc_bridge *b=owner(d);
    uvc_u32 target, result=0, bulk=0;
    int primary;
    if (!b) return which>=CLASS ? NOT_HANDLED : (uvc_u32)EINVAL_;
#ifdef A6400_UVC_ENUMERATION_ONLY
    /* Enumeration has no video-control owner or sensor feeder. Do not enter
     * reference PROBE/COMMIT/vendor handlers with an incomplete application. */
    if (which==CLASS || which==VENDOR) return NOT_HANDLED;
#endif
    primary=d->interface_number==b->snapshot.primary_interface;
    /* Endpoint-bearing START and its matching STOP can use either shadow.
     * Other notifications retain the reference's primary-only routing. */
    if (!primary && which<CLASS && which!=START && which!=STOP) return 0;
    if (which==STOP && d->interface_number!=b->started_interface) return 0;
    target=b->snapshot.callback[which];
    if (!target) return which>=CLASS ? NOT_HANDLED : 0;
    if (which==CLASS || which==VENDOR) {
        const uvc_u8 *request=(const uvc_u8 *)a1;
        if (!request) return NOT_HANDLED;
        if ((request[0]&0x1fu)==1u &&
            request[4]!=d->interface_number)
            return NOT_HANDLED;
        /* Interface recipient uses only wIndex low byte. UVC's high byte is
         * an entity ID, preserved for the original reference handler. */
    }
    /* Never forward an empty endpoint list: the original callback dereferences
     * its first entry. Bulk streaming may use alternate setting zero. */
    /* Kernel ldm loads a byte count together with three unrelated padding bytes.
     * Original make_ep_list consumes only the low byte (ldrb at .text+28f8). */
    if (which==START) a2 &= 0xffu;
    if (which==START && b->bulk_endpoint) {
        bulk=b->bulk_endpoint(a2,a3);
        if (!bulk) return 0;
        /* Original make_ep_list synchronously copies these wrapper pointers. */
        a2=1;a3=(uvc_u32)&bulk;
    }
    if (which==START && (a2==0 || a3==0)) return 0;
    if (which==START && !__sync_bool_compare_and_swap(&b->started,0,2)) {
        b->last_error=EBUSY_; return (uvc_u32)EBUSY_;
    }
    if (which==STOP && !__sync_bool_compare_and_swap(&b->started,1,2)) {
        if (b->started) b->last_error=EBUSY_;
        return 0;
    }
    __sync_add_and_fetch(&b->in_flight,1);
    if (b->active!=1 || !stable(b)) {
        b->last_error=ESTALE_;
        if (which==START) b->started=0;
        if (which==STOP) b->started=1;
        __sync_sub_and_fetch(&b->in_flight,1);
        return which>=CLASS ? NOT_HANDLED : (uvc_u32)ESTALE_;
    }
    /* E0357: translate the CLASS setup packet for the non-primary (VS) shadow so
     * the reference handler sees its native interface number. Only class/interface
     * requests are translated by the helper; everything else passes unchanged. */
    uvc_u8 translated[8];
    uvc_u32 forward_a1=a1;
    if (which==CLASS && a1 && d->interface_number!=b->snapshot.primary_interface) {
        const uvc_u8 *wire=(const uvc_u8 *)a1;
        if (a6400_uvc_ptp_translate_setup(wire,d->interface_number,translated)==0) {
            forward_a1=(uvc_u32)translated;
#if A6400_UVC_TRACE
            printk("[a6400_uvc] CLASS translated wire_iface=%u idx=%04x -> native idx=%04x\n",
                   d->interface_number,
                   (unsigned)(wire[4]|((unsigned)wire[5]<<8)),
                   (unsigned)(translated[4]|((unsigned)translated[5]<<8)));
#endif
        }
    }
    if (which==CLASS || which==VENDOR) {
#if A6400_UVC_TRACE
        const uvc_u8 *rq=(const uvc_u8 *)a1;
        /* E0356: log the exact setup packet and the synchronous reference
         * result. This is the camera-side substitute for the missing host
         * URB/setup trace (E0355): bmRequestType/bRequest/wValue/wIndex/wLength
         * are the fields usbvideo uses for VS_PROBE/CONTROL 0x0100, COMMIT
         * 0x0200 and SET_INTERFACE. */
#if A6400_UVC_TRACE
        if (rq) {
            printk("[a6400_uvc] %s entry rt=%02x req=%02x val=%04x idx=%04x len=%04x\n",
                   which==CLASS?"CLASS":"VENDOR",
                   rq[0],rq[1],
                   (unsigned)(rq[2]|((unsigned)rq[3]<<8)),
                   (unsigned)(rq[4]|((unsigned)rq[5]<<8)),
                   (unsigned)(rq[6]|((unsigned)rq[7]<<8)));
        } else {
            printk("[a6400_uvc] %s entry request=NULL\n",
                   which==CLASS?"CLASS":"VENDOR");
        }
#endif
#endif
        if (which==CLASS) b->class_requests++;
        else b->vendor_requests++;
    }
    if (primary || which==START || which==STOP) b->reference->alternate=d->alternate;
    if (which==START) { a6400_uvc_ring_install_early(); a6400_uvc_ring_record(0u,g_ep0_last,(uvc_u32)a2,0,(uvc_u32)a3); }
#if A6400_UVC_TRACE
    if (which==START) {
        printk("[a6400_uvc] START entry a1=%08x a2=%08x a3=%08x ep0_last=%08x\n",(unsigned)a1,(unsigned)a2,(unsigned)a3,(unsigned)g_ep0_last);
        if (g_ep0_last) a6400_uvc_gcro("START pre",g_ep0_last,0);
    }
#endif
    if (which==START || which==STOP) {
        printk("[a6400_uvc] reference %s entry iface=%u count=%u\n",
               which==START?"START":"STOP",d->interface_number,(unsigned)(a2&0xffu));
        /* E0360: after the 5 s host timeout the EP0 request state is the only way
         * to tell "completion never fired" (request still pending/BUSY) from
         * "completion fired but the host rejected/missed the data". Read-only. */
#if A6400_UVC_TRACE
        if (which==STOP && g_ep0_last)
        {
            if (g_ep0_last) a6400_uvc_log_events("STOP",a6400_uvc_rd32((uvc_u32)g_ep0_last+0x48u));
            a6400_uvc_gc_wrap_restore();
            a6400_uvc_ep0_snapshot("STOP-pre",g_ep0_last);
            a6400_uvc_ep0_wrap_restore((void *)(uvc_u32)g_ep0_last);
        }
#endif
    }
    if (which==CLASS) {
        const uvc_u8 *drq=(const uvc_u8 *)a1;
        if (drq) g_class_dir_out=((drq[0]&0x80u)==0u)?1:0;
        a6400_uvc_ring_record(1u,(uvc_u32)a2,0,(const uvc_u8 *)a1,0);
        if (drq) { if (drq[0]&0x80u) g_get_cur_count++; else g_set_cur_count++; }
        a6400_uvc_ring_install((uvc_u32)a2);
#if A6400_UVC_TRACE
        g_class_lr=(uvc_u32)__builtin_return_address(0);
        {   uvc_u32 d=(a2 && a6400_uvc_kernel_ptr((uvc_u32)a2))?a6400_uvc_rd32((uvc_u32)a2+0x48u):0;
            printk("[a6400_uvc] CLASS lr=%08x ep=%08x a3=%08x dwc=%08x state=%02x next=%08x fl=%02x\n",
                   (unsigned)g_class_lr,(unsigned)a2,(unsigned)a3,(unsigned)d,
                   (unsigned)((d&&a6400_uvc_kernel_ptr(d))?a6400_uvc_rd8(d+0x2d8u):0),
                   (unsigned)((d&&a6400_uvc_kernel_ptr(d))?a6400_uvc_rd32(d+0x2dcu):0),
                   (unsigned)((d&&a6400_uvc_kernel_ptr(d))?a6400_uvc_rd8(d+0x2d8u):0)); }
        if (a2) a6400_uvc_log_events("CLASS pre",a6400_uvc_rd32((uvc_u32)a2+0x48u));
        a6400_uvc_tstamp("CLASS-pre-ts");
        if (a2) a6400_uvc_gcro("CLASS pre",(uvc_u32)a2,(uvc_u32)a1);
        a6400_uvc_ep0_snapshot("CLASS ep0-pre",a2);
        a6400_uvc_gc_wrap_install((uvc_u32)a2);
        a6400_uvc_ep0_wrap_install((void *)(uvc_u32)a2);
#endif
    }
    if (which==STOP) { a6400_uvc_ring_dump(); a6400_uvc_ring_restore(); }
    if (which==DISCONNECT && !b->started && !g_disconnect_restored) {
        g_disconnect_restored=1;
        printk("[a6400_uvc] DISCONNECT schedule deferred restore started=%u in_flight=%u\n",(unsigned)b->started,(unsigned)b->in_flight);
        a6400_uvc_schedule_restore();
    }
    if (which==START || which==STOP || (which>=SUSPEND && which<=DISCONNECT)) {
        ((void (*)(struct uvc_reference_descriptor *,uvc_u32,uvc_u32,uvc_u32))target)
            (b->reference,forward_a1,a2,a3);
    } else {
        result=((uvc_u32 (*)(struct uvc_reference_descriptor *,uvc_u32,uvc_u32,uvc_u32))target)
            (b->reference,forward_a1,a2,a3);
    }
    if (which==CLASS) {
        b->class_last_result=result;
        a6400_uvc_ring_record(4u,(uvc_u32)a2,0,(const uvc_u8 *)a1,result);
#if A6400_UVC_TRACE
        a6400_uvc_tstamp("CLASS-post-ts");
        if (a2) { a6400_uvc_gcro("CLASS post",(uvc_u32)a2,(uvc_u32)a1); }
        a6400_uvc_ep0_snapshot("CLASS ep0-post",a2);
        printk("[a6400_uvc] CLASS exit result=%d\n",(int)result);
#endif
    } else if (which==VENDOR) {
        printk("[a6400_uvc] VENDOR exit result=%d\n",(int)result);
    } else if (which==START) {
        printk("[a6400_uvc] reference START returned iface=%u count=%u\n",
               d->interface_number,(unsigned)(a2&0xffu));
    } else if (which==STOP) {
        printk("[a6400_uvc] reference STOP returned iface=%u\n",d->interface_number);
    }
    if (which==START) {
        printk("[a6400_uvc] START exit result=%d\n",(int)result);
        if (g_ep0_last) a6400_uvc_gcro("START post",g_ep0_last,0);
        b->started_interface=d->interface_number;b->started=1;
    }
    if (which==STOP) b->started=0;
    __sync_sub_and_fetch(&b->in_flight,1);
    return result;
}

#define VOID_THUNK(name,id) \
static void name(struct uvc_old_descriptor *d,uvc_u32 a,uvc_u32 c,uvc_u32 e) \
{ (void)invoke(d,id,a,c,e); }
#define RESULT_THUNK(name,id) \
static uvc_u32 name(struct uvc_old_descriptor *d,uvc_u32 a,uvc_u32 c,uvc_u32 e) \
{ return invoke(d,id,a,c,e); }
VOID_THUNK(start_cb,START)
VOID_THUNK(stop_cb,STOP)
RESULT_THUNK(set_halt_cb,SET_HALT)
RESULT_THUNK(clear_halt_cb,CLEAR_HALT)
VOID_THUNK(suspend_cb,SUSPEND)
VOID_THUNK(resume_cb,RESUME)
VOID_THUNK(disconnect_cb,DISCONNECT)
RESULT_THUNK(class_cb,CLASS)
RESULT_THUNK(vendor_cb,VENDOR)

uvc_u32 a6400_uvc_bridge_size(void) { return sizeof(struct uvc_bridge); }

int a6400_uvc_bridge_prepare(struct uvc_bridge *b,struct uvc_reference_descriptor *r)
{
    uvc_u32 i,j;
    const uvc_u32 callbacks[9]={(uvc_u32)start_cb,(uvc_u32)stop_cb,
        (uvc_u32)set_halt_cb,(uvc_u32)clear_halt_cb,(uvc_u32)suspend_cb,
        (uvc_u32)resume_cb,(uvc_u32)disconnect_cb,(uvc_u32)class_cb,(uvc_u32)vendor_cb};
    if (!b || !r || !r->name || !r->config || !r->interfaces ||
        r->interface_count!=2 || r->interfaces[0]==r->interfaces[1] ||
        (r->primary_interface!=r->interfaces[0] && r->primary_interface!=r->interfaces[1]) ||
        !r->callback[START] || !r->callback[STOP] || !r->callback[CLASS]) return EINVAL_;
    if (b->magic || !__sync_bool_compare_and_swap(&current,(void *)0,b)) return EBUSY_;
    b->magic=MAGIC;b->active=0;b->in_flight=0;b->started=0;b->last_error=0;
    b->started_interface=0xffffffffu;b->bulk_endpoint=0;
    b->reference=r;b->snapshot=*r;
    for (i=0;i<2;i++) {
        struct uvc_old_descriptor *d=&b->shadow[i];
        b->interface_snapshot[i]=r->interfaces[i];
        d->name=r->name;d->config=r->config;d->interface_number=r->interfaces[i];
        d->reserved[0]=r->reserved[0];d->reserved[1]=r->reserved[1];
        d->private_data=r->private_data;d->alternate=0;
        for (j=0;j<3;j++) d->state_reserved[j]=0;
        for (j=0;j<9;j++) d->callback[j]=r->callback[j] ? callbacks[j] : 0;
    }
    return 0;
}

int a6400_uvc_bridge_activate(struct uvc_bridge *b,uvc_u32 registered_mask)
{
    if (!b || b!=current || b->magic!=MAGIC || b->active || registered_mask!=3 || !stable(b))
        return EINVAL_;
    __sync_synchronize();b->active=1;a6400_uvc_ring_install_early();return 0;
}

int a6400_uvc_bridge_retire(struct uvc_bridge *b,uvc_u32 still_registered_mask)
{
    uvc_u32 previous;
    if (!b || b!=current || b->magic!=MAGIC) return EINVAL_;
    if (still_registered_mask) return EBUSY_;
    previous=b->active;
    if (previous>1 || !__sync_bool_compare_and_swap(&b->active,previous,2)) return EBUSY_;
    __sync_synchronize();
    if (b->started || b->in_flight) { b->active=previous; return EBUSY_; }
    current=(void *)0;b->active=0;b->magic=0;return 0; /* context retired and ready for reuse */
}

int a6400_uvc_bridge_quiesce(struct uvc_bridge *b)
{
    struct uvc_old_descriptor *primary;
    if (!b || b!=current || b->magic!=MAGIC) return EINVAL_;
    if (!b->started) return 0;
    if (!stable(b)) { b->last_error=ESTALE_; return ESTALE_; }
    primary = (b->shadow[0].interface_number==b->started_interface) ?
              &b->shadow[0] : &b->shadow[1];
    (void)invoke(primary, STOP, 0, 0, 0);
    if (b->started || b->in_flight) return EBUSY_;
    return 0;
}

int a6400_uvc_bridge_register(struct uvc_bridge *b, uvc_register_fn reg_fn, uvc_unregister_fn unreg_fn)
{
    int ret;
    if (!b || b!=current || b->magic!=MAGIC || b->active || !reg_fn || !unreg_fn)
        return EINVAL_;
    if (!stable(b)) return ESTALE_;
    ret = reg_fn(&b->shadow[0]);
    if (ret != 0) return ret;
    ret = reg_fn(&b->shadow[1]);
    if (ret != 0) {
        unreg_fn(&b->shadow[0]);
        return ret;
    }
    ret = a6400_uvc_bridge_activate(b, 3);
    if (ret != 0) {
        unreg_fn(&b->shadow[1]);
        unreg_fn(&b->shadow[0]);
        return ret;
    }
    return 0;
    if (ret==0) a6400_uvc_ring_install_early();
}

int a6400_uvc_bridge_unregister(struct uvc_bridge *b, uvc_unregister_fn unreg_fn)
{
    int ret;
    if (!b || b!=current || b->magic!=MAGIC || !unreg_fn) return EINVAL_;
    ret = a6400_uvc_bridge_quiesce(b);
    if (ret != 0) return ret;
    unreg_fn(&b->shadow[1]);
    unreg_fn(&b->shadow[0]);
    return a6400_uvc_bridge_retire(b, 0);
}

struct uvc_old_descriptor *a6400_uvc_bridge_shadow(struct uvc_bridge *b,uvc_u32 index)
{
    if (!b || b!=current || b->magic!=MAGIC || index>=2) return (void *)0;
    return &b->shadow[index];
}
int a6400_uvc_bridge_last_error(struct uvc_bridge *b)
{ return b && b->magic==MAGIC ? b->last_error : EINVAL_; }
