/*
 * patch_inh_factor.c
 * Lifts USB shooting inhibition factor 0x85b in im.elf (PID 149)
 */

#define SYS_exit      1
#define SYS_read      3
#define SYS_write     4
#define SYS_open      5
#define SYS_close     6
#define SYS_lseek     19
#define SYS_nanosleep 162

#define O_RDONLY      0
#define O_WRONLY      1
#define O_RDWR        2

struct timespec { long tv_sec; long tv_nsec; };

static inline int sys_open(const char *path, int flags, int mode) {
    register int r0 __asm__("r0") = (int)path;
    register int r1 __asm__("r1") = flags;
    register int r2 __asm__("r2") = mode;
    register int r7 __asm__("r7") = SYS_open;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}
static inline int sys_close(int fd) {
    register int r0 __asm__("r0") = fd;
    register int r7 __asm__("r7") = SYS_close;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r7) : "memory");
    return r0;
}
static inline int sys_read(int fd, void *buf, int count) {
    register int r0 __asm__("r0") = fd;
    register int r1 __asm__("r1") = (int)buf;
    register int r2 __asm__("r2") = count;
    register int r7 __asm__("r7") = SYS_read;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}
static inline int sys_write(int fd, const void *buf, int count) {
    register int r0 __asm__("r0") = fd;
    register int r1 __asm__("r1") = (int)buf;
    register int r2 __asm__("r2") = count;
    register int r7 __asm__("r7") = SYS_write;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}
static inline int sys_lseek(int fd, unsigned long offset, int whence) {
    register int r0 __asm__("r0") = fd;
    register int r1 __asm__("r1") = (int)offset;
    register int r2 __asm__("r2") = whence;
    register int r7 __asm__("r7") = SYS_lseek;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}
static inline void sys_exit(int c) {
    register int r0 __asm__("r0") = c;
    register int r7 __asm__("r7") = SYS_exit;
    __asm__ __volatile__("svc 0" : : "r"(r0), "r"(r7) : "memory");
    while(1){}
}

static void print_str(const char *s) {
    int len = 0; while (s[len]) len++; sys_write(1, s, len);
}
static void print_hex(unsigned int v) {
    const char h[] = "0123456789abcdef";
    char b[11] = "0x00000000";
    for (int i=7; i>=0; i--) b[2 + (7-i)] = h[(v >> (i*4)) & 0xf];
    sys_write(1, b, 10);
}
static void print_int(int v) {
    char buf[16]; int i = 0;
    if (v < 0) { sys_write(1, "-", 1); v = -v; }
    if (v == 0) { sys_write(1, "0", 1); return; }
    while (v > 0) { buf[i++] = '0' + (v % 10); v /= 10; }
    for (int j = 0; j < i/2; j++) { char t = buf[j]; buf[j] = buf[i-1-j]; buf[i-1-j] = t; }
    sys_write(1, buf, i);
}

void _start(void) {
    print_str("=== PATCH INH FACTOR 0x85b IN IM.ELF ===\n");
    int fd = sys_open("/proc/149/mem", O_RDWR, 0);
    print_str("open(/proc/149/mem) = "); print_int(fd); print_str("\n");
    if (fd < 0) sys_exit(1);

    // 1. Read mp_inhMgrInsList pointer at 0x041388dc
    sys_lseek(fd, 0x041388dc, 0);
    unsigned int list_ptr = 0;
    sys_read(fd, &list_ptr, 4);
    print_str("mp_inhMgrInsList = "); print_hex(list_ptr); print_str("\n");
    if (!list_ptr) { sys_close(fd); sys_exit(2); }

    // 2. Read node at list_ptr
    // In node, InhMgr pointer is at offset 8: 0x05ac4008
    sys_lseek(fd, list_ptr + 8, 0);
    unsigned int inhmgr_ptr = 0;
    sys_read(fd, &inhmgr_ptr, 4);
    print_str("inhmgr_ptr = "); print_hex(inhmgr_ptr); print_str("\n");
    if (!inhmgr_ptr) { sys_close(fd); sys_exit(3); }

    // 3. Read bitmask_array 1 and 2 from InhMgr
    sys_lseek(fd, inhmgr_ptr, 0);
    unsigned int bm1_ptr = 0, bm2_ptr = 0;
    sys_read(fd, &bm1_ptr, 4);
    sys_read(fd, &bm2_ptr, 4);
    print_str("bm1 = "); print_hex(bm1_ptr);
    print_str(" bm2 = "); print_hex(bm2_ptr); print_str("\n");

    // 4. In bm1, word 66 (offset 66*4 = 264 = 0x108) holds InhFactor 0x85b (bit 27)
    unsigned int word66_addr = bm1_ptr + 66 * 4;
    sys_lseek(fd, word66_addr, 0);
    unsigned int w66 = 0;
    sys_read(fd, &w66, 4);
    print_str("Pre-patch word66 = "); print_hex(w66); print_str("\n");

    // Set bit 27 (1 << 27 = 0x08000000)
    w66 |= (1u << 27);
    sys_lseek(fd, word66_addr, 0);
    int written = sys_write(fd, &w66, 4);
    print_str("Write result = "); print_int(written); print_str("\n");

    // Re-read to verify
    sys_lseek(fd, word66_addr, 0);
    unsigned int verify = 0;
    sys_read(fd, &verify, 4);
    print_str("Post-patch word66 = "); print_hex(verify); print_str("\n");
    print_str("Bit 27 is now: "); print_int((verify >> 27) & 1); print_str("\n");

    // Also set bit 27 in bm2 if present
    if (bm2_ptr) {
        unsigned int bm2_w66_addr = bm2_ptr + 66 * 4;
        sys_lseek(fd, bm2_w66_addr, 0);
        unsigned int w66_2 = 0;
        sys_read(fd, &w66_2, 4);
        w66_2 |= (1u << 27);
        sys_lseek(fd, bm2_w66_addr, 0);
        sys_write(fd, &w66_2, 4);
        print_str("Patched bm2 word66\n");
    }

    sys_close(fd);
    print_str("=== PATCH COMPLETE ===\n");
    sys_exit(0);
}
