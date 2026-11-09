/* Freestanding tiny ARM Linux probe for /tmp_bt/video ioctl(0x4038e000) */

#define SYS_exit   1
#define SYS_read   3
#define SYS_write  4
#define SYS_open   5
#define SYS_close  6
#define SYS_ioctl  54

#define O_RDWR   2

#define IOCTL_UVC_INIT      0x4038e000
#define IOCTL_UVC_STOP      0x0000e001
#define IOCTL_UVC_REG_BUF   0x4008f000
#define IOCTL_UVC_UNREG_BUF 0x0000f001

struct uvc_buf_info {
    unsigned int size;
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

struct uvc_user_probe_info {
    void *context;
    void (*callbacks[8])(void);
    void *interfaces_ptr;
    unsigned int reserved40;
    unsigned char reserved44;
    unsigned char interface_count;
    unsigned short reserved46;
    void *extra_info_ptr;
    unsigned int extra_info_size;
};

static void dummy_event_cb(void) {
}

static unsigned char g_interfaces[4] = { 0, 1, 1, 2 };

void _start(void) {
    print_str("INIT_PROBE_START\n");
    int fd = sys_open("/tmp_bt/video", O_RDWR, 0);
    print_str("OPEN_FD=");
    print_int(fd);
    print_str("\n");
    if (fd < 0) {
        sys_exit(1);
    }

    struct uvc_user_probe_info info;
    info.context = (void *)0x1234;
    for (int i = 0; i < 8; i++) {
        info.callbacks[i] = dummy_event_cb;
    }
    info.interfaces_ptr = g_interfaces;
    info.reserved40 = 0;
    info.reserved44 = 0;
    info.interface_count = 2;
    info.reserved46 = 0;
    info.extra_info_ptr = (void *)0;
    info.extra_info_size = 0;

    print_str("CALLING_IOCTL_0x4038e000...\n");
    int ret = sys_ioctl(fd, IOCTL_UVC_INIT, &info);
    print_str("IOCTL_INIT_RESULT=");
    print_int(ret);
    print_str("\n");

    if (ret == 0) {
        struct uvc_buf_info binfo;
        binfo.size = 1325056;
        binfo.phys_addr = 0x20000000;
        print_str("CALLING_IOCTL_0x4008f000 (REG_BUF)...\n");
        int reg_buf_ret = sys_ioctl(fd, IOCTL_UVC_REG_BUF, &binfo);
        print_str("IOCTL_REG_BUF_RESULT=");
        print_int(reg_buf_ret);
        print_str("\n");

        print_str("CALLING_IOCTL_0xf001 (UNREG_BUF)...\n");
        int unreg_buf_ret = sys_ioctl(fd, IOCTL_UVC_UNREG_BUF, 0);
        print_str("IOCTL_UNREG_BUF_RESULT=");
        print_int(unreg_buf_ret);
        print_str("\n");

        print_str("CALLING_IOCTL_0xe001 (STOP)...\n");
        int unreg_ret = sys_ioctl(fd, IOCTL_UVC_STOP, 0);
        print_str("IOCTL_STOP_RESULT=");
        print_int(unreg_ret);
        print_str("\n");
    }

    int c = sys_close(fd);
    print_str("CLOSE_RESULT=");
    print_int(c);
    print_str("\n");

    sys_exit(ret == 0 ? 0 : 2);
}
