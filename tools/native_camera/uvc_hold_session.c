/* Freestanding tiny ARM Linux UVC session runner.
 * Holds UVC mode active for duration seconds, allowing host enumeration,
 * then cleanly unregisters and restores Mass Storage mode.
 */

#define SYS_exit      1
#define SYS_read      3
#define SYS_write     4
#define SYS_open      5
#define SYS_close     6
#define SYS_ioctl     54
#define SYS_nanosleep 162

#define O_RDWR   2

#define IOCTL_UVC_INIT      0x4038e000
#define IOCTL_UVC_STOP      0x0000e001
#define IOCTL_UVC_REG_BUF   0x4008f000
#define IOCTL_UVC_UNREG_BUF 0x0000f001

struct timespec {
    long tv_sec;
    long tv_nsec;
};

struct uvc_buf_info {
    unsigned int size;
    unsigned int phys_addr;
};

struct reg_video_drv_arg {
    void *context;
    int (*callbacks[8])(void *, int, void *);
    void *interfaces_ptr;
    unsigned int reserved40;
    unsigned int reserved44;
    unsigned short interface_count;
    unsigned short reserved46;
    void *extra_info_ptr;
    unsigned int extra_info_size;
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

static inline int sys_nanosleep(const struct timespec *req, struct timespec *rem) {
    register int r0 __asm__("r0") = (int)req;
    register int r1 __asm__("r1") = (int)rem;
    register int r7 __asm__("r7") = SYS_nanosleep;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r7) : "memory");
    return r0;
}

static inline void sys_exit(int code) {
    register int r0 __asm__("r0") = code;
    register int r7 __asm__("r7") = SYS_exit;
    __asm__ __volatile__("svc 0" : : "r"(r0), "r"(r7) : "memory");
}

static int dummy_event_cb(void *ctx, int ev, void *arg) {
    (void)ctx; (void)ev; (void)arg;
    return 0;
}

static unsigned char g_interfaces[128];

void _start(void) {
    const char dev[] = "/tmp_bt/video";
    int fd = sys_open(dev, O_RDWR, 0);
    if (fd < 0) {
        sys_exit(1);
    }

    struct reg_video_drv_arg info;
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

    int ret = sys_ioctl(fd, IOCTL_UVC_INIT, &info);
    if (ret != 0) {
        sys_close(fd);
        sys_exit(2);
    }

    struct uvc_buf_info binfo;
    binfo.size = 1325056;
    binfo.phys_addr = 0x20000000;
    sys_ioctl(fd, IOCTL_UVC_REG_BUF, &binfo);

    /* Hold UVC mode active for 60 seconds (allowing Windows DirectShow enumeration) */
    struct timespec ts;
    ts.tv_sec = 1;
    ts.tv_nsec = 0;
    for (int i = 0; i < 60; i++) {
        sys_nanosleep(&ts, 0);
    }

    /* Clean teardown and restore Mass Storage mode */
    sys_ioctl(fd, IOCTL_UVC_UNREG_BUF, 0);
    sys_ioctl(fd, IOCTL_UVC_STOP, 0);
    sys_close(fd);

    sys_exit(0);
}
