#include "uvc_ptp_entry_hook.h"
#include "uvc_ptp_route_lease.h"
#include "uvc_module_self_ref.h"
#include "uvc_ptp_code_sync.h"

extern long a6400_uvc_native_ioctl_tail(void *,unsigned int,unsigned long);

static struct a6400_uvc_ioctl_guard entry_guard = {
    .gate = {0},
    .original = a6400_uvc_native_ioctl_tail,
    .fault = 0
};

static volatile unsigned int *const entry_slot = (volatile unsigned int *)0x602b8844u;
static const unsigned int original_instruction = 0xe1a0c00du; /* mov ip, sp */
static unsigned int hook_branch = 0;

static const struct a6400_verified_stops *active_scope;
static int barrier_held;
static int pin_held;
#ifdef A6400_UVC_TRACE_CONTROL
extern int printk(const char *,...);
static unsigned int trace_calls;
#endif

long a6400_uvc_native_entry_wrapper(void *file,unsigned int command,unsigned long arg)
{
    long result;
#ifdef A6400_UVC_TRACE_CONTROL
    unsigned int before=entry_guard.gate.word;
#endif
    result=a6400_uvc_guard_dispatch(&entry_guard,file,command,arg);
#ifdef A6400_UVC_TRACE_CONTROL
    if(__sync_fetch_and_add(&trace_calls,1)<64)
        printk("[a6400_native_ioctl] cmd=%08x ret=%ld gate_before=%08x gate_after=%08x\n",
               command,result,before,entry_guard.gate.word);
#endif
    return result;
}

struct a6400_uvc_ioctl_guard *a6400_uvc_entry_guard(void)
{
    return &entry_guard;
}

static int prepare_branch(void)
{
    long delta = (long)a6400_uvc_native_entry_wrapper - (long)(0x602b8844u + 8);
    if ((delta & 3) || delta < -(1l << 25) || delta > ((1l << 25) - 4)) return -34;
    hook_branch = 0xea000000u | (((unsigned int)(delta >> 2)) & 0x00ffffffu);
    return 0;
}

static int scope_valid(void)
{
    return active_scope && active_scope->owner == 149 &&
           active_scope->count > 0 && active_scope->count <= 512 &&
           active_scope->tids != 0;
}

static int entry_pin(void *ctx)
{
    int ret;
    (void)ctx;
    if (pin_held || !scope_valid()) return -16;
    ret = a6400_module_self_get();
    if (!ret) pin_held = 1;
    return ret;
}

static void entry_unpin(void *ctx)
{
    (void)ctx;
    pin_held = 0;
    a6400_module_self_put();
}

static int entry_enter(void *ctx)
{
    (void)ctx;
    if (!scope_valid() || barrier_held || !pin_held) return -16;
    barrier_held = 1;
    return 0;
}

static int entry_leave(void *ctx)
{
    int ret;
    (void)ctx;
    if (!scope_valid() || !barrier_held) return -16;
    ret = a6400_uvc_sync_code(0x602b8844u, 0x602b8848u);
    if (ret) return ret;
    barrier_held = 0;
    return 0;
}

static int entry_retirable(void *ctx)
{
    (void)ctx;
    if (!scope_valid() || !barrier_held || !pin_held) return -16;
    if (entry_guard.fault) return entry_guard.fault;
    if (entry_guard.gate.word != 0) return -16;
    return 0;
}

static int entry_recover(void *ctx)
{
    (void)ctx;
    if (!scope_valid() || !pin_held) return -16;
    barrier_held = 1;
    return 0;
}

static struct a6400_route_lease entry_lease = {
    .slot = (volatile unsigned int *)0x602b8844u,
    .original = 0xe1a0c00du,
    .wrapper = 0,
    .phase = A6400_ROUTE_IDLE,
    .pinned = 0,
    .published = 0,
    .barrier_held = 0,
    .context = 0,
    .ops = {
        .pin = entry_pin,
        .unpin = entry_unpin,
        .barrier_enter = entry_enter,
        .barrier_leave = entry_leave,
        .retirable = entry_retirable,
        .barrier_recover = entry_recover
    }
};

unsigned int a6400_uvc_entry_hook_phase(void)
{
    return entry_lease.phase;
}

int a6400_uvc_entry_hook_publish(const struct a6400_verified_stops *scope)
{
    int ret;
    if (active_scope) return -16;
    if (!scope) return -22;
    active_scope = scope;
    if (!scope_valid()) { ret = -22; goto out; }
    if (*entry_slot != original_instruction) { ret = -116; goto out; }
    ret = prepare_branch();
    if (ret) goto out;
    entry_lease.wrapper = hook_branch;
    ret = a6400_route_publish(&entry_lease);
out:
    active_scope = 0;
    return ret;
}

int a6400_uvc_entry_hook_retire(const struct a6400_verified_stops *scope)
{
    int ret;
    if (active_scope) return -16;
    if (!scope) return -22;
    active_scope = scope;
    if (!scope_valid()) { ret = -22; goto out; }
    ret = a6400_route_retire(&entry_lease);
out:
    active_scope = 0;
    return ret;
}

int a6400_uvc_entry_hook_recover(const struct a6400_verified_stops *scope)
{
    int ret;
    if (active_scope) return -16;
    if (!scope) return -22;
    active_scope = scope;
    if (!scope_valid()) { ret = -22; goto out; }
    ret = a6400_route_recover(&entry_lease);
out:
    active_scope = 0;
    return ret;
}
