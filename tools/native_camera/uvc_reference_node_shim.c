/* Explicit MOD descriptor for an OFFLINE node-only reference port.
 * This does not fix the gadget callback ABI and MUST NOT be installed.
 * Original video module refers to udif_devnodes + 0x294 (entry 55).
 * Keep that addend, but bind it to this private module-owned table.
 */
struct a6400_udif_node {
    const char *name;
    unsigned int kind_major;
    unsigned int minor_count;
};

_Static_assert(sizeof(void *) == 4, "ARM32 only");
_Static_assert(sizeof(struct a6400_udif_node) == 12, "verified devno stride");

struct a6400_udif_node a6400_uvc_devnodes[56] = {
    [55] = { "usb/video", 248u << 16, (1u << 16) | 33u }
};
