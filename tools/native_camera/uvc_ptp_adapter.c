#include "uvc_ptp_adapter.h"
_Static_assert(sizeof(void *)==4, "ARM32 endpoint ABI");

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
    if (!dwc || !list || !count || count>16) return 0;
    /* Original dwc3_wIndex_to_dep: ((ep&15)*2 + direction + 0x34)*4. */
    raw=*(void **)((unsigned char *)dwc+0xe4);
    if (!raw || !(*(unsigned int *)((unsigned char *)raw+0x4c)&1u)) return 0;
    desc=*(const unsigned char **)((unsigned char *)raw+0x1c);
    if (!desc || desc[0]!=7 || desc[1]!=5 || desc[2]!=0x82 ||
        (desc[3]&3)!=2 || desc[4]!=0 || desc[5]!=2) return 0;
    for (i=0; i<count; ++i) {
        void *wrapper=list[i];
        if (!wrapper || *(void **)((unsigned char *)wrapper+0x24)!=raw) continue;
        if (found) return 0; /* ambiguous/duplicate ownership */
        found=wrapper;
    }
    return (unsigned int)found;
}
