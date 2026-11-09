#include "uvc_module_self_ref.h"
extern unsigned char __this_module[];
extern unsigned long __per_cpu_offset[];
extern unsigned int nr_cpu_ids;
extern void preempt_schedule(void);
extern void module_put(void *);
_Static_assert(sizeof(void *)==4 && sizeof(unsigned long)==4,"Sony ARM32 module ABI");

/* This is MOD code implementing the target's public inline module-get contract.
 * No call to the GPL-only __symbol_get entry and no license metadata change. */
int a6400_module_self_get(void)
{
    unsigned int sp,cpu,count,ref,old;
    volatile unsigned int *ti,*counter;
    int result=-16;
    if(*(volatile unsigned int *)0x60163100u!=0xe5933138u ||
       *(volatile unsigned int *)0x60162a2cu!=0xe5903138u ||
       *(volatile unsigned int *)0x60162a34u!=0xe2833004u)return -116;
    __asm__ volatile("mov %0, sp":"=r"(sp));
    ti=(volatile unsigned int *)(sp&~0x1fffu);
    if(ti[1]==0xffffffffu)return -75;
    ++ti[1];__asm__ volatile("":::"memory");
    /* LIVE only is deliberately stricter than a generic module-get helper. */
    if(*(volatile unsigned int *)__this_module==0) {
        cpu=ti[5];count=nr_cpu_ids;
        ref=*(volatile unsigned int *)(__this_module+0x138);
        if(count && count<=32 && cpu<count && ref && !(ref&3u)) {
            counter=(volatile unsigned int *)(ref+(unsigned int)__per_cpu_offset[cpu]);
            old=*counter;
            if(old!=0xffffffffu){*counter=old+1;result=0;}
            else result=-75;
        } else result=-22;
    }
    __asm__ volatile("":::"memory");--ti[1];
    if(ti[0]&2u)preempt_schedule();
    return result;
}
void a6400_module_self_put(void)
{
    module_put(__this_module);
}
