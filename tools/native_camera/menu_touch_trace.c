/* Temporary finite logger at the ORIGINAL release consumer. No selection. */
#include <stdint.h>
#define MAGIC 0x4d544c47u
#define SYSTEM 0x956f0u
#define STATE 0x7143920u
#define CAPACITY 24u
struct event { uint32_t sequence,tid,system,before_framebuffer_xy,mouse_button,framebuffer_xy,raw_xy,buttons,time_lo,time_hi,native_result,transport_type; };
struct trace { uint32_t magic,version,enabled,count,inflight,capacity,error,expected_system;struct event events[CAPACITY]; };
extern uint32_t mt_original_release(void *,void *) __attribute__((visibility("hidden")));
static uint32_t tid(void) {
    register uint32_t r0 __asm__("r0")=0;
    register uint32_t r7 __asm__("r7")=224;
    __asm__ volatile("svc 0" : "+r"(r0) : "r"(r7) : "memory","cc");return r0;
}
uint32_t mt_trace_release(void *system,void *message) {
    volatile struct trace *s=(volatile struct trace *)STATE;
    if(s->magic!=MAGIC || s->version!=1)return mt_original_release(system,message);
    __sync_fetch_and_add(&s->inflight,1);
    unsigned mouse=0,button=0,valid=0;uint32_t lo=0,hi=0,tag=0,before=0;
    if(s->enabled && (uint32_t)system==SYSTEM && message) {
        const uint8_t *p=(const uint8_t *)message;
        mouse=p[0x14];button=p[0x15];lo=*(const uint32_t *)(p+8);hi=*(const uint32_t *)(p+12);tag=*(const uint32_t *)(p+16);
        valid=mouse<4;
        if(valid)before=*(const uint32_t *)((const uint8_t *)system+mouse*20+0x4a8);
        if(!valid){s->error=1;s->enabled=0;}
    }
    uint32_t result=mt_original_release(system,message);
    if(valid && s->enabled) {
        unsigned i=__sync_fetch_and_add(&s->count,1);
        if(i<CAPACITY) {
            const uint8_t *p=(const uint8_t *)system+mouse*20;
            volatile struct event *e=&s->events[i];
            e->tid=tid();e->system=(uint32_t)system;e->before_framebuffer_xy=before;e->mouse_button=mouse|(button<<8);
            e->framebuffer_xy=*(const uint32_t *)(p+0x4a8);e->raw_xy=*(const uint32_t *)(p+0x4ac);e->buttons=*(const uint32_t *)(p+0x4b0);
            e->time_lo=lo;e->time_hi=hi;e->native_result=result;e->transport_type=tag;
            __sync_synchronize();e->sequence=i+1;
        }
        if(i+1>=CAPACITY)s->enabled=0;
    }
    __sync_fetch_and_sub(&s->inflight,1);return result;
}
