/* Sony reference-to-a6400 descriptor/callback bridge. No USB enumeration,
 * registration success, frame contents, or encoder decisions are synthesized.
 * A single caller-owned context is reusable after complete retirement.
 * Native registration, quiescence and module-unload lifetime remain separate.
 */
#include "uvc_callback_bridge.h"
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
    if (primary || which==START || which==STOP) b->reference->alternate=d->alternate;
    if (which==START || which==STOP || (which>=SUSPEND && which<=DISCONNECT)) {
        ((void (*)(struct uvc_reference_descriptor *,uvc_u32,uvc_u32,uvc_u32))target)
            (b->reference,a1,a2,a3);
    } else {
        result=((uvc_u32 (*)(struct uvc_reference_descriptor *,uvc_u32,uvc_u32,uvc_u32))target)
            (b->reference,a1,a2,a3);
    }
    if (which==START) { b->started_interface=d->interface_number;b->started=1; }
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
    __sync_synchronize();b->active=1;return 0;
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
