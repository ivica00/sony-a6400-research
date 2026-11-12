/* E0404 B1b: read-only gadgetcore / descriptor-tree inspection.
 *
 * No writes of any kind. Loaded from /tmp_bt, prints the live MS OS gate
 * (gadgetcore+0x84), the installed device descriptor's bcdUSB and class, and
 * the current configuration's interface/alternate topology, then unloads.
 * Every read is bounds-checked; an unexpected pointer stops the probe instead
 * of faulting.
 */
typedef unsigned int u32;
typedef unsigned char u8;
typedef unsigned int usize;

__attribute__((section(".modinfo"), used)) static const char a6400_license[] = "license=GPL";
__attribute__((section(".modinfo"), used)) static const char a6400_author[] = "author=a6400 research";
__attribute__((section(".modinfo"), used)) static const char a6400_description[] =
    "description=read-only gadgetcore and descriptor tree probe";

extern int printk(const char *format, ...);
extern int probe_kernel_read(void *dst, const void *src, usize size);

/* Literal loaded by usb_gadgetcore_register_driver (VA 0x602b861c -> 0x6051b17c). */
#define GADGETCORE_SLOT_VA 0x6051b17Cu
#define GC_ROOT_OFFSET     0x6Cu
#define GC_MODE_OFFSET     0x84u
#define GC_MAXSPEED_OFFSET 0x85u
#define DEVICE_ENTRY_SIZE  16u
#define CONFIG_STRUCT_SIZE 24u

static int readable_range(u32 address, usize size)
{
    return address >= 0x60000000u && address + size > address && address + size <= 0x70000000u;
}

static u32 read_word_safe(u32 address, int *error)
{
    u32 value = 0;
    int result;
    if (!readable_range(address, 4)) { *error = -14; return 0; }
    result = probe_kernel_read(&value, (const void *)address, 4);
    if (result) *error = result;
    return value;
}

int init_module(void)
{
    u32 gadgetcore = 0;
    u32 root = 0, configs = 0, interfaces = 0, alternates = 0;
    u8 bcd_usb[2] = {0, 0};
    u8 mode = 0, max_speed = 0, device_class = 0, config_count = 0;
    u8 interface_count = 0;
    u8 device_entry[DEVICE_ENTRY_SIZE];
    u8 config[CONFIG_STRUCT_SIZE];
    int error = 0;
    unsigned int index;

    printk("A6400DBGPROBE begin slot_va=%08x\n", GADGETCORE_SLOT_VA);
    error = probe_kernel_read(&gadgetcore, (const void *)GADGETCORE_SLOT_VA, 4);
    if (error || !readable_range(gadgetcore, 0x90)) {
        printk("A6400DBGPROBE gadgetcore_unreadable error=%d value=%08x\n",
               error, gadgetcore);
        return 0;
    }
    printk("A6400DBGPROBE gadgetcore=%08x\n", gadgetcore);
    mode = *(volatile u8 *)(gadgetcore + GC_MODE_OFFSET);
    max_speed = *(volatile u8 *)(gadgetcore + GC_MAXSPEED_OFFSET);
    root = read_word_safe(gadgetcore + GC_ROOT_OFFSET, &error);
    printk("A6400DBGPROBE mode=%u max_speed=%u root=%08x read_error=%d\n",
           mode, max_speed, root, error);
    if (!readable_range(root, 88)) {
        printk("A6400DBGPROBE root_unreadable\n");
        return 0;
    }
    if (probe_kernel_read(device_entry, (const void *)root, DEVICE_ENTRY_SIZE)) {
        printk("A6400DBGPROBE device_read_failed\n");
        return 0;
    }
    bcd_usb[0] = device_entry[2];
    bcd_usb[1] = device_entry[3];
    device_class = device_entry[4];
    config_count = device_entry[5];
    configs = *(volatile u32 *)(root + 8);
    printk("A6400DBGPROBE device len=%u type=%u bcdUSB=%02x%02x class=%02x configs=%u config_ptr=%08x\n",
           device_entry[0], device_entry[1], bcd_usb[1], bcd_usb[0], device_class,
           config_count, configs);
    if (!readable_range(configs, 88)) {
        printk("A6400DBGPROBE config_ptr_unreadable\n");
        return 0;
    }
    if (probe_kernel_read(config, (const void *)configs, CONFIG_STRUCT_SIZE)) {
        printk("A6400DBGPROBE config_read_failed\n");
        return 0;
    }
    interface_count = config[2];
    interfaces = *(volatile u32 *)(config + 4);
    printk("A6400DBGPROBE config value=%u interfaces=%u interface_ptr=%08x attrs=%02x power=%u\n",
           config[1], interface_count, interfaces, config[6], config[7]);
    if (!readable_range(interfaces, interface_count * 8u)) {
        printk("A6400DBGPROBE interface_table_unreadable\n");
        return 0;
    }
    for (index = 0; index < interface_count && index < 8u; index++) {
        u8 interface[8];
        u8 alternate[20];
        u32 alternate_ptr;
        if (probe_kernel_read(interface, (const void *)(interfaces + index * 8u), 8)) {
            printk("A6400DBGPROBE iface%u_read_failed\n", index);
            break;
        }
        alternate_ptr = *(volatile u32 *)(interface + 4);
        printk("A6400DBGPROBE iface%u number=%u alternates=%u alt_ptr=%08x\n",
               index, interface[0], interface[1], alternate_ptr);
        if (interface[1] == 0 || !readable_range(alternate_ptr, 20)) continue;
        if (probe_kernel_read(alternate, (const void *)alternate_ptr, 20)) continue;
        alternates = *(volatile u32 *)(alternate + 4);
        printk("A6400DBGPROBE iface%u alt0 class=%02x subclass=%02x protocol=%02x endpoints=%u ep_ptr=%08x extra=%u\n",
               index, alternate[8], alternate[9], alternate[10], alternate[1],
               alternates, *(volatile u32 *)(alternate + 16));
    }
    printk("A6400DBGPROBE end\n");
    return 0;
}

void cleanup_module(void)
{
    printk("A6400DBGPROBE unloaded\n");
}
