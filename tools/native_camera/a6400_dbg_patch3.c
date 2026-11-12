/* E0407a: three-target bounded save/restore, no descriptor or USB changes. */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef unsigned int usize;

__attribute__((section(".modinfo"), used)) static const char a6400_license[] = "license=GPL";
__attribute__((section(".modinfo"), used)) static const char a6400_author[] = "author=a6400 research";
__attribute__((section(".modinfo"), used)) static const char a6400_description[] =
    "description=three-target RAM save/restore for E0407a";

extern int printk(const char *format, ...);
extern void *memcpy(void *dest, const void *src, usize count);
extern int probe_kernel_read(void *dst, const void *src, usize size);
extern int probe_kernel_write(void *dst, const void *src, usize size);

#define OS_STRING_VA 0x604E5130u
#define OS_STRING_LEN 18u
#define GC_SLOT_VA 0x6051B17Cu
#define GC_MODE 0x84u
#define GC_ROOT 0x6Cu
#define BCDUSB_STOCK 0x0200u
#define BCDUSB_OS20 0x0210u

static const u8 stock_os[OS_STRING_LEN] = {
    0x12, 0x03, 0x4d, 0x00, 0x53, 0x00, 0x46, 0x00, 0x54, 0x00,
    0x31, 0x00, 0x30, 0x00, 0x30, 0x00, 0x30, 0x00};
static const u8 os20_os[OS_STRING_LEN] = {
    0x12, 0x03, 0x4d, 0x00, 0x53, 0x00, 0x46, 0x00, 0x54, 0x00,
    0x32, 0x00, 0x30, 0x00, 0x00, 0x00, 0x02, 0x00};

static u8 saved_os[OS_STRING_LEN];
static u8 saved_mode;
static u16 saved_bcdusb;
static u32 gc_ptr, bcdusb_address;
static int patched_os, patched_mode, patched_bcdusb;

static u32 crc32_bytes(const u8 *data, usize length)
{
    u32 crc = 0xffffffffu;
    usize i, bit;
    for (i = 0; i < length; i++) {
        crc ^= data[i];
        for (bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ (0xedb88320u & (u32)-(int)(crc & 1u));
    }
    return ~crc;
}

static int bytes_equal(const u8 *a, const u8 *b, usize length)
{
    usize i;
    for (i = 0; i < length; i++) if (a[i] != b[i]) return 0;
    return 1;
}

static int os_state(u32 *crc_out)
{
    u8 current[OS_STRING_LEN];
    if (probe_kernel_read(current, (const void *)OS_STRING_VA, OS_STRING_LEN))
        return -5;
    *crc_out = crc32_bytes(current, OS_STRING_LEN);
    if (bytes_equal(current, stock_os, OS_STRING_LEN)) return 0;
    if (bytes_equal(current, os20_os, OS_STRING_LEN)) return 1;
    return -5;
}

static int select_bcdusb(void)
{
    u32 gadget = 0, root = 0;
    u8 speed = 0;
    u32 record;
    if (probe_kernel_read(&gc_ptr, (const void *)GC_SLOT_VA, 4) || !gc_ptr)
        return -5;
    if (gc_ptr < 0x60000000u || gc_ptr > 0x6fffffffu) return -5;
    if (probe_kernel_read(&gadget, (const void *)gc_ptr, 4) || !gadget)
        return -5;
    if (probe_kernel_read(&speed, (const void *)(gadget + 0x20u), 1)) return -5;
    if (probe_kernel_read(&root, (const void *)(gc_ptr + GC_ROOT), 4) || !root)
        return -5;
    if (root < 0x60000000u || root > 0x6fffffffu) return -5;
    record = root + (speed == 5u ? 0x20u : (speed == 3u ? 0x10u : 0x00u));
    if (probe_kernel_read(&saved_bcdusb, (const void *)record, 2)) return -5;
    bcdusb_address = record;
    return saved_bcdusb == BCDUSB_STOCK ? 0 : -5;
}

static int mode_value(u8 *value)
{
    return probe_kernel_read(value, (const void *)(gc_ptr + GC_MODE), 1);
}

static void restore_all(void)
{
    unsigned int attempt;
    u32 os_crc = 0;
    u8 mode = 0xFF;
    u16 bcdusb = 0;
    int os_ok = 0, mode_ok = 0, bcdusb_ok = 0;

    for (attempt = 0; attempt < 3; attempt++) {
        if (patched_os) {
            (void)probe_kernel_write((void *)OS_STRING_VA, saved_os, OS_STRING_LEN);
            os_ok = os_state(&os_crc) == 0;
        } else os_ok = 1;
        if (patched_mode) {
            (void)probe_kernel_write((void *)(gc_ptr + GC_MODE), &saved_mode, 1);
            mode_ok = mode_value(&mode) == 0 && mode == saved_mode;
        } else mode_ok = 1;
        if (patched_bcdusb) {
            (void)probe_kernel_write((void *)bcdusb_address, &saved_bcdusb, 2);
            bcdusb_ok = probe_kernel_read(&bcdusb, (const void *)bcdusb_address, 2) == 0
                        && bcdusb == saved_bcdusb;
        } else bcdusb_ok = 1;
        if (os_ok && mode_ok && bcdusb_ok) break;
    }
    printk("A6400DBG3 RESTORE_OK os_crc=%08x os_ok=%d mode=%u mode_ok=%d bcdusb=%04x bcdusb_ok=%d attempts=%u\n",
           os_crc, os_ok, (unsigned)mode, mode_ok, (unsigned)bcdusb, bcdusb_ok, attempt + 1);
}

int init_module(void)
{
    u32 os_crc = 0;
    u8 mode = 0;
    u16 current_bcdusb = 0;
    u8 one = 1;
    u16 os20 = BCDUSB_OS20;
    int error;

    printk("A6400DBG3 init begin\n");
    if (os_state(&os_crc) != 0) {
        printk("A6400DBG3 PRECHECK_REJECT_OS crc=%08x\n", os_crc);
        return -5;
    }
    memcpy(saved_os, (const void *)OS_STRING_VA, OS_STRING_LEN);
    if (select_bcdusb()) {
        printk("A6400DBG3 PRECHECK_REJECT_BCDUSB bcdusb=%04x\n", (unsigned)saved_bcdusb);
        return -5;
    }
    if (mode_value(&mode) || mode != 0) {
        printk("A6400DBG3 PRECHECK_REJECT_MODE value=%u\n", (unsigned)mode);
        return -5;
    }
    saved_mode = mode;
    printk("A6400DBG3 PRECHECK_OK os_crc=%08x gc=%08x mode=%u bcdusb_addr=%08x bcdusb=%04x\n",
           os_crc, gc_ptr, (unsigned)mode, bcdusb_address, (unsigned)saved_bcdusb);

    error = probe_kernel_write((void *)OS_STRING_VA, os20_os, OS_STRING_LEN);
    if (error || os_state(&os_crc) != 1) { printk("A6400DBG3 PATCH_FAIL_OS err=%d crc=%08x\n", error, os_crc); goto fail; }
    patched_os = 1;
    error = probe_kernel_write((void *)(gc_ptr + GC_MODE), &one, 1);
    if (error || mode_value(&mode) || mode != 1) { printk("A6400DBG3 PATCH_FAIL_MODE err=%d v=%u\n", error, (unsigned)mode); goto fail; }
    patched_mode = 1;
    error = probe_kernel_write((void *)bcdusb_address, &os20, 2);
    if (error || probe_kernel_read(&current_bcdusb, (const void *)bcdusb_address, 2) || current_bcdusb != BCDUSB_OS20) {
        printk("A6400DBG3 PATCH_FAIL_BCDUSB err=%d v=%04x\n", error, (unsigned)current_bcdusb); goto fail;
    }
    patched_bcdusb = 1;
    printk("A6400DBG3 PATCH_OK os_crc=%08x mode=1 bcdusb=0210\n", crc32_bytes(os20_os, OS_STRING_LEN));
    return 0;
fail:
    restore_all();
    patched_os = patched_mode = patched_bcdusb = 0;
    return -5;
}

void cleanup_module(void)
{
    if (!patched_os && !patched_mode && !patched_bcdusb) {
        printk("A6400DBG3 exit inactive\n");
        return;
    }
    restore_all();
    patched_os = patched_mode = patched_bcdusb = 0;
}
