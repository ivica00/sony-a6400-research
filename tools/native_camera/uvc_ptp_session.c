#include "uvc_ptp_session.h"
#include "uvc_ptp_adapter.h"
#include "uvc_ptp_soft_disconnect.h"

/* E0354 Run B pre-flight instrumentation: the shared ENDPOINT selector was
 * silent; log why it returns 0 so a single physical run can distinguish the
 * five live preconditions. Reporting only: no control flow changes. */
extern int printk(const char *fmt, ...);

static struct a6400_uvc_ptp_session *owner;

static unsigned int shared_endpoint(unsigned int count,unsigned int array)
{
    void *gadget;
    unsigned int endpoint;
    unsigned int speed;
    if (!owner || !owner->gc) {
        printk("[a6400_sel] shared reject owner/gc NULL\n");
        return 0;
    }
    gadget=*(void **)owner->gc;
    if (!gadget) {
        printk("[a6400_sel] shared reject gadget=NULL\n");
        return 0;
    }
    speed=*(unsigned int *)((unsigned char *)gadget+0x20);
    if (speed!=3) {
        printk("[a6400_sel] shared reject speed=%u (need 3)\n",speed);
        return 0;
    }
    endpoint=a6400_uvc_ptp_select_endpoint((unsigned char *)gadget-0x150,count,(void *const *)array);
    printk("[a6400_sel] shared selector=%08x count=%u\n",endpoint,count&0xffu);
#ifdef A6400_UVC_START_PROBE_ONLY
    (void)endpoint;
    return 0; /* enumeration candidate: never enter native video START */
#else
    return endpoint;
#endif
}

static int hold(struct a6400_uvc_ptp_session *s,int error)
{ s->phase=A6400_SESSION_HELD;s->last_error=error;return error; }

static int original_pc_remote(void *root)
{
    const struct a6400_candidate_device *d=root;
    const struct a6400_candidate_config *c;
    const struct a6400_candidate_interface *i;
    const struct a6400_candidate_alternate *a;
    const struct a6400_candidate_endpoint *e;
    const unsigned char *metadata;
    if (!root || d->config_count!=1 || !d->configs ||
        d->device_fields[2] || d->device_fields[3] || d->device_fields[4]) return 0;
    metadata=(const unsigned char *)root+48;
    if (metadata[0]!=0x4c || metadata[1]!=5 || metadata[2]!=0xaa || metadata[3]!=0x0c) return 0;
    c=d->configs;
    if (c->index || c->value!=1 || c->interface_count!=1 || !c->interfaces) return 0;
    i=c->interfaces;
    if (i->number || i->alternate_count!=1 || !i->alternates) return 0;
    a=i->alternates;
    if (a->alternate || a->klass!=6 || a->subclass!=1 || a->protocol!=1 ||
        a->endpoint_count!=3 || !a->endpoints) return 0;
    e=a->endpoints;
    return e[0].address==0x81 && e[0].attributes==2 && e[0].max_packet==512 &&
        e[1].address==2 && e[1].attributes==2 && e[1].max_packet==512 &&
        e[2].address==0x83 && e[2].attributes==3 && e[2].max_packet==32 && e[2].interval==7;
}

int a6400_uvc_ptp_session_releasable(const struct a6400_uvc_ptp_session *s)
{
    return s && s->phase==A6400_SESSION_IDLE && !s->stopped && !s->prepared && !s->registered &&
        !s->hook_attempted && !s->bridge.magic && !s->bridge.in_flight &&
        a6400_descriptor_source_releasable(&s->lease);
}

int a6400_uvc_ptp_session_end(struct a6400_uvc_ptp_session *s)
{
    unsigned int i;
    int ret;
    if (!s) return -22;
    if (a6400_uvc_ptp_session_releasable(s)) return 0;
    if (s!=owner || !s->gc) return -22;
    /* The whole end path is one ordered sequence: original clear-configuration
     * and the reference STOP first, then the UDC stop, then hook/record/table
     * release, then an explicit reconnect. A failure still holds the session
     * (no release, no unload receipt) but the sequence is ordered so a late
     * failure cannot leave the host with a bound EP0 hook over a freed table. */
    ret=a6400_uvc_soft_disconnect(s,&s->teardown);
    if (ret) return hold(s,ret);
    owner=0;
    for (i=0;i<sizeof(*s);++i) ((unsigned char *)s)[i]=0;
    return 0;
}

int a6400_uvc_ptp_session_begin(struct a6400_uvc_ptp_session *s,void *gc,
                               struct uvc_reference_descriptor *r,
                               const struct a6400_descriptor_arg *arg,
                               const struct a6400_uvc_ptp_ops *ops)
{
    int ret,cleanup;
    if (!s || !gc || !r || !arg || !ops || !ops->quiesce || !ops->resume ||
        !ops->bind_ep0 || !ops->unbind_ep0 || !ops->reg || !ops->unreg ||
        !ops->descriptor.save || !ops->descriptor.free) return -22;
    if (owner || !a6400_uvc_ptp_session_releasable(s)) return -16;
    if (!r->interfaces || r->interface_count!=2 || r->config!=1 ||
        r->interfaces[0]!=1 || r->interfaces[1]!=2 ||
        (r->primary_interface!=1 && r->primary_interface!=2) ||
        !r->callback[0] || !r->callback[1] || !r->callback[7] ||
        !original_pc_remote(*(void **)((unsigned char *)gc+0x6c))) return -22;
    if (!arg->table || arg->extra || arg->extra_len || arg->is_dual ||
        arg->max_speed!=1 || arg->pad ||
        a6400_uvc_ptp_validate_native_copy(arg->table,arg->table)) return -22;
    s->gc=gc;s->ops=*ops;s->original_root=*(void **)((unsigned char *)gc+0x6c);
    s->original_flags=*(unsigned int *)((unsigned char *)gc+0x68);
    s->original_mode=((unsigned char *)gc)[0x84];s->original_speed=((unsigned char *)gc)[0x85];
    s->phase=A6400_SESSION_PREPARING;owner=s;
    ret=s->ops.quiesce(gc);
    if (ret) return hold(s,ret);
    s->stopped=1;
    ret=a6400_uvc_bridge_prepare(&s->bridge,r);
    if (ret) goto rollback;
    s->prepared=1;s->bridge.bulk_endpoint=shared_endpoint;
    ret=a6400_uvc_bridge_register(&s->bridge,s->ops.reg,s->ops.unreg);
    if (ret) goto rollback;
    s->registered=1;
    ret=a6400_descriptor_install(&s->lease,gc,arg,&s->ops.descriptor);
    if (ret) goto rollback;
    s->hook_attempted=1;
    ret=s->ops.bind_ep0(gc,arg->table);
    if (ret) goto rollback;
    s->stopped=0;
    ret=s->ops.resume(gc);
    if (ret) goto rollback;
    s->phase=A6400_SESSION_ACTIVE;s->last_error=0;return 0;
rollback:
    cleanup=a6400_uvc_ptp_session_end(s);
    return cleanup ? cleanup:ret;
}
