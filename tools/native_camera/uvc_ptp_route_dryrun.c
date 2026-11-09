#include "uvc_ptp_route_dryrun.h"
#include "uvc_ptp_route_lease.h"
#include "uvc_module_self_ref.h"
#include "uvc_ptp_code_sync.h"
static volatile unsigned int test_slot=0x13572468u;
static const struct a6400_verified_stops *active_scope;
static int barrier,pin_held;
static int (*can_retire)(void);

static int scope_valid(void)
{
    return active_scope && active_scope->owner==149 && active_scope->count &&
        active_scope->count<=512 && active_scope->tids && can_retire;
}
static int pin(void *ctx)
{
    int ret;(void)ctx;
    if(pin_held || !scope_valid())return -16;
    ret=a6400_module_self_get();if(!ret)pin_held=1;
    return ret;
}
static void unpin(void *ctx)
{
    (void)ctx;pin_held=0;a6400_module_self_put();
}
static int enter(void *ctx)
{
    (void)ctx;
    if(!scope_valid() || barrier || !pin_held)return -16;
    barrier=1;return 0;
}
static int leave(void *ctx)
{
    int ret;
    (void)ctx;if(!scope_valid() || !barrier)return -16;
    ret=a6400_uvc_sync_code((unsigned long)&test_slot,(unsigned long)&test_slot+4);
    if(ret)return ret;
    barrier=0;return 0;
}
static int retirable(void *ctx)
{
    (void)ctx;
    return scope_valid() && barrier && pin_held ? can_retire():-16;
}
static int recover(void *ctx)
{
    (void)ctx;if(!scope_valid() || !pin_held)return -16;
    barrier=1;return 0;
}
static struct a6400_route_lease lease={
    .slot=&test_slot,.original=0x13572468u,.wrapper=0x24681357u,
    .ops={pin,unpin,enter,leave,retirable,recover}
};

int a6400_uvc_route_dryrun(void *context,const struct a6400_verified_stops *scope)
{
    int ret;
    /* Caller is serialized by module control gate. The adapter's "barrier"
     * covers this private word only: never apply it to a native kernel slot. */
    if(active_scope)return -16;
    active_scope=scope;can_retire=(int (*)(void))context;
    if(!scope_valid()){ret=-22;goto done;}
    if(*(volatile unsigned int *)0x604e5098u!=0x602b8844u){ret=-116;goto done;}
    ret=can_retire();if(ret)goto done;
    if(lease.phase==A6400_ROUTE_HELD)ret=a6400_route_recover(&lease);
    else {
        if(lease.phase==A6400_ROUTE_IDLE) {
            ret=a6400_route_publish(&lease);if(ret)goto done;
        }
        ret=a6400_route_retire(&lease);
    }
    if(!ret && (test_slot!=lease.original || lease.pinned || pin_held || barrier || lease.published))ret=-116;
    if(!ret && *(volatile unsigned int *)0x604e5098u!=0x602b8844u)ret=-116;
done:
    active_scope=0;can_retire=0;
    return ret;
}
