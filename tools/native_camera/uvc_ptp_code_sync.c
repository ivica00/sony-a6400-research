#include "uvc_ptp_code_sync.h"
extern unsigned int cpu_cache[];
extern const unsigned int *cpu_online_mask;
extern unsigned int nr_cpu_ids;
extern int on_each_cpu(void (*)(void *),void *,int);
extern int printk(const char *,...);
struct sync_context {volatile unsigned int seen;volatile int error;};

static void synchronize_cpu(void *opaque)
{
    struct sync_context *context=opaque;
    unsigned int sp,cpu;
    __asm__ volatile("mov %0, sp":"=r"(sp));
    cpu=*(volatile unsigned int *)((sp&~0x1fffu)+0x14);
    __asm__ volatile("dsb sy\nisb sy":::"memory");
    if(cpu>=32)__sync_val_compare_and_swap(&context->error,0,-22);
    else __sync_or_and_fetch(&context->seen,1u<<cpu);
}

int a6400_uvc_sync_code(unsigned long start,unsigned long end)
{
    struct sync_context context={0,0};
    unsigned int expected,allowed,count=nr_cpu_ids;
    const volatile unsigned int *function=(const volatile unsigned int *)0x60119de4u;
    int result;
    if(!start || end<=start || end-start>4096 || !count || count>32 || !cpu_online_mask)return -22;
    if(cpu_cache[4]!=0x60119de4u || function[0]!=0xee103f30u || function[1]!=0xe1a03823u)return -116;
    allowed=count==32 ? 0xffffffffu:(1u<<count)-1;
    expected=*cpu_online_mask;
    if(!expected || (expected&~allowed))return -22;
    /* Native helper cleans D-cache lines to PoU before I-cache invalidation,
     * branch-predictor invalidation, DSB and local ISB. */
    ((void (*)(unsigned long,unsigned long))cpu_cache[4])(start,end);
    result=on_each_cpu(synchronize_cpu,&context,1);
    if(!result)result=context.error;
    if(!result && (context.seen!=expected || *cpu_online_mask!=expected))result=-16;
    printk("[a6400_code_sync] seen=%x expected=%x result=%d\n",context.seen,expected,result);
    return result;
}
