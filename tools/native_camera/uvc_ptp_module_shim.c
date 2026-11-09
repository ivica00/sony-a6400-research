/* Enumeration-only adapter. Native routing publication/quiescence remains a
 * commissioning prerequisite. A separate local gate serializes MOD entry while
 * native exclusion remains reserved for the complete session lifetime. */
#include "uvc_ptp_native_backend.h"
#include "uvc_module_self_ref.h"
#include "uvc_ptp_ioctl_guard.h"
#include "uvc_ptp_stop_attest.h"
#include "uvc_ptp_route_dryrun.h"
#include "uvc_ptp_entry_hook.h"
extern long usbg_video_core_ioctl(void *,unsigned int,unsigned long);
extern int usbg_video_core_release(void *,void *);
extern long a6400_uvc_legacy_dma_ioctl(void *,unsigned int,unsigned long);
extern int a6400_usb_sync_free_phys_buffer(int,unsigned short);
extern int printk(const char *,...);
extern unsigned long __copy_to_user(void *,const void *,unsigned long);

static struct a6400_uvc_ptp_candidate source;
static struct a6400_uvc_ptp_session session;
static struct a6400_uvc_ptp_native_backend backend;
static struct a6400_uvc_ptp_ops ops;
static struct uvc_reference_descriptor *reference;
static const unsigned char wire_interfaces[2]={1,2};
static const unsigned char *old_interfaces;
static unsigned char old_primary,old_alternate;
static unsigned int pinned;
static struct a6400_uvc_ioctl_guard native_guard = {
    .gate = {0},
    .original = (a6400_native_ioctl_fn)0x602b8844u,
    .fault = 0
};
static volatile unsigned int control_gate;
static unsigned int native_reserved;
long a6400_uvc_native_gadgetcore_ioctl(void *,unsigned int,unsigned long);

static int native_route_bound(void)
{
    return *(volatile unsigned int *)0x604e5098u==
        (unsigned int)a6400_uvc_native_gadgetcore_ioctl ||
        (a6400_uvc_entry_hook_phase()==A6400_ROUTE_PUBLISHED &&
         *(volatile unsigned int *)0x604e5098u==0x602b8844u);
}

static int dryrun_retirable(void)
{
    return control_gate && native_reserved && !native_guard.fault &&
        native_guard.gate.word==0x80000000u && !pinned && !backend.gc &&
        a6400_uvc_ptp_session_releasable(&session) ? 0:-16;
}

static int entry_hook_cycle_consumer(void *ctx,const struct a6400_verified_stops *scope)
{
    int ret;
    (void)ctx;
    if(*(volatile unsigned int *)0x604e5098u!=0x602b8844u)return -116;
    ret=a6400_uvc_entry_hook_publish(scope);
    if(ret)return ret;
    ret=a6400_uvc_entry_hook_retire(scope);
    if(!ret && *(volatile unsigned int *)0x604e5098u!=0x602b8844u)ret=-116;
    return ret;
}

static int entry_hook_publish_consumer(void *ctx,const struct a6400_verified_stops *scope)
{
    (void)ctx;
    if(*(volatile unsigned int *)0x604e5098u!=0x602b8844u)return -116;
    return a6400_uvc_entry_hook_publish(scope);
}

static int entry_hook_retire_consumer(void *ctx,const struct a6400_verified_stops *scope)
{
    int ret;
    (void)ctx;
    ret=a6400_uvc_entry_hook_retire(scope);
    if(!ret && *(volatile unsigned int *)0x604e5098u!=0x602b8844u)ret=-116;
    return ret;
}

long a6400_uvc_native_gadgetcore_ioctl(void *file,unsigned int command,unsigned long arg)
{
    return a6400_uvc_guard_dispatch(&native_guard,file,command,arg);
}

static int control_enter(void)
{
    int ret;
    if(!__sync_bool_compare_and_swap(&control_gate,0,1))return -16;
    if(native_reserved) {
        ret=native_guard.fault;
        if(!ret && native_guard.gate.word!=0x80000000u)ret=-116;
    } else {
        ret=a6400_uvc_guard_claim(&native_guard);
        if(!ret)native_reserved=1;
    }
    if(ret){__sync_synchronize();control_gate=0;}
    return ret;
}

static long control_leave(long result)
{
    int ret;
    /* ACTIVE and HELD sessions must continue excluding native reconfiguration
     * between ioctls. Release only after every session/backend owner retired. */
    if(native_reserved && !pinned && !backend.gc &&
       a6400_uvc_ptp_session_releasable(&session)) {
        ret=a6400_uvc_guard_release(&native_guard);
        if(ret)result=ret;
        else native_reserved=0;
    }
    __sync_synchronize();control_gate=0;
    return result;
}

static int cleanup(void)
{
    int ret;
    if(!pinned) return 0;
    ret=a6400_uvc_ptp_session_end(&session);if(ret)return ret;
    if(backend.gc) { ret=a6400_uvc_ptp_native_backend_retire(&backend);if(ret)return ret; }
    if(reference) {
        reference->interfaces=old_interfaces;
        reference->primary_interface=old_primary;
        reference->alternate=old_alternate;
    }
    reference=0;pinned=0;
    a6400_module_self_put();
    return 0;
}

static int capture_identity(void *gc)
{
    unsigned char device[18],strings[3][66],request[8]={0x80,6,0,1,0,0,18,0};
    const unsigned char *table;
    const struct a6400_candidate_language *language;
    unsigned int i;
    int ret;
    if(!gc || !*(void **)gc || !*(void **)((unsigned char *)gc+4)) return -22;
    table=*(const unsigned char **)((unsigned char *)gc+0x6c);
    if(!table || table[2] || table[3] || table[4] ||
        table[48]!=0x4c || table[49]!=5 || table[50]!=0xaa || table[51]!=0x0c || table[58]!=1) return -22;
    language=*(const struct a6400_candidate_language *const *)(table+60);
    if(!language || language->language!=0x409 || language->string_count!=3 || !language->strings) return -22;
    for(i=0;i<3;++i)
        if(language->strings[i].index!=i+1 || !language->strings[i].size ||
            language->strings[i].size>64 || (language->strings[i].size&1) || !language->strings[i].data) return -22;
    ret=((int (*)(void *,const void *,void *))0x602bb988u)(gc,request,device);
    if(ret!=18) return -22;
    for(i=0;i<3;++i) {
        request[2]=(unsigned char)(i+1);request[3]=3;request[4]=9;request[5]=4;request[6]=66;
        ret=((int (*)(void *,const void *,void *))0x602bc0ccu)(gc,request,strings[i]);
        if(ret!=(int)language->strings[i].size+2) return -22;
    }
    a6400_uvc_ptp_candidate_init(&source);
    return a6400_uvc_ptp_candidate_identity(&source,device,strings[0],strings[1],strings[2]);
}

int a6400_uvc_shared_register_hook(struct uvc_reference_descriptor *r)
{
    struct a6400_descriptor_arg arg;
    void *gc;
    int ret,restored;
    if(!control_gate || !native_reserved || native_guard.gate.word!=0x80000000u ||
       !native_route_bound() || !r || pinned || reference) return -16;
    ret=a6400_uvc_ptp_native_kernel_preflight();if(ret)return ret;
    ret=a6400_module_self_get();if(ret)return ret;
    pinned=1;
    gc=*(void **)0x6051b17cu;
    ret=capture_identity(gc);if(ret)goto failure;
    ret=a6400_uvc_ptp_native_backend_init(&backend,&session,&source,&ops);if(ret)goto failure;
    reference=r;old_interfaces=r->interfaces;old_primary=r->primary_interface;old_alternate=r->alternate;
    r->interfaces=wire_interfaces;r->primary_interface=1;
    arg.table=&source;arg.extra=0;arg.extra_len=0;arg.is_dual=0;arg.max_speed=1;arg.pad=0;
    ret=a6400_uvc_ptp_session_begin(&session,gc,r,&arg,&ops);
    if(!ret) {
        printk("[a6400_shared] enumeration session active; video START/submission disabled\n");
        return 0;
    }
failure:
    restored=cleanup();
    if(restored) printk("[a6400_shared] cleanup held=%d, module remains pinned\n",restored);
    return restored ? restored:ret;
}

int a6400_uvc_shared_unregister_hook(struct uvc_reference_descriptor *r)
{
    (void)r;
    if(!control_gate || !native_reserved || native_guard.gate.word!=0x80000000u) return -16;
    return cleanup();
}

long a6400_uvc_shared_ioctl(void *file,unsigned int command,unsigned long arg)
{
    long ret;
    int entered=control_enter();if(entered)return entered;
    if(command==A6400_UVC_ROUTE_DRYRUN) {
        ret=dryrun_retirable();
        if(!ret)ret=a6400_uvc_with_stops(arg,a6400_uvc_route_dryrun,(void *)dryrun_retirable);
    } else if(command==A6400_UVC_ENTRY_HOOK_CYCLE) {
        ret=dryrun_retirable();
        if(!ret)ret=a6400_uvc_with_stops(arg,entry_hook_cycle_consumer,(void *)dryrun_retirable);
    } else if(command==A6400_UVC_ENTRY_HOOK_PUBLISH) {
        ret=dryrun_retirable();
        if(!ret)ret=a6400_uvc_with_stops(arg,entry_hook_publish_consumer,(void *)dryrun_retirable);
    } else if(command==A6400_UVC_ENTRY_HOOK_RETIRE) {
        ret=dryrun_retirable();
        if(!ret)ret=a6400_uvc_with_stops(arg,entry_hook_retire_consumer,(void *)dryrun_retirable);
    } else if(command==A6400_UVC_ATTEST_STOPS) {
        ret=(pinned || backend.gc || !a6400_uvc_ptp_session_releasable(&session)) ?
            -16:a6400_uvc_attest_stops(arg);
    } else if(command==A6400_UVC_QUERY_IDENTITY) {
        void *gc=*(void **)0x6051b17cu;
        const unsigned char *table;
        unsigned short ids[2]={0,0};
        if(!gc || !*(void **)gc || !*(void **)((unsigned char *)gc+4)) ret=-22;
        else {
            table=*(const unsigned char **)((unsigned char *)gc+0x6c);
            if(!table) ret=-22;
            else {
                ids[0]=(unsigned short)(table[48] | ((unsigned short)table[49]<<8));
                ids[1]=(unsigned short)(table[50] | ((unsigned short)table[51]<<8));
                ret=(!arg || __copy_to_user((void *)arg,ids,sizeof(ids))) ? -14:0;
            }
        }
    } else if(command==A6400_UVC_QUERY_USB_STATE) {
        unsigned int state[4];
        ret=a6400_uvc_ptp_native_runtime(state);
        if(!ret)ret=(!arg || __copy_to_user((void *)arg,state,sizeof(state))) ? -14:0;
    } else if(command==0x8010f022u) {
        int status[4]={(int)session.phase,(int)pinned,(int)backend.hook_mask,
                       backend.last_error ? backend.last_error:session.last_error};
        ret=(!arg || __copy_to_user((void *)arg,status,sizeof(status))) ? -14:0;
    } else if(command==0xe001u) {
        ret=cleanup();
        if(!ret)ret=a6400_uvc_legacy_dma_ioctl(file,command,arg);
    } else if(pinned && session.phase==A6400_SESSION_HELD) ret=-16;
    else if(command==0x4038e000u && !native_route_bound())ret=-19;
    else if(command==0x4038e000u || command==0x8010f020u)
        ret=a6400_uvc_legacy_dma_ioctl(file,command,arg);
    else ret=-95; /* enumeration/control candidate: no buffer/stream ioctls */
    return control_leave(ret);
}

int a6400_uvc_shared_release(void *inode,void *file)
{
    int ret;
    ret=control_enter();if(ret)return ret;
    ret=cleanup();
    /* Original release ignores free-buffer errors and frees probe data. Never
     * enter it while any native hook/reference may still consume that data. */
    if(!ret)ret=usbg_video_core_release(inode,file);
    return (int)control_leave(ret);
}

int a6400_uvc_shared_free_phys_buffer(int task,unsigned short handle)
{
    if(!a6400_uvc_ptp_session_releasable(&session) || pinned || backend.gc) return -16;
    return a6400_usb_sync_free_phys_buffer(task,handle);
}
