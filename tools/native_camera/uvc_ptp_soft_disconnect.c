/* Ordered soft-disconnect teardown. See uvc_ptp_soft_disconnect.h for the
 * invariants and the evidence for each phase. */
#include "uvc_ptp_soft_disconnect.h"
#include "uvc_ptp_session.h"

extern int printk(const char *,...);
/* usbg_video.ko driver accessor (E0319 section 11): returns the single global
 * 0xC0 driver context. The endpoint map is written by the module's own
 * usbg_cmn_make_ep_list copy at +0xB2 (ep id), +0xB4 (list), +0xB8 (count) and
 * released by usbg_cmn_clear_ep_list, which the reference STOP callback
 * (core_cb_stop, 0x744) calls. Reads only; this file never writes driver
 * context state, because only the driver's own callbacks may do that. */
extern void *usbg_video_get_this(void);

#define TD_BIT(n) (1u<<(n))

/* gc->drv_list head (verified by the native registry walker in
 * uvc_ptp_native_backend.c and by promote/demote in uvc_composite_shim.c):
 * head = gc+0x78; node = *(head); record = node-4; record[0] = descriptor. */
#define TD_DRV_LIST 0x78u
#define TD_DRV_MAX_STEPS 64u

static void td_reset(struct a6400_uvc_teardown_trace *t)
{
    unsigned int i;
    unsigned char *p=(unsigned char *)t;
    for (i=0;i<sizeof(*t);++i) p[i]=0;
    t->version=1;
    t->failed_phase=A6400_TD_PHASE_COUNT;
    t->ep_state=A6400_TD_EP_UNKNOWN;
    t->descriptor_state=A6400_TD_DESC_UNTOUCHED;
}

static void td_phase(struct a6400_uvc_teardown_trace *t,unsigned int phase)
{
    t->phases|=TD_BIT(phase);
}

static int td_fail(struct a6400_uvc_teardown_trace *t,unsigned int phase,int error)
{
    if (!t->first_error) {
        t->first_error=error;
        t->failed_phase=phase;
    }
    return error;
}

/* Read-only release check of the reference driver's endpoint map. */
static void td_read_ep_map(struct a6400_uvc_teardown_trace *t)
{
    unsigned char *ctx=(unsigned char *)usbg_video_get_this();
    t->ep_id=0;t->ep_list=0;t->ep_count=0;
    if (!ctx) { t->ep_state=A6400_TD_EP_ABSENT;return; }
    t->ep_id=(unsigned int)ctx[0xb2];
    t->ep_list=*(unsigned int *)(ctx+0xb4);
    t->ep_count=(unsigned int)ctx[0xb8];
    t->ep_state=t->ep_list ? A6400_TD_EP_RESIDUAL : A6400_TD_EP_CLEARED;
}

/* Count (and optionally locate) the two shadow records in gc->drv_list. */
static int td_shadow_records(void *gc,void *d0,void *d1,unsigned char **found)
{
    unsigned char *head,*node;
    unsigned int steps=0,count=0;
    if (found) { found[0]=0;found[1]=0; }
    if (!gc || (!d0 && !d1)) return 0;
    head=(unsigned char *)gc+TD_DRV_LIST;
    node=*(unsigned char **)head;
    while (node!=head) {
        unsigned char *record;
        void *descriptor;
        if (!node || ++steps>TD_DRV_MAX_STEPS) return -116;
        record=node-4;
        descriptor=*(void **)record;
        if (found && d0 && descriptor==d0 && !found[0]) found[0]=node;
        if (found && d1 && descriptor==d1 && !found[1]) found[1]=node;
        if ((d0 && descriptor==d0) || (d1 && descriptor==d1)) ++count;
        node=*(unsigned char **)node;
    }
    return (int)count;
}

/* Move the shadow records to the tail of gc->drv_list so the firmware's own
 * driver records (usbg_stillimage) are matched first again. Same link
 * discipline as the shipped a6400_demote_uvc_drivers(); every link is
 * validated before it is written and the walk is bounded. */
static int td_demote_shadows(void *gc,void *d0,void *d1)
{
    unsigned char *found[2]={0,0};
    unsigned char *head;
    int count=td_shadow_records(gc,d0,d1,found),i;
    if (count<=0) return count;
    head=(unsigned char *)gc+TD_DRV_LIST;
    for (i=0;i<2;++i) {
        unsigned char *node=found[i],*prev,*next,*tail;
        if (!node || node==head) continue;
        prev=*(unsigned char **)(node+4);
        next=*(unsigned char **)(node+0);
        if (!prev || !next || prev==node || next==node) return -116;
        tail=*(unsigned char **)(head+4);
        if (!tail) return -116;
        *(unsigned char **)(prev+0)=next;
        *(unsigned char **)(next+4)=prev;
        tail=*(unsigned char **)(head+4);
        if (!tail) return -116;
        *(unsigned char **)(node+0)=head;
        *(unsigned char **)(node+4)=tail;
        *(unsigned char **)(tail+0)=node;
        *(unsigned char **)(head+4)=node;
    }
    return count;
}

/* Descriptor restore. Never frees a table the owner replaced, never touches a
 * quarantined lease, and never writes the saved root when the owner's own
 * table is the coherent one. */
static int td_restore_descriptors(struct a6400_uvc_ptp_session *s,
                                  struct a6400_uvc_teardown_trace *t)
{
    void *gc;
    int ret;
    if (!s->gc) return -22;
    gc=s->gc;
    if (s->lease.phase==A6400_LEASE_EMPTY) {
        t->descriptor_state=A6400_TD_DESC_NOT_INSTALLED;
        t->descriptor_root=*(void **)((unsigned char *)gc+0x6c);
        return 0;
    }
    if (s->lease.phase!=A6400_LEASE_INSTALLED) return -16;
    if (*(void **)((unsigned char *)gc+0x6c)!=s->lease.installed) {
        /* The firmware re-created the gadget during the session and already
         * freed the table this module installed. Installing the saved root
         * would publish a pointer the owner no longer owns. Keep the owner's
         * table and record the deviation instead of claiming a restore. */
        t->descriptor_state=A6400_TD_DESC_OWNER_KEPT;
        t->descriptor_root=*(void **)((unsigned char *)gc+0x6c);
        printk("[a6400_td] descriptor table replaced by owner; saved root not installed\n");
        return 0;
    }
    ret=a6400_descriptor_restore(&s->lease,&s->ops.descriptor);
    if (ret) return ret;
    if (*(void **)((unsigned char *)gc+0x6c)!=s->original_root) return -116;
    *(unsigned int *)((unsigned char *)gc+0x68)=s->original_flags;
    ((unsigned char *)gc)[0x84]=s->original_mode;
    ((unsigned char *)gc)[0x85]=s->original_speed;
    t->descriptor_state=A6400_TD_DESC_RESTORED;
    t->descriptor_root=*(void **)((unsigned char *)gc+0x6c);
    return 0;
}

int a6400_uvc_soft_disconnect(struct a6400_uvc_ptp_session *s,
                              struct a6400_uvc_teardown_trace *t)
{
    void *gc;
    void *shadow0=(void *)0,*shadow1=(void *)0;
    unsigned int started_at_entry;
    int ret,error=0;

    if (!s || !t || !s->gc) return -22;
    td_reset(t);
    gc=s->gc;
    started_at_entry=s->bridge.started;
    /* Shadow record identities are resolved before any phase can branch to the
     * demote step; a NULL identity simply skips the list walk. */
    shadow0=a6400_uvc_bridge_shadow(&s->bridge,0);
    shadow1=a6400_uvc_bridge_shadow(&s->bridge,1);

    /* 1. Original clear-configuration (0x602b90cc): stops interfaces 0/1/2
     * through the original interface-stop path, which clears the registry
     * active flag, delivers the descriptor STOP callback, releases each
     * endpoint wrapper and disables the interface endpoints, then clears the
     * configuration/alternate bookkeeping. It does not touch the UDC (the
     * trailing gadget ioctl(1,0) is a verified no-op, E0250). E0252 is the
     * only recorded clean physical teardown and it used exactly this order. */
    if (!s->stopped) {
        td_phase(t,A6400_TD_UNCONFIGURE);
        if (s->ops.unconfigure) {
            ret=s->ops.unconfigure(gc);
            if (ret) return td_fail(t,A6400_TD_UNCONFIGURE,ret);
        }
    }

    /* 2. Reference STOP callback, if the interface stop above did not deliver
     * it (the bridge quiesce is idempotent and refuses while a callback is in
     * flight). */
    if (s->bridge.magic) {
        td_phase(t,A6400_TD_BRIDGE_QUIESCE);
        if (s->bridge.in_flight) return td_fail(t,A6400_TD_BRIDGE_QUIESCE,-16);
        ret=a6400_uvc_bridge_quiesce(&s->bridge);
        if (ret) return td_fail(t,A6400_TD_BRIDGE_QUIESCE,ret);
        if (s->bridge.started) return td_fail(t,A6400_TD_BRIDGE_QUIESCE,-16);
        t->stream_stopped=(started_at_entry && !s->bridge.started) ? 1u:0u;
    }

    /* 3. The reference driver's endpoint map (ctx+0xB2/B4/B8, E0319) must be
     * released before the UDC goes down: a residual list still references the
     * composite Bulk IN 0x84 wrapper. */
    td_phase(t,A6400_TD_EP_MAP);
    td_read_ep_map(t);
    if (t->ep_state==A6400_TD_EP_RESIDUAL) return td_fail(t,A6400_TD_EP_MAP,-16);

    /* 4. UDC down: pullup(0), native disconnect, controller stop. The native
     * guards require this state before any driver record or descriptor table
     * may be released. */
    if (!s->stopped) {
        td_phase(t,A6400_TD_UDC_DOWN);
        if (!s->ops.quiesce) return td_fail(t,A6400_TD_UDC_DOWN,-22);
        ret=s->ops.quiesce(gc);
        if (ret) return td_fail(t,A6400_TD_UDC_DOWN,ret);
        s->stopped=1;
        t->udc_down=1;
    }
    if (s->ops.check_error && (ret=s->ops.check_error(gc))) {
        error=td_fail(t,A6400_TD_UDC_DOWN,ret);
        goto demote;
    }

    /* 5. Restore the four EP0 descriptor call sites. From here on the host is
     * answered by the native descriptor path again, so the module's table must
     * stay valid until it is either restored or deliberately kept. */
    if (s->hook_attempted) {
        td_phase(t,A6400_TD_UNBIND_EP0);
        if (!s->ops.unbind_ep0) {
            error=td_fail(t,A6400_TD_UNBIND_EP0,-22);
            goto demote;
        }
        ret=s->ops.unbind_ep0(gc);
        if (ret) {
            error=td_fail(t,A6400_TD_UNBIND_EP0,ret);
            /* Hooks still bound: free no table, keep the composite coherent,
             * and reconnect so the host sees the audited 0322 device. */
            goto demote;
        }
        s->hook_attempted=0;
    }

    /* 6. Unregister both shadow driver records (the native unregister is the
     * only operation that unlinks them; it refuses unless the controller is
     * stopped). On failure the table must not be freed: a registered record
     * may still be dispatched. The session keeps its `registered` bit until the
     * native error check passes, so a retried teardown re-enters this phase
     * instead of falling through to the descriptor free. */
    if (s->registered) {
        td_phase(t,A6400_TD_UNREGISTER);
        if (!s->ops.unreg) {
            error=td_fail(t,A6400_TD_UNREGISTER,-22);
            goto demote;
        }
        ret=a6400_uvc_bridge_unregister(&s->bridge,s->ops.unreg);
        if (ret) {
            error=td_fail(t,A6400_TD_UNREGISTER,ret);
            goto demote;
        }
        if (s->ops.check_error && (ret=s->ops.check_error(gc))) {
            error=td_fail(t,A6400_TD_UNREGISTER,ret);
            goto demote;
        }
        s->registered=0;s->prepared=0;
    } else if (s->prepared) {
        td_phase(t,A6400_TD_UNREGISTER);
        ret=a6400_uvc_bridge_retire(&s->bridge,0);
        if (ret) {
            error=td_fail(t,A6400_TD_UNREGISTER,ret);
            goto demote;
        }
        if (s->ops.check_error && (ret=s->ops.check_error(gc))) {
            error=td_fail(t,A6400_TD_UNREGISTER,ret);
            goto demote;
        }
        s->prepared=0;
    }

    /* 7. Descriptor restore (only with the hooks unbound and every shadow
     * record retired). */
    td_phase(t,A6400_TD_DESCRIPTOR);
    if ((shadow0 || shadow1) && td_shadow_records(gc,shadow0,shadow1,0)!=0) {
        /* A registered record may still be dispatched to; keep the table. */
        error=td_fail(t,A6400_TD_DESCRIPTOR,-16);
        goto demote;
    }
    ret=td_restore_descriptors(s,t);
    if (ret) {
        error=td_fail(t,A6400_TD_DESCRIPTOR,ret);
        goto demote;
    }
    if (s->ops.check_error && (ret=s->ops.check_error(gc))) {
        error=td_fail(t,A6400_TD_DESCRIPTOR,ret);
        goto demote;
    }

demote:
    /* 8. Demote any shadow record that is still linked so the firmware's own
     * driver records are matched first. Normally both were unregistered. */
    td_phase(t,A6400_TD_DEMOTE);
    t->shadow_records=td_shadow_records(gc,shadow0,shadow1,0);
    if (t->shadow_records>0) {
        ret=td_demote_shadows(gc,shadow0,shadow1);
        if (ret<0 && !error) error=td_fail(t,A6400_TD_DEMOTE,ret);
        t->shadow_records=td_shadow_records(gc,shadow0,shadow1,0);
    }
    /* Retired means: no shadow record is linked any more and the session no
     * longer claims either the registered or the prepared bridge state. */
    t->drivers_retired=(t->shadow_records==0 && !s->registered && !s->prepared) ? 1u:0u;

    /* 9. Explicit soft reconnect: controller start, EP0 re-arm, D+ high. The
     * host sees a fresh enumeration; the firmware's next USB mode transition
     * then starts from a connected gadget with a coherent descriptor table. */
    td_phase(t,A6400_TD_RECONNECT);
    if (!s->ops.resume) {
        /* No resume op means this caller cannot own a reconnect. Keep the
         * earlier error and never call through a NULL slot. */
        if (!error) error=td_fail(t,A6400_TD_RECONNECT,-22);
        return error;
    }
    s->stopped=0; /* resume may partially enable hardware even on failure */
    ret=s->ops.resume(gc);
    t->reconnect=ret ? ret:1;
    if (ret) {
        if (!error) error=td_fail(t,A6400_TD_RECONNECT,ret);
    } else if (t->udc_down) {
        t->transitions=1;
    }
    printk("[a6400_td] done phases=%03x failed=%u error=%d ep=%u list=%08x id=%u count=%u "
           "desc=%u root=%p retired=%u shadow=%d reconnect=%d\n",
           t->phases,t->failed_phase,error,t->ep_state,t->ep_list,t->ep_id,
           t->ep_count,t->descriptor_state,t->descriptor_root,
           t->drivers_retired,t->shadow_records,t->reconnect);
    return error;
}
