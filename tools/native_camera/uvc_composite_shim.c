/* Composite bridge shim for a6400 UVC module.
 * Bridges:
 * 1. Device node table: maps entry 55 (usb/video) to major 248, minor 33.
 * 2. Gadgetcore descriptor: bridges 2-interface reference descriptor to
 *    dual 1-interface shadow descriptors with proactive DMA quiescence.
 * 3. Atomic descriptor switcher: commits UVC 720p30 descriptors on register,
 *    and restores original Mass Storage descriptors on unregister.
 */

#include "uvc_callback_bridge.h"
#include "zve10_uvc_tree.h"
#include "test_pattern_720p.h"

extern int printk(const char *fmt, ...);
extern void *arch_phys_to_noncache(unsigned int phys);
extern void *memcpy(void *dest, const void *src, unsigned int n);
extern int osal_snd_msg(unsigned int queue, void *message);
extern int osal_rcv_msg_tmo(unsigned int queue, void **message, int timeout);
static unsigned int g_dmm_reply_queue;

/* Native DMM diagnostic wrappers preserve original transport/results. These
 * imports are redirected only in the native-buffer-allocation build. */
int a6400_uvc_dmm_snd_log(unsigned int queue, void *message)
{
    unsigned int *p=message;
    if ((queue&0xffffu)==0x3cu && p) {
        g_dmm_reply_queue=p[-1]; /* Original helper's OSAL reply-id header. */
        printk("[a6400_uvc] DMM send q=%08x words=%08x %08x %08x %08x %08x %08x\n",
               queue,p[0],p[1],p[2],p[3],p[4],p[5]);
    }
    return osal_snd_msg(queue,message);
}

int a6400_uvc_dmm_rcv_log(unsigned int queue, void **message, int timeout)
{
    int result=osal_rcv_msg_tmo(queue,message,timeout);
    if (queue==g_dmm_reply_queue)
        printk("[a6400_uvc] DMM receive q=%08x result=%d\n",queue,result);
    if (queue==g_dmm_reply_queue && result==0 && message && *message) {
        unsigned int *p=*message;
        printk("[a6400_uvc] DMM reply words=%08x %08x %08x %08x %08x %08x\n",
               p[0],p[1],p[2],p[3],p[4],p[5]);
    }
    return result;
}

/* 1. Device Node Table */
struct a6400_udif_node {
    const char *name;
    unsigned int kind_major;
    unsigned int minor_count;
};

_Static_assert(sizeof(void *) == 4, "ARM32 ABI");
_Static_assert(sizeof(struct a6400_udif_node) == 12, "verified devno stride");

struct a6400_udif_node a6400_uvc_devnodes[56] = {
    [55] = { "usb/video", 248u << 16, (1u << 16) | 33u }
};

/* 2. Kernel Gadgetcore Hooks */
extern int usb_gadgetcore_register_driver(struct uvc_old_descriptor *);
extern int usb_gadgetcore_unregister_driver(struct uvc_old_descriptor *);

static struct uvc_bridge g_uvc_bridge;
static uvc_u32 g_reference_start;

static void a6400_uvc_reference_start(struct uvc_reference_descriptor *r,
                                    uvc_u32 speed, uvc_u32 count, uvc_u32 array)
{
    printk("[a6400_uvc] reference START enter speed=%u count=%u array=%08x\n",speed,count,array);
    ((void (*)(struct uvc_reference_descriptor *,uvc_u32,uvc_u32,uvc_u32))g_reference_start)
        (r,speed,count,array);
    printk("[a6400_uvc] reference START returned\n");
}

static inline unsigned int *a6400_gadgetcore_flags(void)
{
    void **p_gc = (void **)0x6051b17cu;
    if (!p_gc || !*p_gc) return (void *)0;
    return (unsigned int *)((char *)*p_gc + 0x68);
}

static inline unsigned long a6400_get_fs(void)
{
    unsigned long sp;
    __asm__ __volatile__("mov %0, sp" : "=r"(sp));
    return *(unsigned long *)((sp & ~0x1ffful) + 8);
}

static inline void a6400_set_fs(unsigned long val)
{
    unsigned long sp;
    __asm__ __volatile__("mov %0, sp" : "=r"(sp));
    *(unsigned long *)((sp & ~0x1ffful) + 8) = val;
}

/* 3. UVC Descriptor Bundle */
struct a6400_uvc_bundle {
    unsigned char tbl_88[88];
    unsigned char fs_cfg[24];
    unsigned char hs_cfg[24];
    unsigned char ss_cfg[24];
    unsigned char ntsc_iface[96];
    unsigned char sub_1cd90[20];
    unsigned char sub_1cda4[20];
    unsigned char sub_1cbac[20];
    unsigned char sub_1cbc0[40];
    unsigned char sub_1cdcc[20];
    unsigned char sub_1cde0[20];
    unsigned char sub_1cbe8[20];
    unsigned char sub_1cbfc[40];
    unsigned char sub_1ce08[20];
    unsigned char sub_1ce1c[20];
    unsigned char sub_1cc24[20];
    unsigned char sub_1cc38[40];
    unsigned char ep_fs[20];
    unsigned char ep_hs[20];
    unsigned char ep_ss[20];
    unsigned char ep_1cd54[20];
    unsigned char ep_1cd68[20];
    unsigned char ep_1cd7c[20];
    unsigned char ca90[80];
    unsigned char desc_12530[8];
    unsigned char desc_12537[61];
    unsigned char desc_12574[20];
    unsigned char desc_12588[4];
    unsigned char desc_1258c[12];
    unsigned char desc_12598[40];
    unsigned char desc_125c0[30];
    unsigned char desc_125de[4];
    unsigned char desc_125e2[4];
    unsigned char desc_12625[61];
    unsigned char strings_1e3d4[128];
    unsigned char str1[8];
    unsigned char str2[40];
    unsigned char str3[16];
};

static struct a6400_uvc_bundle g_bundle;
static void *g_saved_msc_desc_tbl = (void *)0;
static int g_uvc_registered = 0;

static int a6400_uvc_restore_descriptors(void);

#define COPY_NODE(name) memcpy(g_bundle.name, s_##name##_template, sizeof(g_bundle.name))

static void init_uvc_bundle(void)
{
    COPY_NODE(tbl_88);
    COPY_NODE(fs_cfg);
    COPY_NODE(hs_cfg);
    COPY_NODE(ss_cfg);
    COPY_NODE(ntsc_iface);
    COPY_NODE(sub_1cd90);
    COPY_NODE(sub_1cda4);
    COPY_NODE(sub_1cbac);
    COPY_NODE(sub_1cbc0);
    COPY_NODE(sub_1cdcc);
    COPY_NODE(sub_1cde0);
    COPY_NODE(sub_1cbe8);
    COPY_NODE(sub_1cbfc);
    COPY_NODE(sub_1ce08);
    COPY_NODE(sub_1ce1c);
    COPY_NODE(sub_1cc24);
    COPY_NODE(sub_1cc38);
    COPY_NODE(ep_fs);
    COPY_NODE(ep_hs);
    COPY_NODE(ep_ss);
    COPY_NODE(ep_1cd54);
    COPY_NODE(ep_1cd68);
    COPY_NODE(ep_1cd7c);
    COPY_NODE(ca90);
    COPY_NODE(desc_12530);
    COPY_NODE(desc_12537);
    COPY_NODE(desc_12574);
    COPY_NODE(desc_12588);
    COPY_NODE(desc_1258c);
    COPY_NODE(desc_12598);
    COPY_NODE(desc_125c0);
    COPY_NODE(desc_125de);
    COPY_NODE(desc_125e2);
    COPY_NODE(desc_12625);
    COPY_NODE(strings_1e3d4);
    COPY_NODE(str1);
    COPY_NODE(str2);
    COPY_NODE(str3);

    /* 1. Link config and interface pointers in tbl_88 */
    *(void **)&g_bundle.tbl_88[8]  = g_bundle.fs_cfg;
    *(void **)&g_bundle.tbl_88[24] = g_bundle.hs_cfg;
    *(void **)&g_bundle.tbl_88[40] = g_bundle.ss_cfg;
    *(void **)&g_bundle.tbl_88[60] = g_bundle.ca90;
    *(void **)&g_bundle.tbl_88[76] = g_bundle.desc_12588;

    /* 2. Link interface groups in configs */
    *(void **)&g_bundle.fs_cfg[4]  = &g_bundle.ntsc_iface[0];
    *(void **)&g_bundle.fs_cfg[20] = g_bundle.desc_1258c;

    *(void **)&g_bundle.hs_cfg[4]  = &g_bundle.ntsc_iface[32];
    *(void **)&g_bundle.hs_cfg[20] = g_bundle.desc_1258c;

    *(void **)&g_bundle.ss_cfg[4]  = &g_bundle.ntsc_iface[64];
    *(void **)&g_bundle.ss_cfg[20] = g_bundle.desc_1258c;

    /* 3. Link sub-nodes in ntsc_iface */
    *(void **)&g_bundle.ntsc_iface[0 * 8 + 4]  = g_bundle.sub_1cd90;
    *(void **)&g_bundle.ntsc_iface[1 * 8 + 4]  = g_bundle.sub_1cda4;
    *(void **)&g_bundle.ntsc_iface[2 * 8 + 4]  = g_bundle.sub_1cbac;
    *(void **)&g_bundle.ntsc_iface[3 * 8 + 4]  = g_bundle.sub_1cbc0;

    *(void **)&g_bundle.ntsc_iface[4 * 8 + 4]  = g_bundle.sub_1cdcc;
    *(void **)&g_bundle.ntsc_iface[5 * 8 + 4]  = g_bundle.sub_1cde0;
    *(void **)&g_bundle.ntsc_iface[6 * 8 + 4]  = g_bundle.sub_1cbe8;
    *(void **)&g_bundle.ntsc_iface[7 * 8 + 4]  = g_bundle.sub_1cbfc;

    *(void **)&g_bundle.ntsc_iface[8 * 8 + 4]  = g_bundle.sub_1ce08;
    *(void **)&g_bundle.ntsc_iface[9 * 8 + 4]  = g_bundle.sub_1ce1c;
    *(void **)&g_bundle.ntsc_iface[10 * 8 + 4] = g_bundle.sub_1cc24;
    *(void **)&g_bundle.ntsc_iface[11 * 8 + 4] = g_bundle.sub_1cc38;

    /* 4. Link endpoints and raw descriptors in sub-nodes */
    *(void **)&g_bundle.sub_1cd90[16] = g_bundle.desc_12598;
    *(void **)&g_bundle.sub_1cda4[4]  = g_bundle.ep_fs;
    *(void **)&g_bundle.sub_1cda4[16] = g_bundle.desc_12625;
    *(void **)&g_bundle.sub_1cbac[16] = g_bundle.desc_125c0;
    *(void **)&g_bundle.sub_1cbc0[20 + 4]  = g_bundle.ep_1cd54;
    *(void **)&g_bundle.sub_1cbc0[20 + 16] = g_bundle.desc_12574;

    *(void **)&g_bundle.sub_1cdcc[16] = g_bundle.desc_12598;
    *(void **)&g_bundle.sub_1cde0[4]  = g_bundle.ep_hs;
    *(void **)&g_bundle.sub_1cde0[16] = g_bundle.desc_12625;
    *(void **)&g_bundle.sub_1cbe8[16] = g_bundle.desc_125c0;
    *(void **)&g_bundle.sub_1cbfc[20 + 4]  = g_bundle.ep_1cd68;
    *(void **)&g_bundle.sub_1cbfc[20 + 16] = g_bundle.desc_12574;

    *(void **)&g_bundle.sub_1ce08[16] = g_bundle.desc_12598;
    *(void **)&g_bundle.sub_1ce1c[4]  = g_bundle.ep_ss;
    *(void **)&g_bundle.sub_1ce1c[16] = g_bundle.desc_12625;
    *(void **)&g_bundle.sub_1cc24[16] = g_bundle.desc_125c0;
    *(void **)&g_bundle.sub_1cc38[20 + 4]  = g_bundle.ep_1cd7c;
    *(void **)&g_bundle.sub_1cc38[20 + 16] = g_bundle.desc_12574;

    /* 5. Link ca90 interface table and strings */
    *(void **)&g_bundle.strings_1e3d4[0 * 8 + 4] = g_bundle.str1;
    *(void **)&g_bundle.strings_1e3d4[1 * 8 + 4] = g_bundle.str2;
    *(void **)&g_bundle.strings_1e3d4[2 * 8 + 4] = g_bundle.str3;

    *(void **)&g_bundle.ca90[4]  = g_bundle.strings_1e3d4;
    *(void **)&g_bundle.ca90[24] = g_bundle.desc_12598;
    *(void **)&g_bundle.ca90[32] = g_bundle.ep_fs;
    *(void **)&g_bundle.ca90[44] = g_bundle.desc_12537;
    *(void **)&g_bundle.ca90[52] = g_bundle.ep_fs;

    /* 6. Link descriptors inside endpoint templates */
    *(void **)&g_bundle.ep_1cd54[12] = g_bundle.desc_12530;
    *(void **)&g_bundle.ep_1cd68[12] = g_bundle.desc_12530;
    *(void **)&g_bundle.ep_1cd7c[12] = g_bundle.desc_12530;
    *(void **)&g_bundle.ep_1cd7c[16] = g_bundle.desc_125e2;
    *(void **)&g_bundle.ep_ss[16]    = g_bundle.desc_125de;
}

struct a6400_desc_arg {
    void *desc_tbl;
    void *extra_ptr;
    unsigned char extra_len;
    unsigned char is_dual;   /* byte 9: 0 for single-function (UVC), 1 for dual */
    unsigned char max_speed; /* byte 10: 1 for High Speed */
    unsigned char pad;       /* byte 11 */
};

static unsigned char g_saved_byte_84 = 1;
static unsigned char g_saved_byte_85 = 1;

/* IAD descriptors for UVC and Audio */
static const unsigned char s_uvc_video_iad[8] = {
    0x08, /* bLength = 8 */
    0x0B, /* bDescriptorType = INTERFACE_ASSOCIATION (0x0B) */
    0x00, /* bFirstInterface = 0 (VideoControl) */
    0x02, /* bInterfaceCount = 2 (VC + VS) */
    0x0E, /* bFunctionClass = CC_VIDEO (0x0E) */
    0x03, /* bFunctionSubClass = SC_VIDEO_INTERFACE_COLLECTION (0x03) */
    0x00, /* bFunctionProtocol = PC_PROTOCOL_UNDEFINED (0x00) */
    0x00  /* iFunction = 0 */
};

static const unsigned char s_uvc_audio_iad[8] = {
    0x08, /* bLength = 8 */
    0x0B, /* bDescriptorType = INTERFACE_ASSOCIATION (0x0B) */
    0x02, /* bFirstInterface = 2 (AudioControl) */
    0x02, /* bInterfaceCount = 2 (AC + AS) */
    0x01, /* bFunctionClass = CC_AUDIO (0x01) */
    0x02, /* bFunctionSubClass = SC_AUDIOSTREAMING (0x02) */
    0x00, /* bFunctionProtocol = PC_PROTOCOL_UNDEFINED (0x00) */
    0x00  /* iFunction = 0 */
};

typedef int (*make_config_desc_fn)(void *gc, const void *ctrl, void *buf, int desc_type);
#define ORIG_MAKE_CONFIG_DESC ((make_config_desc_fn)0x602bbc54u)

static unsigned int g_orig_bl_95cc = 0;

static int my_make_config_desc(void *gc, const void *ctrl, void *buf, int desc_type)
{
    int orig_len;
    unsigned char *p = (unsigned char *)buf;
    unsigned char scratch[512];
    int iface2_idx = -1;
    int i;
    unsigned short new_total;
    unsigned short req_wlen;
    const unsigned char *c = (const unsigned char *)ctrl;

    /* 1. Call original kernel make_config_desc */
    orig_len = ORIG_MAKE_CONFIG_DESC(gc, ctrl, buf, desc_type);
    if (orig_len <= 0 || !p) {
        return orig_len;
    }

    /* 2. Check if this is UVC (desc_type == 2 or 7, 4 interfaces) */
    if ((p[1] != 2 && p[1] != 7) || p[4] != 4) {
        return orig_len;
    }

    /* 2a. Windows first requests 9-byte header (ctrl->wLength == 9) to learn wTotalLength!
     * Must report wTotalLength = orig_total + 16 so host requests full buffer on next query! */
    if (orig_len == 9) {
        unsigned short reported_total = (unsigned short)(p[2] | (p[3] << 8));
        reported_total += 16; /* Add 8 bytes Video IAD + 8 bytes Audio IAD */
        p[2] = (unsigned char)(reported_total & 0xff);
        p[3] = (unsigned char)((reported_total >> 8) & 0xff);
        return 9;
    }

    /* 2b. Full hierarchy query: verify Interface 0 is Class 0x0E Video */
    if (orig_len < 18 || p[9] != 9 || p[10] != 4 || p[11] != 0 || p[14] != 0x0e) {
        return orig_len;
    }

    /* 3. Find Interface 2: bLength=9, bDescriptorType=4, bInterfaceNumber=2, bAlternateSetting=0 */
    for (i = 9; i + 9 <= orig_len; i += p[i]) {
        if (p[i] == 0) break;
        if (p[i] == 9 && p[i+1] == 4 && p[i+2] == 2 && p[i+3] == 0) {
            iface2_idx = i;
            break;
        }
    }

    if (iface2_idx < 0 || (orig_len + 16) > (int)sizeof(scratch)) {
        return orig_len;
    }

    /* 4. Assemble output into scratch buffer with both IADs */
    memcpy(scratch, p, 9);
    memcpy(scratch + 9, s_uvc_video_iad, 8);
    memcpy(scratch + 17, p + 9, iface2_idx - 9);
    memcpy(scratch + 17 + (iface2_idx - 9), s_uvc_audio_iad, 8);
    memcpy(scratch + 25 + (iface2_idx - 9), p + iface2_idx, orig_len - iface2_idx);

    /* 5. Update wTotalLength (bytes 2 and 3) */
    new_total = (unsigned short)(orig_len + 16);
    scratch[2] = (unsigned char)(new_total & 0xff);
    scratch[3] = (unsigned char)((new_total >> 8) & 0xff);

    /* 6. Respect host requested length: wLength is ctrl[6..7] */
    req_wlen = (unsigned short)(c[6] | (c[7] << 8));
    if (new_total > req_wlen) {
        new_total = req_wlen;
    }

    memcpy(p, scratch, new_total);
    return new_total;
}

static void a6400_hook_make_config_desc(void)
{
    unsigned int *target = (unsigned int *)0x602b95ccu;
    long offset = ((long)my_make_config_desc - ((long)target + 8)) >> 2;
    unsigned int new_bl = 0xeb000000u | (offset & 0x00ffffffu);

    if (g_orig_bl_95cc == 0) {
        g_orig_bl_95cc = *target;
    }
    *target = new_bl;
    ((void (*)(void))0x60119c80u)(); /* v7_flush_icache_all */
    printk("[a6400_uvc] hook_make_config_desc: patched 0x602b95cc to BL %p (orig=0x%08x new=0x%08x)\n",
           my_make_config_desc, g_orig_bl_95cc, new_bl);
}

static void a6400_unhook_make_config_desc(void)
{
    unsigned int *target = (unsigned int *)0x602b95ccu;
    if (g_orig_bl_95cc != 0) {
        *target = g_orig_bl_95cc;
        ((void (*)(void))0x60119c80u)(); /* v7_flush_icache_all */
        printk("[a6400_uvc] unhook_make_config_desc: restored 0x602b95cc to 0x%08x\n", g_orig_bl_95cc);
        g_orig_bl_95cc = 0;
    }
}

struct a6400_list_node {
    struct a6400_list_node *next;
    struct a6400_list_node *prev;
};

static void a6400_promote_uvc_drivers(void *gc)
{
    struct a6400_list_node *head;
    struct a6400_list_node *pos;
    void *shadow0_desc = (void *)&g_uvc_bridge.shadow[0];
    void *shadow1_desc = (void *)&g_uvc_bridge.shadow[1];
    struct a6400_list_node *node0 = (struct a6400_list_node *)0;
    struct a6400_list_node *node1 = (struct a6400_list_node *)0;

    if (!gc) return;
    head = (struct a6400_list_node *)((char *)gc + 0x78);

    for (pos = head->next; pos != head; pos = pos->next) {
        void *entry = (char *)pos - 4;
        void *r = *(void **)entry;
        if (r == shadow0_desc) node0 = pos;
        if (r == shadow1_desc) node1 = pos;
    }

    if (node1) {
        node1->prev->next = node1->next;
        node1->next->prev = node1->prev;

        node1->next = head->next;
        node1->prev = head;
        head->next->prev = node1;
        head->next = node1;
    }
    if (node0) {
        node0->prev->next = node0->next;
        node0->next->prev = node0->prev;

        node0->next = head->next;
        node0->prev = head;
        head->next->prev = node0;
        head->next = node0;
    }

    printk("[a6400_uvc] promote_uvc_drivers: shadow0/shadow1 at head of gc->drv_list\n");
}

static void a6400_demote_uvc_drivers(void *gc)
{
    struct a6400_list_node *head;
    struct a6400_list_node *pos;
    void *shadow0_desc = (void *)&g_uvc_bridge.shadow[0];
    void *shadow1_desc = (void *)&g_uvc_bridge.shadow[1];
    struct a6400_list_node *node0 = (struct a6400_list_node *)0;
    struct a6400_list_node *node1 = (struct a6400_list_node *)0;

    if (!gc) return;
    head = (struct a6400_list_node *)((char *)gc + 0x78);

    for (pos = head->next; pos != head; pos = pos->next) {
        void *entry = (char *)pos - 4;
        void *r = *(void **)entry;
        if (r == shadow0_desc) node0 = pos;
        if (r == shadow1_desc) node1 = pos;
    }

    if (node0) {
        node0->prev->next = node0->next;
        node0->next->prev = node0->prev;

        node0->next = head;
        node0->prev = head->prev;
        head->prev->next = node0;
        head->prev = node0;
    }
    if (node1) {
        node1->prev->next = node1->next;
        node1->next->prev = node1->prev;

        node1->next = head;
        node1->prev = head->prev;
        head->prev->next = node1;
        head->prev = node1;
    }

    printk("[a6400_uvc] demote_uvc_drivers: shadow0/shadow1 at tail of gc->drv_list\n");
}

static inline void *a6400_get_dwc(void *gc)
{
    void *gadget;
    if (!gc) return (void *)0;
    gadget = *(void **)gc;
    if (!gadget) return (void *)0;
    return (void *)((char *)gadget - 0x150);
}

static void a6400_arm_ep0(void *dwc)
{
    void *ep0_out;
    void *ep0_in;
    void *ep0_desc = (void *)0x604e4e24u;

    if (!dwc) return;
    ep0_out = *(void **)((char *)dwc + 0xd0);
    ep0_in  = *(void **)((char *)dwc + 0xd4);

    printk("[a6400_uvc] arm_ep0: enabling ep0-out=%p ep0-in=%p desc=%p\n", ep0_out, ep0_in, ep0_desc);

    /* 1. Enable ep0-out */
    if (ep0_out) {
        ((int (*)(void *, void *, void *, void *))0x602b05fcu)(ep0_out, ep0_desc, 0, 0);
    }
    /* 2. Enable ep0-in */
    if (ep0_in) {
        ((int (*)(void *, void *, void *, void *))0x602b05fcu)(ep0_in, ep0_desc, 0, 0);
    }
    /* 3. Set dwc->ep0state = EP0_SETUP_PHASE (1) */
    *(unsigned int *)((char *)dwc + 0x2e0) = 1;

    /* 4. Arm EP0 SETUP TRB */
    ((void (*)(void *))0x602b2b40u)(dwc);

    printk("[a6400_uvc] arm_ep0: complete! EP0 ready for SETUP\n");
}

static inline void a6400_usb_pullup(void *gc, int is_on)
{
    void *gadget;
    if (!gc) return;
    gadget = *(void **)gc;
    if (gadget) {
        void *ops = *(void **)((char *)gadget + 0x10);
        if (ops) {
            int (*pullup)(void *, int) = *(int (**)(void *, int))((char *)ops + 0x14);
            if (pullup) {
                pullup(gadget, is_on);
            }
        }
    }
}

static int a6400_uvc_commit_descriptors(void)
{
    void **p_gc = (void **)0x6051b17cu;
    void *gc;
    void *dwc;
    unsigned int *p_flags;
    struct a6400_desc_arg desc_arg;
    unsigned long orig_fs;
    int ret;

    if (!p_gc || !*p_gc) {
        printk("[a6400_uvc] commit: gadgetcore NULL!\n");
        return -1;
    }
    gc = *p_gc;
    dwc = a6400_get_dwc(gc);
    p_flags = (unsigned int *)((char *)gc + 0x68);
    g_saved_msc_desc_tbl = *(void **)((char *)gc + 0x6c);
    g_saved_byte_84 = *(unsigned char *)((char *)gc + 0x84);
    g_saved_byte_85 = *(unsigned char *)((char *)gc + 0x85);

    printk("[a6400_uvc] commit: starting UVC transition (gc=%p dwc=%p saved_msc=%p b84=%u b85=%u)...\n",
           gc, dwc, g_saved_msc_desc_tbl, g_saved_byte_84, g_saved_byte_85);

    /* 1. Drop D+ to signal USB disconnect to Windows */
    a6400_usb_pullup(gc, 0);

    /* 2. Disconnect endpoints and stop gcw */
    ((int (*)(void *))0x602b9464u)(gc); /* setup_disconnect */
    ((int (*)(void *))0x602bd834u)(gc); /* usb_gcw_stop */

    /* 3. Prepare UVC bundle with all 54 relocations */
    init_uvc_bundle();

    desc_arg.desc_tbl = g_bundle.tbl_88;
    desc_arg.extra_ptr = (void *)0;
    desc_arg.extra_len = 0;
    desc_arg.is_dual = 0;   /* Single-function UVC (GCW_STATE_SINGLE = 2) */
    desc_arg.max_speed = 1; /* High Speed */
    desc_arg.pad = 0;

    /* 4. Clear bit 2 of gadgetcore flags to permit descriptor reconfiguration */
    if (p_flags) {
        *p_flags &= ~4u;
    }

    /* 5. Call save_desc_tbl with KERNEL_DS */
    orig_fs = a6400_get_fs();
    a6400_set_fs(0xfffffffful);
    ret = ((int (*)(void *, void *))0x602bc550u)(gc, &desc_arg);
    a6400_set_fs(orig_fs);

    printk("[a6400_uvc] commit: save_desc_tbl ret=%d, new gc->desc_tbl=%p\n",
           ret, *(void **)((char *)gc + 0x6c));

    if (ret != 0) {
        printk("[a6400_uvc] commit: save_desc_tbl FAILED (%d), aborting to Mass Storage...\n", ret);
        a6400_uvc_restore_descriptors();
        return ret;
    }

    /* 6. Start controller in Single-Function mode (is_dual = 0 -> GCW_STATE_SINGLE = 2) */
    ((int (*)(unsigned char))0x602bd7f8u)(0);

    /* 7. Kirurški omogući EP0 i naoružaj SETUP TRB koji je pullup(0) ugasio! */
    a6400_arm_ep0(dwc);

    /* 7.5. Hook make_config_desc to inject IADs for Windows usbccgp / usbvideo */
    a6400_hook_make_config_desc();

    /* 7.6. Promote shadow0 and shadow1 to head of gc->drv_list */
    a6400_promote_uvc_drivers(gc);

    /* 8. Pull D+ high to trigger Windows UVC re-enumeration! */
    a6400_usb_pullup(gc, 1);

    if (p_flags) {
        *p_flags |= 4u;
    }

    printk("[a6400_uvc] commit: complete! D+ HIGH (EP0 armed, UVC 0x0322 active)\n");
    return 0;
}

static int a6400_uvc_restore_descriptors(void)
{
    void **p_gc = (void **)0x6051b17cu;
    void *gc;
    void *dwc;
    unsigned int *p_flags;

    if (!p_gc || !*p_gc) return -1;
    gc = *p_gc;
    dwc = a6400_get_dwc(gc);
    p_flags = (unsigned int *)((char *)gc + 0x68);

    printk("[a6400_uvc] restore: reverting to Mass Storage...\n");

    /* 1. Drop D+ and stop controller */
    a6400_usb_pullup(gc, 0);
    ((int (*)(void *))0x602b9464u)(gc); /* setup_disconnect */
    ((int (*)(void *))0x602bd834u)(gc); /* usb_gcw_stop */

    /* 1.5. Restore gc->drv_list and unhook make_config_desc */
    a6400_demote_uvc_drivers(gc);
    a6400_unhook_make_config_desc();

    /* 2. Clear UVC descriptor table pointer (static bundle, do not call kfree/free_desc_tbl) */
    *(void **)((char *)gc + 0x6c) = (void *)0;

    if (p_flags) {
        *p_flags &= ~4u;
    }

    /* 3. Restore saved Mass Storage descriptor table and state */
    if (g_saved_msc_desc_tbl) {
        *(void **)((char *)gc + 0x6c) = g_saved_msc_desc_tbl;
    }
    *(unsigned char *)((char *)gc + 0x84) = g_saved_byte_84;
    *(unsigned char *)((char *)gc + 0x85) = g_saved_byte_85;

    /* 4. Start controller in saved mode */
    ((int (*)(unsigned char))0x602bd7f8u)(g_saved_byte_84);

    /* 5. Naoružaj EP0 za Mass Storage! */
    a6400_arm_ep0(dwc);

    /* 6. Raise D+ for Mass Storage */
    a6400_usb_pullup(gc, 1);

    if (p_flags) {
        *p_flags |= 4u;
    }

    printk("[a6400_uvc] restore: Mass Storage restored! gc->desc_tbl=%p (b84=%u b85=%u)\n",
           *(void **)((char *)gc + 0x6c), g_saved_byte_84, g_saved_byte_85);
    return 0;
}

/* ep_ctrl_create_ep (602ba8e4) stores the native usb_ep at wrapper+24.
 * The video module consumes this wrapper, not the raw DWC3 usb_ep. */
static uvc_u32 a6400_uvc_bulk_endpoint(uvc_u32 count, uvc_u32 array)
{
    void *gc=*(void **)0x6051b17cu;
    void *dwc=a6400_get_dwc(gc);
    void *raw;
    uvc_u32 i;
    printk("[a6400_uvc] START arguments count=%u array=%08x\n",count,array);
    if (!dwc || !array || count>16) return 0;
    raw=*(void **)((char *)dwc+0xdc);
    if (!raw) return 0;
    for (i=0;i<count;i++) {
        void *ep=((void **)array)[i];
        unsigned char *desc;
        printk("[a6400_uvc] endpoint[%u] wrapper=%p dwc_raw=%p\n",i,ep,raw);
        if (!ep || *(void **)((char *)ep+0x24)!=raw) continue;
        desc=*(unsigned char **)((char *)raw+0x1c);
        printk("[a6400_uvc] endpoint raw matched; descriptor=%p\n",desc);
        if (!desc || desc[0]!=7 || desc[1]!=5 || desc[2]!=0x81 ||
            (desc[3]&3)!=2) continue;
        printk("[a6400_uvc] START bulk bridge count=%u wrapper=%p raw=%p ep=0x81\n",count,ep,raw);
#ifdef A6400_UVC_START_PROBE_ONLY
        printk("[a6400_uvc] START probe-only: reference callback not invoked\n");
        return 0;
#endif
        return (uvc_u32)ep;
    }
    printk("[a6400_uvc] START skipped: no enabled Bulk IN 0x81 in %u endpoints\n",count);
    return 0;
}

int a6400_uvc_gadgetcore_register_hook(struct uvc_reference_descriptor *r)
{
    int ret;
    unsigned int *p_flags;
    unsigned int orig_flags = 0;

    printk("[a6400_uvc] gadgetcore_register_hook: name=%s config=%u ifaces=%u\n",
           (r && r->name) ? (const char *)(unsigned long)r->name : "null",
           r ? r->config : 0, r ? r->interface_count : 0);
    if (!r || !r->callback[0]) return -22;
    g_reference_start=r->callback[0];
    r->callback[0]=(uvc_u32)a6400_uvc_reference_start;
    ret = a6400_uvc_bridge_prepare(&g_uvc_bridge, r);
    if (ret != 0) {
        r->callback[0]=g_reference_start;
        printk("[a6400_uvc] bridge_prepare FAILED: ret=%d\n", ret);
        return ret;
    }
    printk("[a6400_uvc] bridge_prepare SUCCESS, calling bridge_register...\n");
    g_uvc_bridge.bulk_endpoint=a6400_uvc_bulk_endpoint;

    p_flags = a6400_gadgetcore_flags();
    if (p_flags) {
        orig_flags = *p_flags;
        *p_flags &= ~4u;
        printk("[a6400_uvc] cleared bit 2 (flags: 0x%x -> 0x%x)\n", orig_flags, *p_flags);
    }

    ret = a6400_uvc_bridge_register(&g_uvc_bridge,
                                     usb_gadgetcore_register_driver,
                                     usb_gadgetcore_unregister_driver);

    if (p_flags) {
        *p_flags = orig_flags;
        printk("[a6400_uvc] restored flags: 0x%x\n", *p_flags);
    }

    printk("[a6400_uvc] bridge_register result=%d\n", ret);

    if (ret == 0) {
        g_uvc_registered = 1;
        a6400_uvc_commit_descriptors();
    }

    return ret;
}

int a6400_uvc_gadgetcore_unregister_hook(struct uvc_reference_descriptor *r)
{
    int ret;
    unsigned int *p_flags;
    unsigned int orig_flags = 0;

    printk("[a6400_uvc] gadgetcore_unregister_hook called\n");
    (void)r;

    if (!g_uvc_registered) {
        printk("[a6400_uvc] gadgetcore_unregister_hook: already unregistered, skipping\n");
        return 0;
    }
    g_uvc_registered = 0;

    a6400_uvc_restore_descriptors();

    p_flags = a6400_gadgetcore_flags();
    if (p_flags) {
        orig_flags = *p_flags;
        *p_flags &= ~4u;
        printk("[a6400_uvc] unreg: cleared bit 2 (flags: 0x%x -> 0x%x)\n", orig_flags, *p_flags);
    }

    ret = a6400_uvc_bridge_unregister(&g_uvc_bridge,
                                       usb_gadgetcore_unregister_driver);

    if (p_flags) {
        *p_flags = orig_flags;
        printk("[a6400_uvc] unreg: restored flags: 0x%x\n", *p_flags);
    }

    if (ret == 0) {
        if (r) r->callback[0]=g_reference_start;
        g_uvc_bridge.magic = 0;
    }

    printk("[a6400_uvc] bridge_unregister result=%d\n", ret);
    return ret;
}

/* 4. Physical DMA Buffer Allocator Bridge */
#ifdef A6400_UVC_COHERENT_ALLOC
extern void *dma_alloc_coherent(void *device, unsigned int size,
                                unsigned int *dma_handle, unsigned int flags);
extern void dma_free_coherent(void *device, unsigned int size,
                              void *cpu_address, unsigned int dma_handle);
static void *g_dma_cpu;
static unsigned int g_dma_phys;
/* Lifecycle probe capacity only. Streaming integration must enforce per-slot
 * frame bounds and query this actual capacity; historical fixed-PA feeders
 * must never be used with this allocator. */
#define A6400_UVC_DMA_SIZE (256u*1024u)

void *a6400_uvc_owned_noncache(unsigned int phys)
{
    if (g_dma_cpu && phys==g_dma_phys) return g_dma_cpu;
    return arch_phys_to_noncache(phys);
}
#endif

int a6400_usb_sync_alloc_phys_buffer(int task, int unit_type,
                                     unsigned int *out_handle,
                                     unsigned int *out_phys,
                                     unsigned int *out_size)
{
#ifdef A6400_UVC_COHERENT_ALLOC
    /* Original argument 0x50e is a ZV-E10 DMM UnitType, NOT a size. This
     * explicit MOD policy requests a bounded allocation from the a6400 kernel. */
    (void)task;
    *out_handle=0;*out_phys=0;*out_size=0;
    if (unit_type!=0x50e) return -22;
    if (g_dma_cpu) return -16;
    g_dma_cpu=dma_alloc_coherent(0,A6400_UVC_DMA_SIZE,&g_dma_phys,0xd0u);
    if (!g_dma_cpu) return -12;
    *out_handle=1;*out_phys=g_dma_phys;*out_size=A6400_UVC_DMA_SIZE;
    printk("[a6400_uvc] owned coherent alloc cpu=%p phys=%08x size=%u\n",
           g_dma_cpu,g_dma_phys,A6400_UVC_DMA_SIZE);
    return 0;
#else
    void *noncache;
    (void)task;
    (void)unit_type;
    printk("[a6400_uvc] EXPERIMENTAL fixed window: task=%d unit_type=%x (not an allocation)\n", task, unit_type);
    *out_handle = 1u;
    *out_phys = 0x20000000u;
    *out_size = 1294u * 1024u;

    noncache = arch_phys_to_noncache(*out_phys);
    if (noncache) {
        /* Source must not alias either driver's destination slot: Update writes
         * its 12-byte UVC header before DMA copies the JPEG into that slot. */
        _Static_assert(0x120000u+sizeof(s_test_jpeg_720p)<=1294u*1024u,
                       "test JPEG source inside experimental RAM window");
        memcpy((char *)noncache+0x120000u, s_test_jpeg_720p, sizeof(s_test_jpeg_720p));
    }

    printk("[a6400_uvc] fixed test window: phys=0x%x size=%u noncache=%p (injected %u bytes 720p JPEG)\n",
           *out_phys, *out_size, noncache, (unsigned int)sizeof(s_test_jpeg_720p));
    return 0;
#endif
}

int a6400_usb_sync_free_phys_buffer(int task, unsigned short handle)
{
    (void)task;
    (void)handle;
    printk("[a6400_uvc] free_phys called (registered=%d)\n", g_uvc_registered);
    if (g_uvc_registered) {
        printk("[a6400_uvc] free_phys: auto-unregistering dangling UVC session!\n");
        int ret=a6400_uvc_gadgetcore_unregister_hook((struct uvc_reference_descriptor *)0);
        if (ret!=0) return ret;
    }
#ifdef A6400_UVC_COHERENT_ALLOC
    if (!g_dma_cpu || handle!=1) return -22;
    dma_free_coherent(0,A6400_UVC_DMA_SIZE,g_dma_cpu,g_dma_phys);
    printk("[a6400_uvc] owned coherent free phys=%08x size=%u\n",g_dma_phys,A6400_UVC_DMA_SIZE);
    g_dma_cpu=0;g_dma_phys=0;
#endif
    return 0;
}

/* 5. MOD DMA Query and Slot Capacity Enforcement Bridge */
#define IOCTL_UVC_MOD_QUERY_DMA 0x8010f020

struct a6400_uvc_dma_metadata {
    unsigned int phys_addr;
    unsigned int total_size;
    unsigned int slot_size;
    unsigned int max_frame_payload;
};

extern unsigned long __copy_to_user(void *to, const void *from, unsigned long n);
extern unsigned long __copy_from_user(void *to, const void *from, unsigned long n);
extern long usbg_video_core_ioctl(void *filp, unsigned int cmd, unsigned long arg);

long a6400_uvc_video_core_ioctl(void *filp, unsigned int cmd, unsigned long arg)
{
    if (cmd == IOCTL_UVC_MOD_QUERY_DMA) {
        struct a6400_uvc_dma_metadata meta;
#ifdef A6400_UVC_COHERENT_ALLOC
        meta.phys_addr = g_dma_phys;
        meta.total_size = A6400_UVC_DMA_SIZE;
        meta.slot_size = A6400_UVC_DMA_SIZE / 2;
        meta.max_frame_payload = (A6400_UVC_DMA_SIZE / 2) - 12;
#else
        meta.phys_addr = 0x20000000u;
        meta.total_size = 1294u * 1024u;
        meta.slot_size = (1294u * 1024u) / 2;
        meta.max_frame_payload = ((1294u * 1024u) / 2) - 12;
#endif
        if (!arg) return -14; /* -EFAULT */
        if (__copy_to_user((void *)arg, &meta, sizeof(meta)) != 0) return -14;
        printk("[a6400_uvc] MOD DMA query: phys=%08x total=%u slot=%u max_payload=%u\n",
               meta.phys_addr, meta.total_size, meta.slot_size, meta.max_frame_payload);
        return 0;
    }

    if (cmd == 0x4008f000) { /* IOCTL_UVC_REG_BUF */
        struct { unsigned int size; unsigned int phys_addr; } reg;
        if (!arg) return -14;
        if (__copy_from_user(&reg, (void *)arg, sizeof(reg)) != 0) return -14;
#ifdef A6400_UVC_COHERENT_ALLOC
        if (reg.phys_addr != g_dma_phys || reg.size != A6400_UVC_DMA_SIZE) {
            printk("[a6400_uvc] REG_BUF mismatch: req phys=%08x size=%u (expected owned phys=%08x size=%u)\n",
                   reg.phys_addr, reg.size, g_dma_phys, A6400_UVC_DMA_SIZE);
            return -22; /* -EINVAL */
        }
#endif
    }

    if (cmd == 0x4008f003) { /* IOCTL_UVC_UPDATE */
        struct { unsigned int frame_size; unsigned int phys_addr; } data;
        unsigned int slot_cap =
#ifdef A6400_UVC_COHERENT_ALLOC
            A6400_UVC_DMA_SIZE / 2;
#else
            (1294u * 1024u) / 2;
#endif
        if (!arg) return -14;
        if (__copy_from_user(&data, (void *)arg, sizeof(data)) != 0) return -14;

        if (slot_cap < 12 || data.frame_size > slot_cap - 12) {
            printk("[a6400_uvc] REJECT frame_size=%u + 12 > slot_capacity=%u (overflow prevented)\n",
                   data.frame_size, slot_cap);
            return -22; /* -EINVAL: frame exceeds slot capacity */
        }
        if (!data.frame_size || !data.phys_addr ||
            data.phys_addr > 0xffffffffu-data.frame_size) return -22;
#ifdef A6400_UVC_COHERENT_ALLOC
        /* Original Update writes a 12-byte header in its owned destination
         * before copying the source JPEG. A source inside either destination
         * slot can therefore be corrupted even when frame length is valid. */
        if (g_dma_phys && (g_dma_phys > 0xffffffffu-A6400_UVC_DMA_SIZE ||
            (data.phys_addr < g_dma_phys+A6400_UVC_DMA_SIZE &&
             data.phys_addr+data.frame_size > g_dma_phys))) return -22;
#endif
    }

    return usbg_video_core_ioctl(filp, cmd, arg);
}
