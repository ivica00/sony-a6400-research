/* Freestanding tiny ARM Linux probe for UVC DMA metadata and slot guards */

#define SYS_exit   1
#define SYS_read   3
#define SYS_write  4
#define SYS_open   5
#define SYS_close  6
#define SYS_ioctl  54

#define O_RDWR   2

#define IOCTL_UVC_MOD_QUERY_DMA 0x8010f020
#define IOCTL_UVC_REG_BUF       0x4008f000
#define IOCTL_UVC_UNREG_BUF     0x0000f001
#define IOCTL_UVC_UPDATE        0x4008f003

struct a6400_uvc_dma_metadata {
    unsigned int phys_addr;
    unsigned int total_size;
    unsigned int slot_size;
    unsigned int max_frame_payload;
};

struct reg_buf_arg {
    unsigned int size;
    unsigned int phys_addr;
};

struct update_arg {
    unsigned int frame_size;
    unsigned int phys_addr;
};

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

static inline int sys_write(int fd, const void *buf, int count) {
    register int r0 __asm__("r0") = fd;
    register int r1 __asm__("r1") = (int)buf;
    register int r2 __asm__("r2") = count;
    register int r7 __asm__("r7") = SYS_write;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

static inline int sys_ioctl(int fd, unsigned long req, void *arg) {
    register int r0 __asm__("r0") = fd;
    register int r1 __asm__("r1") = (int)req;
    register int r2 __asm__("r2") = (int)arg;
    register int r7 __asm__("r7") = SYS_ioctl;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

static inline void sys_exit(int code) {
    register int r0 __asm__("r0") = code;
    register int r7 __asm__("r7") = SYS_exit;
    __asm__ __volatile__("svc 0" : : "r"(r0), "r"(r7) : "memory");
    while (1) {}
}

static void print_str(const char *s) {
    int len = 0;
    while (s[len]) len++;
    sys_write(1, s, len);
}

static void print_hex(unsigned int val) {
    char buf[11];
    buf[0] = '0';
    buf[1] = 'x';
    const char hex_chars[] = "0123456789abcdef";
    for (int i = 7; i >= 0; i--) {
        buf[2 + (7 - i)] = hex_chars[(val >> (i * 4)) & 0xf];
    }
    buf[10] = '\0';
    sys_write(1, buf, 10);
}

static void print_int(int v) {
    char buf[16];
    int i = 0;
    if (v < 0) {
        sys_write(1, "-", 1);
        v = -v;
    }
    if (v == 0) {
        sys_write(1, "0", 1);
        return;
    }
    while (v > 0) {
        buf[i++] = '0' + (v % 10);
        v /= 10;
    }
    for (int j = 0; j < i / 2; j++) {
        char tmp = buf[j];
        buf[j] = buf[i - 1 - j];
        buf[i - 1 - j] = tmp;
    }
    sys_write(1, buf, i);
}

void _start(void) {
    print_str("DMA_META_PROBE_START\n");
    int fd = sys_open("/tmp_bt/video", O_RDWR, 0);
    print_str("OPEN_FD=");
    print_int(fd);
    print_str("\n");
    if (fd < 0) {
        sys_exit(1);
    }

    /* 1. Query MOD DMA metadata */
    struct a6400_uvc_dma_metadata meta;
    int ret = sys_ioctl(fd, IOCTL_UVC_MOD_QUERY_DMA, &meta);
    print_str("QUERY_DMA_RET=");
    print_int(ret);
    print_str("\n");
    if (ret != 0) {
        sys_close(fd);
        sys_exit(2);
    }

    print_str("DMA_PHYS=");
    print_hex(meta.phys_addr);
    print_str(" TOTAL_SIZE=");
    print_int(meta.total_size);
    print_str(" SLOT_SIZE=");
    print_int(meta.slot_size);
    print_str(" MAX_PAYLOAD=");
    print_int(meta.max_frame_payload);
    print_str("\n");

    /* 2. Test REG_BUF with wrong unowned address 0x20000000 (must be rejected) */
    struct reg_buf_arg bad_reg;
    bad_reg.phys_addr = 0x20000000u;
    bad_reg.size = meta.total_size;
    ret = sys_ioctl(fd, IOCTL_UVC_REG_BUF, &bad_reg);
    print_str("BAD_REG_RET=");
    print_int(ret);
    print_str("\n");
    if (ret == 0) {
        print_str("FAIL: BAD_REG_ACCEPTED\n");
        sys_close(fd);
        sys_exit(3);
    }

    /* 3. Test REG_BUF with valid owned address */
    struct reg_buf_arg good_reg;
    good_reg.phys_addr = meta.phys_addr;
    good_reg.size = meta.total_size;
    ret = sys_ioctl(fd, IOCTL_UVC_REG_BUF, &good_reg);
    print_str("GOOD_REG_RET=");
    print_int(ret);
    print_str("\n");
    if (ret != 0) {
        print_str("FAIL: GOOD_REG_FAILED\n");
        sys_close(fd);
        sys_exit(4);
    }

    /* 4. Test UPDATE with oversized frame (140000 > max_frame_payload) */
    struct update_arg bad_update;
    bad_update.frame_size = 140000;
    bad_update.phys_addr = meta.phys_addr;
    ret = sys_ioctl(fd, IOCTL_UVC_UPDATE, &bad_update);
    print_str("OVERSIZED_UPDATE_RET=");
    print_int(ret);
    print_str("\n");
    if (ret == 0) {
        print_str("FAIL: OVERSIZED_UPDATE_ACCEPTED\n");
        sys_close(fd);
        sys_exit(5);
    }

    /* 5. Clean UNREG_BUF */
    ret = sys_ioctl(fd, IOCTL_UVC_UNREG_BUF, 0);
    print_str("UNREG_BUF_RET=");
    print_int(ret);
    print_str("\n");

    sys_close(fd);
    print_str("DMA_META_PROBE_SUCCESS\n");
    sys_exit(0);
}
