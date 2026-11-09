/* Test opening /dev/uipc and querying init struct with valid output pointer */

#define SYS_exit   1
#define SYS_write  4
#define SYS_open   5
#define SYS_close  6
#define SYS_ioctl  54

#define O_RDWR   2

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

void _start(void) {
    print_str("UIPC_PROBE_START\n");
    int fd = sys_open("/dev/uipc", O_RDWR, 0);
    print_str("OPEN_FD=");
    print_int(fd);
    print_str("\n");
    if (fd < 0) {
        sys_exit(1);
    }

    unsigned int out_meta[8];
    for (int i = 0; i < 8; i++) out_meta[i] = 0;

    struct {
        unsigned int param;
        void *out_ptr;
    } req;
    req.param = 0;
    req.out_ptr = out_meta;

    int ret = sys_ioctl(fd, 0x80000010, &req);
    print_str("IOCTL_INIT_RET=");
    print_int(ret);
    print_str("\n");
    print_str("META[0]=");
    print_int(out_meta[0]);
    print_str(" [1]=");
    print_int(out_meta[1]);
    print_str(" [2]=");
    print_int(out_meta[2]);
    print_str(" [3]=");
    print_int(out_meta[3]);
    print_str("\n");

    sys_close(fd);
    print_str("UIPC_PROBE_END\n");
    sys_exit(0);
}
