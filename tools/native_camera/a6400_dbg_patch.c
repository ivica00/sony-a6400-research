/* E0403 B1c: bounded 18-byte Microsoft OS string patch with mandatory restore.
 *
 * This module deliberately does nothing else: no gadget driver, no descriptors,
 * no char device, no files. It is loaded from /tmp (volatile RAM) only.
 *
 *   VA 0x604E5130 (physical 0x4E5130, /proc/iomem "Kernel data"):
 *     stock "MSFT100" OS string descriptor, 18 bytes
 *     patched "MSFT20"  OS string descriptor, 18 bytes (Microsoft OS 2.0)
 *
 * init_module: read 18 bytes -> CRC32 must equal the stock CRC -> save backup ->
 * probe_kernel_write -> read back -> CRC must equal the patched CRC. Any
 * mismatch restores the saved bytes and fails the load.
 * cleanup_module: restore the saved bytes -> read back -> CRC must equal the
 * stock CRC, retried three times; the result is printed to the kernel log.
 */
typedef unsigned int u32;
typedef unsigned char u8;
typedef unsigned int usize;

/* probe_kernel_write is EXPORT_SYMBOL_GPL; the helper must declare GPL. */
__attribute__((section(".modinfo"), used)) static const char a6400_license[] = "license=GPL";
__attribute__((section(".modinfo"), used)) static const char a6400_author[] = "author=a6400 research";
__attribute__((section(".modinfo"), used)) static const char a6400_description[] =
    "description=bounded MS OS string patch with mandatory restore";

extern int printk(const char *format, ...);
extern void *memcpy(void *dest, const void *src, usize count);
extern int probe_kernel_write(void *dst, const void *src, usize size);

#define OS_STRING_VA 0x604E5130u
#define OS_STRING_LEN 18u

static const u8 stock_bytes[OS_STRING_LEN] = {
    0x12, 0x03,                                    /* bLength, bDescriptorType */
    0x4d, 0x00, 0x53, 0x00, 0x46, 0x00, 0x54, 0x00, /* MSFT */
    0x31, 0x00, 0x30, 0x00, 0x30, 0x00,             /* 100 */
    0x30, 0x00                                      /* vendor code 0x30, pad 0 */
};
static const u8 os20_bytes[OS_STRING_LEN] = {
    0x12, 0x03,
    0x4d, 0x00, 0x53, 0x00, 0x46, 0x00, 0x54, 0x00, /* MSFT */
    0x32, 0x00, 0x30, 0x00, 0x00, 0x00,             /* 20 + NUL */
    0x02, 0x00                                      /* vendor code 0x02, pad 0 */
};

static u8 saved_bytes[OS_STRING_LEN];
static int patch_active;

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

static int readback(const u8 *expected, u32 *actual_crc)
{
    u8 current[OS_STRING_LEN];
    u32 crc;
    memcpy(current, (const void *)OS_STRING_VA, OS_STRING_LEN);
    crc = crc32_bytes(current, OS_STRING_LEN);
    if (actual_crc)
        *actual_crc = crc;
    return crc == crc32_bytes(expected, OS_STRING_LEN) ? 0 : -5;
}

int init_module(void)
{
    u32 stock_crc = crc32_bytes(stock_bytes, OS_STRING_LEN);
    u32 os20_crc = crc32_bytes(os20_bytes, OS_STRING_LEN);
    u32 before = 0, after = 0;
    int error;

    printk("A6400DBG init begin va=%08x len=%u\n", OS_STRING_VA, OS_STRING_LEN);
    memcpy(saved_bytes, (const void *)OS_STRING_VA, OS_STRING_LEN);
    if (readback(stock_bytes, &before)) {
        printk("A6400DBG PRECHECK_REJECT crc=%08x want=%08x\n", before, stock_crc);
        return -5;
    }
    printk("A6400DBG PRECHECK_OK crc=%08x\n", before);
    error = probe_kernel_write((void *)OS_STRING_VA, os20_bytes, OS_STRING_LEN);
    if (error) {
        printk("A6400DBG PATCH_WRITE_FAILED error=%d\n", error);
        return error;
    }
    if (readback(os20_bytes, &after)) {
        printk("A6400DBG PATCH_READBACK_REJECT crc=%08x want=%08x; restoring\n",
               after, os20_crc);
        (void)probe_kernel_write((void *)OS_STRING_VA, saved_bytes, OS_STRING_LEN);
        return -5;
    }
    patch_active = 1;
    printk("A6400DBG PATCH_OK crc_before=%08x crc_after=%08x\n", before, after);
    return 0;
}

void cleanup_module(void)
{
    unsigned int attempt;
    u32 restored_crc = 0;
    int error = -1;

    if (!patch_active) {
        printk("A6400DBG exit inactive\n");
        return;
    }
    for (attempt = 0; attempt < 3; attempt++) {
        error = probe_kernel_write((void *)OS_STRING_VA, saved_bytes, OS_STRING_LEN);
        if (!error && !readback(stock_bytes, &restored_crc)) {
            patch_active = 0;
            printk("A6400DBG RESTORE_OK crc=%08x attempts=%u\n", restored_crc, attempt + 1);
            return;
        }
    }
    printk("A6400DBG RESTORE_FAILED error=%d crc=%08x attempts=%u\n",
           error, restored_crc, attempt);
}
