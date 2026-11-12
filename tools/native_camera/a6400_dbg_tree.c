/* E0407b1 parts 2+3: module-owned deep copy of the gadgetcore per-speed
 * descriptor tree, zero-endpoint vendor interface 1 append, three-target
 * patch/restore and a quiesced root swap.
 *
 * Freestanding kernel C: no libc, fixed-width types only, no floating point,
 * no VLAs, every count bounded, every pointer validated against kernel RAM
 * before use.  The file compiles twice:
 *
 *   production : services bind to exported kernel symbols (__kmalloc, kfree,
 *                memcpy, memset, probe_kernel_read, probe_kernel_write,
 *                printk) and to two fixed in-image text addresses for the
 *                teardown helpers that gadgetcore does not export.
 *   test       : -DA6400_TREE_TEST binds the same service slots to tiny
 *                `tree_*` stubs so the compiled tree logic can run under
 *                Unicorn against a synthetic fixture.
 *
 * The pure tree logic (deep copy / append / validate / free / patch / swap)
 * never touches hardware directly; the only hardware-facing calls are
 * gadget->ops->pullup and the two teardown helpers reached through the
 * service layer.
 *
 * Layout facts and the corrected per-speed record mapping (speed 3 ->
 * root+0x00, speed 5 -> root+0x20, else root+0x10) are from
 * docs/evidence/0407b1-tree-deepcopy-and-udc-abi.md.
 */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef int s32;

/* ------------------------------------------------------------------ */
/* service layer                                                       */
/* ------------------------------------------------------------------ */

#ifdef A6400_TREE_TEST
extern void *tree_alloc(u32 size);
extern void tree_kfree(void *ptr);
extern void *tree_memcpy(void *dst, const void *src, u32 count);
extern void *tree_memset(void *dst, int value, u32 count);
extern int tree_probe_read(void *dst, const void *src, u32 count);
extern int tree_probe_write(void *dst, const void *src, u32 count);
extern int tree_log(const char *format, ...);
extern int tree_pullup(u32 gadget, int on);
extern int tree_stop_disconnect(u32 gc);
extern int tree_gcw_stop(void);
#define A_ALLOC(n)             tree_alloc(n)
#define A_FREE(p)              tree_kfree(p)
#define A_MEMCPY(d, s, n)      tree_memcpy((d), (s), (n))
#define A_MEMSET(d, v, n)      tree_memset((d), (v), (n))
#define A_READ(d, s, n)        tree_probe_read((d), (s), (n))
#define A_WRITE(d, s, n)       tree_probe_write((d), (s), (n))
#define A_LOG(...)             tree_log(__VA_ARGS__)
static int call_stop_disconnect(u32 gc) { return tree_stop_disconnect(gc); }
static int call_gcw_stop(void) { return tree_gcw_stop(); }
#else
extern void *__kmalloc(u32 size, u32 flags);
extern void kfree(const void *ptr);
extern void *memcpy(void *dst, const void *src, u32 count);
extern void *memset(void *dst, int value, u32 count);
extern int probe_kernel_read(void *dst, const void *src, u32 count);
extern int probe_kernel_write(void *dst, const void *src, u32 count);
extern int printk(const char *format, ...);
#define A6400_GFP_KERNEL 0xd0u
#define A_ALLOC(n)             __kmalloc((n), A6400_GFP_KERNEL)
#define A_FREE(p)              kfree(p)
#define A_MEMCPY(d, s, n)      memcpy((d), (s), (n))
#define A_MEMSET(d, v, n)      memset((d), (v), (n))
#define A_READ(d, s, n)        probe_kernel_read((d), (s), (n))
#define A_WRITE(d, s, n)       probe_kernel_write((d), (s), (n))
#define A_LOG(...)             printk(__VA_ARGS__)
/* Fixed text addresses in this exact image (file offset = VA - 0x60108000):
 *   setup_disconnect 0x602b9464, usb_gcw_stop 0x602bd834.
 * Neither is EXPORT_SYMBOL'ed, so they cannot be linked as imports.  They are
 * reached only on the teardown path, only in process context. */
#define A6400_STOP_DISCONNECT_ADDR 0x602b9464u
#define A6400_GCW_STOP_ADDR        0x602bd834u
static int call_stop_disconnect(u32 gc)
{
    return ((int (*)(u32))A6400_STOP_DISCONNECT_ADDR)(gc);
}
static int call_gcw_stop(void)
{
    return ((int (*)(void))A6400_GCW_STOP_ADDR)();
}
#endif

__attribute__((section(".modinfo"), used)) static const char tree_license[] = "license=GPL";
#ifndef A6400_TREE_TEST
__attribute__((section(".modinfo"), used)) static const char tree_author[] = "author=a6400 research";
__attribute__((section(".modinfo"), used)) static const char tree_description[] =
    "description=E0407b1 tree deep copy + vendor interface 1 + quiesced root swap";
#endif

/* ------------------------------------------------------------------ */
/* constants                                                           */
/* ------------------------------------------------------------------ */

#define A6400_ROOT_SIZE        0x58u
#define A6400_RECORD_SIZE      0x10u
#define A6400_CONFIG_SIZE      0x18u
#define A6400_IFACE_SIZE       0x08u
#define A6400_ALT_SIZE         0x14u
#define A6400_EP_SIZE          0x14u
#define A6400_LANG_SIZE        0x08u
#define A6400_STRING_SIZE      0x08u

#define A6400_MAX_CONFIGS      8u
#define A6400_MAX_INTERFACES   16u
#define A6400_MAX_ALTS         8u
#define A6400_MAX_ENDPOINTS    16u
#define A6400_MAX_LANGS        8u
#define A6400_MAX_STRINGS      32u
#define A6400_MAX_EXTRA        4096u
#define A6400_MAX_STRING_BYTES 255u
#define A6400_MAX_TOTAL_DESC   60000u
#define A6400_MAX_NODE_BYTES   0x10000u

#define A6400_RAM_LO           0x60000000u
#define A6400_RAM_HI           0x6fffffffu

#define A6400_GC_SLOT_VA       0x6051b17cu
#define A6400_OS_STRING_VA     0x604e5130u
#define A6400_OS_STRING_LEN    18u
#define A6400_OS_CRC_STOCK     0x6e795789u
#define A6400_OS_CRC_OS20      0xfdadfcbau

#define A6400_GC_FLAGS         0x68u
#define A6400_GC_ROOT          0x6cu
#define A6400_GC_CONFIG        0x74u
#define A6400_GC_MODE          0x84u
#define A6400_STARTED_BIT      0x4u

#define A6400_BCDUSB_STOCK     0x0200u
#define A6400_BCDUSB_OS20      0x0210u

#define A6400_VENDOR_CLASS     0xffu
#define A6400_VENDOR_SUBCLASS  0xdbu
#define A6400_VENDOR_PROTOCOL  0x01u

#define A6400_OK               0
#define A6400_EINVAL          (-22)
#define A6400_ENOMEM          (-12)
#define A6400_EFAULT          (-14)
#define A6400_EBUSY           (-16)
#define A6400_EIO             (-5)
#define A6400_EOPNOTSUPP      (-95)
#define A6400_ERANGE          (-34)

/* MS OS string: stock MSFT100/vendor 0x30 on the wire, MSFT20/vendor 0x02
 * when patched (E0407a targets; CRC stock 6e795789 <-> fdadfcba). */
static const u8 stock_os[A6400_OS_STRING_LEN] = {
    0x12, 0x03, 0x4d, 0x00, 0x53, 0x00, 0x46, 0x00, 0x54, 0x00,
    0x31, 0x00, 0x30, 0x00, 0x30, 0x00, 0x30, 0x00};
static const u8 os20_os[A6400_OS_STRING_LEN] = {
    0x12, 0x03, 0x4d, 0x00, 0x53, 0x00, 0x46, 0x00, 0x54, 0x00,
    0x32, 0x00, 0x30, 0x00, 0x00, 0x00, 0x02, 0x00};

struct a6400_tree_state {
    u32 gc;                 /* gadgetcore object (read from the global slot)   */
    u32 orig_root;          /* kernel root captured before the swap            */
    u32 module_root;        /* module-owned clone installed at gc+0x6c         */
    u32 bcdusb_addr;        /* module-clone record selected at runtime         */
    u32 saved_os_crc;       /* CRC of the original OS string                   */
    u16 saved_bcdusb;       /* stock halfword at bcdusb_addr                   */
    u8  speed;              /* gadget->speed latched before pullup(0)          */
    u8  saved_mode;         /* stock gc+0x84 value                             */
    u8  patched_os;
    u8  patched_mode;
    u8  patched_bcdusb;
    u8  root_installed;
    u8  quiesced;
    u8  reserved0[3];
    u8  saved_os[A6400_OS_STRING_LEN];
};

#define A_NOINLINE __attribute__((noinline, noipa))

static struct a6400_tree_state g_state;

/* ------------------------------------------------------------------ */
/* small helpers                                                       */
/* ------------------------------------------------------------------ */

static u32 crc32_bytes(const u8 *data, u32 length)
{
    u32 crc = 0xffffffffu;
    u32 i, bit;
    for (i = 0; i < length; i++) {
        crc ^= data[i];
        for (bit = 0; bit < 8u; bit++)
            crc = (crc >> 1) ^ (0xedb88320u & (u32)-(s32)(crc & 1u));
    }
    return ~crc;
}

static int bytes_equal(const u8 *a, const u8 *b, u32 length)
{
    u32 i;
    for (i = 0; i < length; i++)
        if (a[i] != b[i])
            return 0;
    return 1;
}

static u16 load_u16(const u8 *p)
{
    return (u16)((u16)p[0] | ((u16)p[1] << 8));
}

static u32 load_u32(const u8 *p)
{
    return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}

static void store_u16(u8 *p, u16 value)
{
    p[0] = (u8)(value & 0xffu);
    p[1] = (u8)((value >> 8) & 0xffu);
}

static void store_u32(u8 *p, u32 value)
{
    p[0] = (u8)(value & 0xffu);
    p[1] = (u8)((value >> 8) & 0xffu);
    p[2] = (u8)((value >> 16) & 0xffu);
    p[3] = (u8)((value >> 24) & 0xffu);
}

static int range_ok(u32 ptr, u32 length)
{
    if (ptr < A6400_RAM_LO || ptr > A6400_RAM_HI)
        return 0;
    if (length > (u32)((A6400_RAM_HI - ptr) + 1u))
        return 0;
    return 1;
}

static int tree_read(void *dst, u32 src, u32 length)
{
    if (!length)
        return A6400_OK;
    if (!range_ok(src, length))
        return A6400_EFAULT;
    return A_READ(dst, (const void *)src, length) ? A6400_EFAULT : A6400_OK;
}

static int tree_read32(u32 src, u32 *value)
{
    u8 raw[4];
    int rc = tree_read(raw, src, 4);
    if (rc)
        return rc;
    *value = load_u32(raw);
    return A6400_OK;
}

static int tree_read16(u32 src, u16 *value)
{
    u8 raw[2];
    int rc = tree_read(raw, src, 2);
    if (rc)
        return rc;
    *value = load_u16(raw);
    return A6400_OK;
}

static int tree_read8(u32 src, u8 *value)
{
    return tree_read(value, src, 1);
}

static int tree_write(u32 dst, const void *src, u32 length)
{
    if (!length)
        return A6400_OK;
    if (!range_ok(dst, length))
        return A6400_EFAULT;
    return A_WRITE((void *)dst, src, length) ? A6400_EFAULT : A6400_OK;
}

static int tree_write32(u32 dst, u32 value)
{
    u8 raw[4];
    store_u32(raw, value);
    return tree_write(dst, raw, 4);
}

static int tree_write16(u32 dst, u16 value)
{
    u8 raw[2];
    store_u16(raw, value);
    return tree_write(dst, raw, 2);
}

static int tree_write8(u32 dst, u8 value)
{
    return tree_write(dst, &value, 1);
}

static void *tree_zalloc(u32 size)
{
    void *p;
    if (!size)
        size = 4;
    if (size > A6400_MAX_NODE_BYTES)
        return 0;
    p = A_ALLOC(size);
    if (!p)
        return 0;
    /* A module allocator that returns a pointer outside kernel RAM is a hard
     * contract violation; refuse rather than hand it to probe/memcpy. */
    if (!range_ok((u32)p, size)) {
        A_FREE(p);
        return 0;
    }
    A_MEMSET(p, 0, size);
    return p;
}

/* ------------------------------------------------------------------ */
/* deep copy                                                           */
/* ------------------------------------------------------------------ */

static int copy_blob(u32 dst_field, u32 src_ptr, u32 size)
{
    void *p;
    int rc;
    if (!size)
        return A6400_OK;
    if (size > A6400_MAX_EXTRA)
        return A6400_ERANGE;
    if (!range_ok(src_ptr, size))
        return A6400_EFAULT;
    p = tree_zalloc(size);
    if (!p)
        return A6400_ENOMEM;
    if (A_MEMCPY(p, (const void *)src_ptr, size) != p) {
        A_FREE(p);
        return A6400_EFAULT;
    }
    rc = tree_write32(dst_field, (u32)p);
    if (rc)
        A_FREE(p);      /* never leave an unlinked allocation behind */
    return rc;
}

static int copy_alternate(u32 dst_alt, u32 src_alt)
{
    u8 raw[A6400_ALT_SIZE];
    u32 ep_array_src, ep_count, extra_size, extra_ptr;
    u32 ep_array_dst;
    u32 i;
    int rc;

    rc = tree_read(raw, src_alt, A6400_ALT_SIZE);
    if (rc)
        return rc;
    ep_count = raw[1];
    ep_array_src = load_u32(raw + 4);
    extra_size = load_u32(raw + 0x0c);
    extra_ptr = load_u32(raw + 0x10);
    if (ep_count > A6400_MAX_ENDPOINTS || extra_size > A6400_MAX_EXTRA)
        return A6400_ERANGE;
    if (ep_count && !range_ok(ep_array_src, ep_count * A6400_EP_SIZE))
        return A6400_EFAULT;
    if (extra_size && !range_ok(extra_ptr, extra_size))
        return A6400_EFAULT;
    store_u32(raw + 4, 0);          /* never copy the source pointer */
    store_u32(raw + 0x10, 0);       /* set only after a successful copy */
    rc = tree_write(dst_alt, raw, A6400_ALT_SIZE);
    if (rc)
        return rc;
    if (extra_size) {
        rc = copy_blob(dst_alt + 0x10, extra_ptr, extra_size);
        if (rc)
            return rc;
    }
    if (!ep_count)
        return A6400_OK;
    ep_array_dst = (u32)tree_zalloc(ep_count * A6400_EP_SIZE);
    if (!ep_array_dst)
        return A6400_ENOMEM;
    rc = tree_write32(dst_alt + 4, ep_array_dst);
    if (rc) {
        A_FREE((void *)ep_array_dst);
        return rc;
    }
    for (i = 0; i < ep_count; i++) {
        u32 dst_ep = ep_array_dst + i * A6400_EP_SIZE;
        u32 src_ep = ep_array_src + i * A6400_EP_SIZE;
        u8 ep[A6400_EP_SIZE];
        u32 ep_extra, ep_ptr, companion;
        rc = tree_read(ep, src_ep, A6400_EP_SIZE);
        if (rc)
            return rc;
        ep_extra = load_u32(ep + 8);
        ep_ptr = load_u32(ep + 0x0c);
        companion = load_u32(ep + 0x10);
        if (ep_extra > A6400_MAX_EXTRA)
            return A6400_ERANGE;
        if (ep_extra && !range_ok(ep_ptr, ep_extra))
            return A6400_EFAULT;
        if (companion && !range_ok(companion, 4))
            return A6400_EFAULT;
        store_u32(ep + 0x0c, 0);
        store_u32(ep + 0x10, 0);
        rc = tree_write(dst_ep, ep, A6400_EP_SIZE);
        if (rc)
            return rc;
        if (ep_extra) {
            rc = copy_blob(dst_ep + 0x0c, ep_ptr, ep_extra);
            if (rc)
                return rc;
        }
        if (companion) {
            rc = copy_blob(dst_ep + 0x10, companion, 4);
            if (rc)
                return rc;
        }
    }
    return A6400_OK;
}

static int copy_config(u32 dst_cfg, u32 src_cfg)
{
    u8 cfg[A6400_CONFIG_SIZE];
    u32 iface_count, iface_array_src, iface_array_dst;
    u32 six_count, six_src, one_byte_src;
    u32 i;
    int rc;

    rc = tree_read(cfg, src_cfg, A6400_CONFIG_SIZE);
    if (rc)
        return rc;
    iface_count = cfg[2];
    iface_array_src = load_u32(cfg + 4);
    one_byte_src = load_u32(cfg + 0x0c);
    six_count = cfg[0x10];
    six_src = load_u32(cfg + 0x14);
    if (iface_count > A6400_MAX_INTERFACES)
        return A6400_ERANGE;
    if (iface_count && !range_ok(iface_array_src, iface_count * A6400_IFACE_SIZE))
        return A6400_EFAULT;
    if (six_count > 32u)
        return A6400_ERANGE;
    if (six_count && !range_ok(six_src, six_count * 6u))
        return A6400_EFAULT;
    if (one_byte_src && !range_ok(one_byte_src, 1))
        return A6400_EFAULT;
    store_u32(cfg + 4, 0);
    store_u32(cfg + 0x0c, 0);
    store_u32(cfg + 0x14, 0);
    rc = tree_write(dst_cfg, cfg, A6400_CONFIG_SIZE);
    if (rc)
        return rc;
    if (one_byte_src) {
        u8 byte = 0;
        void *p;
        rc = tree_read8(one_byte_src, &byte);
        if (rc)
            return rc;
        /* Native allocates a 4-byte cache object for a 1-byte blob. */
        p = tree_zalloc(4);
        if (!p)
            return A6400_ENOMEM;
        *(u8 *)p = byte;
        rc = tree_write32(dst_cfg + 0x0c, (u32)p);
        if (rc) {
            A_FREE(p);
            return rc;
        }
    }
    if (six_count) {
        void *p = tree_zalloc(six_count * 6u);
        if (!p)
            return A6400_ENOMEM;
        if (A_MEMCPY(p, (const void *)six_src, six_count * 6u) != p) {
            A_FREE(p);
            return A6400_EFAULT;
        }
        rc = tree_write32(dst_cfg + 0x14, (u32)p);
        if (rc) {
            A_FREE(p);
            return rc;
        }
    }
    if (!iface_count)
        return A6400_OK;
    iface_array_dst = (u32)tree_zalloc(iface_count * A6400_IFACE_SIZE);
    if (!iface_array_dst)
        return A6400_ENOMEM;
    rc = tree_write32(dst_cfg + 4, iface_array_dst);
    if (rc) {
        A_FREE((void *)iface_array_dst);
        return rc;
    }
    for (i = 0; i < iface_count; i++) {
        u32 dst_iface = iface_array_dst + i * A6400_IFACE_SIZE;
        u32 src_iface = iface_array_src + i * A6400_IFACE_SIZE;
        u8 grp[A6400_IFACE_SIZE];
        u32 alt_count, alt_array_src, alt_array_dst, j;
        rc = tree_read(grp, src_iface, A6400_IFACE_SIZE);
        if (rc)
            return rc;
        alt_count = grp[1];
        alt_array_src = load_u32(grp + 4);
        if (alt_count > A6400_MAX_ALTS)
            return A6400_ERANGE;
        if (alt_count && !range_ok(alt_array_src, alt_count * A6400_ALT_SIZE))
            return A6400_EFAULT;
        store_u32(grp + 4, 0);
        rc = tree_write(dst_iface, grp, A6400_IFACE_SIZE);
        if (rc)
            return rc;
        if (!alt_count)
            continue;
        alt_array_dst = (u32)tree_zalloc(alt_count * A6400_ALT_SIZE);
        if (!alt_array_dst)
            return A6400_ENOMEM;
        rc = tree_write32(dst_iface + 4, alt_array_dst);
        if (rc) {
            A_FREE((void *)alt_array_dst);
            return rc;
        }
        for (j = 0; j < alt_count; j++) {
            rc = copy_alternate(alt_array_dst + j * A6400_ALT_SIZE,
                                alt_array_src + j * A6400_ALT_SIZE);
            if (rc)
                return rc;
        }
    }
    return A6400_OK;
}

static int copy_record(u32 dst_record, u32 src_record)
{
    u8 rec[A6400_RECORD_SIZE];
    u32 cfg_count, cfg_array_src, cfg_array_dst;
    u32 i;
    int rc;

    rc = tree_read(rec, src_record, A6400_RECORD_SIZE);
    if (rc)
        return rc;
    cfg_count = rec[5];
    cfg_array_src = load_u32(rec + 8);
    if (cfg_count < 1u || cfg_count > A6400_MAX_CONFIGS)
        return A6400_ERANGE;
    if (!range_ok(cfg_array_src, cfg_count * A6400_CONFIG_SIZE))
        return A6400_EFAULT;
    store_u32(rec + 8, 0);
    rc = tree_write(dst_record, rec, A6400_RECORD_SIZE);
    if (rc)
        return rc;
    cfg_array_dst = (u32)tree_zalloc(cfg_count * A6400_CONFIG_SIZE);
    if (!cfg_array_dst)
        return A6400_ENOMEM;
    rc = tree_write32(dst_record + 8, cfg_array_dst);
    if (rc) {
        A_FREE((void *)cfg_array_dst);
        return rc;
    }
    for (i = 0; i < cfg_count; i++) {
        rc = copy_config(cfg_array_dst + i * A6400_CONFIG_SIZE,
                         cfg_array_src + i * A6400_CONFIG_SIZE);
        if (rc)
            return rc;
    }
    return A6400_OK;
}

static int copy_strings(u32 dst_root, u32 src_root)
{
    u8 root[A6400_ROOT_SIZE];
    u32 lang_count, lang_array_src, lang_array_dst;
    u32 i;
    int rc;

    rc = tree_read(root, src_root, A6400_ROOT_SIZE);
    if (rc)
        return rc;
    lang_count = root[0x3a];
    lang_array_src = load_u32(root + 0x3c);
    if (lang_count > A6400_MAX_LANGS)
        return A6400_ERANGE;
    if (lang_count && !range_ok(lang_array_src, lang_count * A6400_LANG_SIZE))
        return A6400_EFAULT;
    if (!lang_count)
        return A6400_OK;
    lang_array_dst = (u32)tree_zalloc(lang_count * A6400_LANG_SIZE);
    if (!lang_array_dst)
        return A6400_ENOMEM;
    rc = tree_write32(dst_root + 0x3c, lang_array_dst);
    if (rc) {
        A_FREE((void *)lang_array_dst);
        return rc;
    }
    for (i = 0; i < lang_count; i++) {
        u32 dst_lang = lang_array_dst + i * A6400_LANG_SIZE;
        u32 src_lang = lang_array_src + i * A6400_LANG_SIZE;
        u8 lang[A6400_LANG_SIZE];
        u32 string_count, strings_src, strings_dst, k;
        rc = tree_read(lang, src_lang, A6400_LANG_SIZE);
        if (rc)
            return rc;
        string_count = lang[2];
        strings_src = load_u32(lang + 4);
        if (string_count > A6400_MAX_STRINGS)
            return A6400_ERANGE;
        if (string_count && !range_ok(strings_src, string_count * A6400_STRING_SIZE))
            return A6400_EFAULT;
        store_u32(lang + 4, 0);
        rc = tree_write(dst_lang, lang, A6400_LANG_SIZE);
        if (rc)
            return rc;
        if (!string_count)
            continue;
        strings_dst = (u32)tree_zalloc(string_count * A6400_STRING_SIZE);
        if (!strings_dst)
            return A6400_ENOMEM;
        rc = tree_write32(dst_lang + 4, strings_dst);
        if (rc) {
            A_FREE((void *)strings_dst);
            return rc;
        }
        for (k = 0; k < string_count; k++) {
            u32 dst_str = strings_dst + k * A6400_STRING_SIZE;
            u32 src_str = strings_src + k * A6400_STRING_SIZE;
            u8 str[A6400_STRING_SIZE];
            u32 length, data_src;
            rc = tree_read(str, src_str, A6400_STRING_SIZE);
            if (rc)
                return rc;
            length = str[1];
            data_src = load_u32(str + 4);
            if (length > A6400_MAX_STRING_BYTES)
                return A6400_ERANGE;
            if (length && !range_ok(data_src, length))
                return A6400_EFAULT;
            store_u32(str + 4, 0);
            rc = tree_write(dst_str, str, A6400_STRING_SIZE);
            if (rc)
                return rc;
            if (length) {
                rc = copy_blob(dst_str + 4, data_src, length);
                if (rc)
                    return rc;
            }
        }
    }
    return A6400_OK;
}

/* ------------------------------------------------------------------ */
/* free                                                                */
/* ------------------------------------------------------------------ */

static void free_alternate(u32 alt)
{
    u8 raw[A6400_ALT_SIZE];
    u32 ep_array, ep_count, extra_ptr;
    u32 i;

    if (!range_ok(alt, A6400_ALT_SIZE))
        return;
    if (tree_read(raw, alt, A6400_ALT_SIZE))
        return;
    ep_count = raw[1];
    ep_array = load_u32(raw + 4);
    extra_ptr = load_u32(raw + 0x10);
    if (extra_ptr)
        A_FREE((void *)extra_ptr);
    if (!ep_count || ep_count > A6400_MAX_ENDPOINTS)
        return;
    if (!range_ok(ep_array, ep_count * A6400_EP_SIZE))
        return;
    for (i = 0; i < ep_count; i++) {
        u32 ep = ep_array + i * A6400_EP_SIZE;
        u32 ptr;
        if (tree_read32(ep + 0x0c, &ptr) == A6400_OK && ptr)
            A_FREE((void *)ptr);
        if (tree_read32(ep + 0x10, &ptr) == A6400_OK && ptr)
            A_FREE((void *)ptr);
    }
    A_FREE((void *)ep_array);
}

static void free_interface_array(u32 array, u32 count)
{
    u32 i;
    if (!array || !count || count > A6400_MAX_INTERFACES)
        return;
    if (!range_ok(array, count * A6400_IFACE_SIZE))
        return;
    for (i = 0; i < count; i++) {
        u32 iface = array + i * A6400_IFACE_SIZE;
        u8 grp[A6400_IFACE_SIZE];
        u32 alt_array, alt_count, j;
        if (tree_read(grp, iface, A6400_IFACE_SIZE))
            continue;
        alt_count = grp[1];
        alt_array = load_u32(grp + 4);
        if (!alt_array || !alt_count || alt_count > A6400_MAX_ALTS)
            continue;
        if (!range_ok(alt_array, alt_count * A6400_ALT_SIZE))
            continue;
        for (j = 0; j < alt_count; j++)
            free_alternate(alt_array + j * A6400_ALT_SIZE);
        A_FREE((void *)alt_array);
    }
    A_FREE((void *)array);
}

static void free_config_array(u32 array, u32 count)
{
    u32 i;
    if (!array || !count || count > A6400_MAX_CONFIGS)
        return;
    if (!range_ok(array, count * A6400_CONFIG_SIZE))
        return;
    for (i = 0; i < count; i++) {
        u32 cfg = array + i * A6400_CONFIG_SIZE;
        u8 raw[A6400_CONFIG_SIZE];
        u32 iface_array, iface_count, ptr;
        if (tree_read(raw, cfg, A6400_CONFIG_SIZE))
            continue;
        iface_count = raw[2];
        iface_array = load_u32(raw + 4);
        free_interface_array(iface_array, iface_count);
        ptr = load_u32(raw + 0x0c);
        if (ptr)
            A_FREE((void *)ptr);
        ptr = load_u32(raw + 0x14);
        if (ptr)
            A_FREE((void *)ptr);
    }
    A_FREE((void *)array);
}

static void free_record(u32 record)
{
    u8 raw[A6400_RECORD_SIZE];
    u32 count, array;
    if (!record || !range_ok(record, A6400_RECORD_SIZE))
        return;
    if (tree_read(raw, record, A6400_RECORD_SIZE))
        return;
    count = raw[5];
    array = load_u32(raw + 8);
    free_config_array(array, count);
}

/* Free a tree produced by tree_deepcopy()/tree_append_vendor_interface().
 * Unlike native free_desc_tbl() this frees all three per-speed records
 * (root+0x00, root+0x10 and root+0x20). */
static A_NOINLINE void tree_free(u32 root)
{
    u8 raw[A6400_ROOT_SIZE];
    u32 lang_array, lang_count, ptr;
    u32 i, j;

    if (!root)
        return;
    if (!range_ok(root, A6400_ROOT_SIZE)) {
        A_LOG("A6400TREE free REJECT root=%08x (outside kernel RAM)\n", root);
        return;
    }
    if (tree_read(raw, root, A6400_ROOT_SIZE))
        return;
    free_record(root + 0x00u);
    free_record(root + 0x10u);
    free_record(root + 0x20u);
    lang_count = raw[0x3a];
    lang_array = load_u32(raw + 0x3c);
    ptr = load_u32(raw + 0x44);
    if (ptr)
        A_FREE((void *)ptr);
    if (lang_array && lang_count && lang_count <= A6400_MAX_LANGS
        && range_ok(lang_array, lang_count * A6400_LANG_SIZE)) {
        for (i = 0; i < lang_count; i++) {
            u32 lang = lang_array + i * A6400_LANG_SIZE;
            u8 entry[A6400_LANG_SIZE];
            u32 strings, count;
            if (tree_read(entry, lang, A6400_LANG_SIZE))
                continue;
            count = entry[2];
            strings = load_u32(entry + 4);
            if (!strings || !count || count > A6400_MAX_STRINGS)
                continue;
            if (!range_ok(strings, count * A6400_STRING_SIZE))
                continue;
            for (j = 0; j < count; j++) {
                u32 data_ptr;
                if (tree_read32(strings + j * A6400_STRING_SIZE + 4, &data_ptr) == A6400_OK
                    && data_ptr)
                    A_FREE((void *)data_ptr);
            }
            A_FREE((void *)strings);
        }
        A_FREE((void *)lang_array);
    }
    ptr = load_u32(raw + 0x4c);
    if (ptr)
        A_FREE((void *)ptr);
    ptr = load_u32(raw + 0x50);
    if (ptr)
        A_FREE((void *)ptr);
    ptr = load_u32(raw + 0x54);
    if (ptr)
        A_FREE((void *)ptr);
    A_FREE((void *)root);
}

/* ------------------------------------------------------------------ */
/* deep copy entry point                                               */
/* ------------------------------------------------------------------ */

static A_NOINLINE int tree_deepcopy(u32 src_root, u32 *out_root)
{
    u8 root[A6400_ROOT_SIZE];
    u32 dst;
    u32 serial_len, serial_src;
    u32 blob4, blob8, blob16;
    int rc;

    if (!out_root)
        return A6400_EINVAL;
    *out_root = 0;
    if (!src_root || !range_ok(src_root, A6400_ROOT_SIZE))
        return A6400_EFAULT;
    rc = tree_read(root, src_root, A6400_ROOT_SIZE);
    if (rc)
        return rc;
    if (root[0x3a] > A6400_MAX_LANGS)
        return A6400_ERANGE;
    serial_len = load_u16(root + 0x40);
    serial_src = load_u32(root + 0x44);
    blob4 = load_u32(root + 0x4c);
    blob8 = load_u32(root + 0x50);
    blob16 = load_u32(root + 0x54);
    if (serial_len > A6400_MAX_STRING_BYTES)
        return A6400_ERANGE;
    if (serial_len && !range_ok(serial_src, serial_len))
        return A6400_EFAULT;
    if (blob4 && !range_ok(blob4, 4))
        return A6400_EFAULT;
    if (blob8 && !range_ok(blob8, 8))
        return A6400_EFAULT;
    if (blob16 && !range_ok(blob16, 16))
        return A6400_EFAULT;

    dst = (u32)tree_zalloc(A6400_ROOT_SIZE);
    if (!dst)
        return A6400_ENOMEM;
    /* Write only non-pointer bytes first: a partially copied node must never
     * contain a source pointer, otherwise tree_free() would free kernel
     * memory on the error path. */
    store_u32(root + 0x08, 0);
    store_u32(root + 0x18, 0);
    store_u32(root + 0x28, 0);
    store_u32(root + 0x3c, 0);
    store_u32(root + 0x44, 0);
    store_u32(root + 0x4c, 0);
    store_u32(root + 0x50, 0);
    store_u32(root + 0x54, 0);
    rc = tree_write(dst, root, A6400_ROOT_SIZE);
    if (rc)
        goto fail;

    rc = copy_record(dst + 0x00u, src_root + 0x00u);
    if (rc)
        goto fail;
    rc = copy_record(dst + 0x10u, src_root + 0x10u);
    if (rc)
        goto fail;
    rc = copy_record(dst + 0x20u, src_root + 0x20u);
    if (rc)
        goto fail;

    if (serial_len) {
        rc = copy_blob(dst + 0x44u, serial_src, serial_len);
        if (rc)
            goto fail;
    }
    rc = copy_strings(dst, src_root);
    if (rc)
        goto fail;
    if (blob4) {
        rc = copy_blob(dst + 0x4cu, blob4, 4);
        if (rc)
            goto fail;
    }
    if (blob8) {
        rc = copy_blob(dst + 0x50u, blob8, 8);
        if (rc)
            goto fail;
    }
    if (blob16) {
        rc = copy_blob(dst + 0x54u, blob16, 16);
        if (rc)
            goto fail;
    }
    *out_root = dst;
    return A6400_OK;

fail:
    tree_free(dst);
    return rc;
}

/* ------------------------------------------------------------------ */
/* append zero-endpoint vendor interface 1                             */
/* ------------------------------------------------------------------ */

static int append_to_config(u32 cfg)
{
    u8 raw[A6400_CONFIG_SIZE];
    u32 iface_count, iface_array_src, iface_array_dst, alt_array;
    u32 i;
    int rc;

    rc = tree_read(raw, cfg, A6400_CONFIG_SIZE);
    if (rc)
        return rc;
    iface_count = raw[2];
    iface_array_src = load_u32(raw + 4);
    if (iface_count < 1u || iface_count >= A6400_MAX_INTERFACES)
        return A6400_ERANGE;
    if (!range_ok(iface_array_src, iface_count * A6400_IFACE_SIZE))
        return A6400_EFAULT;
    for (i = 0; i < iface_count; i++) {
        u8 grp[A6400_IFACE_SIZE];
        rc = tree_read(grp, iface_array_src + i * A6400_IFACE_SIZE, A6400_IFACE_SIZE);
        if (rc)
            return rc;
        if (grp[0] == (u8)iface_count)
            return A6400_EINVAL;  /* number already used */
    }
    iface_array_dst = (u32)tree_zalloc((iface_count + 1u) * A6400_IFACE_SIZE);
    if (!iface_array_dst)
        return A6400_ENOMEM;
    if (A_MEMCPY((void *)iface_array_dst, (const void *)iface_array_src,
                 iface_count * A6400_IFACE_SIZE) != (void *)iface_array_dst) {
        A_FREE((void *)iface_array_dst);
        return A6400_EFAULT;
    }
    alt_array = (u32)tree_zalloc(A6400_ALT_SIZE);
    if (!alt_array) {
        A_FREE((void *)iface_array_dst);
        return A6400_ENOMEM;
    }
    {
        u8 alt[A6400_ALT_SIZE];
        A_MEMSET(alt, 0, A6400_ALT_SIZE);
        alt[0] = 0;                                   /* bAlternateSetting */
        alt[1] = 0;                                   /* bNumEndpoints     */
        alt[8] = A6400_VENDOR_CLASS;
        alt[9] = A6400_VENDOR_SUBCLASS;
        alt[10] = A6400_VENDOR_PROTOCOL;
        alt[11] = 0;                                  /* iInterface        */
        rc = tree_write(alt_array, alt, A6400_ALT_SIZE);
        if (rc) {
            A_FREE((void *)alt_array);
            A_FREE((void *)iface_array_dst);
            return rc;
        }
    }
    {
        u8 grp[A6400_IFACE_SIZE];
        A_MEMSET(grp, 0, A6400_IFACE_SIZE);
        grp[0] = (u8)iface_count;
        grp[1] = 1;
        store_u32(grp + 4, alt_array);
        rc = tree_write(iface_array_dst + iface_count * A6400_IFACE_SIZE,
                        grp, A6400_IFACE_SIZE);
        if (rc) {
            A_FREE((void *)alt_array);
            A_FREE((void *)iface_array_dst);
            return rc;
        }
    }
    rc = tree_write32(cfg + 4u, iface_array_dst);
    if (rc) {
        A_FREE((void *)alt_array);
        A_FREE((void *)iface_array_dst);
        return rc;
    }
    rc = tree_write8(cfg + 2u, (u8)(iface_count + 1u));
    if (rc) {
        /* Roll the pointer back so the tree stays self-consistent. */
        (void)tree_write32(cfg + 4u, iface_array_src);
        A_FREE((void *)alt_array);
        A_FREE((void *)iface_array_dst);
        return rc;
    }
    A_FREE((void *)iface_array_src);
    return A6400_OK;
}

static int append_to_record(u32 record)
{
    u8 raw[A6400_RECORD_SIZE];
    u32 count, array, i;
    int rc;

    rc = tree_read(raw, record, A6400_RECORD_SIZE);
    if (rc)
        return rc;
    count = raw[5];
    array = load_u32(raw + 8);
    if (!count || count > A6400_MAX_CONFIGS || !array)
        return A6400_ERANGE;
    if (!range_ok(array, count * A6400_CONFIG_SIZE))
        return A6400_EFAULT;
    for (i = 0; i < count; i++) {
        rc = append_to_config(array + i * A6400_CONFIG_SIZE);
        if (rc)
            return rc;
    }
    return A6400_OK;
}

static A_NOINLINE int tree_append_vendor_interface(u32 root)
{
    int rc;
    if (!root || !range_ok(root, A6400_ROOT_SIZE))
        return A6400_EFAULT;
    /* All three per-speed records get the interface so that whichever record
     * the serializer selects always serves the vendor function. */
    rc = append_to_record(root + 0x00u);
    if (rc)
        return rc;
    rc = append_to_record(root + 0x10u);
    if (rc)
        return rc;
    rc = append_to_record(root + 0x20u);
    if (rc)
        return rc;
    return A6400_OK;
}

/* ------------------------------------------------------------------ */
/* validation                                                          */
/* ------------------------------------------------------------------ */

static int extra_ok(u32 size, u32 ptr)
{
    if (!size)
        return ptr == 0;
    if (size > A6400_MAX_EXTRA)
        return 0;
    return range_ok(ptr, size);
}

static int optional_blob_ok(u32 ptr, u32 size)
{
    if (!ptr)
        return 1;
    return range_ok(ptr, size);
}

static int validate_config(u32 cfg, u32 speed)
{
    u8 raw[A6400_CONFIG_SIZE];
    u32 iface_count, iface_array, total;
    u32 numbers[A6400_MAX_INTERFACES];
    u32 used_eps = 0;
    u32 i, j, k;

    if (tree_read(raw, cfg, A6400_CONFIG_SIZE))
        return A6400_EFAULT;
    iface_count = raw[2];
    iface_array = load_u32(raw + 4);
    if (raw[0] > 7u)
        return A6400_EINVAL;          /* GET_DESCRIPTOR config index */
    if (raw[1] == 0)
        return A6400_EINVAL;          /* bConfigurationValue        */
    if (iface_count < 1u || iface_count > A6400_MAX_INTERFACES)
        return A6400_ERANGE;
    if (!range_ok(iface_array, iface_count * A6400_IFACE_SIZE))
        return A6400_EFAULT;
    if (raw[9] == 0)
        return A6400_EINVAL;          /* bmAttributes must be non-zero */
    if (load_u32(raw + 0x0c)) {
        if (!range_ok(load_u32(raw + 0x0c), 1))
            return A6400_EFAULT;
        total = 12u;
    } else {
        total = 9u;
    }
    if (load_u32(raw + 0x14)) {
        if (raw[0x10] > 32u
            || !range_ok(load_u32(raw + 0x14), (u32)raw[0x10] * 6u))
            return A6400_EFAULT;
    }
    for (i = 0; i < iface_count; i++) {
        u8 grp[A6400_IFACE_SIZE];
        u32 alt_count, alt_array;
        if (tree_read(grp, iface_array + i * A6400_IFACE_SIZE, A6400_IFACE_SIZE))
            return A6400_EFAULT;
        numbers[i] = grp[0];
        for (j = 0; j < i; j++)
            if (numbers[j] == numbers[i])
                return A6400_EINVAL;
        if (grp[0] >= 128u)
            return A6400_EINVAL;
        alt_count = grp[1];
        alt_array = load_u32(grp + 4);
        if (alt_count < 1u || alt_count > A6400_MAX_ALTS)
            return A6400_ERANGE;
        if (!range_ok(alt_array, alt_count * A6400_ALT_SIZE))
            return A6400_EFAULT;
        for (j = 0; j < alt_count; j++) {
            u8 alt[A6400_ALT_SIZE];
            u32 ep_count, ep_array, extra_size, extra_ptr;
            if (tree_read(alt, alt_array + j * A6400_ALT_SIZE, A6400_ALT_SIZE))
                return A6400_EFAULT;
            if (j == 0 && alt[0] != 0)
                return A6400_EINVAL;      /* alternate 0 must exist */
            ep_count = alt[1];
            ep_array = load_u32(alt + 4);
            extra_size = load_u32(alt + 0x0c);
            extra_ptr = load_u32(alt + 0x10);
            if (!extra_ok(extra_size, extra_ptr))
                return A6400_EINVAL;
            if (ep_count > A6400_MAX_ENDPOINTS)
                return A6400_ERANGE;
            if (ep_count && !range_ok(ep_array, ep_count * A6400_EP_SIZE))
                return A6400_EFAULT;
            total += 9u;
            if (extra_size)
                total += (extra_size & 0xffffu);
            for (k = 0; k < ep_count; k++) {
                u8 ep[A6400_EP_SIZE];
                u32 ep_extra, ep_ptr, companion, slot;
                if (tree_read(ep, ep_array + k * A6400_EP_SIZE, A6400_EP_SIZE))
                    return A6400_EFAULT;
                ep_extra = load_u32(ep + 8);
                ep_ptr = load_u32(ep + 0x0c);
                companion = load_u32(ep + 0x10);
                if (!extra_ok(ep_extra, ep_ptr))
                    return A6400_EINVAL;
                if (companion && !range_ok(companion, 4))
                    return A6400_EFAULT;
                slot = ep[0] & 0x0fu;
                if (used_eps & (1u << slot))
                    return A6400_EINVAL;  /* duplicate endpoint number */
                used_eps |= 1u << slot;
                total += 7u;
                if (speed == 5u && companion)
                    total += 6u;
                if (ep_extra)
                    total += (ep_extra & 0xffffu);
                if (total > A6400_MAX_TOTAL_DESC)
                    return A6400_ERANGE;
            }
        }
    }
    return total > A6400_MAX_TOTAL_DESC ? A6400_ERANGE : A6400_OK;
}

static int validate_record(u32 record, u32 speed)
{
    u8 raw[A6400_RECORD_SIZE];
    u32 count, array, i;
    if (tree_read(raw, record, A6400_RECORD_SIZE))
        return A6400_EFAULT;
    count = raw[5];
    array = load_u32(raw + 8);
    if (count < 1u || count > A6400_MAX_CONFIGS)
        return A6400_ERANGE;
    if (!array || !range_ok(array, count * A6400_CONFIG_SIZE))
        return A6400_EFAULT;
    for (i = 0; i < count; i++) {
        int rc = validate_config(array + i * A6400_CONFIG_SIZE, speed);
        if (rc)
            return rc;
    }
    return A6400_OK;
}

static A_NOINLINE int tree_validate(u32 root)
{
    u8 raw[A6400_ROOT_SIZE];
    u32 lang_count, lang_array;
    u32 i, j;
    int rc;

    if (!root || !range_ok(root, A6400_ROOT_SIZE))
        return A6400_EFAULT;
    rc = tree_read(raw, root, A6400_ROOT_SIZE);
    if (rc)
        return rc;
    rc = validate_record(root + 0x00u, 3u);
    if (rc)
        return rc;
    rc = validate_record(root + 0x10u, 2u);
    if (rc)
        return rc;
    rc = validate_record(root + 0x20u, 5u);
    if (rc)
        return rc;
    {
        u32 serial_len = load_u16(raw + 0x40);
        u32 serial_ptr = load_u32(raw + 0x44);
        if (serial_len > A6400_MAX_STRING_BYTES)
            return A6400_ERANGE;
        if (serial_len && !range_ok(serial_ptr, serial_len))
            return A6400_EFAULT;
    }
    if (!optional_blob_ok(load_u32(raw + 0x4c), 4)
        || !optional_blob_ok(load_u32(raw + 0x50), 8)
        || !optional_blob_ok(load_u32(raw + 0x54), 16))
        return A6400_EINVAL;
    lang_count = raw[0x3a];
    lang_array = load_u32(raw + 0x3c);
    if (lang_count > A6400_MAX_LANGS)
        return A6400_ERANGE;
    if (!lang_count)
        return lang_array ? A6400_EINVAL : A6400_OK;
    if (!lang_array || !range_ok(lang_array, lang_count * A6400_LANG_SIZE))
        return A6400_EFAULT;
    for (i = 0; i < lang_count; i++) {
        u8 entry[A6400_LANG_SIZE];
        u32 strings, count;
        if (tree_read(entry, lang_array + i * A6400_LANG_SIZE, A6400_LANG_SIZE))
            return A6400_EFAULT;
        count = entry[2];
        strings = load_u32(entry + 4);
        if (count > A6400_MAX_STRINGS)
            return A6400_ERANGE;
        if (!count) {
            if (strings)
                return A6400_EINVAL;
            continue;
        }
        if (!strings || !range_ok(strings, count * A6400_STRING_SIZE))
            return A6400_EFAULT;
        for (j = 0; j < count; j++) {
            u8 str[A6400_STRING_SIZE];
            u32 length, data_ptr;
            if (tree_read(str, strings + j * A6400_STRING_SIZE, A6400_STRING_SIZE))
                return A6400_EFAULT;
            length = str[1];
            data_ptr = load_u32(str + 4);
            if (length > A6400_MAX_STRING_BYTES)
                return A6400_ERANGE;
            if (length && !range_ok(data_ptr, length))
                return A6400_EFAULT;
        }
    }
    return A6400_OK;
}

/* ------------------------------------------------------------------ */
/* patch / restore                                                     */
/* ------------------------------------------------------------------ */

static u32 record_offset(void)
{
    if (g_state.speed == 5u)
        return 0x20u;
    if (g_state.speed == 3u)
        return 0x00u;
    return 0x10u;
}

/* 0 = stock, 1 = MS OS 2.0 patched, negative = unreadable/unknown. */
static int os_state(u32 *crc_out)
{
    u8 current[A6400_OS_STRING_LEN];
    u32 crc;
    if (A_READ(current, (const void *)A6400_OS_STRING_VA, A6400_OS_STRING_LEN))
        return A6400_EFAULT;
    crc = crc32_bytes(current, A6400_OS_STRING_LEN);
    if (crc_out)
        *crc_out = crc;
    if (bytes_equal(current, stock_os, A6400_OS_STRING_LEN))
        return 0;
    if (bytes_equal(current, os20_os, A6400_OS_STRING_LEN))
        return 1;
    return A6400_EIO;
}

static int patch_os(struct a6400_tree_state *state)
{
    u32 crc = 0;
    if (A_READ(state->saved_os, (const void *)A6400_OS_STRING_VA, A6400_OS_STRING_LEN))
        return A6400_EFAULT;
    state->saved_os_crc = crc32_bytes(state->saved_os, A6400_OS_STRING_LEN);
    if (!bytes_equal(state->saved_os, stock_os, A6400_OS_STRING_LEN))
        return A6400_EIO;
    /* Mark before writing: a partially completed probe write must still be
     * restored by the failure path. */
    state->patched_os = 1;
    if (A_WRITE((void *)A6400_OS_STRING_VA, os20_os, A6400_OS_STRING_LEN))
        return A6400_EFAULT;
    if (os_state(&crc) != 1)
        return A6400_EIO;
    return A6400_OK;
}

static int patch_mode(struct a6400_tree_state *state)
{
    u8 mode = 0;
    if (tree_read8(state->gc + A6400_GC_MODE, &mode))
        return A6400_EFAULT;
    if (mode != 0)
        return A6400_EINVAL;
    state->saved_mode = mode;
    state->patched_mode = 1;
    if (tree_write8(state->gc + A6400_GC_MODE, 1))
        return A6400_EFAULT;
    if (tree_read8(state->gc + A6400_GC_MODE, &mode) || mode != 1)
        return A6400_EIO;
    return A6400_OK;
}

static int patch_bcdusb(struct a6400_tree_state *state, u32 target_root)
{
    u16 value = 0;
    u32 addr;
    if (!target_root || !range_ok(target_root, A6400_ROOT_SIZE))
        return A6400_EFAULT;
    addr = target_root + record_offset();
    if (!range_ok(addr, 2))
        return A6400_EFAULT;
    if (tree_read16(addr, &value))
        return A6400_EFAULT;
    if (value != A6400_BCDUSB_STOCK)
        return A6400_EINVAL;
    state->bcdusb_addr = addr;
    state->saved_bcdusb = value;
    state->patched_bcdusb = 1;
    if (tree_write16(addr, A6400_BCDUSB_OS20))
        return A6400_EFAULT;
    if (tree_read16(addr, &value) || value != A6400_BCDUSB_OS20)
        return A6400_EIO;
    return A6400_OK;
}

static A_NOINLINE void tree_restore_patches(struct a6400_tree_state *state)
{
    unsigned int attempt;
    int ok = 0;

    for (attempt = 0; attempt < 3u && !ok; attempt++) {
        int os_ok = 1, mode_ok = 1, bcd_ok = 1;
        u32 crc = 0;
        u8 mode = 0;
        u16 bcd = 0;
        if (state->patched_os) {
            if (A_WRITE((void *)A6400_OS_STRING_VA, state->saved_os, A6400_OS_STRING_LEN))
                os_ok = 0;
            if (os_ok && os_state(&crc) != 0)
                os_ok = 0;
        }
        if (state->patched_mode) {
            if (tree_write8(state->gc + A6400_GC_MODE, state->saved_mode))
                mode_ok = 0;
            if (mode_ok
                && (tree_read8(state->gc + A6400_GC_MODE, &mode) || mode != state->saved_mode))
                mode_ok = 0;
        }
        if (state->patched_bcdusb) {
            if (tree_write16(state->bcdusb_addr, state->saved_bcdusb))
                bcd_ok = 0;
            if (bcd_ok
                && (tree_read16(state->bcdusb_addr, &bcd) || bcd != state->saved_bcdusb))
                bcd_ok = 0;
        }
        ok = os_ok && mode_ok && bcd_ok;
    }
    A_LOG("A6400TREE RESTORE os_crc=%08x os=%u mode=%u bcdusb=%04x bcd=%u ok=%d attempts=%u\n",
          crc32_bytes(stock_os, A6400_OS_STRING_LEN), (unsigned)state->patched_os,
          (unsigned)state->saved_mode, (unsigned)state->saved_bcdusb,
          (unsigned)state->patched_bcdusb, ok, attempt);
    if (ok) {
        state->patched_os = 0;
        state->patched_mode = 0;
        state->patched_bcdusb = 0;
    }
}

static A_NOINLINE int tree_apply_patches(struct a6400_tree_state *state, u32 target_root)
{
    int rc;
    rc = patch_os(state);
    if (rc)
        goto fail;
    rc = patch_mode(state);
    if (rc)
        goto fail;
    rc = patch_bcdusb(state, target_root);
    if (rc)
        goto fail;
    A_LOG("A6400TREE PATCH_OK os_crc=%08x mode=1 speed=%u record=%08x bcdusb=0210\n",
          A6400_OS_CRC_OS20, (unsigned)state->speed, state->bcdusb_addr);
    return A6400_OK;
fail:
    A_LOG("A6400TREE PATCH_FAIL rc=%d os=%u mode=%u bcd=%u\n", rc,
          (unsigned)state->patched_os, (unsigned)state->patched_mode,
          (unsigned)state->patched_bcdusb);
    tree_restore_patches(state);
    return rc;
}

/* ------------------------------------------------------------------ */
/* quiesce / root swap                                                 */
/* ------------------------------------------------------------------ */

static int tree_gadget_pullup(u32 gadget, int on)
{
    u32 ops = 0, fn = 0;
    int rc;
    if (!gadget)
        return A6400_EINVAL;
    rc = tree_read32(gadget + 0x10u, &ops);
    if (rc || !ops)
        return A6400_EIO;
    rc = tree_read32(ops + 0x14u, &fn);
    if (rc || !fn)
        return A6400_EOPNOTSUPP;
    return ((int (*)(u32, int))fn)(gadget, on);
}

static int read_gc(u32 *gc_out)
{
    u32 gc = 0;
    if (tree_read32(A6400_GC_SLOT_VA, &gc))
        return A6400_EFAULT;
    if (!gc || !range_ok(gc, 0x90))
        return A6400_EFAULT;
    *gc_out = gc;
    return A6400_OK;
}

static int read_gadget(u32 gc, u32 *gadget_out)
{
    u32 gadget = 0;
    if (tree_read32(gc, &gadget))
        return A6400_EFAULT;
    if (!gadget || !range_ok(gadget, 0x28))
        return A6400_EFAULT;
    *gadget_out = gadget;
    return A6400_OK;
}

/* 1 = started gate set, 0 = idle, negative = unreadable. */
static int read_udc_state(u32 gc, u8 *configured)
{
    u32 flags = 0;
    u8 config = 0;
    if (tree_read32(gc + A6400_GC_FLAGS, &flags))
        return A6400_EFAULT;
    if (tree_read8(gc + A6400_GC_CONFIG, &config))
        return A6400_EFAULT;
    if (configured)
        *configured = config;
    return (flags & A6400_STARTED_BIT) ? 1 : 0;
}

/* Native ioctl stop order: clear gc+0x68 bit 2, pull D+ low, setup_disconnect,
 * usb_gcw_stop.  Only process context; the caller must be the module's own
 * entry point. */
static A_NOINLINE int tree_quiesce(struct a6400_tree_state *state)
{
    u32 flags = 0, gadget = 0;
    u8 config = 0;
    int running, rc;

    if (!state->gc)
        return A6400_EINVAL;
    running = read_udc_state(state->gc, &config);
    if (running < 0)
        return running;
    if (running == 0 && config == 0) {
        state->quiesced = 1;
        return A6400_OK;
    }
    if (read_gadget(state->gc, &gadget))
        return A6400_EFAULT;
    if (running) {
        if (tree_read32(state->gc + A6400_GC_FLAGS, &flags))
            return A6400_EFAULT;
        flags &= ~(u32)A6400_STARTED_BIT;
        if (tree_write32(state->gc + A6400_GC_FLAGS, flags))
            return A6400_EFAULT;
    }
    rc = tree_gadget_pullup(gadget, 0);
    (void)call_stop_disconnect(state->gc);
    (void)call_gcw_stop();
    if (rc)
        return rc;
    if (tree_read8(state->gc + A6400_GC_CONFIG, &config) || config != 0) {
        A_LOG("A6400TREE QUIESCE_BUSY config=%u\n", (unsigned)config);
        return A6400_EBUSY;
    }
    state->quiesced = 1;
    A_LOG("A6400TREE QUIESCE_OK gc=%08x\n", state->gc);
    return A6400_OK;
}

static A_NOINLINE int tree_install_root(struct a6400_tree_state *state)
{
    u32 current = 0;
    if (!state->quiesced)
        return A6400_EBUSY;
    if (!state->module_root || !range_ok(state->module_root, A6400_ROOT_SIZE))
        return A6400_EINVAL;
    if (tree_read32(state->gc + A6400_GC_ROOT, &current))
        return A6400_EFAULT;
    if (current != state->orig_root)
        return A6400_EBUSY;
    if (tree_write32(state->gc + A6400_GC_ROOT, state->module_root))
        return A6400_EFAULT;
    /* Mark ownership before verification: if the read-back fails, the unload
     * path must re-read gc+0x6c and never free a tree that may still be
     * installed. */
    state->root_installed = 1;
    if (tree_read32(state->gc + A6400_GC_ROOT, &current)
        || current != state->module_root)
        return A6400_EIO;
    return A6400_OK;
}

/* 0 = restored or not owner, positive = gc+0x6c points at someone else's
 * tree, negative = read/write/verify failure (the caller must not free). */
static A_NOINLINE int tree_restore_root(struct a6400_tree_state *state)
{
    u32 current = 0;
    if (!state->root_installed)
        return 0;
    if (tree_read32(state->gc + A6400_GC_ROOT, &current)) {
        state->root_installed = 1;
        return A6400_EFAULT;
    }
    if (current != state->module_root) {
        state->root_installed = 0;
        return 1;
    }
    if (tree_write32(state->gc + A6400_GC_ROOT, state->orig_root))
        return A6400_EFAULT;
    if (tree_read32(state->gc + A6400_GC_ROOT, &current)
        || current != state->orig_root)
        return A6400_EIO;
    state->root_installed = 0;
    return 0;
}

/* ------------------------------------------------------------------ */
/* preflight and module entry points                                   */
/* ------------------------------------------------------------------ */

static int tree_preflight(struct a6400_tree_state *state)
{
    u32 gc = 0, gadget = 0, root = 0;
    u8 speed = 0, mode = 0;
    u16 bcd = 0;
    u32 crc = 0;
    int running;
    u8 configured = 0;

    if (read_gc(&gc))
        return A6400_EFAULT;
    if (read_gadget(gc, &gadget))
        return A6400_EFAULT;
    if (tree_read32(gc + A6400_GC_ROOT, &root) || !root
        || !range_ok(root, A6400_ROOT_SIZE))
        return A6400_EFAULT;
    /* Latch the host speed BEFORE pullup(0): dwc3_gadget_pullup(gadget, 0)
     * writes 0 to gadget.speed, so a later read would select the wrong
     * per-speed record. */
    if (tree_read8(gadget + 0x20u, &speed))
        return A6400_EFAULT;
    if (tree_read8(gc + A6400_GC_MODE, &mode))
        return A6400_EFAULT;
    if (mode != 0)
        return A6400_EBUSY;
    if (tree_read16(root + (speed == 5u ? 0x20u : (speed == 3u ? 0x00u : 0x10u)), &bcd))
        return A6400_EFAULT;
    if (bcd != A6400_BCDUSB_STOCK)
        return A6400_EINVAL;
    if (os_state(&crc) != 0)
        return A6400_EIO;
    state->gc = gc;
    state->orig_root = root;
    state->speed = speed;
    running = read_udc_state(gc, &configured);
    if (running < 0)
        return running;
    A_LOG("A6400TREE PREFLIGHT gc=%08x root=%08x gadget=%08x speed=%u bcdusb=%04x started=%d config=%u os_crc=%08x\n",
          gc, root, gadget, (unsigned)speed, (unsigned)bcd, running,
          (unsigned)configured, crc);
    return A6400_OK;
}

static A_NOINLINE void tree_unload(struct a6400_tree_state *state)
{
    int installed = 0;
    int rc = A6400_OK;

    if (!state->module_root) {
        A_LOG("A6400TREE exit inactive\n");
        return;
    }
    if (state->root_installed) {
        u32 current = 0;
        if (tree_read32(state->gc + A6400_GC_ROOT, &current)) {
            installed = 1;   /* unknown: assume ours, leak rather than free */
        } else if (current == state->module_root) {
            installed = 1;
        } else {
            state->root_installed = 0;   /* app-installed tree: not ours */
        }
    }
    if (installed) {
        u8 configured = 0;
        int running = read_udc_state(state->gc, &configured);
        if (running != 0 || configured != 0) {
            rc = tree_quiesce(state);
            if (!rc)
                running = read_udc_state(state->gc, &configured);
        }
        if (rc || running != 0 || configured != 0 || state->gc == 0) {
            A_LOG("A6400TREE LEAK rc=%d running=%d config=%u gc=%08x module_root=%08x (UDC not proven stopped)\n",
                  rc, running, (unsigned)configured, state->gc, state->module_root);
            tree_restore_patches(state);
            state->module_root = 0;
            state->root_installed = 0;
            return;
        }
        tree_restore_patches(state);
        rc = tree_restore_root(state);
        if (rc) {
            A_LOG("A6400TREE LEAK root_restore rc=%d module_root=%08x\n",
                  rc, state->module_root);
            state->module_root = 0;
            state->root_installed = 0;
            return;
        }
    } else {
        tree_restore_patches(state);
    }
    A_LOG("A6400TREE FREE_BEGIN root=%08x\n", state->module_root);
    tree_free(state->module_root);
    A_LOG("A6400TREE FREE_OK\n");
    state->module_root = 0;
}

int init_module(void)
{
    int rc;

    if (g_state.module_root || g_state.root_installed) {
        A_LOG("A6400TREE init BUSY already active module_root=%08x\n",
              g_state.module_root);
        return A6400_EBUSY;
    }
    A_MEMSET(&g_state, 0, (u32)sizeof(g_state));
    A_LOG("A6400TREE init begin\n");
    rc = tree_preflight(&g_state);
    if (rc) {
        A_LOG("A6400TREE PRECHECK_REJECT rc=%d\n", rc);
        return rc;
    }
    rc = tree_quiesce(&g_state);
    if (rc)
        goto fail;
    rc = tree_deepcopy(g_state.orig_root, &g_state.module_root);
    if (rc) {
        A_LOG("A6400TREE DEEPCOPY_FAIL rc=%d\n", rc);
        goto fail;
    }
    rc = tree_append_vendor_interface(g_state.module_root);
    if (rc) {
        A_LOG("A6400TREE APPEND_FAIL rc=%d\n", rc);
        goto fail;
    }
    rc = tree_validate(g_state.module_root);
    if (rc) {
        A_LOG("A6400TREE VALIDATE_FAIL rc=%d\n", rc);
        goto fail;
    }
    {
        u32 current = 0;
        if (tree_read32(g_state.gc + A6400_GC_ROOT, &current)
            || current != g_state.orig_root) {
            rc = A6400_EBUSY;
            A_LOG("A6400TREE SOURCE_MOVED rc=%d\n", rc);
            goto fail;
        }
    }
    rc = tree_apply_patches(&g_state, g_state.module_root);
    if (rc)
        goto fail;
    rc = tree_install_root(&g_state);
    if (rc)
        goto fail;
    {
        u32 root_now = 0;
        u16 served = 0;
        if (tree_read32(g_state.gc + A6400_GC_ROOT, &root_now)
            || root_now != g_state.module_root
            || tree_read16(root_now + record_offset(), &served)
            || served != A6400_BCDUSB_OS20) {
            rc = A6400_EIO;
            A_LOG("A6400TREE SWAP_VERIFY_FAIL rc=%d\n", rc);
            goto fail;
        }
    }
    A_LOG("A6400TREE INSTALL_OK module_root=%08x orig=%08x speed=%u record=%08x\n",
          g_state.module_root, g_state.orig_root, (unsigned)g_state.speed,
          g_state.bcdusb_addr);
    return A6400_OK;

fail:
    tree_unload(&g_state);
    return rc;
}

void cleanup_module(void)
{
    A_LOG("A6400TREE cleanup begin\n");
    tree_unload(&g_state);
    A_LOG("A6400TREE cleanup done\n");
}
