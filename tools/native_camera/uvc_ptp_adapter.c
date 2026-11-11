#include "uvc_ptp_adapter.h"
_Static_assert(sizeof(void *)==4, "ARM32 endpoint ABI");

/* E0354 Run B pre-flight instrumentation: make the live START selector audible.
 * The selector fails closed and, before this change, silently returned 0 for any
 * of the five live preconditions, which the bridge turns into "skip reference
 * START". These printks only report values; no control flow, return value or
 * memory access is changed. printk is the same kernel symbol the rest of the
 * module already imports (`uvc_composite_shim.c:17`). */
extern int printk(const char *fmt, ...);

int a6400_uvc_ptp_translate_setup(const unsigned char *wire,
                                unsigned int wire_interface,
                                unsigned char *native)
{
    unsigned int i;
    if (!wire || !native || (wire_interface!=1 && wire_interface!=2)) return -22;
    if ((unsigned int)wire-(unsigned int)native<8u ||
        (unsigned int)native-(unsigned int)wire<8u) return -22;
    /* Only class/interface requests belong to these UVC shadows. Preserve
     * wIndex high byte (entity ID); it is not part of the interface number. */
    if ((wire[0]&0x7f)!=0x21 || wire[4]!=wire_interface) return -22;
    for (i=0; i<8; ++i) native[i]=wire[i];
    native[4]=(unsigned char)(wire_interface-1);
    return 0;
}

unsigned int a6400_uvc_ptp_select_endpoint(void *dwc, unsigned int packed_count,
                                        void *const *list)
{
    unsigned int count=packed_count&0xffu, i;
    void *raw, *found=(void *)0;
    const unsigned char *desc;
    unsigned int flags;
    if (!dwc || !list || !count || count>16) {
        printk("[a6400_sel] reject args dwc=%p list=%p count=%u\n",dwc,list,count);
        return 0;
    }
    /* Original dwc3_wIndex_to_dep: ((ep&15)*2 + direction + 0x34)*4. */
    raw=*(void **)((unsigned char *)dwc+0xf4);
    if (!raw) {
        printk("[a6400_sel] reject dep=NULL (dwc=%p)\n",dwc);
        return 0;
    }
    flags=*(unsigned int *)((unsigned char *)raw+0x4c);
    if (!(flags&1u)) {
        printk("[a6400_sel] reject dep-disabled dep=%p flags=%08x\n",raw,flags);
        return 0;
    }
    desc=*(const unsigned char **)((unsigned char *)raw+0x1c);
    if (!desc) {
        printk("[a6400_sel] reject desc=NULL dep=%p\n",raw);
        return 0;
    }
    if (desc[0]!=7 || desc[1]!=5 || desc[2]!=0x84 ||
        (desc[3]&3)!=2 || desc[4]!=0 || desc[5]!=2) {
        printk("[a6400_sel] reject desc bytes=%02x %02x %02x %02x %02x %02x\n",
               desc[0],desc[1],desc[2],desc[3],desc[4],desc[5]);
        return 0;
    }
    for (i=0; i<count; ++i) {
        void *wrapper=list[i];
        if (!wrapper || *(void **)((unsigned char *)wrapper+0x24)!=raw) continue;
        if (found) {
            printk("[a6400_sel] reject duplicate-owner wrapper=%p first=%p dep=%p\n",
                   wrapper,found,raw);
            return 0; /* ambiguous/duplicate ownership */
        }
        found=wrapper;
    }
    if (!found) {
        printk("[a6400_sel] reject no-owner dep=%p in %u entries\n",raw,count);
        return 0;
    }
    printk("[a6400_sel] match wrapper=%p raw=%p ep=0x84 flags=%08x count=%u\n",
           found,raw,flags,count);
    return (unsigned int)found;
}
