/* Freestanding ARM native UVC 720p @ 30 FPS Stream Feeder for Sony a6400
 * Direct Linux ARM EABI syscalls (svc 0) - zero libc dependencies.
 */

#define SYS_exit       1
#define SYS_read       3
#define SYS_write      4
#define SYS_open       5
#define SYS_close      6
#define SYS_ioctl      54
#define SYS_setsid     66
#define SYS_fsync      118
#define SYS_nanosleep  162
#define SYS_clock_gettime 263
#define SYS_clock_nanosleep 265

#define O_RDONLY    00
#define O_WRONLY    01
#define O_RDWR      02
#define O_CREAT     0100
#define O_TRUNC     01000

#define IOCTL_UVC_INIT     0x4038e000
#define IOCTL_UVC_STOP     0x0000e001
#define IOCTL_UVC_REG_BUF  0x4008f000
#define IOCTL_UVC_UNREG    0x0000f001
#define IOCTL_UVC_UPDATE   0x4008f003
#define IOCTL_UVC_WAIT     0x0000f002
#define IOCTL_UVC_ENABLE   0x0000f006

#ifndef UVC_TEST_TICKS
#define UVC_TEST_TICKS 900
#endif

struct usbg_video_buf_info {
    unsigned int size;
    unsigned int phys_addr;
};

struct usbg_video_data_info {
    unsigned int frame_size;
    unsigned int phys_addr;
};

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

/* In ZV-E10 descriptor tree:
 * Interface 0 = VideoControl (MI_00)
 * Interface 1 = VideoStreaming (MI_01)
 * Config = 1
 * [0]=0, [1]=interface0 (VC=0), [2]=config (1), [3]=interface1 (VS=1)
 */
static unsigned char g_interfaces[4] = { 0, 0, 1, 1 };

struct timespec {
    long tv_sec;
    long tv_nsec;
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

static inline int sys_setsid(void) {
    register int r0 __asm__("r0");
    register int r7 __asm__("r7") = SYS_setsid;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r7) : "memory");
    return r0;
}

static inline int sys_fsync(int fd) {
    register int r0 __asm__("r0") = fd;
    register int r7 __asm__("r7") = SYS_fsync;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r7) : "memory");
    return r0;
}

static inline void sys_nanosleep(const struct timespec *req) {
    register const void *r0 __asm__("r0") = req;
    register void *r1 __asm__("r1") = 0;
    register int r7 __asm__("r7") = SYS_nanosleep;
    __asm__ __volatile__("svc 0" : : "r"(r0), "r"(r1), "r"(r7) : "memory");
}

static inline void sys_exit(int code) __attribute__((noreturn));
static inline void sys_exit(int code) {
    register int r0 __asm__("r0") = code;
    register int r7 __asm__("r7") = SYS_exit;
    __asm__ __volatile__("svc 0" : : "r"(r0), "r"(r7) : "memory");
    while (1) {}
}

static int g_log_fd = 1;

static void print_str(const char *s) {
    int len = 0;
    while (s[len]) len++;
    sys_write(g_log_fd, s, len);
    if (g_log_fd > 2) sys_fsync(g_log_fd);
}

static void print_dec(int v) {
    char buf[16];
    int i = 0;
    if (v == 0) {
        print_str("0");
        return;
    }
    if (v < 0) {
        print_str("-");
        v = -v;
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
    buf[i] = 0;
    print_str(buf);
}

static void sleep_ms(int ms) {
    struct timespec ts;
    ts.tv_sec = ms / 1000;
    ts.tv_nsec = (ms % 1000) * 1000000L;
    sys_nanosleep(&ts);
}

static int monotonic_time(struct timespec *ts) {
    register int r0 __asm__("r0") = 1; /* CLOCK_MONOTONIC */
    register void *r1 __asm__("r1") = ts;
    register int r7 __asm__("r7") = SYS_clock_gettime;
    __asm__ __volatile__("svc 0" : "+r"(r0) : "r"(r1), "r"(r7) : "memory");
    return r0;
}

static int sleep_until(const struct timespec *ts) {
    register int r0 __asm__("r0") = 1; /* CLOCK_MONOTONIC */
    register int r1 __asm__("r1") = 1; /* TIMER_ABSTIME */
    register const void *r2 __asm__("r2") = ts;
    register void *r3 __asm__("r3") = 0;
    register int r7 __asm__("r7") = SYS_clock_nanosleep;
    __asm__ __volatile__("svc 0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r3), "r"(r7) : "memory");
    return r0;
}

void _start(void) {
    struct usbg_video_buf_info reg_buf;
    struct usbg_video_data_info data_info;
    struct uvc_user_probe_info info;
    int uvc_fd = -1;
    int ret;
    int frame_count = 0;
    int total_ticks = 0;
    int max_ticks = UVC_TEST_TICKS; /* Scheduling bound; an ioctl may block. */
    struct timespec next_frame;

    /* Escape parent process group and close inherited pipes so execute() in a6400_usb_debugd
     * finishes immediately (EOF) and NEVER sends kill(-child, SIGKILL) after 5 seconds! */
    sys_setsid();
    sys_close(0);
    sys_close(1);
    sys_close(2);

    /* Wait 800 ms so launching shell & SCSI transaction can cleanly finish */
    sleep_ms(800);

    /* Open log file in /tmp_bt/feeder.log */
    int f = sys_open("/tmp_bt/feeder.log", O_RDWR | O_CREAT | O_TRUNC, 0666);
    if (f >= 0) g_log_fd = f;

    print_str(">>> a6400 UVC 720p @ 30 FPS Stream Feeder starting <<<\n");

    /* 1. Open UVC character device node */
    uvc_fd = sys_open("/tmp_bt/video", O_RDWR, 0);
    if (uvc_fd < 0) {
        print_str("ERROR: Cannot open /tmp_bt/video (fd=");
        print_dec(uvc_fd);
        print_str(")\n");
        if (g_log_fd > 2) sys_close(g_log_fd);
        sys_exit(1);
    }
    print_str("[feeder] /tmp_bt/video opened, fd=");
    print_dec(uvc_fd);
    print_str("\n");

    /* 2. Initialize UVC driver callbacks and commit UVC descriptors */
    print_str("[feeder] initializing UVC driver & committing descriptors...\n");
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

    ret = sys_ioctl(uvc_fd, IOCTL_UVC_INIT, &info);
    print_str("[feeder] IOCTL_UVC_INIT result=");
    print_dec(ret);
    print_str("\n");

    /* 3. Register physical DMA video buffer (1325056 bytes at 0x20000000) */
    reg_buf.size = 1325056;
    reg_buf.phys_addr = 0x20000000;
    ret = sys_ioctl(uvc_fd, IOCTL_UVC_REG_BUF, &reg_buf);
    print_str("[feeder] IOCTL_UVC_REG_BUF result=");
    print_dec(ret);
    print_str("\n");

    /* 4. Enable UVC Bulk flag in kernel */
    ret = sys_ioctl(uvc_fd, IOCTL_UVC_ENABLE, (void *)0);
    print_str("[feeder] IOCTL_UVC_ENABLE result=");
    print_dec(ret);
    print_str("\n");

    print_str("[feeder] streaming loop active (720p @ 30 FPS)...\n");

    /* 5. Feed frames at 30 FPS */
    data_info.frame_size = 29452;
    data_info.phys_addr = 0x20120000; /* Disjoint from both UVC destination slots. */
    sleep_ms(1000);
    if (monotonic_time(&next_frame) != 0) max_ticks=0;

    while (total_ticks < max_ticks) {
        total_ticks++;

        /* Check stop signal from host */
        int stop_fd = sys_open("/tmp_bt/stop_feeder", O_RDONLY, 0);
        if (stop_fd >= 0) {
            sys_close(stop_fd);
            print_str("[feeder] stop signal detected via /tmp_bt/stop_feeder\n");
            break;
        }

        /* Submit frame to UVC transfer engine */
#ifdef UVC_NO_SUBMIT
        (void)data_info;
        ret = -16; /* Diagnostic: no frame submission, not a driver result. */
#else
        ret = sys_ioctl(uvc_fd, IOCTL_UVC_WAIT, (void *)0);
        if (ret == 0) ret = sys_ioctl(uvc_fd, IOCTL_UVC_UPDATE, &data_info);
#endif
        if (total_ticks == 1) {
#ifdef UVC_NO_SUBMIT
            print_str("[feeder] diagnostic: frame submissions disabled; marker=");
#else
            print_str("[feeder] first IOCTL_UVC_UPDATE result=");
#endif
            print_dec(ret);
            print_str("\n");
        }
        if (ret == 0) {
            frame_count++;
            if ((frame_count % 30) == 0) {
                print_str("[feeder] frames sent: ");
                print_dec(frame_count);
                print_str(" (accepted submissions; host FPS unverified)\n");
            }
        }
        if (ret < 0 && ret != -16) {
            print_str("[feeder] transfer failed, result=");
            print_dec(ret);print_str("\n");
            break;
        }

        /* Absolute deadlines avoid accumulating syscall cost/jiffy rounding. */
        next_frame.tv_nsec += 33333333L;
        if (next_frame.tv_nsec >= 1000000000L) {
            next_frame.tv_nsec -= 1000000000L;
            next_frame.tv_sec++;
        }
        ret=sleep_until(&next_frame);
        if (ret != 0 && ret != -4) {
            print_str("[feeder] absolute sleep failed: ");print_dec(ret);print_str("\n");
            break;
        }
    }

    print_str("[feeder] streaming loop finished, total ticks=");
    print_dec(total_ticks);
    print_str(", frames sent=");
    print_dec(frame_count);
    print_str("\n");

    /* 6. Teardown: unregister DMA buffer and restore Mass Storage descriptors */
    print_str("[feeder] tearing down & restoring Mass Storage...\n");
    ret = sys_ioctl(uvc_fd, IOCTL_UVC_UNREG, (void *)0);
    print_str("[feeder] IOCTL_UVC_UNREG result=");
    print_dec(ret);
    print_str("\n");

    ret = sys_ioctl(uvc_fd, IOCTL_UVC_STOP, (void *)0);
    print_str("[feeder] IOCTL_UVC_STOP result=");
    print_dec(ret);
    print_str("\n");

    sys_close(uvc_fd);

    print_str("[feeder] clean teardown complete! Mass Storage restored.\n");
    if (g_log_fd > 2) sys_close(g_log_fd);
    sys_exit(0);
}
